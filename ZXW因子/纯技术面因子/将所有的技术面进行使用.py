# -*- coding: utf-8 -*-
"""后复权、向量化生成全部纯技术面因子并增量写入本地因子库。"""
from __future__ import annotations

import argparse
import gc
import os
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, Sequence

import duckdb
import numpy as np
import pandas as pd
import polars as pl


ZXW_DIR = Path(__file__).resolve().parent.parent
if str(ZXW_DIR) not in sys.path:
    sys.path.append(str(ZXW_DIR))

from 纯技术面因子_bundle import (  # noqa: E402
    INDICATOR_NAMES,
    get_factor_catalog,
    get_factor_lookback_config,
    iter_pure_technical_factor_bundles,
)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


DEFAULT_START_DATE = "2010-01-01"
DEFAULT_STOCK_BASE_PATH = Path(r"D:\database\stock_basic_data_daily")
DEFAULT_INDEX_BASE_PATH = Path(r"D:\database\index_data_daily")
DEFAULT_ETF_BASE_PATH = Path(r"D:\database\ETF_basic_data_daily")
DEFAULT_ADJ_FACTOR_BASE_PATH = Path(r"D:\database\stock_adj_daily\adj_factor_daily")
DEFAULT_WIDE_XDY_BASE_PATH = Path(r"D:\database\stock_adj_daily\wide_xdy")
DEFAULT_OUTPUT_BASE_PATH = Path(r"D:\database\signal_daily")
FACTOR_PATH_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')
SIGNAL_KEY_COLUMNS = ["time", "htsc_code"]


def _normalize_date(value: str | pd.Timestamp) -> pd.Timestamp:
    result = pd.Timestamp(value).floor("D")
    if pd.isna(result):
        raise ValueError(f"无效日期: {value}")
    return result


def _month_starts(start_date: str | pd.Timestamp, end_date: str | pd.Timestamp) -> list[pd.Timestamp]:
    start = _normalize_date(start_date)
    end = _normalize_date(end_date)
    if start > end:
        raise ValueError(f"开始日期不能晚于结束日期: {start.date()} > {end.date()}")
    cursor = pd.Timestamp(start.year, start.month, 1)
    last = pd.Timestamp(end.year, end.month, 1)
    result: list[pd.Timestamp] = []
    while cursor <= last:
        result.append(cursor)
        cursor += pd.offsets.MonthBegin(1)
    return result


