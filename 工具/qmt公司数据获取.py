#!/usr/bin/python3
# -*- coding: utf-8 -*-
r"""QMT 公司数据下载。

数据源：xtquant.xtdata 财务接口。
落盘：D:\database\qmt_company_data/table=<QMT表名>/year=YYYY/month=MM/merged.parquet
财报表按 report_date 分区；迅投因子字典表按 time 分区。
"""

from __future__ import annotations

import argparse
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import polars as pl
from xtquant import xtdata

BASE_DIR = r"D:\database\qmt_company_data"
DEFAULT_SECTOR_NAME = "沪深A股"
DEFAULT_START_DATE = "2010-01-01"
DEFAULT_OVERLAP_DAYS = 456
DEFAULT_BATCH_SIZE = 20
DEFAULT_SLEEP_SEC = 0.0005
MERGED_FILE_NAME = "merged.parquet"
MIN_PARQUET_BYTES = 12
QMT_TABLES = ("Income", "Balance", "CashFlow", "PershareIndex", "Capital")
QMT_FACTOR_TABLES = ("factor_base_derivative", "factor_metrics")
DEDUP_COLUMNS = ("htsc_code", "table_name", "report_date", "announce_date")
DAILY_FACTOR_DEDUP_COLUMNS = ("htsc_code", "table_name", "time")
FACTOR_DATE_COLUMN_CANDIDATES = ("time", "trading_day", "date", "m_timetag")
INSIGHT_VALUATION_BASE_DIR = r"D:\database\stock_financial_statements\stock_valuation_data"

FACTOR_TABLE_FIELDS: dict[str, tuple[str, ...]] = {
    "factor_base_derivative": (
        "circ_market_value",
        "op_cash_flow_ttm",
        "net_profit_ttm",
        "net_profit_attr_shr_ttm",
        "op_rev_ttm",
        "total_rev_ttm",
        "cf_mv_ratio",
        "fin_exp_ttm",
        "admin_exp_ttm",
        "op_cost_ttm",
        "op_profit_ttm",
        "non_op_inc_ttm",
        "non_op_exp_ttm",
        "non_op_net_inc_ttm",
        "total_profit_ttm",
        "net_debt",
        "ret_earnings",
        "net_wc",
        "fin_cash_flow_ttm",
        "impair_loss_ttm",
    ),
    "factor_metrics": (
        "total_mv",
        "pb_ratio",
        "eps_ttm",
        "op_revenue_ps_ttm",
        "op_cash_flow_ps",
        "net_assets_ps",
        "ret_earnings_ps",
        "undist_profit_ps",
        "cash_equiv_ps",
        "op_profit_ps_ttm",
        "op_revenue_ps",
        "total_op_revenue_ps",
        "cap_reserve_ps",
    ),
}
EXCLUDED_FACTOR_FIELDS = {"pe", "pettm", "pc", "pcttm", "ps", "psttm"}


def normalize_code(code: str) -> str:
    return str(code or "").strip().upper()


def parse_qmt_date(value: Any) -> pd.Timestamp | pd.NaT:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NaT
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat"}:
        return pd.NaT
    if text.endswith(".0"):
        text = text[:-2]
    if len(text) >= 8 and text[:8].isdigit():
        return pd.to_datetime(text[:8], format="%Y%m%d", errors="coerce")
    return pd.to_datetime(text, errors="coerce")


def parse_daily_factor_time(value: Any) -> pd.Timestamp | pd.NaT:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NaT
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat"}:
        return pd.NaT
    if text.endswith(".0"):
        text = text[:-2]
    if text.isdigit():
        if len(text) >= 13:
            return pd.to_datetime(int(text), unit="ms", errors="coerce").floor("D")
        if len(text) >= 8:
            return pd.to_datetime(text[:8], format="%Y%m%d", errors="coerce")
    return pd.to_datetime(text, errors="coerce").floor("D")


def period_from_report_date(value: Any) -> str:
    ts = parse_qmt_date(value)
    if pd.isna(ts):
        return ""
    month = int(ts.month)
    if month <= 3:
        return "Q1"
    if month <= 6:
        return "Q2"
    if month <= 9:
        return "Q3"
    return "Q4"


