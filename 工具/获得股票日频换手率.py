#!/usr/bin/python3
# -*- coding: utf-8 -*-
r"""日频换手率生成。

数据源：
- 日 K：D:\database\stock_basic_data_daily
- 股本：D:\database\qmt_company_data\table=Capital

输出：
D:\database\qmt_turnover_data\year=YYYY\month=MM\merged.parquet

换手率口径：turnover_rate = volume / circulating_capital * 100。
Capital 按 max(report_date, announce_date) <= 交易日 的最近一条匹配。
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import polars as pl

DAILY_BASE_DIR = r"D:\database\stock_basic_data_daily"
CAPITAL_BASE_DIR = r"D:\database\qmt_company_data"
BASE_DIR = r"D:\database\qmt_turnover_data"
MERGED_FILE_NAME = "merged.parquet"
MIN_PARQUET_BYTES = 12
PARQUET_WRITE_RETRIES = 5
PARQUET_WRITE_RETRY_SLEEP_SEC = 0.5
DEFAULT_LOOKBACK_DAYS = 5
DEFAULT_START_DATE = "2010-01-01"


def _timestamp_token() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _parquet_pattern(base_dir: str) -> str:
    return str(Path(base_dir) / "year=*" / "month=*" / MERGED_FILE_NAME).replace("\\", "/")


def _capital_pattern(capital_base_dir: str) -> str:
    return str(Path(capital_base_dir) / "table=Capital" / "year=*" / "month=*" / MERGED_FILE_NAME).replace("\\", "/")


def scan_latest_turnover_time(base_dir: str) -> datetime | None:
    parquet_pattern = _parquet_pattern(base_dir)
    try:
        con = duckdb.connect()
        latest_df = con.execute(
            """
            SELECT MAX(CAST(time AS TIMESTAMP)) AS latest_time
            FROM read_parquet(?, hive_partitioning=1, union_by_name=true)
            WHERE time IS NOT NULL
            """,
            [parquet_pattern],
        ).df()
    except Exception:
        return None
    finally:
        try:
            con.close()
        except Exception:
            pass
    if latest_df.empty or pd.isna(latest_df.loc[0, "latest_time"]):
        return None
    return pd.to_datetime(latest_df.loc[0, "latest_time"]).floor("D").to_pydatetime()


def resolve_default_start_date(base_dir: str, end_date: datetime) -> str:
    latest_time = scan_latest_turnover_time(base_dir)
    if latest_time is None:
        return DEFAULT_START_DATE
    start_time = latest_time - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    if start_time > end_date:
        start_time = end_date
    return start_time.strftime("%Y-%m-%d")


def normalize_code(code: str) -> str:
    return str(code or "").strip().upper()


def parse_codes(codes: str | None) -> list[str]:
    if not codes:
        return []
    return sorted({normalize_code(part) for part in str(codes).replace("，", ",").split(",") if part.strip()})


def calculate_turnover_frame(daily: pd.DataFrame, capital: pd.DataFrame) -> pd.DataFrame:
    """用日 K 和 Capital 计算换手率及市值，并清洗无效自由流通股本。"""
    if daily is None or daily.empty or capital is None or capital.empty:
        return pd.DataFrame()

    daily_df = daily.copy()
    capital_df = capital.copy()
    daily_df["htsc_code"] = daily_df["htsc_code"].map(normalize_code)
    capital_df["htsc_code"] = capital_df["htsc_code"].map(normalize_code)
    daily_df["time"] = pd.to_datetime(daily_df["time"], errors="coerce").dt.floor("D")
    capital_df["report_date"] = pd.to_datetime(capital_df["report_date"], errors="coerce").dt.floor("D")
    if "announce_date" in capital_df.columns:
        capital_df["announce_date"] = pd.to_datetime(capital_df["announce_date"], errors="coerce").dt.floor("D")
    else:
        capital_df["announce_date"] = capital_df["report_date"]
    capital_df["capital_effective_date"] = capital_df[
        ["report_date", "announce_date"]
    ].max(axis=1)

    daily_df["volume"] = pd.to_numeric(daily_df["volume"], errors="coerce")
    if "value" in daily_df.columns:
        daily_df["value"] = pd.to_numeric(daily_df["value"], errors="coerce")
    if "close" in daily_df.columns:
        daily_df["close"] = pd.to_numeric(daily_df["close"], errors="coerce")

    for column in ("total_capital", "circulating_capital", "freeFloatCapital"):
        if column not in capital_df.columns:
            capital_df[column] = pd.NA
        capital_df[column] = pd.to_numeric(capital_df[column], errors="coerce")
    capital_df["freeFloatCapital"] = capital_df["freeFloatCapital"].where(
        capital_df["freeFloatCapital"].gt(0)
        & capital_df["freeFloatCapital"].le(capital_df["circulating_capital"])
    )

    daily_df = daily_df.dropna(subset=["htsc_code", "time", "volume"])
    capital_df = capital_df.dropna(
        subset=["htsc_code", "capital_effective_date", "circulating_capital"]
    )
    daily_df = daily_df[daily_df["volume"] > 0].copy()
    capital_df = capital_df[capital_df["circulating_capital"] > 0].copy()
    if daily_df.empty or capital_df.empty:
        return pd.DataFrame()

    daily_df = daily_df.sort_values(["htsc_code", "time"]).reset_index(drop=True)
    capital_df = (
        capital_df.sort_values(
            [
                "htsc_code",
                "capital_effective_date",
                "announce_date",
                "report_date",
            ],
            na_position="first",
        )
        .drop_duplicates(["htsc_code", "capital_effective_date"], keep="last")
        .reset_index(drop=True)
    )

    frames: list[pd.DataFrame] = []
    capital_groups = dict(tuple(capital_df.groupby("htsc_code", sort=False)))
    for code, day_group in daily_df.groupby("htsc_code", sort=False):
        cap_group = capital_groups.get(code)
        if cap_group is None or cap_group.empty:
            continue
        merged = pd.merge_asof(
            day_group.sort_values("time"),
            cap_group[
                [
                    "report_date",
                    "announce_date",
                    "capital_effective_date",
                    "total_capital",
                    "circulating_capital",
                    "freeFloatCapital",
                ]
            ].sort_values("capital_effective_date"),
            left_on="time",
            right_on="capital_effective_date",
            direction="backward",
        )
        frames.append(merged)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True).dropna(subset=["circulating_capital"]).copy()
    out["freeFloatCapital"] = out.groupby("htsc_code", sort=False)[
        "freeFloatCapital"
    ].ffill()
    out["freeFloatCapital"] = out["freeFloatCapital"].where(
        out["freeFloatCapital"].gt(0)
        & out["freeFloatCapital"].le(out["circulating_capital"])
    )
    out["turnover_rate"] = out["volume"] / out["circulating_capital"] * 100.0
    out["capital_report_date"] = out["report_date"]
    out["capital_announce_date"] = out["announce_date"]
    out["turnover_source"] = "qmt_capital_circulating"
    out["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if "close" in out.columns:
        out["floating_market_val"] = out["close"] * out["circulating_capital"]
        out["free_float_market_val"] = out["close"] * out["freeFloatCapital"]
        out["total_market_val"] = out["close"] * out["total_capital"]
    else:
        out["floating_market_val"] = pd.NA
        out["free_float_market_val"] = pd.NA
        out["total_market_val"] = pd.NA

    if "value" in out.columns:
        out["avg_price"] = out["value"] / out["volume"]
    else:
        out["avg_price"] = pd.NA

    keep_cols = [
        "htsc_code",
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "value",
        "turnover_rate",
        "avg_price",
        "floating_market_val",
        "free_float_market_val",
        "total_market_val",
        "total_capital",
        "circulating_capital",
        "freeFloatCapital",
        "capital_report_date",
        "capital_announce_date",
        "capital_effective_date",
        "turnover_source",
        "updated_at",
    ]
    for column in keep_cols:
        if column not in out.columns:
            out[column] = pd.NA
    return out[keep_cols].sort_values(["time", "htsc_code"]).reset_index(drop=True)


def _is_readable_parquet(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= MIN_PARQUET_BYTES and not pl.read_parquet(str(path), n_rows=1).is_empty()
    except Exception:
        return False


def _write_parquet_atomic_with_retry(df: pl.DataFrame, file_path: Path, compression: str = "zstd") -> None:
    last_exc: Exception | None = None
    for attempt in range(1, PARQUET_WRITE_RETRIES + 1):
        temp_path = file_path.parent / f"{file_path.name}.{os.getpid()}.{time.time_ns()}.tmp"
        try:
            df.write_parquet(str(temp_path), compression=compression)
            temp_path.replace(file_path)
            return
        except OSError as exc:
            last_exc = exc
            try:
                if temp_path.exists() and temp_path.stat().st_size == 0:
                    temp_path.unlink()
            except OSError:
                pass
            if attempt < PARQUET_WRITE_RETRIES:
                time.sleep(PARQUET_WRITE_RETRY_SLEEP_SEC * attempt)
                continue
            raise
    if last_exc is not None:
        raise last_exc


def transform_turnover_merged(df: pl.DataFrame) -> pl.DataFrame:
    if "time" not in df.columns or "htsc_code" not in df.columns:
        return df
    return (
        df.with_columns(
            [
                pl.col("time")
                .map_elements(lambda v: pd.to_datetime(v, errors="coerce"), return_dtype=pl.Datetime)
                .dt.truncate("1d")
                .alias("time"),
                pl.col("htsc_code").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("htsc_code"),
            ]
        )
        .drop_nulls(["time", "htsc_code"])
        .unique(subset=["htsc_code", "time"], keep="last")
        .sort(["time", "htsc_code"])
    )


def save_partitioned_parquet(df: pl.DataFrame, base_dir: str) -> set[tuple[int, int]]:
    if df.is_empty():
        return set()
    df = transform_turnover_merged(df)
    df = df.with_columns(
        [
            pl.col("time").dt.year().alias("year"),
            pl.col("time").dt.month().alias("month"),
        ]
    )
    touched: set[tuple[int, int]] = set()
    for partition_df in df.partition_by(["year", "month"]):
        year = int(partition_df["year"][0])
        month = int(partition_df["month"][0])
        dir_path = Path(base_dir) / f"year={year}" / f"month={month:02d}"
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = dir_path / f"{_timestamp_token()}_year_{year}_month_{month:02d}.parquet"
        _write_parquet_atomic_with_retry(partition_df.drop(["year", "month"]), file_path, compression="zstd")
        touched.add((year, month))
        print(f"[OK] 已保存 QMT 换手率: {file_path} ({len(partition_df)} 条)")
    return touched


def rebuild_merged_parquets(
    base_dir: str,
    touched_partitions: set[tuple[int, int]],
    *,
    replace_existing: bool = False,
) -> list[Path]:
    rebuilt: list[Path] = []
    for year, month in sorted(touched_partitions):
        partition_dir = Path(base_dir) / f"year={year}" / f"month={month:02d}"
        merged_path = partition_dir / MERGED_FILE_NAME
        raw_files = sorted(path for path in partition_dir.glob("*.parquet") if path.name != MERGED_FILE_NAME)
        input_files = raw_files if replace_existing else (
            ([merged_path] if merged_path.exists() else []) + raw_files
        )
        input_files = [path for path in input_files if _is_readable_parquet(path)]
        if not input_files:
            continue

        merged_df = pl.concat([pl.scan_parquet(str(path)) for path in input_files], how="diagonal_relaxed").collect(engine="streaming")
        if replace_existing:
            if "capital_effective_date" not in merged_df.columns:
                raise ValueError(
                    f"替换分区缺少 capital_effective_date 新口径字段: {partition_dir}"
                )
            merged_df = merged_df.filter(
                pl.col("capital_effective_date").is_not_null()
            )
        merged_df = transform_turnover_merged(merged_df)
        _write_parquet_atomic_with_retry(merged_df, merged_path, compression="zstd")
        rebuilt.append(merged_path)
        for raw_file in raw_files:
            try:
                raw_file.unlink()
            except OSError as exc:
                print(f"[WARN] 删除原始文件失败: {raw_file} | {exc}")
        print(f"[OK] 已重建 QMT 换手率 merged: {merged_path}")
    return rebuilt


def load_source_frames(
    daily_base_dir: str,
    capital_base_dir: str,
    start: str,
    end: str,
    codes: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_pattern = _parquet_pattern(daily_base_dir)
    capital_pattern = _capital_pattern(capital_base_dir)
    codes_filter = ""
    params: list[object] = [daily_pattern, start, end]
    if codes:
        codes_filter = "AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN (SELECT code FROM code_list)"

    con = duckdb.connect()
    try:
        if codes:
            con.register("code_list", pd.DataFrame({"code": codes}))
        daily = con.execute(
            f"""
            SELECT
                UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                CAST(time AS TIMESTAMP) AS time,
                CAST(open AS DOUBLE) AS open,
                CAST(high AS DOUBLE) AS high,
                CAST(low AS DOUBLE) AS low,
                CAST(close AS DOUBLE) AS close,
                CAST(volume AS DOUBLE) AS volume,
                CAST(value AS DOUBLE) AS value
            FROM read_parquet(?, hive_partitioning=1, union_by_name=true)
            WHERE CAST(time AS DATE) >= CAST(? AS DATE)
              AND CAST(time AS DATE) <= CAST(? AS DATE)
              {codes_filter}
            """,
            params,
        ).df()
        capital = con.execute(
            f"""
            SELECT
                UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                CAST(report_date AS TIMESTAMP) AS report_date,
                CAST(announce_date AS TIMESTAMP) AS announce_date,
                CAST(total_capital AS DOUBLE) AS total_capital,
                CAST(circulating_capital AS DOUBLE) AS circulating_capital,
                CAST(freeFloatCapital AS DOUBLE) AS freeFloatCapital
            FROM read_parquet(?, hive_partitioning=1, union_by_name=true)
            WHERE CAST(report_date AS DATE) <= CAST(? AS DATE)
              AND circulating_capital IS NOT NULL
              AND circulating_capital > 0
              {codes_filter}
            """,
            [capital_pattern, end],
        ).df()
    finally:
        con.close()
    return daily, capital


def main() -> None:
    parser = argparse.ArgumentParser(description="QMT 日频换手率：日K volume / Capital.circulating_capital * 100")
    parser.add_argument("--base-dir", default=BASE_DIR, help="QMT 换手率输出目录")
    parser.add_argument("--daily-base-dir", default=DAILY_BASE_DIR, help="QMT 日 K 数据目录")
    parser.add_argument("--capital-base-dir", default=CAPITAL_BASE_DIR, help="QMT 公司数据根目录")
    parser.add_argument("--start", default="", help="开始日期 YYYY-MM-DD，默认从本地最新换手率回溯 5 天")
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"), help="结束日期 YYYY-MM-DD")
    parser.add_argument("--codes", default="", help="逗号分隔股票代码；空表示全量")
    parser.add_argument(
        "--replace-existing-partitions",
        action="store_true",
        help="用本次完整结果替换涉及月份；仅用于统一口径的全量重建",
    )
    args = parser.parse_args()

    codes = parse_codes(args.codes)
    end_date = datetime.strptime(args.end, "%Y-%m-%d")
    start = args.start or resolve_default_start_date(args.base_dir, end_date)
    print(f"QMT 换手率计算: {start} ~ {args.end} | codes={len(codes) or 'ALL'}")
    daily, capital = load_source_frames(args.daily_base_dir, args.capital_base_dir, start, args.end, codes)
    print(f"日 K 行数: {len(daily)} | Capital 行数: {len(capital)}")
    result = calculate_turnover_frame(daily, capital)
    if result.empty:
        print("[WARN] 未生成任何 QMT 换手率记录。")
        return
    touched = save_partitioned_parquet(pl.from_pandas(result), args.base_dir)
    rebuild_merged_parquets(
        args.base_dir,
        touched,
        replace_existing=args.replace_existing_partitions,
    )
    print(f"[OK] QMT 换手率生成完成: {len(result)} 条 | 分区 {len(touched)} 个")


if __name__ == "__main__":
    main()
