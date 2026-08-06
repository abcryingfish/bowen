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
DAILY_DATA_BASE_DIR = r"D:\database\stock_basic_data_daily"
DEFAULT_SECTOR_NAME = "沪深A股"
DEFAULT_START_DATE = "2010-01-01"
DEFAULT_OVERLAP_DAYS = 300
DEFAULT_BATCH_SIZE = 200
DEFAULT_SLEEP_SEC = 0.0005
MERGED_FILE_NAME = "merged.parquet"
MIN_PARQUET_BYTES = 12
QMT_TABLES = ("Income", "Balance", "CashFlow", "PershareIndex", "Capital")
QMT_FACTOR_TABLES = ("factor_base_derivative", "factor_metrics")
FUNDAMENTAL_VALUATION_TABLE = "factor_fundamental_valuation"
DEDUP_COLUMNS = ("htsc_code", "table_name", "report_date", "announce_date")
DAILY_FACTOR_DEDUP_COLUMNS = ("htsc_code", "table_name", "time")
FACTOR_DATE_COLUMN_CANDIDATES = ("time", "trading_day", "date", "m_timetag")

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
    announce_source = (
        out["m_anntime"]
        if "m_anntime" in out.columns
        else pd.Series(pd.NaT, index=out.index)
    )
    out["report_date"] = pd.Series(report_source).map(parse_qmt_date)
    out["announce_date"] = pd.Series(announce_source).map(parse_qmt_date)
    out["htsc_code"] = normalize_code(code)
    out["name"] = str(name or "")
    out["table_name"] = str(table_name)
    out["period"] = out["report_date"].map(period_from_report_date)
    out["updated_at"] = updated_at
    out = out.dropna(subset=["report_date", "announce_date"]).copy()
    if out.empty:
        return out
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


def _timestamp_token() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


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


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column in df.columns:
        return pd.to_numeric(df[column], errors="coerce")
    return pd.Series(pd.NA, index=df.index, dtype="Float64")


def _normalize_statement_input(df: pd.DataFrame, value_columns: list[str], prefix: str) -> pd.DataFrame:
    if df is None or df.empty:
        columns = ["htsc_code", f"{prefix}_report_date", f"{prefix}_announce_date", *value_columns]
        return pd.DataFrame(columns=columns)
    out = pd.DataFrame()
    out["htsc_code"] = df["htsc_code"].map(normalize_code)
    out[f"{prefix}_report_date"] = pd.to_datetime(df["report_date"], errors="coerce").dt.floor("D")
    out[f"{prefix}_announce_date"] = pd.to_datetime(df["announce_date"], errors="coerce").dt.floor("D")
    for column in value_columns:
        out[column] = _numeric_series(df, column)
    out = out.dropna(subset=["htsc_code", f"{prefix}_report_date", f"{prefix}_announce_date"]).copy()
    sort_cols = ["htsc_code", f"{prefix}_announce_date", f"{prefix}_report_date"]
    return out.sort_values(sort_cols).drop_duplicates(sort_cols, keep="last").reset_index(drop=True)


