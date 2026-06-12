"""生成蜡烛图（无成交量）形态信号并落盘到 signal_daily_形态。

增量逻辑对齐 `ZXW因子/ZXW策略技术因子生成.ipynb`：
- auto 模式扫描已有 events，生成按股票补写计划
- 全市场单次 DuckDB 查询 + 一次 unstack + 一次算形态
- 与库中已有 events 对账，只写缺失 (htsc_code, time, signal_name)
- 默认只写 part，合并由 `形态面增量信号保存.py` 另行执行
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MORPH_DIR = PROJECT_ROOT / "形态趋势通道因子"
DEFAULT_MARKET_EQUITY_PATH = r"D:\database\stock_financial_statements\market_equity_data"
DEFAULT_OUTPUT_BASE = r"D:\database\signal_daily_形态\candlestick_no_vol"
DEFAULT_CODES = ""
DEFAULT_BATCH_SIZE = 0
DEFAULT_MODE = "auto"
DEFAULT_START_DATE = "2010-01-01"
DEFAULT_LOOKBACK_DAYS = 0
LOOKBACK_BUFFER_DAYS = 20
INCREMENTAL_SAVE_SCRIPT = PROJECT_ROOT / "工具" / "形态面增量信号保存.py"
_PATTERN_LOOKBACK_INTERNAL = 45


def _load_pattern_class():
    module_path = MORPH_DIR / "蜡烛图无成交量.py"
    spec = importlib.util.spec_from_file_location("candlestick_no_vol", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 Pattern 模块: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Pattern


def _load_meta_module():
    module_path = MORPH_DIR / "morph_candlestick_meta.py"
    spec = importlib.util.spec_from_file_location("morph_candlestick_meta", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载元数据模块: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _glob_parquet_pattern(base_path: str) -> str:
    normalized = base_path.replace("\\", "/")
    return f"{normalized}/year=*/month=*/merged.parquet"


def _normalize_date_str(value: str) -> str:
    return pd.Timestamp(str(value).strip()).strftime("%Y-%m-%d")


def _date_to_yyyymmdd(value) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, pd.Timestamp):
        return int(value.strftime("%Y%m%d"))
    parsed = pd.to_datetime(value)
    return int(parsed.strftime("%Y%m%d"))


def _yyyymmdd_to_ts(value: int) -> pd.Timestamp:
    return pd.Timestamp(str(int(value))).floor("D")


def compute_required_lookback_days(meta_module, override: int = 0) -> int:
    if override > 0:
        return int(override)
    max_span = max(meta_module.SIGNAL_BAR_SPAN.values(), default=1)
    return max(max_span, _PATTERN_LOOKBACK_INTERNAL) + LOOKBACK_BUFFER_DAYS


_BAR_TIME_SQL = """
    COALESCE(
        TRY_CAST(time AS TIMESTAMP),
        to_timestamp(COALESCE(
            TRY_CAST(time AS BIGINT),
            CAST(EPOCH(TRY_CAST(time AS TIMESTAMP)) AS BIGINT)
        ))
    )