def parse_tables_arg(value: str) -> list[str]:
    text = str(value or "").strip()
    if text.lower() == "none":
        return []
    if not text or text.lower() == "all":
        return list(QMT_TABLES)
    requested = [part.strip() for part in text.split(",") if part.strip()]
    canonical = {table.lower(): table for table in QMT_TABLES}
    tables: list[str] = []
    for item in requested:
        key = item.lower()
        if key not in canonical:
            valid = ", ".join(["all", *QMT_TABLES])
            raise ValueError(f"未知 QMT 表: {item}，可选: {valid}")
        tables.append(canonical[key])
    return list(dict.fromkeys(tables))


def parse_factor_tables_arg(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text or text.lower() == "none":
        return []
    if text.lower() == "all":
        return list(QMT_FACTOR_TABLES)
    requested = [part.strip() for part in text.split(",") if part.strip()]
    canonical = {table.lower(): table for table in QMT_FACTOR_TABLES}
    tables: list[str] = []
    for item in requested:
        key = item.lower()
        if key not in canonical:
            valid = ", ".join(["none", "all", *QMT_FACTOR_TABLES])
            raise ValueError(f"未知 QMT 因子表: {item}，可选: {valid}")
        tables.append(canonical[key])
    return list(dict.fromkeys(tables))


def load_xtquant_sector_universe(sector_name: str) -> list[str]:
    xtdata.download_sector_data()
    stock_list = xtdata.get_stock_list_in_sector(sector_name)
    if not stock_list:
        raise RuntimeError(f"xtquant 板块股票池为空: {sector_name}")
    return sorted({normalize_code(code) for code in stock_list if str(code).strip()})


def resolve_codes(sector_name: str, codes_arg: str | None = None) -> list[str]:
    manual = [normalize_code(part) for part in str(codes_arg or "").replace("，", ",").split(",") if part.strip()]
    if manual:
        return sorted(set(manual))
    return load_xtquant_sector_universe(sector_name)


def load_xtquant_name(code: str) -> str:
    try:
        detail = xtdata.get_instrument_detail(normalize_code(code)) or {}
    except Exception:
        return ""
    return str(detail.get("InstrumentName") or detail.get("Name") or "").strip()


def normalize_qmt_table_frame(
    raw_df: pd.DataFrame,
    table_name: str,
    code: str,
    name: str,
    updated_at: str,
) -> pd.DataFrame:
    if raw_df is None or raw_df.empty:
        return pd.DataFrame()
    out = raw_df.copy()
    report_source = out["m_timetag"] if "m_timetag" in out.columns else pd.NaT
    announce_source = out["m_anntime"] if "m_anntime" in out.columns else report_source
    out["report_date"] = pd.Series(report_source).map(parse_qmt_date)
    out["announce_date"] = pd.Series(announce_source).map(parse_qmt_date)
    out["htsc_code"] = normalize_code(code)
    out["name"] = str(name or "")
    out["table_name"] = str(table_name)
    out["period"] = out["report_date"].map(period_from_report_date)
    out["updated_at"] = updated_at
    out = out.dropna(subset=["report_date"]).copy()
    if out.empty:
        return out
    out["announce_date"] = out["announce_date"].fillna(out["report_date"])
    out = out.drop_duplicates(subset=list(DEDUP_COLUMNS), keep="last")
    meta_cols = ["htsc_code", "name", "table_name", "report_date", "announce_date", "period", "updated_at"]
    other_cols = [col for col in out.columns if col not in meta_cols]
    return out[meta_cols + other_cols].sort_values(["report_date", "announce_date", "htsc_code"]).reset_index(drop=True)


def _find_daily_factor_date_column(raw_df: pd.DataFrame) -> str | None:
    lower_to_original = {str(col).lower(): str(col) for col in raw_df.columns}
    for candidate in FACTOR_DATE_COLUMN_CANDIDATES:
        found = lower_to_original.get(candidate.lower())
        if found:
            return found
    return None


def normalize_daily_factor_frame(
    raw_df: pd.DataFrame,
    table_name: str,
    code: str,
    name: str,
    updated_at: str,
) -> pd.DataFrame:
    if raw_df is None or raw_df.empty:
        return pd.DataFrame()
    date_col = _find_daily_factor_date_column(raw_df)
    if not date_col:
        raise ValueError(f"{table_name} 接口结果缺少日频日期列，可识别列: {FACTOR_DATE_COLUMN_CANDIDATES}")

    field_names = FACTOR_TABLE_FIELDS[table_name]
    out = pd.DataFrame()
    out["time"] = raw_df[date_col].map(parse_daily_factor_time)
    out["htsc_code"] = normalize_code(code)
    out["name"] = str(name or "")
    out["table_name"] = str(table_name)
    out["updated_at"] = updated_at
    for field in field_names:
        if field in EXCLUDED_FACTOR_FIELDS:
            continue
        if field in raw_df.columns:
            out[field] = pd.to_numeric(raw_df[field], errors="coerce")
    out = out.dropna(subset=["time", "htsc_code"]).copy()
    if out.empty:
        return out
    keep_cols = ["htsc_code", "name", "table_name", "time", "updated_at"]
    keep_cols.extend([field for field in field_names if field in out.columns and field not in EXCLUDED_FACTOR_FIELDS])
    out = out.drop_duplicates(subset=list(DAILY_FACTOR_DEDUP_COLUMNS), keep="last")
    return out[keep_cols].sort_values(["time", "htsc_code"]).reset_index(drop=True)


def _table_base_dir(base_dir: str, table_name: str) -> Path:
    return Path(base_dir) / f"table={table_name}"


def _is_readable_parquet(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= MIN_PARQUET_BYTES and not pl.read_parquet(str(path), n_rows=1).is_empty()
    except Exception:
        return False


def deduplicate_qmt_df(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty():
        return df
    subset = [col for col in DEDUP_COLUMNS if col in df.columns]
    if len(subset) >= 3:
        if "updated_at" in df.columns:
            df = df.sort("updated_at")
        df = df.unique(subset=subset, keep="last")
    return df.sort([col for col in ("report_date", "announce_date", "htsc_code") if col in df.columns])


def deduplicate_daily_factor_df(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty():
        return df
    subset = [col for col in DAILY_FACTOR_DEDUP_COLUMNS if col in df.columns]
    if len(subset) >= 2:
        if "updated_at" in df.columns:
            df = df.sort("updated_at")
        df = df.unique(subset=subset, keep="last")
    return df.sort([col for col in ("time", "htsc_code") if col in df.columns])


def save_partitioned_parquet(df: pd.DataFrame, base_dir: str, table_name: str) -> list[tuple[int, int]]:
    if df is None or df.empty:
        return []
    pl_df = pl.from_pandas(df)
    pl_df = (
        pl_df.with_columns(
            pl.col("report_date").cast(pl.Datetime, strict=False).dt.truncate("1d").alias("report_date"),
            pl.col("announce_date").cast(pl.Datetime, strict=False).dt.truncate("1d").alias("announce_date"),
            pl.col("htsc_code").cast(pl.Utf8).str.to_uppercase().str.strip_chars().alias("htsc_code"),
            pl.lit(table_name).alias("table_name"),
        )
        .drop_nulls(["report_date", "htsc_code"])
    )
    pl_df = deduplicate_qmt_df(pl_df)
    pl_df = pl_df.with_columns(
        pl.col("report_date").dt.year().alias("year"),
        pl.col("report_date").dt.month().alias("month"),
    )

    touched: list[tuple[int, int]] = []
    for partition_df in pl_df.partition_by(["year", "month"]):
        year = int(partition_df["year"][0])
        month = int(partition_df["month"][0])
        dir_path = _table_base_dir(base_dir, table_name) / f"year={year}" / f"month={month:02d}"
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = dir_path / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_year_{year}_month_{month:02d}.parquet"
        save_df = partition_df.drop(["year", "month"])
        save_df.write_parquet(str(file_path), compression="zstd")
        touched.append((year, month))
        print(f"[OK] 已保存 {file_path} ({len(save_df)} 条)")
    return touched


def save_daily_factor_partitioned_parquet(df: pd.DataFrame, base_dir: str, table_name: str) -> list[tuple[int, int]]:
    if df is None or df.empty:
        return []
    pl_df = pl.from_pandas(df)
    pl_df = (
        pl_df.with_columns(
            pl.col("time").cast(pl.Datetime, strict=False).dt.truncate("1d").alias("time"),
            pl.col("htsc_code").cast(pl.Utf8).str.to_uppercase().str.strip_chars().alias("htsc_code"),
            pl.lit(table_name).alias("table_name"),
        )
        .drop_nulls(["time", "htsc_code"])
    )
    pl_df = deduplicate_daily_factor_df(pl_df)
    pl_df = pl_df.with_columns(
        pl.col("time").dt.year().alias("year"),
        pl.col("time").dt.month().alias("month"),
    )

    touched: list[tuple[int, int]] = []
    for partition_df in pl_df.partition_by(["year", "month"]):
        year = int(partition_df["year"][0])
        month = int(partition_df["month"][0])
        dir_path = _table_base_dir(base_dir, table_name) / f"year={year}" / f"month={month:02d}"
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = dir_path / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_year_{year}_month_{month:02d}.parquet"
        save_df = partition_df.drop(["year", "month"])
        save_df.write_parquet(str(file_path), compression="zstd")
        touched.append((year, month))
        print(f"[OK] 已保存日频因子 {file_path} ({len(save_df)} 条)")
    return touched


def rebuild_merged_parquets(base_dir: str, table_name: str, touched_partitions: set[tuple[int, int]]) -> list[Path]:
    rebuilt: list[Path] = []
    for year, month in sorted(touched_partitions):
        partition_dir = _table_base_dir(base_dir, table_name) / f"year={year}" / f"month={month:02d}"
        if not partition_dir.exists():
            continue
        merged_path = partition_dir / MERGED_FILE_NAME
        raw_files = sorted(path for path in partition_dir.glob("*.parquet") if path.name != MERGED_FILE_NAME)
        input_files = ([merged_path] if merged_path.exists() else []) + raw_files
        input_files = [path for path in input_files if _is_readable_parquet(path)]
        if not input_files:
            continue
        try:
            merged_df = pl.concat([pl.scan_parquet(str(path)) for path in input_files], how="diagonal_relaxed").collect(engine="streaming")
            merged_df = deduplicate_qmt_df(merged_df)
            temp_path = partition_dir / f"{MERGED_FILE_NAME}.{os.getpid()}.{time.time_ns()}.tmp"
            merged_df.write_parquet(str(temp_path), compression="zstd")
            temp_path.replace(merged_path)
            rebuilt.append(merged_path)
            print(f"[OK] 已重建 merged: {merged_path}")
        except Exception as exc:
            print(f"[WARN] 重建 {partition_dir} 失败: {exc}")
            continue
        for raw_file in raw_files:
            try:
                raw_file.unlink()
            except OSError as exc:
                print(f"[WARN] 删除原始文件失败: {raw_file} | {exc}")
    return rebuilt


def rebuild_daily_factor_merged_parquets(base_dir: str, table_name: str, touched_partitions: set[tuple[int, int]]) -> list[Path]:
    rebuilt: list[Path] = []
    for year, month in sorted(touched_partitions):
        partition_dir = _table_base_dir(base_dir, table_name) / f"year={year}" / f"month={month:02d}"
        if not partition_dir.exists():
            continue
        merged_path = partition_dir / MERGED_FILE_NAME
        raw_files = sorted(path for path in partition_dir.glob("*.parquet") if path.name != MERGED_FILE_NAME)
        input_files = ([merged_path] if merged_path.exists() else []) + raw_files
        input_files = [path for path in input_files if _is_readable_parquet(path)]
        if not input_files:
            continue
        try:
            merged_df = pl.concat([pl.scan_parquet(str(path)) for path in input_files], how="diagonal_relaxed").collect(engine="streaming")
            merged_df = deduplicate_daily_factor_df(merged_df)
            temp_path = partition_dir / f"{MERGED_FILE_NAME}.{os.getpid()}.{time.time_ns()}.tmp"
            merged_df.write_parquet(str(temp_path), compression="zstd")
            temp_path.replace(merged_path)
            rebuilt.append(merged_path)
            print(f"[OK] 已重建日频因子 merged: {merged_path}")
        except Exception as exc:
            print(f"[WARN] 重建日频因子 {partition_dir} 失败: {exc}")
            continue
        for raw_file in raw_files:
            try:
                raw_file.unlink()
            except OSError as exc:
                print(f"[WARN] 删除原始文件失败: {raw_file} | {exc}")
    return rebuilt


def scan_latest_report_dates(base_dir: str, table_name: str) -> dict[str, datetime]:
    table_dir = _table_base_dir(base_dir, table_name)
    if not table_dir.exists():
        return {}
    pattern = str(table_dir / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")
    try:
        query = f"""
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            MAX(CAST(report_date AS TIMESTAMP)) AS latest_report_date
        FROM read_parquet('{pattern}', union_by_name=true)
        WHERE htsc_code IS NOT NULL AND report_date IS NOT NULL
        GROUP BY 1
        """
        latest_df = duckdb.query(query).df()
    except Exception:
        return {}
    latest: dict[str, datetime] = {}
    if latest_df.empty:
        return latest
    latest_df["latest_report_date"] = pd.to_datetime(latest_df["latest_report_date"]).dt.floor("D")
    for _, row in latest_df.iterrows():
        latest[normalize_code(row["htsc_code"])] = row["latest_report_date"].to_pydatetime()
    return latest


def scan_latest_daily_factor_times(base_dir: str, table_name: str) -> dict[str, datetime]:
    table_dir = _table_base_dir(base_dir, table_name)
    if not table_dir.exists():
        return {}
    pattern = str(table_dir / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")
    try:
        query = f"""
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            MAX(CAST(time AS TIMESTAMP)) AS latest_time
        FROM read_parquet('{pattern}', union_by_name=true)
        WHERE htsc_code IS NOT NULL AND time IS NOT NULL
        GROUP BY 1
        """
        latest_df = duckdb.query(query).df()
    except Exception:
        return {}
    latest: dict[str, datetime] = {}
    if latest_df.empty:
        return latest
    latest_df["latest_time"] = pd.to_datetime(latest_df["latest_time"]).dt.floor("D")
    for _, row in latest_df.iterrows():
        latest[normalize_code(row["htsc_code"])] = row["latest_time"].to_pydatetime()
    return latest


def build_download_plan(
    codes: list[str],
    latest_map: dict[str, datetime],
    default_start: datetime,
    end_date: datetime,
    overlap_days: int,
) -> list[tuple[str, datetime]]:
    tasks: list[tuple[str, datetime]] = []
    for code in codes:
        latest = latest_map.get(normalize_code(code))
        start = default_start if latest is None else latest - timedelta(days=overlap_days)
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        if start <= end_date:
            tasks.append((normalize_code(code), start))
    return tasks


def chunked(items: list[tuple[str, datetime]], batch_size: int) -> list[list[tuple[str, datetime]]]:
    size = max(int(batch_size), 1)
    return [items[i : i + size] for i in range(0, len(items), size)]


def format_qmt_date(value: datetime) -> str:
    return value.strftime("%Y%m%d")


def fetch_batch_tables(
    batch_codes: list[str],
    table_names: list[str],
    start_date: datetime,
    end_date: datetime,
    names: dict[str, str],
) -> dict[str, pd.DataFrame]:
    start_text = format_qmt_date(start_date)
    end_text = format_qmt_date(end_date)
    xtdata.download_financial_data2(batch_codes, table_names, start_text, end_text, callback=lambda _data: None)
    raw = xtdata.get_financial_data(batch_codes, table_names, start_text, end_text)
    updated_at = datetime.now().isoformat(timespec="seconds")
    out: dict[str, list[pd.DataFrame]] = {table: [] for table in table_names}
    if not isinstance(raw, dict):
        return {table: pd.DataFrame() for table in table_names}
    for code, table_map in raw.items():
        if not isinstance(table_map, dict):
            continue
        normalized = normalize_code(code)
        for table in table_names:
            frame = table_map.get(table)
            normalized_frame = normalize_qmt_table_frame(frame, table, normalized, names.get(normalized, ""), updated_at)
            if not normalized_frame.empty:
                out[table].append(normalized_frame)
    return {
        table: pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        for table, frames in out.items()
    }


def fetch_batch_factor_tables(
    batch_codes: list[str],
    table_names: list[str],
    start_date: datetime,
    end_date: datetime,
    names: dict[str, str],
    *,
    download: bool = True,
) -> dict[str, pd.DataFrame]:
    start_text = format_qmt_date(start_date)
    end_text = format_qmt_date(end_date)
    if download:
        xtdata.download_financial_data2(batch_codes, table_names, start_text, end_text, callback=lambda _data: None)
    raw = xtdata.get_financial_data(batch_codes, table_names, start_text, end_text)
    updated_at = datetime.now().isoformat(timespec="seconds")
    out: dict[str, list[pd.DataFrame]] = {table: [] for table in table_names}
    if not isinstance(raw, dict):
        return {table: pd.DataFrame() for table in table_names}
    for code, table_map in raw.items():
        if not isinstance(table_map, dict):
            continue
        normalized = normalize_code(code)
        for table in table_names:
            frame = table_map.get(table)
            normalized_frame = normalize_daily_factor_frame(frame, table, normalized, names.get(normalized, ""), updated_at)
            if not normalized_frame.empty:
                out[table].append(normalized_frame)
    return {
        table: pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        for table, frames in out.items()
    }


def probe_factor_tables(args: argparse.Namespace, codes: list[str], names: dict[str, str], factor_tables: list[str], end_date: datetime) -> bool:
    if not factor_tables:
        return True
    probe_codes = codes[: max(int(args.probe_codes), 1)]
    probe_start = end_date - timedelta(days=max(int(args.probe_days), 1))
    print(
        f"[PROBE] 因子表接口探测: {', '.join(factor_tables)} | "
        f"{len(probe_codes)} 只 | {probe_start.date()} ~ {end_date.date()}"
    )
    try:
        frames = fetch_batch_factor_tables(
            probe_codes,
            factor_tables,
            probe_start,
            end_date,
            names,
            download=not args.no_factor_download,
        )
    except Exception as exc:
        print(f"[ERROR] QMT 因子表探测失败，未写入数据: {exc}")
        return False

    ok = True
    for table in factor_tables:
        frame = frames.get(table, pd.DataFrame())
        if frame.empty:
            print(f"[ERROR] QMT 因子表探测无数据: {table}")
            ok = False
            continue
        missing = [field for field in FACTOR_TABLE_FIELDS[table] if field not in frame.columns]
        print(
            f"[PROBE] {table}: rows={len(frame)} cols={len(frame.columns)} "
            f"time={frame['time'].min()}~{frame['time'].max()} "
            f"missing_fields={missing[:8]}"
        )
        if missing:
            ok = False
    if not ok:
        print("[ERROR] QMT 因子表未通过探测，停止下载；不会写入空表或伪造数据。")
    return ok


def _existing_valuation_paths(base_dir: str, start_date: datetime, end_date: datetime) -> list[str]:
    base = Path(base_dir)
    paths: list[str] = []
    cursor = start_date.replace(day=1)
    end_month = end_date.replace(day=1)
    while cursor <= end_month:
        path = base / f"year={cursor.year}" / f"month={cursor.month:02d}" / MERGED_FILE_NAME
        if _is_readable_parquet(path):
            paths.append(str(path).replace("\\", "/"))
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)
    return paths


def warn_factor_unit_scale(base_dir: str, touched_by_table: dict[str, set[tuple[int, int]]]) -> None:
    touched = set().union(*touched_by_table.values()) if touched_by_table else set()
    if not touched:
        return
    min_year, min_month = min(touched)
    start_date = datetime(min_year, min_month, 1)
    max_year, max_month = max(touched)
    end_date = datetime(max_year, max_month, 28) + timedelta(days=4)
    end_date = end_date - timedelta(days=end_date.day)
    valuation_paths = _existing_valuation_paths(INSIGHT_VALUATION_BASE_DIR, start_date, end_date)
    if not valuation_paths:
        print("[UNIT] 未发现对应旧 Insight 估值 parquet，跳过单位对照。")
        return

    checks = [
        ("factor_metrics", "total_mv", "total_market_val"),
        ("factor_metrics", "pb_ratio", "pb"),
        ("factor_base_derivative", "circ_market_value", "floating_market_val"),
    ]
    con = duckdb.connect(database=":memory:")
    try:
        for table, qmt_col, insight_col in checks:
            table_dir = _table_base_dir(base_dir, table)
            if not table_dir.exists():
                continue
            qmt_paths = [
                str(table_dir / f"year={year}" / f"month={month:02d}" / MERGED_FILE_NAME).replace("\\", "/")
                for year, month in touched_by_table.get(table, set())
                if _is_readable_parquet(table_dir / f"year={year}" / f"month={month:02d}" / MERGED_FILE_NAME)
            ]
            if not qmt_paths:
                continue
            qmt_reader, qmt_params = _parquet_reader(qmt_paths)
            val_reader, val_params = _parquet_reader(valuation_paths)
            sql = f"""
            SELECT median(abs(CAST(q.{qmt_col} AS DOUBLE)) / nullif(abs(CAST(v.{insight_col} AS DOUBLE)), 0)) AS ratio
            FROM {qmt_reader} q
            JOIN {val_reader} v
              ON q.htsc_code = v.htsc_code
             AND CAST(q.time AS DATE) = CAST(v.time AS DATE)
            WHERE q.{qmt_col} IS NOT NULL AND v.{insight_col} IS NOT NULL
            """
            ratio_df = con.execute(sql, [*qmt_params, *val_params]).df()
            ratio = ratio_df.iloc[0]["ratio"] if not ratio_df.empty else None
            if ratio is None or pd.isna(ratio):
                print(f"[UNIT] {table}.{qmt_col} 无可对照样本。")
                continue
            ratio_float = float(ratio)
            level = "WARN" if ratio_float < 0.01 or ratio_float > 100 else "OK"
            print(f"[UNIT-{level}] {table}.{qmt_col} / Insight.{insight_col} median_ratio={ratio_float:.6g}")
            if ratio_float < 0.01 or ratio_float > 100:
                print(f"[UNIT-WARN] {table}.{qmt_col} 可能存在元/万/亿单位差异，请人工确认后再替代使用。")
    finally:
        con.close()


def rebuild_existing_tables(base_dir: str, table_names: list[str]) -> None:
    for table in table_names:
        table_dir = _table_base_dir(base_dir, table)
        touched: set[tuple[int, int]] = set()
        for path in table_dir.glob("year=*/month=*"):
            try:
                year = int(path.parent.name.split("=", 1)[1])
                month = int(path.name.split("=", 1)[1])
            except Exception:
                continue
            touched.add((year, month))
        rebuild_merged_parquets(base_dir, table, touched)


def rebuild_existing_daily_factor_tables(base_dir: str, table_names: list[str]) -> None:
    for table in table_names:
        table_dir = _table_base_dir(base_dir, table)
        touched: set[tuple[int, int]] = set()
        for path in table_dir.glob("year=*/month=*"):
            try:
                year = int(path.parent.name.split("=", 1)[1])
                month = int(path.name.split("=", 1)[1])
            except Exception:
                continue
            touched.add((year, month))
        rebuild_daily_factor_merged_parquets(base_dir, table, touched)


def run_daily_factor_download(
    args: argparse.Namespace,
    factor_tables: list[str],
    codes: list[str],
    names: dict[str, str],
    default_start: datetime,
    end_date: datetime,
) -> None:
    if not factor_tables:
        return
    if args.probe_factor_tables and not probe_factor_tables(args, codes, names, factor_tables, end_date):
        return

    latest_by_table = {table: scan_latest_daily_factor_times(args.base_dir, table) for table in factor_tables}
    tasks_by_start: dict[datetime, list[str]] = defaultdict(list)
    for code in codes:
        starts = []
        for table in factor_tables:
            latest = latest_by_table[table].get(code)
            starts.append(default_start if latest is None else latest - timedelta(days=args.overlap_days))
        start = min(starts).replace(hour=0, minute=0, second=0, microsecond=0)
        if start <= end_date:
            tasks_by_start[start].append(code)

    total_codes = sum(len(v) for v in tasks_by_start.values())
    if total_codes == 0:
        print("QMT 因子表无需要更新的数据。")
        return
    print(f"QMT 因子表需更新代码数: {total_codes} | 表: {', '.join(factor_tables)}")

    touched_by_table: dict[str, set[tuple[int, int]]] = {table: set() for table in factor_tables}
    processed = 0
    for start_date, group_codes in sorted(tasks_by_start.items(), key=lambda item: item[0]):
        for batch_codes in [group_codes[i : i + args.batch_size] for i in range(0, len(group_codes), args.batch_size)]:
            processed += len(batch_codes)
            print(f"[RUN-FACTOR] {processed}/{total_codes} | {start_date.date()} ~ {end_date.date()} | {len(batch_codes)} 只")
            try:
                frames = fetch_batch_factor_tables(
                    batch_codes,
                    factor_tables,
                    start_date,
                    end_date,
                    names,
                    download=not args.no_factor_download,
                )
            except Exception as exc:
                print(f"[WARN] 因子表批次失败: {exc}")
                time.sleep(args.sleep_sec)
                continue
            for table, frame in frames.items():
                touched = save_daily_factor_partitioned_parquet(frame, args.base_dir, table)
                touched_by_table[table].update(touched)
            time.sleep(args.sleep_sec)

    for table, touched in touched_by_table.items():
        if touched:
            rebuild_daily_factor_merged_parquets(args.base_dir, table, touched)
        else:
            print(f"[INFO] 因子表 {table} 无新增分区。")
    warn_factor_unit_scale(args.base_dir, touched_by_table)


def run_download(args: argparse.Namespace) -> None:
    tables = parse_tables_arg(args.tables)
    factor_tables = parse_factor_tables_arg(args.factor_tables)
    if args.rebuild_only:
        rebuild_existing_tables(args.base_dir, tables)
        rebuild_existing_daily_factor_tables(args.base_dir, factor_tables)
        return
    end_text = str(args.end or "").strip()
    end_date = datetime.now() if not end_text else datetime.strptime(end_text, "%Y-%m-%d")
    end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    default_start = datetime.strptime(args.default_start, "%Y-%m-%d")

    print(f"从 QMT 加载股票池: {args.codes or args.sector_name}")
    codes = resolve_codes(args.sector_name, args.codes)
    print(f"股票池: {len(codes)} 只 | 财报表: {', '.join(tables) if tables else 'none'} | 因子表: {', '.join(factor_tables) if factor_tables else 'none'}")
    names = {code: load_xtquant_name(code) for code in codes}

    if factor_tables:
        run_daily_factor_download(args, factor_tables, codes, names, default_start, end_date)

    if not tables:
        return

    latest_by_table = {table: scan_latest_report_dates(args.base_dir, table) for table in tables}
    tasks_by_start: dict[datetime, list[str]] = defaultdict(list)
    for code in codes:
        starts = []
        for table in tables:
            latest = latest_by_table[table].get(code)
            starts.append(default_start if latest is None else latest - timedelta(days=args.overlap_days))
        start = min(starts).replace(hour=0, minute=0, second=0, microsecond=0)
        if start <= end_date:
            tasks_by_start[start].append(code)

    total_codes = sum(len(v) for v in tasks_by_start.values())
    if total_codes == 0:
        print("无需要更新的数据。")
        return
    print(f"需更新代码数: {total_codes}")

    touched_by_table: dict[str, set[tuple[int, int]]] = {table: set() for table in tables}
    processed = 0
    for start_date, group_codes in sorted(tasks_by_start.items(), key=lambda item: item[0]):
        for batch_codes in [group_codes[i : i + args.batch_size] for i in range(0, len(group_codes), args.batch_size)]:
            processed += len(batch_codes)
            print(f"[RUN] {processed}/{total_codes} | {start_date.date()} ~ {end_date.date()} | {len(batch_codes)} 只")
            try:
                frames = fetch_batch_tables(batch_codes, tables, start_date, end_date, names)
            except Exception as exc:
                print(f"[WARN] 批次失败: {exc}")
                time.sleep(args.sleep_sec)
                continue
            for table, frame in frames.items():
                touched = save_partitioned_parquet(frame, args.base_dir, table)
                touched_by_table[table].update(touched)
            time.sleep(args.sleep_sec)

    for table, touched in touched_by_table.items():
        if touched:
            rebuild_merged_parquets(args.base_dir, table, touched)
        else:
            print(f"[INFO] {table} 无新增分区。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QMT 公司数据下载：财务三表、主要指标、股本结构")
    parser.add_argument("--tables", default="all", help="all 或逗号分隔：Income,Balance,CashFlow,PershareIndex,Capital")
    parser.add_argument(
        "--factor-tables",
        default="none",
        help="none/all 或逗号分隔：factor_base_derivative,factor_metrics；默认 none",
    )
    parser.add_argument("--sector-name", default=DEFAULT_SECTOR_NAME, help="xtquant 板块名称，默认 沪深A股")
    parser.add_argument("--codes", default="", help="逗号分隔的手动股票代码；不填则使用 --sector-name 股票池")
    parser.add_argument("--default-start", default=DEFAULT_START_DATE, help="首次全量起始报告期，YYYY-MM-DD")
    parser.add_argument("--end", default="", help="结束日期，默认今天，YYYY-MM-DD")
    parser.add_argument("--overlap-days", type=int, default=DEFAULT_OVERLAP_DAYS, help="增量回溯天数")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="每批股票数")
    parser.add_argument("--base-dir", default=BASE_DIR, help="输出根目录")
    parser.add_argument("--sleep-sec", type=float, default=DEFAULT_SLEEP_SEC, help="批次间隔秒数")
    parser.add_argument("--rebuild-only", action="store_true", help="只重建已有分区 merged.parquet")
    parser.add_argument("--probe-factor-tables", action="store_true", help="先小样本探测 QMT 因子表，失败则不写入")
    parser.add_argument("--probe-codes", type=int, default=3, help="因子表探测股票数量，默认 3")
    parser.add_argument("--probe-days", type=int, default=92, help="因子表探测回看天数，默认 92")
    parser.add_argument("--no-factor-download", action="store_true", help="因子表只查询本地缓存，不调用 download_financial_data2")
    return parser.parse_args()


def main() -> None:
    run_download(parse_args())


if __name__ == "__main__":
    main()
