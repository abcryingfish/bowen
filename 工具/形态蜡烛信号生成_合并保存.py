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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
DEFAULT_MARKET_EQUITY_PATH = r"D:\database\stock_basic_data_daily"
DEFAULT_MARKET_ETF_PATH = r"D:\database\ETF_basic_data_daily"
DEFAULT_MARKET_SOURCE_PATHS = [DEFAULT_MARKET_EQUITY_PATH, DEFAULT_MARKET_ETF_PATH]
DEFAULT_ADJ_WIDE_BASE_PATH = r"D:\database\stock_adj_daily\wide_xdy"
DEFAULT_OUTPUT_BASE = r"D:\database\signal_daily_形态\candlestick_no_vol"
DEFAULT_CODES = ""
DEFAULT_BATCH_SIZE = 0
DEFAULT_MODE = "auto"
DEFAULT_START_DATE = "2010-01-01"
DEFAULT_LOOKBACK_DAYS = 0
LOOKBACK_BUFFER_DAYS = 20
INCREMENTAL_SAVE_SCRIPT = PROJECT_ROOT / "工具" / "形态面增量信号保存.py"
_PATTERN_LOOKBACK_INTERNAL = 45
_OHLC_COLUMNS = ["open", "high", "low", "close"]


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


def _normalize_market_source_paths(source_paths: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(source_paths, str):
        raw_parts = source_paths.replace("\n", ";").split(";")
    else:
        raw_parts = [str(path) for path in source_paths]
    return [str(path).strip() for path in raw_parts if str(path).strip()]


def _existing_market_daily_globs(source_paths: str | list[str] | tuple[str, ...]) -> list[str]:
    globs: list[str] = []
    for source_path in _normalize_market_source_paths(source_paths):
        root = Path(source_path)
        if not root.exists():
            print(f"[WARN] 日 K 数据目录不存在，已跳过: {root}")
            continue
        if not list(root.glob("year=*/month=*/merged.parquet")):
            print(f"[WARN] 日 K 数据目录无 merged.parquet，已跳过: {root}")
            continue
        globs.append(_glob_parquet_pattern(str(root)))
    return globs


def _read_parquet_source_sql(source_globs: list[str]) -> str:
    if not source_globs:
        raise FileNotFoundError("没有可用日 K 数据源")
    escaped = [str(path).replace("\\", "/").replace("'", "''") for path in source_globs]
    path_list = "[" + ", ".join(f"'{path}'" for path in escaped) + "]"
    return f"read_parquet({path_list}, hive_partitioning = true, union_by_name = true)"


def resolve_market_source_paths(args: argparse.Namespace) -> list[str]:
    market_paths = str(getattr(args, "market_paths", "") or "").strip()
    if market_paths:
        return _normalize_market_source_paths(market_paths)

    paths = [args.market_equity_path]
    etf_path = str(getattr(args, "market_etf_path", "") or "").strip()
    if etf_path:
        paths.append(etf_path)
    return _normalize_market_source_paths(paths)


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


def scan_market_date_range_by_code(
    market_source_paths: str | list[str] | tuple[str, ...],
) -> tuple[dict[str, pd.Timestamp], dict[str, pd.Timestamp]]:
    source_globs = _existing_market_daily_globs(market_source_paths)
    source_sql = _read_parquet_source_sql(source_globs)
    conn = duckdb.connect(database=":memory:")
    try:
        rows = conn.execute(
            f"""
            SELECT
                UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                MIN({_BAR_TIME_SQL}) AS min_time,
                MAX({_BAR_TIME_SQL}) AS max_time
            FROM {source_sql}
            WHERE htsc_code IS NOT NULL
            GROUP BY 1
            """
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
    full_history_missing_codes: set[str] | None = None,
) -> pd.DataFrame:
    """按标的生成补写计划，语义对齐 notebook 的 build_factor_fill_plan。"""
    start_dt = pd.Timestamp(start_date).floor("D")
    end_dt = pd.Timestamp(end_date).floor("D")
    full_history_missing_codes = {str(code).strip().upper() for code in (full_history_missing_codes or set())}
    latest_values = [
        pd.Timestamp(value).floor("D")
        for value in signal_latest.values()
        if value is not None and pd.notna(value)
    ]
    incremental_mark = max(latest_values) if latest_values else start_dt
    effective_start_dt = max(start_dt, incremental_mark)
    rewind_days = int(lookback_days) + int(LOOKBACK_BUFFER_DAYS)
    rows: list[dict[str, object]] = []

    for code in codes:
        m_max = market_max.get(code)
        if m_max is None:
            continue
        target_end = min(m_max, end_dt)
        last_dt = signal_latest.get(code)

        if last_dt is None:
            if code in full_history_missing_codes:
                plan_start = start_dt
                reason = f"新增非股票标的尚无形态 events，从 start-date={start_dt.date()} 回补历史"
            else:
                plan_start = effective_start_dt
                reason = f"该标的尚无形态 events，按全市场 mark={incremental_mark.date()} 增量补写"
            status = "missing"
        elif last_dt < target_end:
            plan_start = max(effective_start_dt, (last_dt - pd.Timedelta(days=rewind_days)).floor("D"))
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
    print(f"[PLAN] 待补写标的: {len(need)} / {len(plan_df)}")
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
        event_dt = _yyyymmdd_to_ts(_date_to_yyyymmdd(row["Date"]))
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
            _yyyymmdd_to_ts(_date_to_yyyymmdd(row["Date"])),
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


def fetch_universe_codes_from_market_equity(market_source_paths: str | list[str] | tuple[str, ...]) -> list[str]:
    source_globs = _existing_market_daily_globs(market_source_paths)
    source_sql = _read_parquet_source_sql(source_globs)
    conn = duckdb.connect(database=":memory:")
    try:
        rows = conn.execute(
            f"""
            SELECT DISTINCT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code
            FROM {source_sql}
            WHERE htsc_code IS NOT NULL
              AND TRIM(CAST(htsc_code AS VARCHAR)) <> ''
              AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) NOT LIKE '%.YKRS'
            ORDER BY htsc_code
            """
        ).fetchdf()
    finally:
        conn.close()

    if rows.empty:
        raise RuntimeError(f"未在 {source_globs} 找到任何标的代码")
    return rows["htsc_code"].astype(str).tolist()


def resolve_codes(codes_arg: str, market_source_paths: str | list[str] | tuple[str, ...]) -> list[str]:
    raw = str(codes_arg).strip()
    if not raw or raw.upper() in {"ALL", "*", "FULL", "MARKET"}:
        codes = fetch_universe_codes_from_market_equity(market_source_paths)
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


def _backward_factor_series(xdy_series: pd.Series) -> pd.Series:
    values = pd.to_numeric(xdy_series, errors="coerce").astype(np.float64).sort_index()
    values = values.replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return pd.Series(dtype=np.float64)
    raw_values = values.to_numpy(dtype=np.float64)
    segment_start = np.ones(len(raw_values), dtype=bool)
    if len(raw_values) > 1:
        segment_start[1:] = raw_values[1:] != raw_values[:-1]
    segment_factors = np.where(segment_start, raw_values, 1.0)
    return pd.Series(np.cumprod(segment_factors), index=values.index, dtype=np.float64)


def load_wide_xdy_series(
    adj_wide_base_path: str,
    target_codes: list[str] | None = None,
) -> dict[str, pd.Series]:
    base = Path(adj_wide_base_path)
    if not base.exists():
        print(f"[ADJ] 复权 wide_xdy 目录不存在，跳过比例后复权: {adj_wide_base_path}")
        return {}

    paths = sorted(base.glob("year=*/month=*/merged.parquet"))
    if not paths:
        print(f"[ADJ] 未找到 wide_xdy merged.parquet，跳过比例后复权: {adj_wide_base_path}")
        return {}

    code_filter = {str(c).strip().upper() for c in target_codes} if target_codes else None
    series_by_code: dict[str, list[pd.Series]] = {}

    for path in paths:
        try:
            frame = pd.read_parquet(path)
        except Exception as exc:
            print(f"[WARN] 读取复权 wide_xdy 失败: {path} | {exc}")
            continue
        if frame.empty:
            continue

        code_col = "htsc_code" if "htsc_code" in frame.columns else frame.columns[0]
        frame[code_col] = frame[code_col].astype(str).str.strip().str.upper()
        if code_filter:
            frame = frame[frame[code_col].isin(code_filter)]
        if frame.empty:
            continue

        date_cols = []
        for col in frame.columns:
            if col == code_col:
                continue
            day = pd.to_datetime(str(col), format="%Y/%m/%d", errors="coerce")
            if pd.isna(day):
                continue
            date_cols.append((col, pd.Timestamp(day).normalize()))
        if not date_cols:
            continue

        for _, row in frame.iterrows():
            code = str(row[code_col]).strip().upper()
            values = {}
            for col, day in date_cols:
                value = pd.to_numeric(row[col], errors="coerce")
                if pd.isna(value):
                    continue
                values[day] = float(value)
            if values:
                series_by_code.setdefault(code, []).append(pd.Series(values, dtype=np.float64))

    out: dict[str, pd.Series] = {}
    for code, parts in series_by_code.items():
        merged = pd.concat(parts).sort_index()
        merged = merged[~merged.index.duplicated(keep="last")]
        out[code] = merged
    print(f"[ADJ] 加载 wide_xdy 比例复权因子 {len(out)} 只")
    return out


def apply_ratio_backward_adjustment(rows: pd.DataFrame, xdy_by_code: dict[str, pd.Series]) -> pd.DataFrame:
    if rows.empty or not xdy_by_code:
        return rows

    out = rows.copy()
    out["htsc_code"] = out["htsc_code"].astype(str).str.strip().str.upper()
    days = pd.to_datetime(out["date_key"].astype(str), format="%Y%m%d", errors="coerce").dt.normalize()
    adjusted_rows = 0

    for code, idx in out.groupby("htsc_code", sort=False).groups.items():
        xdy_series = xdy_by_code.get(code)
        if xdy_series is None or xdy_series.empty:
            continue
        factors_by_day = _backward_factor_series(xdy_series)
        if factors_by_day.empty:
            continue

        row_pos = out.index.get_indexer(idx)
        row_days = days.iloc[row_pos]
        first_day = factors_by_day.index.min()
        last_day = factors_by_day.index.max()
        last_factor = float(factors_by_day.iloc[-1])
        factors = row_days.map(factors_by_day).astype(float)
        factors = factors.mask(row_days > last_day, last_factor)
        factors = factors.mask(row_days < first_day, 1.0)
        factors = factors.fillna(1.0).to_numpy(dtype=np.float64)

        values = out.iloc[row_pos][_OHLC_COLUMNS].to_numpy(dtype=np.float64, copy=True)
        values = values * factors[:, None]
        out.iloc[row_pos, out.columns.get_indexer(_OHLC_COLUMNS)] = values
        adjusted_rows += int(len(row_pos))

    print(f"[ADJ] wide_xdy backward 比例后复权 rows={adjusted_rows} / {len(out)}")
    return out


def load_ohlcv_from_duckdb(
    market_source_paths: str | list[str] | tuple[str, ...],
    *,
    query_start_date: str,
    query_end_date: str,
    target_codes: list[str] | None = None,
    adj_wide_base_path: str = DEFAULT_ADJ_WIDE_BASE_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    source_globs = _existing_market_daily_globs(market_source_paths)
    source_sql = _read_parquet_source_sql(source_globs)
    filters = [
        "open IS NOT NULL",
        "high IS NOT NULL",
        "low IS NOT NULL",
        "close IS NOT NULL",
        f"CAST(strftime({_BAR_TIME_SQL}, '%Y-%m-%d') AS DATE) >= CAST(? AS DATE)",
        f"CAST(strftime({_BAR_TIME_SQL}, '%Y-%m-%d') AS DATE) <= CAST(? AS DATE)",
        "UPPER(TRIM(CAST(htsc_code AS VARCHAR))) NOT LIKE '%.YKRS'",
    ]
    params: list = [query_start_date, query_end_date]

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
    FROM {source_sql}
    WHERE {' AND '.join(filters)}
    ORDER BY htsc_code, bar_time
    """

    conn = duckdb.connect(database=":memory:")
    try:
        rows = conn.execute(sql, params).fetchdf()
    finally:
        conn.close()

    if rows.empty:
        raise RuntimeError(f"未在 {source_globs} 找到 OHLCV 数据")

    rows["date_key"] = pd.to_datetime(rows["bar_time"], errors="coerce").dt.strftime("%Y%m%d").astype("int64")
    rows = rows.dropna(subset=["date_key"])
    xdy_by_code = load_wide_xdy_series(
        adj_wide_base_path,
        target_codes=target_codes,
    )
    rows = apply_ratio_backward_adjustment(rows, xdy_by_code)
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



# ---- Inline logic from 工具/形态面增量信号保存.py ----
FACTOR_KEY_COLS = ["time", "htsc_code"]
EVENT_KEY_COLS = ["time", "htsc_code", "signal_name"]
DEFAULT_BASE_DIR = r"D:\database\signal_daily_形态\candlestick_no_vol"
EVENTS_DIR_NAME = "events"


def _align_polars_schema(df: pl.DataFrame, columns_order: list[str]) -> pl.DataFrame:
    aligned = df
    for col in columns_order:
        if col not in aligned.columns:
            aligned = aligned.with_columns(pl.lit(None).alias(col))
    return aligned.select(columns_order)


def _merge_with_priority(
    old_df: pl.DataFrame,
    new_df: pl.DataFrame,
    key_cols: list[str],
    *,
    prefer_new: bool,
) -> pl.DataFrame:
    """prefer_new=False 时旧 merged 优先（历史全量）；True 时新 part 优先（增量更新）。"""
    all_cols = list(dict.fromkeys([*old_df.columns, *new_df.columns]))
    value_cols = [c for c in all_cols if c not in key_cols]

    old_prio, new_prio = (1, 0) if prefer_new else (0, 1)
    old_aligned = (
        _align_polars_schema(old_df, all_cols)
        .sort(key_cols)
        .unique(subset=key_cols, keep="last")
        .with_columns(pl.lit(old_prio).alias("__prio"))
    )
    new_aligned = (
        _align_polars_schema(new_df, all_cols)
        .sort(key_cols)
        .unique(subset=key_cols, keep="last")
        .with_columns(pl.lit(new_prio).alias("__prio"))
    )

    agg_exprs = [pl.col(c).drop_nulls().first().alias(c) for c in value_cols]
    merged = (
        pl.concat([old_aligned, new_aligned], how="vertical_relaxed")
        .sort([*key_cols, "__prio"])
        .group_by(key_cols, maintain_order=True)
        .agg(agg_exprs)
        .select(all_cols)
        .sort(key_cols)
    )
    return merged


def _merge_preserve_old_values(
    old_df: pl.DataFrame,
    new_df: pl.DataFrame,
    key_cols: list[str],
) -> pl.DataFrame:
    return _merge_with_priority(old_df, new_df, key_cols, prefer_new=False)


def _cleanup_tmp_file(tmp_path: str) -> None:
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _write_parquet_atomic_with_retry(
    df: pl.DataFrame,
    file_path: str,
    *,
    compression: str = "snappy",
    max_retries: int = 60,
    sleep_seconds: float = 1.0,
) -> None:
    dir_path = os.path.dirname(file_path)
    os.makedirs(dir_path, exist_ok=True)
    tmp_dir = os.path.join(dir_path, ".__tmp_writes__")
    os.makedirs(tmp_dir, exist_ok=True)

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        tmp_path = os.path.join(
            tmp_dir,
            f"tmp_{os.getpid()}_{int(time.time() * 1000)}_{uuid.uuid4().hex}.bin",
        )
        try:
            df.write_parquet(tmp_path, compression=compression)
            os.replace(tmp_path, file_path)
            return
        except OSError as exc:
            last_error = exc
            _cleanup_tmp_file(tmp_path)
            if attempt == 1 or attempt % 5 == 0:
                print(f"[WARN] 写入被占用，等待重试: {file_path} ({attempt}/{max_retries})")
            time.sleep(sleep_seconds)

    raise OSError(f"写入 parquet 失败: {file_path}") from last_error


def _move_corrupt_parquet(file_path: str, reason: str) -> None:
    corrupt_path = f"{file_path}.corrupt.{int(time.time())}"
    print(f"[WARN] 历史分区不可读，已备份: {file_path} -> {corrupt_path}，原因: {reason}")
    try:
        os.replace(file_path, corrupt_path)
    except OSError as exc:
        print(f"[WARN] 备份损坏文件失败: {exc}")


def _read_existing_partition(file_path: str, key_cols: list[str]) -> pl.DataFrame | None:
    if not os.path.exists(file_path):
        return None

    try:
        if os.path.getsize(file_path) < 12:
            _move_corrupt_parquet(file_path, "文件小于 12 字节")
            return None
        df = pl.read_parquet(file_path)
        casts = [
            pl.col("time").cast(pl.Datetime),
            pl.col("htsc_code").cast(pl.Utf8),
        ]
        if "signal_name" in df.columns:
            casts.append(pl.col("signal_name").cast(pl.Utf8))
        return df.with_columns(casts)
    except Exception as exc:
        _move_corrupt_parquet(file_path, repr(exc))
        return None


def _resolve_factor_month_dirs(
    base_dir: Path,
    factor: str | None,
    year: int | None,
    month: int | None,
) -> list[Path]:
    if factor:
        factor_dirs = [base_dir / f"factor={factor}"]
    else:
        factor_dirs = sorted(base_dir.glob("factor=*"))

    month_dirs: list[Path] = []
    for factor_dir in factor_dirs:
        if not factor_dir.exists():
            continue
        year_dirs = [factor_dir / f"year={int(year)}"] if year else sorted(factor_dir.glob("year=*"))
        for year_dir in year_dirs:
            if not year_dir.exists():
                continue
            cur_month_dirs = (
                [year_dir / f"month={int(month):02d}"]
                if month
                else sorted(year_dir.glob("month=*"))
            )
            for month_dir in cur_month_dirs:
                if month_dir.exists():
                    month_dirs.append(month_dir)
    return month_dirs


def _resolve_events_month_dirs(
    base_dir: Path,
    year: int | None,
    month: int | None,
) -> list[Path]:
    events_base = base_dir / EVENTS_DIR_NAME
    if not events_base.exists():
        return []

    month_dirs: list[Path] = []
    year_dirs = [events_base / f"year={int(year)}"] if year else sorted(events_base.glob("year=*"))
    for year_dir in year_dirs:
        if not year_dir.exists():
            continue
        cur_month_dirs = (
            [year_dir / f"month={int(month):02d}"]
            if month
            else sorted(year_dir.glob("month=*"))
        )
        for month_dir in cur_month_dirs:
            if month_dir.exists():
                month_dirs.append(month_dir)
    return month_dirs


def compact_month_partition(
    month_dir: Path,
    *,
    key_cols: list[str],
    keep_parts: bool = False,
    prefer_new: bool = False,
) -> tuple[int, int]:
    part_paths = sorted(month_dir.glob("part_*.parquet"))
    if not part_paths:
        return 0, 0

    merged_path = month_dir / "merged.parquet"
    new_frames = [pl.read_parquet(str(path)) for path in part_paths if path.stat().st_size >= 12]
    if not new_frames:
        print(f"[SKIP] 无有效 part 文件: {month_dir}")
        return 0, 0

    new_df = (
        pl.concat(new_frames, how="vertical_relaxed", rechunk=True)
        .sort(key_cols)
        .unique(subset=key_cols, keep="last")
        .sort(key_cols)
    )

    old_df = _read_existing_partition(str(merged_path), key_cols)
    if old_df is None:
        save_df = new_df
        print(f"[NEW] {month_dir} 新建 merged (新 {len(new_df)})")
    else:
        save_df = _merge_with_priority(old_df, new_df, key_cols, prefer_new=prefer_new)
        tag = "新优先" if prefer_new else "旧优先"
        print(f"[MERGE/{tag}] {month_dir} (旧 {len(old_df)} + 新 {len(new_df)} => {len(save_df)})")

    _write_parquet_atomic_with_retry(save_df, str(merged_path), compression="snappy")

    if not keep_parts:
        for path in part_paths:
            try:
                path.unlink()
            except OSError as exc:
                print(f"[WARN] 删除 part 文件失败: {path}，原因: {exc}")

    return len(part_paths), len(save_df)


def _default_workers() -> int:
    cpu = os.cpu_count() or 4
    return max(1, min(4, cpu))


def _compact_task(
    month_dir: Path,
    key_cols: list[str],
    keep_parts: bool,
    prefer_new: bool,
) -> tuple[Path, int, int]:
    parts, rows = compact_month_partition(
        month_dir,
        key_cols=key_cols,
        keep_parts=keep_parts,
        prefer_new=prefer_new,
    )
    return month_dir, parts, rows


def _run_compact_jobs(
    month_dirs: list[Path],
    *,
    key_cols: list[str],
    keep_parts: bool,
    workers: int,
    label: str,
    prefer_new: bool = False,
) -> tuple[int, int]:
    if not month_dirs:
        print(f"没有找到需要处理的 {label} 月份目录。")
        return 0, 0

    print(f"待处理 {label} 月份目录数: {len(month_dirs)}，workers={max(1, int(workers))}")
    total_parts = 0
    touched_months = 0
    workers = max(1, int(workers))

    if workers == 1 or len(month_dirs) <= 1:
        for month_dir in month_dirs:
            parts, _ = compact_month_partition(
                month_dir,
                key_cols=key_cols,
                keep_parts=keep_parts,
                prefer_new=prefer_new,
            )
            if parts > 0:
                touched_months += 1
                total_parts += parts
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_compact_task, month_dir, key_cols, keep_parts, prefer_new): month_dir
                for month_dir in month_dirs
            }
            for future in as_completed(futures):
                month_dir = futures[future]
                try:
                    _, parts, _rows = future.result()
                except Exception as exc:
                    print(f"[ERROR] 处理失败: {month_dir}，原因: {exc}")
                    continue
                if parts > 0:
                    touched_months += 1
                    total_parts += parts

    print(f"{label} 处理完成: 命中月份 {touched_months}，合并 part 文件总数 {total_parts}")
    return touched_months, total_parts


def run_incremental_save(output_base: Path, python_exe: str, *, prefer_new: bool = False) -> None:
    """Inline version of 形态面增量信号保存.py for this combined script.

    python_exe is kept in the signature for CLI compatibility with the
    original generator; the combined version no longer starts a subprocess.
    """
    _ = python_exe
    base_dir = Path(output_base)
    if not base_dir.exists():
        raise FileNotFoundError(f"base_dir 不存在: {base_dir}")

    workers = _default_workers()
    print(f"[RUN] inline 形态面增量信号保存 --base-dir {base_dir} --prefer-new={prefer_new}")

    factor_month_dirs = _resolve_factor_month_dirs(
        base_dir=base_dir,
        factor=None,
        year=None,
        month=None,
    )
    _run_compact_jobs(
        factor_month_dirs,
        key_cols=FACTOR_KEY_COLS,
        keep_parts=False,
        workers=workers,
        label="factor",
        prefer_new=prefer_new,
    )

    events_month_dirs = _resolve_events_month_dirs(
        base_dir=base_dir,
        year=None,
        month=None,
    )
    _run_compact_jobs(
        events_month_dirs,
        key_cols=EVENT_KEY_COLS,
        keep_parts=False,
        workers=workers,
        label="events",
        prefer_new=prefer_new,
    )



def _run_pipeline_once(
    pattern,
    meta_module,
    market_source_paths: list[str],
    output_base: Path,
    *,
    query_start_date: str,
    query_end_date: str,
    plan_df: pd.DataFrame,
    target_codes: list[str] | None,
    check_missing_pairs: bool,
    adj_wide_base_path: str,
) -> int:
    need_codes = _plan_codes(plan_df)
    load_codes = target_codes if target_codes else None
    if load_codes is None and need_codes:
        load_codes = None

    open_prices, high_prices, low_prices, close_prices, volume = load_ohlcv_from_duckdb(
        market_source_paths,
        query_start_date=query_start_date,
        query_end_date=query_end_date,
        target_codes=load_codes,
        adj_wide_base_path=adj_wide_base_path,
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
    parser.add_argument("--market-etf-path", default=DEFAULT_MARKET_ETF_PATH)
    parser.add_argument(
        "--market-paths",
        default="",
        help="分号分隔的日 K 数据根目录；非空时覆盖 --market-equity-path/--market-etf-path",
    )
    parser.add_argument(
        "--adj-wide-base-path",
        default=DEFAULT_ADJ_WIDE_BASE_PATH,
        help="比例后复权 wide_xdy 根目录；默认 D:\\database\\stock_adj_daily\\wide_xdy",
    )
    parser.add_argument("--output-base", default=DEFAULT_OUTPUT_BASE)
    parser.add_argument(
        "--merge",
        action="store_true",
        help="兼容旧参数；合并版默认会在写 part 后自动合并 merged",
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="只写 part_*.parquet，不执行内置 merged 合并",
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
    market_source_paths = resolve_market_source_paths(args)
    print(f"[SOURCE] 日 K 数据源: {market_source_paths}")
    market_min, market_max = scan_market_date_range_by_code(market_source_paths)
    try:
        stock_code_set = set(fetch_universe_codes_from_market_equity([args.market_equity_path]))
    except Exception as exc:
        print(f"[WARN] 股票代码池读取失败，无法精确识别非股票新增标的: {exc}")
        stock_code_set = set()

    raw_codes = str(args.codes).strip()
    is_full_market = not raw_codes or raw_codes.upper() in {"ALL", "*", "FULL", "MARKET"}
    if is_full_market:
        codes = sorted(market_max.keys())
        codes = [c for c in codes if not c.endswith(".YKRS")]
        print(f"[UNIVERSE] 全市场 {len(codes)} 只")
    else:
        codes = resolve_codes(args.codes, market_source_paths)

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
            full_history_missing_codes={code for code in codes if code not in stock_code_set},
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
                market_source_paths,
                output_base,
                query_start_date=query_start,
                query_end_date=query_end,
                plan_df=batch_plan,
                target_codes=batch_codes,
                check_missing_pairs=check_missing,
                adj_wide_base_path=args.adj_wide_base_path,
            )
    else:
        total_events = _run_pipeline_once(
            pattern,
            meta_module,
            market_source_paths,
            output_base,
            query_start_date=query_start,
            query_end_date=query_end,
            plan_df=plan_df,
            target_codes=target_codes,
            check_missing_pairs=check_missing,
            adj_wide_base_path=args.adj_wide_base_path,
        )

    print(
        f"[TOTAL] mode={mode} codes={len(need_codes)} "
        f"write≈{effective_start.date()}~{effective_end.date()} new_events={total_events}"
    )
    print("说明: 合并版默认会在写 part_*.parquet 后执行内置 merged 合并。")

    if not args.no_merge and total_events > 0:
        run_incremental_save(output_base, args.python_exe, prefer_new=True)

    print("[DONE] 形态蜡烛信号生成完成")


if __name__ == "__main__":
    main()