"""


def _floor_day(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(None)
    return ts.floor("D")


def scan_latest_ts_by_code(parquet_glob: str) -> dict[str, pd.Timestamp]:
    conn = duckdb.connect(database=":memory:")
    try:
        try:
            rows = conn.execute(
                """
                SELECT
                    UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                    MAX(
                        COALESCE(
                            TRY_CAST(time AS TIMESTAMP),
                            to_timestamp(COALESCE(
                                TRY_CAST(time AS BIGINT),
                                CAST(EPOCH(TRY_CAST(time AS TIMESTAMP)) AS BIGINT)
                            ))
                        )
                    ) AS max_time
                FROM read_parquet(?, hive_partitioning = true, union_by_name = true)
                WHERE htsc_code IS NOT NULL
                GROUP BY 1
                """,
                [parquet_glob],
            ).fetchdf()
        except duckdb.Error:
            return {}
    finally:
        conn.close()
    if rows.empty:
        return {}
    out: dict[str, pd.Timestamp] = {}
    for _, row in rows.iterrows():
        code = str(row["htsc_code"]).strip().upper()
        val = row["max_time"]
        if code and pd.notna(val):
            out[code] = _floor_day(val)
    return out


def scan_market_date_range_by_code(market_equity_path: str) -> tuple[dict[str, pd.Timestamp], dict[str, pd.Timestamp]]:
    parquet_glob = _glob_parquet_pattern(market_equity_path)
    conn = duckdb.connect(database=":memory:")
    try:
        rows = conn.execute(
            f"""
            SELECT
                UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                MIN({_BAR_TIME_SQL}) AS min_time,
                MAX({_BAR_TIME_SQL}) AS max_time
            FROM read_parquet(?, hive_partitioning = true, union_by_name = true)
            WHERE htsc_code IS NOT NULL
            GROUP BY 1
            """,
            [parquet_glob],
        ).fetchdf()
    finally:
        conn.close()
    min_map: dict[str, pd.Timestamp] = {}
    max_map: dict[str, pd.Timestamp] = {}
    if rows.empty:
        return min_map, max_map
    for _, row in rows.iterrows():
        code = str(row["htsc_code"]).strip().upper()
        if not code:
            continue
        if pd.notna(row["min_time"]):
            min_map[code] = _floor_day(row["min_time"])
        if pd.notna(row["max_time"]):
            max_map[code] = _floor_day(row["max_time"])
    return min_map, max_map


def scan_signal_latest_from_output(output_base: Path) -> dict[str, pd.Timestamp]:
    events_glob = str(output_base / "events" / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")
    return scan_latest_ts_by_code(events_glob)


def build_stock_fill_plan(
    codes: list[str],
    signal_latest: dict[str, pd.Timestamp],
    market_max: dict[str, pd.Timestamp],
    *,
    start_date: str,
    end_date: str,
    lookback_days: int,
) -> pd.DataFrame:
    """按股票生成补写计划，语义对齐 notebook 的 build_factor_fill_plan。"""
    start_dt = pd.Timestamp(start_date).floor("D")
    end_dt = pd.Timestamp(end_date).floor("D")
    rewind_days = int(lookback_days) + int(LOOKBACK_BUFFER_DAYS)
    rows: list[dict[str, object]] = []

    for code in codes:
        m_max = market_max.get(code)
        if m_max is None:
            continue
        target_end = min(m_max, end_dt)
        last_dt = signal_latest.get(code)

        if last_dt is None:
            plan_start = start_dt
            status = "missing"
            reason = "该股票尚无形态 events"
        elif last_dt < target_end:
            plan_start = max(start_dt, (last_dt - pd.Timedelta(days=rewind_days)).floor("D"))
            status = "stale"
            reason = f"events 末日={last_dt.date()}，需补到 {target_end.date()}"
        else:
            plan_start = None
            status = "up_to_date"
            reason = f"events 末日={last_dt.date()}，已覆盖目标区间"

        rows.append(
            {
                "htsc_code": code,
                "lookback_days": lookback_days,
                "last_dt": last_dt,
                "status": status,
                "reason": reason,
                "plan_start": plan_start,
                "plan_end": target_end if plan_start is not None else None,
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "htsc_code",
                "lookback_days",
                "last_dt",
                "status",
                "reason",
                "plan_start",
                "plan_end",
            ]
        )
    plan_df = pd.DataFrame(rows).sort_values(["status", "htsc_code"], ascending=[True, True]).reset_index(drop=True)
    return plan_df


def _plan_codes(plan_df: pd.DataFrame) -> list[str]:
    need = plan_df[plan_df["status"].isin(["missing", "stale"])].copy()
    return need["htsc_code"].astype(str).tolist()


def _compute_query_window(
    plan_df: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
    lookback_days: int,
) -> tuple[str, str, pd.Timestamp, pd.Timestamp]:
    need = plan_df[plan_df["status"].isin(["missing", "stale"])].copy()
    if need.empty:
        raise ValueError("补写计划为空")
    effective_start = min(pd.Timestamp(x).floor("D") for x in need["plan_start"])
    end_dt = pd.Timestamp(end_date).floor("D")
    query_start = (effective_start - pd.Timedelta(days=int(lookback_days) + int(LOOKBACK_BUFFER_DAYS))).floor("D")
    start_dt = pd.Timestamp(start_date).floor("D")
    if query_start < start_dt:
        query_start = start_dt
    return query_start.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"), effective_start, end_dt


def print_plan_summary(plan_df: pd.DataFrame, *, lookback_days: int, query_start: str, query_end: str) -> None:
    need = plan_df[plan_df["status"].isin(["missing", "stale"])]
    print(f"[PLAN] 回看窗口(天): {lookback_days} + buffer {LOOKBACK_BUFFER_DAYS}")
    print(f"[PLAN] 查询区间(含回看): {query_start} ~ {query_end}")
    print(f"[PLAN] 待补写股票: {len(need)} / {len(plan_df)}")
    if not need.empty:
        print(
            "[PLAN] 补写起点范围: "
            f"{need['plan_start'].min()} ~ {need['plan_start'].max()}"
        )
        preview = need[["htsc_code", "status", "last_dt", "plan_start", "plan_end"]].head(10)
        print(preview.to_string(index=False))


def _filter_signals_by_stock_plan(
    signals_df: pd.DataFrame,
    plan_df: pd.DataFrame,
) -> pd.DataFrame:
    if signals_df.empty:
        return signals_df
    need = plan_df[plan_df["status"].isin(["missing", "stale"])][["htsc_code", "plan_start", "plan_end"]].copy()
    if need.empty:
        return signals_df.iloc[0:0].copy()
    plan_map = {
        str(row["htsc_code"]): (
            pd.Timestamp(row["plan_start"]).floor("D"),
            pd.Timestamp(row["plan_end"]).floor("D"),
        )
        for _, row in need.iterrows()
    }

    def _keep(row) -> bool:
        code = str(row["Contract"])
        bounds = plan_map.get(code)
        if bounds is None:
            return False
        plan_start, plan_end = bounds
        event_dt = pd.Timestamp(_date_to_yyyymmdd(row["Date"]), format="%Y%m%d").floor("D")
        return plan_start <= event_dt <= plan_end

    mask = signals_df.apply(_keep, axis=1)
    filtered = signals_df.loc[mask].copy()
    print(f"[FILTER/plan] 保留补写窗口内信号 {len(filtered)} / {len(signals_df)}")
    return filtered


def _load_existing_event_pairs(
    output_base: Path,
    *,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
    target_codes: list[str] | None = None,
) -> set[tuple[str, pd.Timestamp, str]]:
    events_glob = str(output_base / "events" / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")
    conn = duckdb.connect(database=":memory:")
    try:
        try:
            rows = conn.execute(
                f"""
                SELECT
                    UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                    {_BAR_TIME_SQL} AS bar_time,
                    TRIM(CAST(signal_name AS VARCHAR)) AS signal_name
                FROM read_parquet(?, hive_partitioning = true, union_by_name = true)
                WHERE htsc_code IS NOT NULL
                  AND signal_name IS NOT NULL
                """,
                [events_glob],
            ).fetchdf()
        except duckdb.Error:
            return set()
    finally:
        conn.close()

    if rows.empty:
        return set()
    rows["time"] = pd.to_datetime(rows["bar_time"], errors="coerce", utc=True).dt.tz_convert(None).dt.floor("D")
    rows = rows.dropna(subset=["time"])
    rows = rows[(rows["time"] >= start_dt) & (rows["time"] <= end_dt)]
    if target_codes:
        code_set = {str(c).strip().upper() for c in target_codes}
        rows = rows[rows["htsc_code"].astype(str).str.upper().isin(code_set)]
    pairs = {
        (str(r["htsc_code"]).upper(), pd.Timestamp(r["time"]).floor("D"), str(r["signal_name"]))
        for _, r in rows.iterrows()
    }
    return pairs


def _filter_signals_to_missing_pairs(
    signals_df: pd.DataFrame,
    existing_pairs: set[tuple[str, pd.Timestamp, str]],
) -> pd.DataFrame:
    if signals_df.empty:
        return signals_df

    def _pair(row) -> tuple[str, pd.Timestamp, str]:
        return (
            str(row["Contract"]).upper(),
            pd.Timestamp(_date_to_yyyymmdd(row["Date"]), format="%Y%m%d").floor("D"),
            str(row["signal_name"]),
        )

    pairs = signals_df.apply(_pair, axis=1)
    keep_mask = ~pairs.isin(existing_pairs)
    filtered = signals_df.loc[keep_mask].copy()
    print(
        f"[FILTER/missing] 自动缺失事件 {len(filtered)} / {len(signals_df)} "
        f"(已有 {len(existing_pairs)} 对)"
    )
    return filtered


def _yyyymmdd_to_unix_day_start(value: int) -> int:
    dt = datetime.strptime(str(int(value)), "%Y%m%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _unix_day_start_from_any(value) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        iv = int(value)
        if 19000101 <= iv <= 21001231:
            return _yyyymmdd_to_unix_day_start(iv)
        if iv > 10_000_000_000:
            iv = iv // 1000
        if iv > 86400 * 10:
            return int(iv // 86400 * 86400)
    return _yyyymmdd_to_unix_day_start(_date_to_yyyymmdd(value))


def _write_part_parquet(df: pl.DataFrame, file_path: Path) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = file_path.parent / ".__tmp_writes__"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, 61):
        tmp_path = tmp_dir / f"part_{int(time.time() * 1000)}_{uuid.uuid4().hex}.parquet"
        try:
            df.write_parquet(str(tmp_path), compression="snappy")
            os.replace(str(tmp_path), str(file_path))
            return
        except OSError as exc:
            last_error = exc
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            if attempt == 1 or attempt % 5 == 0:
                print(f"[WARN] 写入被占用，等待重试: {file_path} ({attempt}/60)")
            time.sleep(1.0)
    raise OSError(f"写入 parquet 失败: {file_path}") from last_error


def fetch_universe_codes_from_market_equity(market_equity_path: str) -> list[str]:
    if not os.path.isdir(market_equity_path):
        raise FileNotFoundError(f"market_equity_data 目录不存在: {market_equity_path}")

    parquet_glob = _glob_parquet_pattern(market_equity_path)
    conn = duckdb.connect(database=":memory:")
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code
            FROM read_parquet(?, hive_partitioning = true, union_by_name = true)
            WHERE htsc_code IS NOT NULL
              AND TRIM(CAST(htsc_code AS VARCHAR)) <> ''
              AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) NOT LIKE '%.YKRS'
            ORDER BY htsc_code
            """,
            [parquet_glob],
        ).fetchdf()
    finally:
        conn.close()

    if rows.empty:
        raise RuntimeError(f"未在 {market_equity_path} 找到任何股票代码")
    return rows["htsc_code"].astype(str).tolist()