def _latest_statement_by_announce(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    if df.empty:
        return df
    return (
        df.sort_values(["htsc_code", f"{prefix}_announce_date", f"{prefix}_report_date"])
        .drop_duplicates(["htsc_code", f"{prefix}_announce_date"], keep="last")
        .reset_index(drop=True)
    )


def _add_ttm_values(
    df: pd.DataFrame,
    value_column: str,
    output_column: str,
    report_date_column: str,
) -> pd.DataFrame:
    if df.empty:
        df[output_column] = pd.Series(dtype="float64")
        return df
    out = df.copy()
    out["_report_year"] = out[report_date_column].dt.year
    out["_report_month"] = out[report_date_column].dt.month
    lookup = {
        (row["htsc_code"], int(row["_report_year"]), int(row["_report_month"])): row[value_column]
        for _, row in out.iterrows()
    }

    def calc(row: pd.Series) -> float | pd.NA:
        current = row[value_column]
        if pd.isna(current):
            return pd.NA
        year = int(row["_report_year"])
        month = int(row["_report_month"])
        if month == 12:
            return current
        annual = lookup.get((row["htsc_code"], year - 1, 12), pd.NA)
        same_period = lookup.get((row["htsc_code"], year - 1, month), pd.NA)
        if pd.isna(annual) or pd.isna(same_period):
            return pd.NA
        return current + annual - same_period

    out[output_column] = out.apply(calc, axis=1)
    return out.drop(columns=["_report_year", "_report_month"])


def _merge_asof_by_code(left: pd.DataFrame, right: pd.DataFrame, right_on: str) -> pd.DataFrame:
    if left.empty or right.empty:
        return left.copy()
    parts: list[pd.DataFrame] = []
    for code, left_group in left.groupby("htsc_code", sort=False):
        right_group = right[right["htsc_code"] == code]
        if right_group.empty:
            parts.append(left_group.copy())
            continue
        merged = pd.merge_asof(
            left_group.sort_values("time"),
            right_group.sort_values(right_on),
            left_on="time",
            right_on=right_on,
            by="htsc_code",
            direction="backward",
        )
        parts.append(merged)
    if not parts:
        return left.copy()
    return pd.concat(parts, ignore_index=True)


def build_fundamental_valuation_frame(
    income_df: pd.DataFrame,
    balance_df: pd.DataFrame,
    pershare_df: pd.DataFrame,
    capital_df: pd.DataFrame,
    daily_df: pd.DataFrame,
) -> pd.DataFrame:
    daily = daily_df.copy()
    if daily.empty:
        return pd.DataFrame()
    daily["htsc_code"] = daily["htsc_code"].map(normalize_code)
    daily["time"] = pd.to_datetime(daily["time"], errors="coerce").dt.floor("D")
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    daily = daily.dropna(subset=["htsc_code", "time", "close"]).sort_values(["htsc_code", "time"])
    if daily.empty:
        return pd.DataFrame()

    income = _normalize_statement_input(
        income_df,
        ["revenue", "net_profit_excl_min_int_inc"],
        "income",
    )
    income = _add_ttm_values(income, "revenue", "revenue_ttm", "income_report_date")
    income = _add_ttm_values(
        income,
        "net_profit_excl_min_int_inc",
        "net_profit_parent_ttm",
        "income_report_date",
    )
    income = _latest_statement_by_announce(income, "income")

    balance = _normalize_statement_input(
        balance_df,
        ["tot_shrhldr_eqy_excl_min_int"],
        "balance",
    )
    balance = _latest_statement_by_announce(balance, "balance")

    pershare = _normalize_statement_input(
        pershare_df,
        ["equity_roe", "net_roe"],
        "roe",
    )
    pershare = _latest_statement_by_announce(pershare, "roe")

    capital = _normalize_statement_input(
        capital_df,
        ["total_capital"],
        "capital",
    )
    capital = _latest_statement_by_announce(capital, "capital")

    out = _merge_asof_by_code(daily, income, "income_announce_date")
    out = _merge_asof_by_code(out, balance, "balance_announce_date")
    out = _merge_asof_by_code(out, pershare, "roe_announce_date")
    out = _merge_asof_by_code(out, capital, "capital_announce_date")
    out = out.dropna(subset=["income_report_date", "balance_report_date", "capital_report_date"]).copy()
    if out.empty:
        return out

    out["revenue"] = out["revenue"].astype(float)
    out["net_profit_parent"] = out["net_profit_excl_min_int_inc"].astype(float)
    out["equity_parent"] = out["tot_shrhldr_eqy_excl_min_int"].astype(float)
    out["roe"] = out["equity_roe"].astype(float)
    out["total_market_val"] = out["close"] * out["total_capital"]
    out["pe_ttm"] = _safe_ratio(out["total_market_val"], out["net_profit_parent_ttm"])
    out["pb"] = _safe_ratio(out["total_market_val"], out["equity_parent"])
    out["table_name"] = FUNDAMENTAL_VALUATION_TABLE
    out["updated_at"] = datetime.now().isoformat(timespec="seconds")

    columns = [
        "htsc_code",
        "table_name",
        "time",
        "income_report_date",
        "income_announce_date",
        "balance_report_date",
        "balance_announce_date",
        "roe_report_date",
        "roe_announce_date",
        "capital_report_date",
        "capital_announce_date",
        "close",
        "total_capital",
        "total_market_val",
        "revenue",
        "revenue_ttm",
        "net_profit_parent",
        "net_profit_parent_ttm",
        "equity_parent",
        "pe_ttm",
        "pb",
        "roe",
        "net_roe",
        "updated_at",
    ]
    return out[[col for col in columns if col in out.columns]].sort_values(["time", "htsc_code"]).reset_index(drop=True)


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
        file_path = dir_path / f"{_timestamp_token()}_year_{year}_month_{month:02d}.parquet"
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
        file_path = dir_path / f"{_timestamp_token()}_year_{year}_month_{month:02d}.parquet"
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


def _parquet_reader(paths: list[str]) -> tuple[str, list[str]]:
    if not paths:
        raise ValueError("paths must not be empty")
    placeholders = ", ".join(["?"] * len(paths))
    return f"read_parquet([{placeholders}], union_by_name=true)", paths


def _existing_table_paths(base_dir: str, table_name: str, start_date: datetime | None = None, end_date: datetime | None = None) -> list[str]:
    table_dir = _table_base_dir(base_dir, table_name)
    if not table_dir.exists():
        return []
    paths: list[str] = []
    for path in sorted(table_dir.glob("year=*/month=*/merged.parquet")):
        if not _is_readable_parquet(path):
            continue
        if start_date is not None or end_date is not None:
            try:
                year = int(path.parent.parent.name.split("=", 1)[1])
                month = int(path.parent.name.split("=", 1)[1])
            except Exception:
                continue
            partition_start = datetime(year, month, 1)
            partition_end = datetime(year + int(month == 12), 1 if month == 12 else month + 1, 1) - timedelta(days=1)
            if start_date is not None and partition_end < start_date:
                continue
            if end_date is not None and partition_start > end_date:
                continue
        paths.append(str(path).replace("\\", "/"))
    return paths


def _existing_daily_paths(daily_base_dir: str, start_date: datetime, end_date: datetime) -> list[str]:
    base = Path(daily_base_dir)
    if not base.exists():
        return []
    paths: list[str] = []
    for path in sorted(base.glob("year=*/month=*/merged.parquet")):
        if not _is_readable_parquet(path):
            continue
        try:
            year = int(path.parent.parent.name.split("=", 1)[1])
            month = int(path.parent.name.split("=", 1)[1])
        except Exception:
            continue
        partition_start = datetime(year, month, 1)
        partition_end = datetime(year + int(month == 12), 1 if month == 12 else month + 1, 1) - timedelta(days=1)
        if partition_end < start_date or partition_start > end_date:
            continue
        paths.append(str(path).replace("\\", "/"))
    return paths


def _load_table_frame(base_dir: str, table_name: str, columns: list[str]) -> pd.DataFrame:
    paths = _existing_table_paths(base_dir, table_name)
    if not paths:
        return pd.DataFrame(columns=columns)
    reader, params = _parquet_reader(paths)
    select_cols = ", ".join(columns)
    return duckdb.connect(database=":memory:").execute(f"SELECT {select_cols} FROM {reader}", params).df()


def _load_daily_frame(daily_base_dir: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
    paths = _existing_daily_paths(daily_base_dir, start_date, end_date)
    if not paths:
        return pd.DataFrame(columns=["htsc_code", "time", "close"])
    reader, params = _parquet_reader(paths)
    query = f"""
    SELECT
        UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
        CAST(time AS TIMESTAMP) AS time,
        TRY_CAST(close AS DOUBLE) AS close
    FROM {reader}
    WHERE time >= ? AND time <= ?
      AND htsc_code IS NOT NULL
      AND close IS NOT NULL
    """
    return duckdb.connect(database=":memory:").execute(query, [*params, start_date, end_date]).df()


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denom = pd.to_numeric(denominator, errors="coerce")
    denom = denom.mask(denom == 0)
    return pd.to_numeric(numerator, errors="coerce") / denom


def save_fundamental_valuation_partitioned_parquet(df: pd.DataFrame, base_dir: str) -> list[tuple[int, int]]:
    if df is None or df.empty:
        return []
    pl_df = (
        pl.from_pandas(df)
        .with_columns(
            pl.col("time").cast(pl.Datetime, strict=False).dt.truncate("1d").alias("time"),
            pl.col("htsc_code").cast(pl.Utf8).str.to_uppercase().str.strip_chars().alias("htsc_code"),
            pl.lit(FUNDAMENTAL_VALUATION_TABLE).alias("table_name"),
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
        dir_path = _table_base_dir(base_dir, FUNDAMENTAL_VALUATION_TABLE) / f"year={year}" / f"month={month:02d}"
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = dir_path / f"{_timestamp_token()}_year_{year}_month_{month:02d}.parquet"
        save_df = partition_df.drop(["year", "month"])
        save_df.write_parquet(str(file_path), compression="zstd")
        touched.append((year, month))
        print(f"[OK] saved {FUNDAMENTAL_VALUATION_TABLE}: {file_path} ({len(save_df)} rows)")
    return touched


def run_fundamental_valuation_derivation(args: argparse.Namespace, start_date: datetime, end_date: datetime) -> None:
    required = ["Income", "Balance", "PershareIndex", "Capital"]
    missing = [table for table in required if not _existing_table_paths(args.base_dir, table)]
    if missing:
        print(f"[WARN] skip {FUNDAMENTAL_VALUATION_TABLE}; missing tables: {', '.join(missing)}")
        return

    income = _load_table_frame(
        args.base_dir,
        "Income",
        ["htsc_code", "report_date", "announce_date", "revenue", "net_profit_excl_min_int_inc"],
    )
    balance = _load_table_frame(
        args.base_dir,
        "Balance",
        ["htsc_code", "report_date", "announce_date", "tot_shrhldr_eqy_excl_min_int"],
    )
    pershare = _load_table_frame(
        args.base_dir,
        "PershareIndex",
        ["htsc_code", "report_date", "announce_date", "equity_roe", "net_roe"],
    )
    capital = _load_table_frame(
        args.base_dir,
        "Capital",
        ["htsc_code", "report_date", "announce_date", "total_capital"],
    )
    daily = _load_daily_frame(args.daily_base_dir, start_date, end_date)
    derived = build_fundamental_valuation_frame(income, balance, pershare, capital, daily)
    if derived.empty:
        print(f"[INFO] {FUNDAMENTAL_VALUATION_TABLE} no rows for {start_date.date()} ~ {end_date.date()}")
        return
    touched = save_fundamental_valuation_partitioned_parquet(derived, args.base_dir)
    rebuild_daily_factor_merged_parquets(args.base_dir, FUNDAMENTAL_VALUATION_TABLE, set(touched))


def warn_factor_unit_scale(base_dir: str, touched_by_table: dict[str, set[tuple[int, int]]]) -> None:
    del base_dir, touched_by_table
    print("[UNIT] 已切换为 QMT 公司数据主链路，跳过旧估值目录单位对照。")


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
        if args.derive_valuation:
            run_fundamental_valuation_derivation(args, derive_start, derive_end)
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
    derive_end_text = str(args.derive_end or args.end or "").strip()
    derive_end = datetime.now() if not derive_end_text else datetime.strptime(derive_end_text, "%Y-%m-%d")
    derive_end = derive_end.replace(hour=23, minute=59, second=59, microsecond=999999)
    derive_start_text = str(args.derive_start or "").strip()
    derive_start = (
        datetime.strptime(derive_start_text, "%Y-%m-%d")
        if derive_start_text
        else derive_end - timedelta(days=max(int(args.derive_lookback_days), 0))
    )
    derive_start = derive_start.replace(hour=0, minute=0, second=0, microsecond=0)
    if args.derive_only:
        run_fundamental_valuation_derivation(args, derive_start, derive_end)
        return
    if args.rebuild_only:
        rebuild_existing_tables(args.base_dir, tables)
        rebuild_existing_daily_factor_tables(args.base_dir, factor_tables)
        if args.derive_valuation:
            run_fundamental_valuation_derivation(args, derive_start, derive_end)
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
        if args.derive_valuation:
            run_fundamental_valuation_derivation(args, derive_start, derive_end)
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



    if args.derive_valuation:
        run_fundamental_valuation_derivation(args, derive_start, derive_end)
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
    parser.add_argument("--daily-base-dir", default=DAILY_DATA_BASE_DIR, help="daily OHLC root for derived PE/PB table")
    parser.add_argument(
        "--derive-valuation",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="build factor_fundamental_valuation after download/rebuild; use --no-derive-valuation to disable",
    )
    parser.add_argument("--derive-only", action="store_true", help="only build factor_fundamental_valuation; do not download raw statements")
    parser.add_argument("--derive-start", default="", help="derived table start trading day, YYYY-MM-DD; empty uses --derive-lookback-days")
    parser.add_argument("--derive-end", default="", help="derived table end trading day, YYYY-MM-DD; empty follows --end/today")
    parser.add_argument("--derive-lookback-days", type=int, default=7, help="lookback days for derived table when --derive-start is empty; default 7")
    parser.add_argument("--probe-factor-tables", action="store_true", help="先小样本探测 QMT 因子表，失败则不写入")
    parser.add_argument("--probe-codes", type=int, default=3, help="因子表探测股票数量，默认 3")
    parser.add_argument("--probe-days", type=int, default=92, help="因子表探测回看天数，默认 92")
    parser.add_argument("--no-factor-download", action="store_true", help="因子表只查询本地缓存，不调用 download_financial_data2")
    return parser.parse_args()


def main() -> None:
    run_download(parse_args())


if __name__ == "__main__":
    main()
