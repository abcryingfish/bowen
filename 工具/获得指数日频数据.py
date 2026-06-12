#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""指数日频数据下载。

每次运行：扫描本地 parquet 得到各指数最新交易日，再登录 Insight，
for 循环逐只调用 get_kline（指数接口一次只能查一只）。

默认指数：000001.SH（上证指数）、399001.SZ（深证成指）。
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
from insight_python.com.insight import common
from insight_python.com.insight.market_service import market_service
from insight_python.com.insight.query import get_kline

BASE_DIR = r"D:\database\index_data_daily"
DEFAULT_INDEX_CODES = ["000001.SH", "399001.SZ"]
DEFAULT_START_DATE = "2010-01-01"
MIN_PARQUET_BYTES = 12
MERGED_FILE_NAME = "merged.parquet"
REQUEST_INTERVAL_SEC = 0.5


def save_partitioned_parquet(df: pl.DataFrame, base_dir: str) -> list[tuple[int, int]]:
    """按 year/month 分区追加写入 parquet，并把 time 统一压成按天 Datetime。"""
    if df.is_empty():
        return []

    df = (
        df.with_columns(pl.col("time").cast(pl.Datetime, strict=False).dt.truncate("1d").alias("time"))
        .drop_nulls(["time", "htsc_code"])
        .unique(subset=["htsc_code", "time"], keep="last")
        .sort(["time", "htsc_code"])
    )

    df = df.with_columns([
        pl.col("time").dt.year().alias("year"),
        pl.col("time").dt.month().alias("month"),
    ])

    touched_partitions: list[tuple[int, int]] = []
    partitions = df.partition_by(["year", "month"])

    for partition_df in partitions:
        year = int(partition_df["year"][0])
        month = int(partition_df["month"][0])
        dir_path = os.path.join(base_dir, f"year={year}", f"month={month:02d}")
        os.makedirs(dir_path, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{timestamp}_year_{year}_month_{month:02d}.parquet"
        file_path = os.path.join(dir_path, file_name)

        save_df = partition_df.drop(["year", "month"])
        save_df.write_parquet(file_path)
        touched_partitions.append((year, month))
        print(f"✓ 已保存: {file_path} (共 {len(save_df)} 条记录)")

    return touched_partitions


def transform_daily_htsc_time_merged(df: pl.DataFrame) -> pl.DataFrame:
    if "time" not in df.columns or "htsc_code" not in df.columns:
        return df
    return (
        df.with_columns(pl.col("time").cast(pl.Datetime, strict=False).dt.truncate("1d").alias("time"))
        .drop_nulls(["time", "htsc_code"])
        .unique(subset=["htsc_code", "time"], keep="last")
        .sort(["time", "htsc_code"])
    )


def _is_readable_parquet(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= MIN_PARQUET_BYTES and not pl.read_parquet(str(path), n_rows=1).is_empty()
    except Exception:
        return False


def rebuild_merged_parquets(
    base_dir: str,
    touched_partitions: set[tuple[int, int]],
    transform_merged=None,
) -> list[Path]:
    rebuilt_files: list[Path] = []
    for year, month in sorted(touched_partitions):
        partition_dir = Path(base_dir) / f"year={year}" / f"month={month:02d}"
        if not partition_dir.exists():
            continue

        merged_path = partition_dir / MERGED_FILE_NAME
        raw_files = sorted(
            path for path in partition_dir.glob("*.parquet")
            if path.is_file() and path.name != MERGED_FILE_NAME
        )
        input_files = ([merged_path] if merged_path.exists() else []) + raw_files
        input_files = [path for path in input_files if _is_readable_parquet(path)]
        if not input_files:
            print(f"[WARN] 分区 {year}-{month:02d} 无有效 parquet，跳过 merged 重建。")
            continue

        try:
            merged_df = pl.concat(
                [pl.scan_parquet(str(path)) for path in input_files],
                how="diagonal_relaxed",
            ).collect(engine="streaming")
            if transform_merged is not None:
                merged_df = transform_merged(merged_df)
            temp_path = partition_dir / f"{MERGED_FILE_NAME}.{os.getpid()}.{time.time_ns()}.tmp"
            merged_df.write_parquet(str(temp_path), compression="zstd")
            temp_path.replace(merged_path)
            rebuilt_files.append(merged_path)
            print(f"[OK] 已重建 merged: {merged_path}")
        except Exception as exc:
            print(f"[WARN] 分区 {year}-{month:02d} merged 重建失败: {exc}")
            continue

        deleted_count = 0
        for raw_file in raw_files:
            try:
                raw_file.unlink()
                deleted_count += 1
            except OSError as exc:
                print(f"[WARN] 删除原始文件失败，保留到下次合并: {raw_file.name} | {exc}")
        if deleted_count:
            print(f"[OK] 已删除原始 parquet 文件数: {deleted_count} | 分区: {year}-{month:02d}")
    return rebuilt_files


class insightmarketservice(market_service):
    def on_query_response(self, result):
        for response in iter(result):
            print(response)


def login() -> None:
    markets = insightmarketservice()
    user = "MDIL1_01042"
    password = "weS._+7atE4Vdr"
    result = common.login(markets, user, password, login_log=False)
    print(result)


def config(open_trace: bool = True, open_file_log: bool = True, open_cout_log: bool = True) -> None:
    common.config(open_trace, open_file_log, open_cout_log)


def get_version() -> None:
    print(common.get_version())


def fini() -> None:
    common.fini()


def normalize_code(code: str) -> str:
    return str(code).strip().upper()


def scan_latest_downloaded_times(base_dir: str) -> dict[str, datetime]:
    """扫描本地 parquet，返回每个指数已下载到的最新交易日。"""
    latest_time_map: dict[str, datetime] = {}
    if not os.path.exists(base_dir):
        return latest_time_map

    parquet_pattern = os.path.join(base_dir, "**", "*.parquet").replace("\\", "/")
    try:
        print("正在扫描已下载的数据，请稍候...")
        query = f"""
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            MAX(CAST(time AS TIMESTAMP)) AS latest_time
        FROM read_parquet('{parquet_pattern}')
        WHERE htsc_code IS NOT NULL
          AND time IS NOT NULL
        GROUP BY 1
        """
        latest_df = duckdb.query(query).df()
        if latest_df.empty:
            return latest_time_map

        latest_df["latest_time"] = pd.to_datetime(latest_df["latest_time"]).dt.floor("D")
        for _, row in latest_df.iterrows():
            latest_time_map[normalize_code(row["htsc_code"])] = row["latest_time"].to_pydatetime()

        print(f"发现已下载 {len(latest_time_map)} 个指数的历史数据。")
    except Exception:
        print("未发现有效历史数据或读取异常，将按全量起始日处理。")

    return latest_time_map


def resolve_start_date(
    code: str,
    latest_time_map: dict[str, datetime],
    default_start_date: datetime,
) -> datetime:
    latest_time = latest_time_map.get(normalize_code(code))
    start_date = default_start_date if latest_time is None else latest_time + timedelta(days=1)
    return start_date.replace(hour=0, minute=0, second=0, microsecond=0)


def should_relogin(error_msg: str) -> bool:
    msg = error_msg.lower()
    return "login" in msg or "connect" in msg or "session" in msg


def fetch_index_kline_with_retry(
    htsc_code: str,
    time_start_date: datetime,
    time_end_date: datetime,
    max_retries: int = 3,
) -> pd.DataFrame | None:
    """逐只指数拉取日 K；get_kline 每次只传一个 htsc_code。"""
    code = normalize_code(htsc_code)
    retry_count = 0
    while retry_count < max_retries:
        try:
            result = get_kline(
                htsc_code=[code],
                time=[time_start_date, time_end_date],
                frequency="daily",
                fq="none",
            )
            if result is None or len(result) == 0:
                return None

            result = result.copy()
            result["htsc_code"] = result["htsc_code"].map(normalize_code)
            result["time"] = pd.to_datetime(result["time"]).dt.floor("D")
            result = result.drop_duplicates(subset=["htsc_code", "time"], keep="last")
            return result
        except Exception as exc:
            retry_count += 1
            error_msg = str(exc)
            print(f"  ✗ {code} 第 {retry_count} 次尝试失败: {error_msg}")
            if retry_count >= max_retries:
                raise

            wait_time = 2 * retry_count
            print(f"  ⏳ 等待 {wait_time} 秒后重试...")
            time.sleep(wait_time)

            if should_relogin(error_msg):
                print("  🔄 检测到连接问题，尝试重新登录...")
                login()
                config(False, False, False)
                print("  ✓ 重新登录成功")

    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="指数日频下载：for 循环逐只 get_kline，增量写入 parquet")
    parser.add_argument(
        "--codes",
        nargs="+",
        default=DEFAULT_INDEX_CODES,
        help="指数 htsc_code 列表，默认 000001.SH 399001.SZ",
    )
    parser.add_argument(
        "--base-dir",
        default=BASE_DIR,
        help="日频 parquet 根目录",
    )
    parser.add_argument(
        "--default-start",
        default=DEFAULT_START_DATE,
        help="本地尚无该指数时，日频从该日起拉",
    )
    parser.add_argument(
        "--end",
        default="",
        help="日频结束日，默认今天；格式 YYYY-MM-DD",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_dir = str(args.base_dir)
    index_codes = [normalize_code(c) for c in args.codes]
    default_start_date = datetime.strptime(args.default_start, "%Y-%m-%d")
    end_s = (args.end or "").strip()
    time_end_date = datetime.now() if not end_s else datetime.strptime(end_s, "%Y-%m-%d")
    time_end_date = time_end_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    latest_time_map = scan_latest_downloaded_times(base_dir)

    print("=" * 60)
    print("初始化连接…")
    print("=" * 60)
    get_version()
    login()
    config(False, False, False)

    failed_codes: list[dict[str, object]] = []
    processed_count = 0
    skipped_count = 0
    touched_partitions: set[tuple[int, int]] = set()

    print(f"待处理指数: {index_codes}")
    print("=" * 60)

    try:
        total = len(index_codes)
        for idx, code in enumerate(index_codes, start=1):
            start_date = resolve_start_date(code, latest_time_map, default_start_date)
            if start_date > time_end_date:
                skipped_count += 1
                print(f"\n[{idx}/{total}] {code} 已是最新，跳过")
                continue

            print(f"\n[{idx}/{total}] {code}")
            print(f"  下载区间: {start_date.date()} ~ {time_end_date.date()}")

            try:
                result = fetch_index_kline_with_retry(code, start_date, time_end_date)
                if result is None or result.empty:
                    print(f"  ⚠️ {code} 返回空数据")
                    failed_codes.append({"code": code, "error": "返回空数据"})
                    continue

                touched = save_partitioned_parquet(pl.from_pandas(result), base_dir)
                touched_partitions.update(touched)
                processed_count += 1
                print(f"  ✓ 成功 {len(result)} 条，累计成功 {processed_count}/{total - skipped_count}")
                time.sleep(REQUEST_INTERVAL_SEC)
            except Exception as exc:
                error_msg = str(exc)
                print(f"  ✗ {code} 最终失败: {error_msg}")
                failed_codes.append({"code": code, "error": error_msg})
    finally:
        print("\n" + "=" * 60)
        print("处理完成，释放连接...")
        fini()

    print("\n" + "=" * 60)
    print("📊 执行统计")
    print("=" * 60)
    print(f"成功: {processed_count} | 已最新跳过: {skipped_count} | 失败: {len(failed_codes)}")
    print(f"更新到的分区数: {len(touched_partitions)}")

    if touched_partitions:
        rebuilt_files = rebuild_merged_parquets(
            base_dir, touched_partitions, transform_merged=transform_daily_htsc_time_merged
        )
        print(f"重建 merged.parquet 数量: {len(rebuilt_files)}")
    else:
        print("本次无新增数据写入，跳过 merged.parquet 重建。")

    if failed_codes:
        print("\n⚠️ 以下指数失败，可后续补跑:")
        for fail in failed_codes:
            print(f"  - {fail['code']}: {fail['error']}")

    print("=" * 60)


if __name__ == "__main__":
    main()