def resolve_codes(codes_arg: str, market_equity_path: str) -> list[str]:
    raw = str(codes_arg).strip()
    if not raw or raw.upper() in {"ALL", "*", "FULL", "MARKET"}:
        codes = fetch_universe_codes_from_market_equity(market_equity_path)
        print(f"[UNIVERSE] 全市场 {len(codes)} 只（已排除 .YKRS）")
        return codes
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def _chunk_list(items: list[str], size: int) -> list[list[str]]:
    if size <= 0:
        return [items]
    return [items[i : i + size] for i in range(0, len(items), size)]


def _wide_ohlcv_from_long(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows = rows.sort_values(["date_key", "htsc_code"])
    dup_mask = rows.duplicated(subset=["htsc_code", "date_key"], keep=False)
    if dup_mask.any():
        before = len(rows)
        rows = rows.drop_duplicates(subset=["htsc_code", "date_key"], keep="last")
        print(f"[DEDUP] {before} -> {len(rows)} 行（htsc_code+date_key 保留最后一条）")

    wide = (
        rows.set_index(["date_key", "htsc_code"])[["open", "high", "low", "close", "volume"]]
        .sort_index()
        .unstack("htsc_code")
    )
    open_prices = wide["open"].astype(float, copy=False)
    high_prices = wide["high"].astype(float, copy=False)
    low_prices = wide["low"].astype(float, copy=False)
    close_prices = wide["close"].astype(float, copy=False)
    volume = wide["volume"].fillna(0.0).astype(float, copy=False)
    return open_prices, high_prices, low_prices, close_prices, volume


def load_ohlcv_from_duckdb(
    market_equity_path: str,
    *,
    query_start_date: str,
    query_end_date: str,
    target_codes: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not os.path.isdir(market_equity_path):
        raise FileNotFoundError(f"market_equity_data 目录不存在: {market_equity_path}")

    parquet_glob = _glob_parquet_pattern(market_equity_path)
    filters = [
        "open IS NOT NULL",
        "high IS NOT NULL",
        "low IS NOT NULL",
        "close IS NOT NULL",
        f"CAST(strftime({_BAR_TIME_SQL}, '%Y-%m-%d') AS DATE) >= DATE ?",
        f"CAST(strftime({_BAR_TIME_SQL}, '%Y-%m-%d') AS DATE) <= DATE ?",
        "UPPER(TRIM(CAST(htsc_code AS VARCHAR))) NOT LIKE '%.YKRS'",
    ]
    params: list = [parquet_glob, query_start_date, query_end_date]

    if target_codes:
        placeholders = ", ".join(["?"] * len(target_codes))
        filters.append(f"UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN ({placeholders})")
        params.extend([c.upper() for c in target_codes])
        print(f"[LOAD] 指定标的 {len(target_codes)} 只，单次查询")
    else:
        print("[LOAD] 全市场单次查询（已排除 .YKRS）")

    sql = f"""
    SELECT
        UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
        {_BAR_TIME_SQL} AS bar_time,
        TRY_CAST(open AS DOUBLE) AS open,
        TRY_CAST(high AS DOUBLE) AS high,
        TRY_CAST(low AS DOUBLE) AS low,
        TRY_CAST(close AS DOUBLE) AS close,
        TRY_CAST(volume AS DOUBLE) AS volume
    FROM read_parquet(?, hive_partitioning = true, union_by_name = true)
    WHERE {' AND '.join(filters)}
    ORDER BY htsc_code, bar_time
    """

    conn = duckdb.connect(database=":memory:")
    try:
        rows = conn.execute(sql, params).fetchdf()
    finally:
        conn.close()

    if rows.empty:
        raise RuntimeError(f"未在 {market_equity_path} 找到 OHLCV 数据")

    rows["date_key"] = pd.to_datetime(rows["bar_time"], errors="coerce").dt.strftime("%Y%m%d").astype("int64")
    rows = rows.dropna(subset=["date_key"])
    print(
        f"[UNSTACK] long_rows={len(rows)} codes={rows['htsc_code'].nunique()} "
        f"dates={rows['date_key'].nunique()} window={query_start_date}~{query_end_date}"
    )
    t0 = time.perf_counter()
    result = _wide_ohlcv_from_long(rows)
    print(f"[UNSTACK] wide_shape={result[3].shape} elapsed={time.perf_counter() - t0:.2f}s")
    return result


def _build_trading_day_index(close_prices: pd.DataFrame) -> dict[str, list[int]]:
    trading_days = close_prices.index.to_numpy(dtype=np.int64, copy=False)
    day_unix = np.array([_yyyymmdd_to_unix_day_start(int(day)) for day in trading_days], dtype=np.int64)
    values = close_prices.to_numpy(dtype=np.float64, copy=False)
    day_index_by_code: dict[str, list[int]] = {}
    for j, code in enumerate(close_prices.columns):
        valid = day_unix[np.isfinite(values[:, j])]
        day_index_by_code[str(code)] = valid.astype(int).tolist()
    return day_index_by_code


def _resolve_start_time(confirm_unix: int, bar_span: int, trading_days: list[int]) -> int:
    if not trading_days:
        return confirm_unix
    try:
        idx = trading_days.index(confirm_unix)
    except ValueError:
        return confirm_unix
    start_idx = max(0, idx - max(int(bar_span) - 1, 0))
    return int(trading_days[start_idx])


def signals_to_frames(
    signals_df: pd.DataFrame,
    pattern,
    meta_module,
    trading_day_index: dict[str, list[int]],
) -> tuple[dict[str, pl.DataFrame], pl.DataFrame, dict]:
    strength_map = pattern.signal_strength
    if signals_df.empty:
        manifest = meta_module.build_pattern_manifest(strength_map)
        return {}, pl.DataFrame(), manifest

    manifest = meta_module.build_pattern_manifest(strength_map)
    factor_rows: dict[str, list[dict]] = {}
    event_rows: list[dict] = []

    for row in signals_df.itertuples(index=False):
        signal_name = str(getattr(row, "signal_name"))
        contract = str(getattr(row, "Contract"))
        direction = str(getattr(row, "direction"))
        confirm_unix = _unix_day_start_from_any(getattr(row, "Date"))

        default_strength = float(strength_map.get(signal_name, float(getattr(row, "strength"))))
        signed_value = abs(default_strength) if direction == "buy" else -abs(default_strength)
        if direction not in {"buy", "sell"}:
            signed_value = default_strength

        bar_span = meta_module.get_bar_span(signal_name)
        level = meta_module.strength_to_level(default_strength)
        trading_days = trading_day_index.get(contract, [])
        start_time = _resolve_start_time(confirm_unix, bar_span, trading_days)

        factor_rows.setdefault(signal_name, []).append(
            {"time": confirm_unix, "htsc_code": contract, "value": float(signed_value)}
        )
        event_rows.append(
            {
                "time": confirm_unix,
                "htsc_code": contract,
                "signal_name": signal_name,
                "value": float(signed_value),
                "level": level,
                "direction": direction,
                "bar_span": int(bar_span),
                "start_time": int(start_time),
            }
        )

    factor_frames = {
        name: pl.from_pandas(pd.DataFrame(rows)).sort(["time", "htsc_code"])
        for name, rows in factor_rows.items()
        if rows
    }
    events_frame = (
        pl.from_pandas(pd.DataFrame(event_rows)).sort(["time", "htsc_code", "signal_name"])
        if event_rows
        else pl.DataFrame()
    )
    return factor_frames, events_frame, manifest


def write_partitioned_outputs(
    factor_frames: dict[str, pl.DataFrame],
    events_frame: pl.DataFrame,
    output_base: Path,
) -> None:
    ts_tag = int(time.time() * 1000)

    for signal_name, frame in factor_frames.items():
        if frame.is_empty():
            continue
        pdf = frame.to_pandas()
        pdf["year"] = pd.to_datetime(pdf["time"], unit="s", utc=True).dt.year
        pdf["month"] = pd.to_datetime(pdf["time"], unit="s", utc=True).dt.month
        for (year, month), group in pdf.groupby(["year", "month"], sort=True):
            month_dir = output_base / f"factor={signal_name}" / f"year={int(year)}" / f"month={int(month):02d}"
            part_path = month_dir / f"part_{ts_tag}_{uuid.uuid4().hex}.parquet"
            out = pl.from_pandas(group[["time", "htsc_code", "value"]])
            _write_part_parquet(out, part_path)
            print(f"[WRITE] factor={signal_name} {year}-{int(month):02d} rows={len(out)} -> {part_path.name}")

    if not events_frame.is_empty():
        pdf = events_frame.to_pandas()
        pdf["year"] = pd.to_datetime(pdf["time"], unit="s", utc=True).dt.year
        pdf["month"] = pd.to_datetime(pdf["time"], unit="s", utc=True).dt.month
        for (year, month), group in pdf.groupby(["year", "month"], sort=True):
            month_dir = output_base / "events" / f"year={int(year)}" / f"month={int(month):02d}"
            part_path = month_dir / f"part_{ts_tag}_{uuid.uuid4().hex}.parquet"
            cols = ["time", "htsc_code", "signal_name", "value", "level", "direction", "bar_span", "start_time"]
            out = pl.from_pandas(group[cols])
            _write_part_parquet(out, part_path)
            print(f"[WRITE] events {year}-{int(month):02d} rows={len(out)} -> {part_path.name}")


def run_incremental_save(output_base: Path, python_exe: str, *, prefer_new: bool = False) -> None:
    cmd = [python_exe, str(INCREMENTAL_SAVE_SCRIPT), "--base-dir", str(output_base)]
    if prefer_new:
        cmd.append("--prefer-new")
    print(f"[RUN] {' '.join(cmd)}")
    completed = subprocess.run(cmd, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"形态面增量信号保存失败，exit={completed.returncode}")


def _run_pipeline_once(
    pattern,
    meta_module,
    market_equity_path: str,
    output_base: Path,
    *,
    query_start_date: str,
    query_end_date: str,
    plan_df: pd.DataFrame,
    target_codes: list[str] | None,
    check_missing_pairs: bool,
) -> int:
    need_codes = _plan_codes(plan_df)
    load_codes = target_codes if target_codes else None
    if load_codes is None and need_codes:
        load_codes = None

    open_prices, high_prices, low_prices, close_prices, volume = load_ohlcv_from_duckdb(
        market_equity_path,
        query_start_date=query_start_date,
        query_end_date=query_end_date,
        target_codes=load_codes,
    )

    if need_codes:
        keep_cols = [c for c in open_prices.columns if str(c).upper() in {x.upper() for x in need_codes}]
        if keep_cols:
            open_prices = open_prices[keep_cols]
            high_prices = high_prices[keep_cols]
            low_prices = low_prices[keep_cols]
            close_prices = close_prices[keep_cols]
            volume = volume[keep_cols]

    trading_day_index = _build_trading_day_index(close_prices)
    print(f"[COMPUTE] rows={len(close_prices.index)} cols={len(close_prices.columns)}")
    signals_df = pattern.get_detailed_signals_dataframe(
        open_prices,
        high_prices,
        low_prices,
        close_prices,
        volume,
        enabled_signals=None,
    )
    print(f"[SIGNALS] raw events={len(signals_df)}")

    signals_df = _filter_signals_by_stock_plan(signals_df, plan_df)
    if check_missing_pairs and not signals_df.empty:
        need = plan_df[plan_df["status"].isin(["missing", "stale"])]
        write_start = min(pd.Timestamp(x).floor("D") for x in need["plan_start"])
        write_end = max(pd.Timestamp(x).floor("D") for x in need["plan_end"])
        existing_pairs = _load_existing_event_pairs(
            output_base,
            start_dt=write_start,
            end_dt=write_end,
            target_codes=need_codes,
        )
        signals_df = _filter_signals_to_missing_pairs(signals_df, existing_pairs)

    if signals_df.empty:
        print("[WRITE] 无新增事件，跳过落盘")
        return 0

    factor_frames, events_frame, _manifest = signals_to_frames(
        signals_df,
        pattern,
        meta_module,
        trading_day_index,
    )
    write_partitioned_outputs(factor_frames, events_frame, output_base)
    return len(signals_df)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成蜡烛图（无成交量）形态信号")
    parser.add_argument("--codes", default=DEFAULT_CODES, help="逗号分隔；留空=全市场（排除 .YKRS）")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=">0 时分批（legacy）；0=单次全市场查询（默认，对齐 notebook）",
    )
    parser.add_argument("--market-equity-path", default=DEFAULT_MARKET_EQUITY_PATH)
    parser.add_argument("--output-base", default=DEFAULT_OUTPUT_BASE)
    parser.add_argument(
        "--merge",
        action="store_true",
        help="写 part 后自动合并 merged（默认不合并，对齐 notebook）",
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "full"),
        default=DEFAULT_MODE,
        help="auto=按 events 缺失检测补写；full=从 start-date 全量重算并写",
    )
    parser.add_argument("--start-date", default=DEFAULT_START_DATE, help="补写/全量起点，默认 2010-01-01")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help="形态算法回看窗口(日历天)；0=自动",
    )
    parser.add_argument("--python-exe", default=sys.executable)
    args = parser.parse_args()

    start_date = _normalize_date_str(args.start_date)
    end_date = datetime.now().strftime("%Y-%m-%d")
    if pd.Timestamp(start_date) > pd.Timestamp(end_date):
        raise ValueError(f"start-date（{start_date}）不能晚于今天（{end_date}）")

    output_base = Path(args.output_base)
    output_base.mkdir(parents=True, exist_ok=True)

    Pattern = _load_pattern_class()
    meta_module = _load_meta_module()
    pattern = Pattern()
    lookback_days = compute_required_lookback_days(meta_module, args.lookback_days)

    manifest = meta_module.build_pattern_manifest(pattern.signal_strength)
    meta_module.write_manifest(manifest, output_base)
    print(
        f"[MANIFEST] patterns={len(manifest.get('patterns', {}))} -> "
        f"{output_base / meta_module.MANIFEST_FILE_NAME}"
    )

    signal_latest = scan_signal_latest_from_output(output_base)
    market_min, market_max = scan_market_date_range_by_code(args.market_equity_path)

    raw_codes = str(args.codes).strip()
    is_full_market = not raw_codes or raw_codes.upper() in {"ALL", "*", "FULL", "MARKET"}
    if is_full_market:
        codes = sorted(market_max.keys())
        codes = [c for c in codes if not c.endswith(".YKRS")]
        print(f"[UNIVERSE] 全市场 {len(codes)} 只")
    else:
        codes = resolve_codes(args.codes, args.market_equity_path)

    mode = str(args.mode).lower()
    if mode == "auto" and not signal_latest:
        print("[MODE] auto：无历史 events，按 full 处理")
        mode = "full"

    if mode == "full":
        plan_rows = []
        for code in codes:
            m_max = market_max.get(code)
            if m_max is None:
                continue
            plan_rows.append(
                {
                    "htsc_code": code,
                    "lookback_days": lookback_days,
                    "last_dt": signal_latest.get(code),
                    "status": "missing" if code not in signal_latest else "stale",
                    "reason": "full 模式全量重算",
                    "plan_start": pd.Timestamp(start_date).floor("D"),
                    "plan_end": min(m_max, pd.Timestamp(end_date).floor("D")),
                }
            )
        plan_df = pd.DataFrame(plan_rows)
        check_missing = False
    else:
        plan_df = build_stock_fill_plan(
            codes,
            signal_latest,
            market_max,
            start_date=start_date,
            end_date=end_date,
            lookback_days=lookback_days,
        )
        check_missing = True

    need_codes = _plan_codes(plan_df)
    if not need_codes:
        print("[DONE] 形态 events 已与行情对齐，无需补写")
        return

    query_start, query_end, effective_start, effective_end = _compute_query_window(
        plan_df,
        start_date=start_date,
        end_date=end_date,
        lookback_days=lookback_days,
    )
    print(f"[MODE] {mode}（自动缺失检测补写）")
    print(f"[RANGE] 目标区间: {start_date} ~ {end_date}")
    print_plan_summary(plan_df, lookback_days=lookback_days, query_start=query_start, query_end=query_end)

    target_codes = None if is_full_market else codes
    batch_size = int(args.batch_size)

    total_events = 0
    if batch_size > 0:
        batches = _chunk_list(need_codes, batch_size)
        print(f"[BATCH] legacy 分批 {len(batches)} 批，建议 --batch-size 0 对齐 notebook")
        sub_plan = plan_df[plan_df["htsc_code"].isin(need_codes)].copy()
        for batch_idx, batch_codes in enumerate(batches, start=1):
            batch_plan = sub_plan[sub_plan["htsc_code"].isin(batch_codes)].copy()
            print(f"[BATCH {batch_idx}/{len(batches)}] codes={len(batch_codes)}")
            total_events += _run_pipeline_once(
                pattern,
                meta_module,
                args.market_equity_path,
                output_base,
                query_start_date=query_start,
                query_end_date=query_end,
                plan_df=batch_plan,
                target_codes=batch_codes,
                check_missing_pairs=check_missing,
            )
    else:
        total_events = _run_pipeline_once(
            pattern,
            meta_module,
            args.market_equity_path,
            output_base,
            query_start_date=query_start,
            query_end_date=query_end,
            plan_df=plan_df,
            target_codes=target_codes,
            check_missing_pairs=check_missing,
        )

    print(
        f"[TOTAL] mode={mode} codes={len(need_codes)} "
        f"write≈{effective_start.date()}~{effective_end.date()} new_events={total_events}"
    )
    print("说明: 本流程只追加 part_*.parquet；merged 合并请另行运行 形态面增量信号保存.py")

    if args.merge and total_events > 0:
        run_incremental_save(output_base, args.python_exe, prefer_new=True)

    print("[DONE] 形态蜡烛信号生成完成")


if __name__ == "__main__":
    main()
