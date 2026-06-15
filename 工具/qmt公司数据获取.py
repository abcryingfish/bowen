#!/usr/bin/python3
# -*- coding: utf-8 -*-
r"""QMT 公司数据下载。

数据源：xtquant.xtdata 财务接口。
落盘：D:\database\qmt_company_data/table=<QMT表名>/year=YYYY/month=MM/merged.parquet
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
DEDUP_COLUMNS = ("htsc_code", "table_name", "report_date", "announce_date")


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


def run_download(args: argparse.Namespace) -> None:
    tables = parse_tables_arg(args.tables)
    if args.rebuild_only:
        rebuild_existing_tables(args.base_dir, tables)
        return
    end_text = str(args.end or "").strip()
    end_date = datetime.now() if not end_text else datetime.strptime(end_text, "%Y-%m-%d")
    end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    default_start = datetime.strptime(args.default_start, "%Y-%m-%d")

    print(f"从 QMT 加载股票池: {args.codes or args.sector_name}")
    codes = resolve_codes(args.sector_name, args.codes)
    print(f"股票池: {len(codes)} 只 | 表: {', '.join(tables)}")
    names = {code: load_xtquant_name(code) for code in codes}

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
    parser.add_argument("--sector-name", default=DEFAULT_SECTOR_NAME, help="xtquant 板块名称，默认 沪深A股")
    parser.add_argument("--codes", default="", help="逗号分隔的手动股票代码；不填则使用 --sector-name 股票池")
    parser.add_argument("--default-start", default=DEFAULT_START_DATE, help="首次全量起始报告期，YYYY-MM-DD")
    parser.add_argument("--end", default="", help="结束日期，默认今天，YYYY-MM-DD")
    parser.add_argument("--overlap-days", type=int, default=DEFAULT_OVERLAP_DAYS, help="增量回溯天数")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="每批股票数")
    parser.add_argument("--base-dir", default=BASE_DIR, help="输出根目录")
    parser.add_argument("--sleep-sec", type=float, default=DEFAULT_SLEEP_SEC, help="批次间隔秒数")
    parser.add_argument("--rebuild-only", action="store_true", help="只重建已有分区 merged.parquet")
    return parser.parse_args()


def main() -> None:
    run_download(parse_args())


if __name__ == "__main__":
    main()