def _partition_paths(
    base_path: str | Path,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> list[Path]:
    root = Path(base_path)
    if not root.exists():
        return []
    paths: list[Path] = []
    for month_start in _month_starts(start_date, end_date):
        path = root / f"year={month_start.year:04d}" / f"month={month_start.month:02d}" / "merged.parquet"
        if path.is_file():
            paths.append(path)
    return paths


def _sql_path_list(paths: Iterable[str | Path]) -> str:
    values = [str(Path(path)).replace("\\", "/").replace("'", "''") for path in paths]
    if not values:
        raise ValueError("没有可用 Parquet 路径")
    return "[" + ", ".join(f"'{value}'" for value in values) + "]"


def _code_filter_sql(target_codes: Sequence[str] | None) -> str:
    codes = sorted({str(code).strip().upper() for code in (target_codes or []) if str(code).strip()})
    if not codes:
        return ""
    escaped = ", ".join("'" + code.replace("'", "''") + "'" for code in codes)
    return f"AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN ({escaped})"


def _market_paths(
    market_base_paths: Sequence[str | Path],
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> list[Path]:
    paths: list[Path] = []
    for base_path in market_base_paths:
        current = _partition_paths(base_path, start_date, end_date)
        if not current:
            print(f"[WARN] 日线数据源在目标区间无分区，已跳过: {base_path}")
        paths.extend(current)
    if not paths:
        raise FileNotFoundError("目标区间没有可用日线 merged.parquet")
    return paths


def _raw_market_sql(
    paths: Sequence[str | Path],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    target_codes: Sequence[str] | None,
) -> str:
    return f"""
SELECT
    CAST(time AS TIMESTAMP) AS time,
    UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
    TRY_CAST(open AS DOUBLE) AS open,
    TRY_CAST(high AS DOUBLE) AS high,
    TRY_CAST(low AS DOUBLE) AS low,
    TRY_CAST(close AS DOUBLE) AS close,
    TRY_CAST(volume AS DOUBLE) AS volume
FROM read_parquet({_sql_path_list(paths)}, hive_partitioning=1, union_by_name=true)
WHERE CAST(time AS DATE) >= DATE '{start_date:%Y-%m-%d}'
  AND CAST(time AS DATE) <= DATE '{end_date:%Y-%m-%d}'
  AND htsc_code IS NOT NULL
  AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) NOT LIKE '%.YKRS'
  {_code_filter_sql(target_codes)}
"""


def _load_raw_market_data(
    market_base_paths: Sequence[str | Path],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    target_codes: Sequence[str] | None,
) -> pd.DataFrame:
    paths = _market_paths(market_base_paths, start_date, end_date)
    con = duckdb.connect(database=":memory:")
    try:
        frame = con.execute(
            _raw_market_sql(paths, start_date, end_date, target_codes) + " ORDER BY htsc_code, time"
        ).df()
    finally:
        con.close()
    return frame


def _load_wide_xdy_series(
    wide_xdy_base_path: str | Path,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    target_codes: set[str],
) -> dict[str, pd.Series]:
    parts: dict[str, list[pd.Series]] = {}
    for path in _partition_paths(wide_xdy_base_path, start_date, end_date):
        frame = pd.read_parquet(path)
        if frame.empty or "htsc_code" not in frame.columns:
            continue
        frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
        if target_codes:
            frame = frame[frame["htsc_code"].isin(target_codes)]
        date_columns: list[tuple[str, pd.Timestamp]] = []
        for column in frame.columns:
            if column in {"htsc_code", "year", "month"}:
                continue
            date_value = pd.to_datetime(str(column), format="%Y/%m/%d", errors="coerce")
            if not pd.isna(date_value):
                date_columns.append((column, pd.Timestamp(date_value).normalize()))
        for _, row in frame.iterrows():
            code = str(row["htsc_code"]).strip().upper()
            values = {
                date_value: float(row[column])
                for column, date_value in date_columns
                if not pd.isna(row[column])
            }
            if values:
                parts.setdefault(code, []).append(pd.Series(values, dtype=np.float64))
    result: dict[str, pd.Series] = {}
    for code, series_parts in parts.items():
        series = pd.concat(series_parts).sort_index()
        result[code] = series[~series.index.duplicated(keep="last")].astype(float)
    return result


def _backward_factor_series(xdy_series: pd.Series) -> pd.Series:
    values = pd.to_numeric(xdy_series, errors="coerce").dropna().astype(float).sort_index()
    if values.empty:
        return pd.Series(dtype=float)
    raw = values.to_numpy(dtype=float)
    starts = np.ones(len(raw), dtype=bool)
    if len(raw) > 1:
        starts[1:] = raw[1:] != raw[:-1]
    factors = np.where(starts, raw, 1.0)
    return pd.Series(np.cumprod(factors), index=values.index, dtype=float)


def _apply_wide_xdy_backward(
    market: pd.DataFrame,
    wide_xdy_base_path: str | Path,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> tuple[pd.DataFrame, int]:
    if market.empty:
        return market, 0
    factor_by_code = _load_wide_xdy_series(
        wide_xdy_base_path,
        start_date,
        end_date,
        set(market["htsc_code"].astype(str).str.upper()),
    )
    output = market.copy()
    output["time"] = pd.to_datetime(output["time"]).dt.normalize()
    matched_rows = 0
    for code, index_labels in output.groupby("htsc_code", sort=False).groups.items():
        xdy = factor_by_code.get(str(code).upper())
        if xdy is None or xdy.empty:
            continue
        backward = _backward_factor_series(xdy)
        row_index = list(index_labels)
        dates = output.loc[row_index, "time"]
        factors = dates.map(backward)
        factors = factors.mask(dates < backward.index.min(), 1.0)
        factors = factors.mask(dates > backward.index.max(), float(backward.iloc[-1])).fillna(1.0)
        output.loc[row_index, ["open", "high", "low", "close"]] = (
            output.loc[row_index, ["open", "high", "low", "close"]].to_numpy(dtype=float)
            * factors.to_numpy(dtype=float)[:, None]
        )
        matched_rows += len(row_index)
    return output, matched_rows


def load_adjusted_market_data(
    *,
    market_base_paths: Sequence[str | Path],
    adj_factor_base_path: str | Path,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    target_codes: Sequence[str] | None = None,
    wide_xdy_base_path: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """读取目标窗口，并按 notebook 口径执行比例后复权。"""
    start = _normalize_date(start_date)
    end = _normalize_date(end_date)
    market_paths = _market_paths(market_base_paths, start, end)
    adj_paths = _partition_paths(adj_factor_base_path, start, end)
    base_sql = _raw_market_sql(market_paths, start, end, target_codes)

    if adj_paths:
        sql = f"""
WITH d AS (
{base_sql}
), a AS (
    SELECT
        UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
        CAST(time AS DATE) AS time,
        MAX(TRY_CAST(adj_factor AS DOUBLE)) AS adj_factor
    FROM read_parquet({_sql_path_list(adj_paths)}, hive_partitioning=1, union_by_name=true)
    WHERE CAST(time AS DATE) >= DATE '{start:%Y-%m-%d}'
      AND CAST(time AS DATE) <= DATE '{end:%Y-%m-%d}'
    GROUP BY 1, 2
)
SELECT
    d.time,
    d.htsc_code,
    d.open * COALESCE(a.adj_factor, 1.0) AS open,
    d.high * COALESCE(a.adj_factor, 1.0) AS high,
    d.low * COALESCE(a.adj_factor, 1.0) AS low,
    d.close * COALESCE(a.adj_factor, 1.0) AS close,
    d.volume,
    a.adj_factor IS NOT NULL AS adj_factor_matched
FROM d
LEFT JOIN a
  ON d.htsc_code = a.htsc_code
 AND CAST(d.time AS DATE) = a.time
ORDER BY d.htsc_code, d.time
"""
        con = duckdb.connect(database=":memory:")
        try:
            frame = con.execute(sql).df()
        except Exception as exc:
            if wide_xdy_base_path is None:
                raise
            print(f"[WARN] adj_factor_daily 快路径失败，回退 wide_xdy: {exc}")
        else:
            frame["adj_factor_matched"] = frame["adj_factor_matched"].fillna(False).astype(bool)
            frame["time"] = pd.to_datetime(frame["time"]).dt.normalize()
            frame = frame.drop_duplicates(["htsc_code", "time"], keep="last").reset_index(drop=True)
            matched = int(frame.pop("adj_factor_matched").sum())
            return frame, {
                "rows": len(frame),
                "matched_adj_rows": matched,
                "missing_adj_rows": len(frame) - matched,
            }
        finally:
            con.close()

    raw = _load_raw_market_data(market_base_paths, start, end, target_codes)
    raw["time"] = pd.to_datetime(raw["time"]).dt.normalize()
    raw = raw.drop_duplicates(["htsc_code", "time"], keep="last").reset_index(drop=True)
    if wide_xdy_base_path is not None:
        adjusted, matched = _apply_wide_xdy_backward(raw, wide_xdy_base_path, start, end)
    else:
        adjusted, matched = raw, 0
    return adjusted, {
        "rows": len(adjusted),
        "matched_adj_rows": int(matched),
        "missing_adj_rows": len(adjusted) - int(matched),
    }


def get_market_coverage(
    market_base_paths: Sequence[str | Path],
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    target_codes: Sequence[str] | None = None,
) -> tuple[set[str], pd.Timestamp | None]:
    start = _normalize_date(start_date)
    end = _normalize_date(end_date)
    paths = _market_paths(market_base_paths, start, end)
    sql = f"""
SELECT
    UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
    MAX(CAST(time AS DATE)) AS last_dt
FROM read_parquet({_sql_path_list(paths)}, hive_partitioning=1, union_by_name=true)
WHERE CAST(time AS DATE) >= DATE '{start:%Y-%m-%d}'
  AND CAST(time AS DATE) <= DATE '{end:%Y-%m-%d}'
  AND htsc_code IS NOT NULL
  AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) NOT LIKE '%.YKRS'
  {_code_filter_sql(target_codes)}
GROUP BY 1
"""
    con = duckdb.connect(database=":memory:")
    try:
        frame = con.execute(sql).df()
    finally:
        con.close()
    if frame.empty:
        return set(), None
    codes = set(frame["htsc_code"].astype(str).str.upper())
    return codes, pd.Timestamp(frame["last_dt"].max()).floor("D")


def _factor_root(base_dir: str | Path, factor_name: str) -> Path:
    safe = FACTOR_PATH_INVALID_CHARS.sub("_", str(factor_name).strip()).rstrip(" .")
    if not safe:
        raise ValueError("因子名不能为空")
    return Path(base_dir) / f"factor={safe}"


def _factor_storage_paths(base_dir: str | Path, factor_name: str) -> list[Path]:
    root = _factor_root(base_dir, factor_name)
    paths: list[Path] = []
    for month_dir in sorted(root.glob("year=*/month=*")) if root.exists() else []:
        merged_path = month_dir / "merged.parquet"
        if merged_path.is_file():
            paths.append(merged_path)
        paths.extend(sorted(month_dir.glob("part_*.parquet")))
    return paths


def load_factor_storage_summary(
    base_dir: str | Path,
    factor_ids: Sequence[str],
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    con = duckdb.connect(database=":memory:")
    try:
        for factor_id in factor_ids:
            paths = _factor_storage_paths(base_dir, factor_id)
            if not paths:
                continue
            sql = f"""
SELECT MAX(CAST(time AS DATE)) AS last_dt
FROM read_parquet({_sql_path_list(paths)}, union_by_name=true)
"""
            last_dt = con.execute(sql).fetchone()[0]
            code_rows = con.execute(
                f"SELECT DISTINCT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) FROM read_parquet({_sql_path_list(paths)}, union_by_name=true) WHERE htsc_code IS NOT NULL"
            ).fetchall()
            result[str(factor_id)] = {
                "last_dt": pd.Timestamp(last_dt).floor("D") if last_dt is not None else None,
                "codes": {str(row[0]).upper() for row in code_rows if row[0]},
            }
    finally:
        con.close()
    return result


def build_incremental_plan(
    *,
    factor_ids: Sequence[str],
    storage_summary: dict[str, dict[str, object]],
    available_codes: set[str],
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    lookback_config: dict[str, object],
) -> pd.DataFrame:
    start = _normalize_date(start_date)
    end = _normalize_date(end_date)
    lookbacks = dict(lookback_config.get("factor_lookback_days", {}))
    full_history = set(lookback_config.get("full_history_factor_keys", []))
    normalized_codes = {str(code).strip().upper() for code in available_codes if str(code).strip()}
    rows: list[dict[str, object]] = []

    for factor_id in factor_ids:
        factor_id = str(factor_id).strip()
        indicator = factor_id.split("_", 1)[0]
        item = storage_summary.get(factor_id, {})
        last_dt_value = item.get("last_dt")
        last_dt = pd.Timestamp(last_dt_value).floor("D") if last_dt_value is not None else None
        existing_codes = {str(code).strip().upper() for code in item.get("codes", set())}
        missing_codes = tuple(sorted(normalized_codes.difference(existing_codes)))

        if last_dt is None:
            status = "missing"
            compute_start = start
            save_start = start
            reason = "因子目录不存在或无历史数据"
        elif last_dt < end or missing_codes:
            status = "stale"
            if factor_id in full_history or missing_codes:
                compute_start = start
            else:
                compute_start = max(start, last_dt - pd.Timedelta(days=int(lookbacks.get(factor_id, 520))))
            save_start = start if missing_codes else last_dt + pd.Timedelta(days=1)
            reason_parts = []
            if last_dt < end:
                reason_parts.append(f"历史末日={last_dt.date()}，需补到={end.date()}")
            if missing_codes:
                reason_parts.append(f"缺少代码={len(missing_codes)}")
            reason = "；".join(reason_parts)
        else:
            status = "up_to_date"
            compute_start = pd.NaT
            save_start = pd.NaT
            reason = f"历史末日={last_dt.date()}，已覆盖目标区间"

        rows.append(
            {
                "indicator": indicator,
                "factor_id": factor_id,
                "status": status,
                "last_dt": last_dt,
                "compute_start": compute_start,
                "save_start": save_start,
                "save_end": end if status != "up_to_date" else pd.NaT,
                "missing_codes": missing_codes,
                "reason": reason,
            }
        )
    return pd.DataFrame(rows)


def _factor_month_to_long_polars(
    factor_df: pd.DataFrame,
    month_start: pd.Timestamp,
    month_end: pd.Timestamp,
) -> pl.DataFrame | None:
    index = pd.to_datetime(factor_df.index).floor("D")
    keep = (index >= month_start) & (index <= month_end)
    if not bool(keep.any()):
        return None
    sliced = factor_df.loc[keep].copy()
    sliced.index = index[keep]
    sliced.index.name = "time"
    long_df = (
        sliced.reset_index()
        .melt(id_vars="time", var_name="htsc_code", value_name="value")
        .drop_duplicates(["time", "htsc_code"], keep="last")
    )
    if long_df.empty:
        return None
    return (
        pl.from_pandas(long_df, include_index=False)
        .with_columns(
            pl.col("time").cast(pl.Datetime),
            pl.col("htsc_code").cast(pl.Utf8),
            pl.col("value").cast(pl.Float32),
        )
        .sort(SIGNAL_KEY_COLUMNS)
    )


def _write_parquet_atomic(df: pl.DataFrame, file_path: Path, max_retries: int = 20) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = file_path.parent / ".__tmp_writes__"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    abandoned_temp_paths: list[Path] = []
    last_error: Exception | None = None
    try:
        for write_attempt in range(1, max_retries + 1):
            temp_path = temp_dir / f"tmp_{os.getpid()}_{uuid.uuid4().hex}.parquet"
            try:
                df.write_parquet(temp_path, compression="snappy")
                break
            except OSError as exc:
                last_error = exc
                abandoned_temp_paths.append(temp_path)
                if write_attempt == 1 or write_attempt % 5 == 0:
                    print(
                        f"[WARN] 临时 Parquet 写入被占用，等待重试: "
                        f"{file_path} ({write_attempt}/{max_retries})"
                    )
                time.sleep(0.5)
        else:
            raise OSError(f"写入 Parquet 临时文件失败: {file_path}") from last_error

        for attempt in range(1, max_retries + 1):
            try:
                os.replace(temp_path, file_path)
                return
            except OSError as exc:
                last_error = exc
                if attempt == 1 or attempt % 5 == 0:
                    print(f"[WARN] 文件被占用，等待重试: {file_path} ({attempt}/{max_retries})")
                time.sleep(0.5)
        raise OSError(f"写入 Parquet 失败: {file_path}") from last_error
    finally:
        cleanup_paths = [*abandoned_temp_paths]
        if temp_path is not None:
            cleanup_paths.append(temp_path)
        for cleanup_path in cleanup_paths:
            try:
                cleanup_path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            temp_dir.rmdir()
        except OSError:
            pass


def _write_factor_range(
    factor_name: str,
    factor_df: pd.DataFrame,
    output_base_dir: str | Path,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> tuple[str, int, int]:
    months = 0
    rows = 0
    for month_start in _month_starts(start_date, end_date):
        month_end = min(month_start + pd.offsets.MonthEnd(0), end_date)
        frame = _factor_month_to_long_polars(factor_df, max(start_date, month_start), month_end)
        if frame is None or frame.is_empty():
            continue
        month_dir = _factor_root(output_base_dir, factor_name) / f"year={month_start.year:04d}" / f"month={month_start.month:02d}"
        part_path = month_dir / f"part_{int(time.time() * 1000)}_{os.getpid()}_{uuid.uuid4().hex}.parquet"
        _write_parquet_atomic(frame, part_path)
        months += 1
        rows += len(frame)
    return factor_name, months, rows


def write_factor_parts(
    *,
    factor_dfs: dict[str, pd.DataFrame],
    output_base_dir: str | Path,
    save_ranges: dict[str, tuple[pd.Timestamp, pd.Timestamp]],
    max_workers: int = 4,
) -> set[str]:
    tasks = []
    for factor_name, frame in factor_dfs.items():
        if factor_name not in save_ranges or frame.empty:
            continue
        start_date, end_date = save_ranges[factor_name]
        tasks.append((factor_name, frame, _normalize_date(start_date), _normalize_date(end_date)))
    if not tasks:
        return set()

    touched: set[str] = set()
    workers = max(1, min(int(max_workers), len(tasks)))
    if workers == 1:
        results = [
            _write_factor_range(name, frame, output_base_dir, start, end)
            for name, frame, start, end in tasks
        ]
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_write_factor_range, name, frame, output_base_dir, start, end): name
                for name, frame, start, end in tasks
            }
            results = [future.result() for future in as_completed(futures)]
    for factor_name, month_count, row_count in results:
        touched.add(factor_name)
        print(f"因子 part 写入完成: {factor_name}，月份={month_count}，行={row_count}")
    return touched


def _read_signal_parquet(path: Path) -> pl.DataFrame | None:
    if not path.is_file() or path.stat().st_size < 12:
        return None
    try:
        return pl.read_parquet(path).select(
            pl.col("time").cast(pl.Datetime),
            pl.col("htsc_code").cast(pl.Utf8),
            pl.col("value").cast(pl.Float32),
        )
    except Exception as exc:
        corrupt = path.with_name(f"{path.name}.corrupt.{int(time.time())}")
        print(f"[WARN] Parquet 损坏，移到备份: {path} -> {corrupt}，原因: {exc}")
        os.replace(path, corrupt)
        return None


def _compact_month(month_dir: Path, keep_parts: bool = False) -> tuple[int, int]:
    part_paths = sorted(month_dir.glob("part_*.parquet"))
    if not part_paths:
        return 0, 0
    new_frames = [frame for path in part_paths if (frame := _read_signal_parquet(path)) is not None]
    if not new_frames:
        return 0, 0
    new_df = (
        pl.concat(new_frames, how="vertical_relaxed", rechunk=True)
        .unique(SIGNAL_KEY_COLUMNS, keep="last", maintain_order=True)
    )
    merged_path = month_dir / "merged.parquet"
    old_df = _read_signal_parquet(merged_path)
    if old_df is None:
        save_df = new_df.sort(SIGNAL_KEY_COLUMNS)
    else:
        save_df = (
            pl.concat([old_df, new_df], how="vertical_relaxed", rechunk=True)
            .unique(SIGNAL_KEY_COLUMNS, keep="first", maintain_order=True)
            .sort(SIGNAL_KEY_COLUMNS)
        )
    _write_parquet_atomic(save_df, merged_path)
    if not keep_parts:
        for path in part_paths:
            path.unlink(missing_ok=True)
    return len(part_paths), len(save_df)


def compact_signal_daily_parts(
    base_dir: str | Path,
    *,
    factor_names: Sequence[str] | None = None,
    workers: int = 4,
    keep_parts: bool = False,
) -> tuple[int, int]:
    root = Path(base_dir)
    if not root.exists():
        return 0, 0
    if factor_names:
        factor_dirs = [_factor_root(root, name) for name in factor_names]
    else:
        factor_dirs = sorted(root.glob("factor=*"))
    month_dirs = sorted(
        month_dir
        for factor_dir in factor_dirs
        if factor_dir.exists()
        for month_dir in factor_dir.glob("year=*/month=*")
        if any(month_dir.glob("part_*.parquet"))
    )
    if not month_dirs:
        return 0, 0
    total_parts = 0
    touched_months = 0
    worker_count = max(1, min(int(workers), len(month_dirs)))
    if worker_count == 1:
        results = [_compact_month(month_dir, keep_parts=keep_parts) for month_dir in month_dirs]
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(executor.map(lambda path: _compact_month(path, keep_parts), month_dirs))
    for part_count, _ in results:
        if part_count:
            touched_months += 1
            total_parts += part_count
    print(f"part 合并完成: 月份={touched_months}，part 文件={total_parts}")
    return touched_months, total_parts


def _build_price_matrices(frame: pd.DataFrame) -> tuple[pd.DataFrame, ...]:
    if frame.empty:
        raise ValueError("日线数据为空，无法计算因子")
    data = frame.copy()
    data["time"] = pd.to_datetime(data["time"]).dt.normalize()
    data["htsc_code"] = data["htsc_code"].astype(str).str.strip().str.upper()
    data = data.drop_duplicates(["time", "htsc_code"], keep="last")
    wide = (
        data.set_index(["time", "htsc_code"])[["open", "high", "low", "close", "volume"]]
        .sort_index()
        .unstack("htsc_code")
    )
    valid_bar = wide["close"].notna()
    O = wide["open"].ffill().astype(float)
    H = wide["high"].ffill().astype(float)
    L = wide["low"].ffill().astype(float)
    C = wide["close"].ffill().astype(float)
    V = wide["volume"].fillna(0.0).astype(float)
    return O, H, L, C, V, valid_bar


def _parse_tokens(values: Sequence[str] | None, *, upper: bool = False) -> list[str]:
    result: list[str] = []
    for raw in values or []:
        for token in str(raw).replace("，", ",").split(","):
            value = token.strip()
            if value:
                result.append(value.upper() if upper else value)
    return list(dict.fromkeys(result))


def _print_plan(plan: pd.DataFrame) -> None:
    if plan.empty:
        print("没有可用因子计划。")
        return
    summary = plan.groupby("status").size().to_dict()
    print(f"因子计划统计: {summary}")
    pending = plan[plan["status"] != "up_to_date"]
    if not pending.empty:
        print(pending[["indicator", "factor_id", "status", "compute_start", "save_start", "save_end", "reason"]].to_string(index=False))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="后复权向量化生成纯技术面因子并增量写入 signal_daily")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    parser.add_argument("--stock-base-path", default=str(DEFAULT_STOCK_BASE_PATH))
    parser.add_argument("--index-base-path", default=str(DEFAULT_INDEX_BASE_PATH))
    parser.add_argument("--etf-base-path", default=str(DEFAULT_ETF_BASE_PATH))
    parser.add_argument("--adj-factor-base-path", default=str(DEFAULT_ADJ_FACTOR_BASE_PATH))
    parser.add_argument("--wide-xdy-base-path", default=str(DEFAULT_WIDE_XDY_BASE_PATH))
    parser.add_argument("--output-base-dir", default=str(DEFAULT_OUTPUT_BASE_PATH))
    parser.add_argument("--target-codes", nargs="*", default=None)
    parser.add_argument("--selected-indicators", nargs="*", default=None)
    parser.add_argument("--target-factors", nargs="*", default=None)
    parser.add_argument("--max-save-workers", type=int, default=4)
    parser.add_argument("--compact-workers", type=int, default=4)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--no-compact", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> None:
    start = _normalize_date(args.start_date)
    requested_end = _normalize_date(args.end_date)
    output_base = Path(args.output_base_dir)
    market_bases = [args.stock_base_path, args.index_base_path, args.etf_base_path]
    target_codes = _parse_tokens(args.target_codes, upper=True)
    selected_indicators = _parse_tokens(args.selected_indicators, upper=True)
    target_factors = set(_parse_tokens(args.target_factors))

    if not args.plan_only:
        compact_signal_daily_parts(output_base, workers=args.compact_workers)

    cache_path = output_base / "_meta" / "pure_technical_factor_catalog_cache.json"
    catalog = get_factor_catalog(cache_path=cache_path)
    factor_ids = list(catalog["factor_name_map"].values())
    if selected_indicators:
        unknown = sorted(set(selected_indicators).difference(INDICATOR_NAMES))
        if unknown:
            raise ValueError(f"未知指标: {', '.join(unknown)}")
        factor_ids = [name for name in factor_ids if name.split("_", 1)[0] in selected_indicators]
    if target_factors:
        unknown_factors = sorted(target_factors.difference(factor_ids))
        if unknown_factors:
            raise ValueError(f"未知或未选中的因子: {', '.join(unknown_factors)}")
        factor_ids = [name for name in factor_ids if name in target_factors]

    available_codes, market_last_dt = get_market_coverage(market_bases, start, requested_end, target_codes)
    if market_last_dt is None or not available_codes:
        raise ValueError("目标范围内没有可用市场数据")
    effective_end = min(requested_end, market_last_dt)
    if effective_end < requested_end:
        print(f"目标结束日无行情，实际按最新交易日执行: {effective_end.date()}")

    storage_summary = load_factor_storage_summary(output_base, factor_ids)
    plan = build_incremental_plan(
        factor_ids=factor_ids,
        storage_summary=storage_summary,
        available_codes=available_codes,
        start_date=start,
        end_date=effective_end,
        lookback_config=get_factor_lookback_config(),
    )
    _print_plan(plan)
    if args.plan_only:
        return

    pending = plan[plan["status"] != "up_to_date"].copy()
    if pending.empty:
        print("全部纯技术面因子已是最新，无需计算。")
        return

    shared_compute_start = pd.Timestamp(pending["compute_start"].min()).floor("D")
    print(f"\n一次加载共享行情: {shared_compute_start.date()} ~ {effective_end.date()}")
    market, adj_stats = load_adjusted_market_data(
        market_base_paths=market_bases,
        adj_factor_base_path=args.adj_factor_base_path,
        wide_xdy_base_path=args.wide_xdy_base_path,
        start_date=shared_compute_start,
        end_date=effective_end,
        target_codes=target_codes or None,
    )
    print(f"复权覆盖: {adj_stats}")
    O_all, H_all, L_all, C_all, V_all, valid_bar_all = _build_price_matrices(market)
    del market
    gc.collect()

    completed_factors: set[str] = set()
    for indicator in INDICATOR_NAMES:
        indicator_plan = pending[pending["indicator"] == indicator]
        if indicator_plan.empty:
            continue
        compute_start = pd.Timestamp(indicator_plan["compute_start"].min()).floor("D")
        selected_factor_ids = indicator_plan["factor_id"].astype(str).tolist()
        print(f"\n开始指标 {indicator}: 计算区间 {compute_start.date()} ~ {effective_end.date()}，因子={len(selected_factor_ids)}")

        O = O_all.loc[compute_start:effective_end]
        H = H_all.loc[compute_start:effective_end]
        L = L_all.loc[compute_start:effective_end]
        C = C_all.loc[compute_start:effective_end]
        V = V_all.loc[compute_start:effective_end]
        valid_bar = valid_bar_all.loc[compute_start:effective_end]
        output = next(
            iter_pure_technical_factor_bundles(
                O=O,
                H=H,
                L=L,
                C=C,
                V=V,
                valid_bar=valid_bar,
                selected_indicators=[indicator],
                selected_factors=selected_factor_ids,
            )
        )

        plan_by_factor = indicator_plan.set_index("factor_id")
        write_batches: list[
            tuple[dict[str, pd.DataFrame], dict[str, tuple[pd.Timestamp, pd.Timestamp]]]
        ] = [({}, {}), ({}, {})]
        for factor_id, frame in output["factor_dfs"].items():
            row = plan_by_factor.loc[factor_id]
            last_dt = row["last_dt"]
            missing_codes = list(row["missing_codes"])
            factor_jobs: list[tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp]] = []
            if pd.isna(last_dt):
                factor_jobs.append((frame, start, effective_end))
            else:
                last_dt = pd.Timestamp(last_dt).floor("D")
                if missing_codes:
                    missing_columns = [code for code in missing_codes if code in frame.columns]
                    if missing_columns and start <= min(last_dt, effective_end):
                        factor_jobs.append(
                            (frame.loc[:, missing_columns], start, min(last_dt, effective_end))
                        )
                tail_start = last_dt + pd.Timedelta(days=1)
                if tail_start <= effective_end:
                    factor_jobs.append((frame, tail_start, effective_end))

            for batch_index, (job_frame, save_start, save_end) in enumerate(factor_jobs):
                factor_dfs, save_ranges = write_batches[batch_index]
                factor_dfs[factor_id] = job_frame
                save_ranges[factor_id] = (save_start, save_end)

        for factor_dfs, save_ranges in write_batches:
            completed_factors.update(
                write_factor_parts(
                    factor_dfs=factor_dfs,
                    output_base_dir=output_base,
                    save_ranges=save_ranges,
                    max_workers=args.max_save_workers,
                )
            )

        if not args.no_compact:
            compact_signal_daily_parts(
                output_base,
                factor_names=selected_factor_ids,
                workers=args.compact_workers,
            )
        del output, O, H, L, C, V, valid_bar
        gc.collect()
        print(f"指标完成: {indicator}")

    del O_all, H_all, L_all, C_all, V_all, valid_bar_all
    gc.collect()
    print(f"纯技术面因子增量生成完成，写入因子数={len(completed_factors)}")


def main(argv: Sequence[str] | None = None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()
