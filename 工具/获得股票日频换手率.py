#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""日频日行情（get_daily_basic）下载。

每次运行：先扫描本地 parquet；再登录并用 get_all_stocks_info 拉取上海 XSHG +
深圳 XSHE 全市场 htsc_code；与本地对比后逐只增量下载 get_daily_basic 返回的全部字段。

股票代码仅通过 API 获取。数据写入 ``D:\\database\\stock_financial_statements\\market_equity_data``（可通过
``--base-dir`` 覆盖），分区格式：``year=YYYY/month=MM/*.parquet`` + ``merged.parquet``。
"""
from __future__ import annotations

import argparse
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import polars as pl
from insight_python.com.insight import common
from insight_python.com.insight.market_service import market_service
from insight_python.com.insight.query import get_all_stocks_info, get_daily_basic

BASE_DIR = r"D:\database\stock_financial_statements\market_equity_data"
DEFAULT_START_DATE = "2010-01-01"
MIN_PARQUET_BYTES = 12
MERGED_FILE_NAME = "merged.parquet"
SLEEP_SEC = 0.0005

# get_daily_basic SDK 返回的全部字段（trading_day 会映射为 time）
DAILY_BASIC_NUMERIC_COLUMNS: tuple[str, ...] = (
    "prev_close",
    "open",
    "high",
    "low",
    "close",
    "backward_adjusted_closing_price",
    "volume",
    "value",
    "turnover_deals",
    "day_change",
    "turnover_rate",
    "amplitude",
    "avg_price",
    "avg_vol_per_deal",
    "avg_value_per_deal",
    "floating_market_val",
    "total_market_val",
)
DAILY_BASIC_STRING_COLUMNS: tuple[str, ...] = (
    "name",
    "exchange",
    "trading_state",
)




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


def fetch_market_universe_htsc_codes(
    listing_start: datetime,
    listing_end: datetime,
    listing_state: str = "上市交易",
) -> list[str]:
    """上海 + 深圳 get_all_stocks_info，合并 htsc_code 并去重。"""
    codes: set[str] = set()
    for exchange in ("XSHG", "XSHE"):
        result = get_all_stocks_info(
            listing_date=[listing_start, listing_end],
            exchange=exchange,
            listing_state=listing_state,
        )
        if result is None:
            print(f"⚠️ {exchange} get_all_stocks_info 返回 None，跳过")
            continue
        if not hasattr(result, "columns") or "htsc_code" not in result.columns:
            print(f"⚠️ {exchange} 结果无 htsc_code 列: {getattr(result, 'columns', None)}")
            continue
        for raw in result["htsc_code"].tolist():
            codes.add(normalize_code(str(raw)))
        print(f"✓ {exchange} 已合并，当前不重复代码数: {len(codes)}")
    return sorted(codes)


def _collect_scan_parquet_paths(base_dir: str) -> list[str]:
    """优先 merged.parquet；否则仅纳入可读的非空增量文件，跳过损坏小文件。"""
    base_path = Path(base_dir)
    merged_files = sorted(base_path.glob("**/merged.parquet"))
    if merged_files:
        return [str(p).replace("\\", "/") for p in merged_files]

    valid_files: list[str] = []
    skipped_small = 0
    for path in sorted(base_path.glob("**/*.parquet")):
        if path.name == MERGED_FILE_NAME:
            continue
        try:
            if path.stat().st_size < MIN_PARQUET_BYTES:
                skipped_small += 1
                continue
        except OSError:
            skipped_small += 1
            continue
        valid_files.append(str(path).replace("\\", "/"))

    if skipped_small:
        print(f"⚠️ 扫描时跳过 {skipped_small} 个无效/损坏 parquet 小文件。")
    return valid_files


def scan_latest_downloaded_times(base_dir: str) -> dict[str, datetime]:
    """扫描本地 parquet，返回每只股票已下载到的最新交易日。"""
    latest_time_map: dict[str, datetime] = {}
    if not os.path.exists(base_dir):
        return latest_time_map

    parquet_paths = _collect_scan_parquet_paths(base_dir)
    if not parquet_paths:
        print("未发现本地 parquet，将按默认起始日处理新股票。")
        return latest_time_map

    try:
        print(f"正在扫描已下载的数据（{len(parquet_paths)} 个 parquet），请稍候...")
        if len(parquet_paths) == 1:
            from_clause = f"read_parquet('{parquet_paths[0]}', union_by_name=true)"
        else:
            quoted = ", ".join(f"'{path}'" for path in parquet_paths)
            from_clause = f"read_parquet([{quoted}], union_by_name=true)"
        query = f"""
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            MAX(CAST(time AS TIMESTAMP)) AS latest_time
        FROM {from_clause}
        WHERE htsc_code IS NOT NULL
          AND time IS NOT NULL
        GROUP BY 1
        """
        latest_df = duckdb.query(query).df()
        if latest_df.empty:
            print("扫描完成，但未发现有效历史记录。")
            return latest_time_map

        latest_df["latest_time"] = pd.to_datetime(latest_df["latest_time"]).dt.floor("D")
        for _, row in latest_df.iterrows():
            latest_time_map[normalize_code(row["htsc_code"])] = row["latest_time"].to_pydatetime()

        print(f"发现已下载 {len(latest_time_map)} 个股票的历史日行情数据。")
    except Exception as exc:
        print(f"⚠️ 扫描本地历史数据失败，将按默认起始日处理: {exc}")

    return latest_time_map


def build_download_plan(
    all_codes: list[str],
    latest_time_map: dict[str, datetime],
    default_start_date: datetime,
    time_end_date: datetime,
) -> tuple[dict[datetime, list[str]], dict[str, int]]:
    """按起始日期分组，便于逐只下载相同时间范围的股票。"""
    grouped_codes: dict[datetime, list[str]] = defaultdict(list)
    stats = {"up_to_date": 0, "incremental": 0, "full_new": 0}
    for raw_code in all_codes:
        code = normalize_code(raw_code)
        latest_time = latest_time_map.get(code)
        if latest_time is None:
            start_date = default_start_date
            stats["full_new"] += 1
        else:
            start_date = latest_time + timedelta(days=1)
            stats["incremental"] += 1
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        if start_date > time_end_date:
            stats["up_to_date"] += 1
            if latest_time is not None:
                stats["incremental"] -= 1
            else:
                stats["full_new"] -= 1
            continue
        grouped_codes[start_date].append(code)
    return dict(sorted(grouped_codes.items(), key=lambda item: item[0])), stats


def flatten_download_plan(download_plan: dict[datetime, list[str]]) -> list[tuple[datetime, str]]:
    """将按起始日分组的计划展开为 (start_date, code) 列表，便于逐只请求。"""
    tasks: list[tuple[datetime, str]] = []
    for start_date, codes in download_plan.items():
        for code in codes:
            tasks.append((start_date, code))
    return tasks


def should_relogin(error_msg: str) -> bool:
    msg = error_msg.lower()
    return "login" in msg or "connect" in msg or "session" in msg


def normalize_daily_basic_response(raw: pd.DataFrame) -> pd.DataFrame:
    """get_daily_basic 全字段 -> 标准列（htsc_code + time + 接口其余字段）。"""
    if raw.empty:
        return raw

    if "trading_day" not in raw.columns or "htsc_code" not in raw.columns:
        missing = [c for c in ("trading_day", "htsc_code") if c not in raw.columns]
        raise ValueError(f"接口结果缺少列: {missing}")

    out = raw.copy()
    out["htsc_code"] = out["htsc_code"].map(normalize_code)
    out["time"] = pd.to_datetime(out["trading_day"], errors="coerce").dt.floor("D")
    out = out.drop(columns=["trading_day"])

    for col in DAILY_BASIC_NUMERIC_COLUMNS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    for col in DAILY_BASIC_STRING_COLUMNS:
        if col in out.columns:
            out[col] = out[col].astype("string")

    out = out.dropna(subset=["htsc_code", "time"])
    out = out.drop_duplicates(subset=["htsc_code", "time"], keep="last")

    lead_cols = ["htsc_code", "time"]
    tail_cols = [c for c in out.columns if c not in lead_cols]
    return out[lead_cols + tail_cols].sort_values(["time", "htsc_code"]).reset_index(drop=True)


def fetch_single_stock_with_retry(
    code: str,
    time_start_date: datetime,
    time_end_date: datetime,
    max_retries: int = 3,
) -> pd.DataFrame | None:
    """逐只调用 get_daily_basic（该接口仅支持单票）。"""
    retry_count = 0
    while retry_count < max_retries:
        try:
            result = get_daily_basic(
                htsc_code=code,
                trading_day=[time_start_date, time_end_date],
            )
            if result is None or isinstance(result, str):
                return None
            if not hasattr(result, "columns") or result.empty:
                return None

            return normalize_daily_basic_response(result)
        except Exception as exc:
            retry_count += 1
            error_msg = str(exc)
            print(f"  ✗ 第 {retry_count} 次尝试失败: {error_msg}")
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
    parser = argparse.ArgumentParser(
        description="日频日行情下载：get_all_stocks_info 全市场 + get_daily_basic 全字段"
    )
    parser.add_argument(
        "--listing-start",
        default="1990-01-01",
        help="get_all_stocks_info listing_date 左端（默认 1990-01-01）",
    )
    parser.add_argument(
        "--listing-end",
        default="",
        help="listing_date 右端，默认今天；格式 YYYY-MM-DD",
    )
    parser.add_argument(
        "--listing-state",
        default="上市交易",
        help="get_all_stocks_info listing_state",
    )
    parser.add_argument(
        "--base-dir",
        default=BASE_DIR,
        help="日行情 parquet 根目录",
    )
    parser.add_argument(
        "--default-start",
        default=DEFAULT_START_DATE,
        help="本地尚无该票时，日行情从该日起拉（默认与 DEFAULT_START_DATE 一致）",
    )
    parser.add_argument(
        "--end",
        default="",
        help="日行情结束日，默认今天；格式 YYYY-MM-DD",
    )
    parser.add_argument(
        "--sleep-sec",
        type=float,
        default=SLEEP_SEC,
        help="逐只请求间隔秒数（默认 0.0005）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_dir = str(args.base_dir)
    os.makedirs(base_dir, exist_ok=True)
    default_start_date = datetime.strptime(args.default_start, "%Y-%m-%d")
    end_s = (args.end or "").strip()
    time_end_date = datetime.now() if not end_s else datetime.strptime(end_s, "%Y-%m-%d")
    time_end_date = time_end_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    latest_time_map = scan_latest_downloaded_times(base_dir)

    print("=" * 60)
    print("初始化连接并获取全市场股票池（XSHG + XSHE）…")
    print("=" * 60)
    get_version()
    login()
    config(False, False, False)
    listing_start = datetime.strptime(args.listing_start.strip(), "%Y-%m-%d")
    le_s = (args.listing_end or "").strip()
    listing_end = datetime.now() if not le_s else datetime.strptime(le_s, "%Y-%m-%d")
    all_codes = fetch_market_universe_htsc_codes(listing_start, listing_end, args.listing_state)
    print(f"股票池（API）: {len(all_codes)} 只")
    print("=" * 60)

    download_plan, plan_stats = build_download_plan(
        all_codes, latest_time_map, default_start_date, time_end_date
    )
    tasks = flatten_download_plan(download_plan)
    pending_total = len(tasks)
    print(
        "增量计划: "
        f"已最新 {plan_stats['up_to_date']} 只 | "
        f"增量补拉 {plan_stats['incremental']} 只 | "
        f"首次全量 {plan_stats['full_new']} 只"
    )
    if download_plan:
        plan_preview = ", ".join(
            f"{start.date()}({len(codes)}只)" for start, codes in list(download_plan.items())[:5]
        )
        print(f"下载起点分组(前5): {plan_preview}")
    if pending_total == 0:
        print("所有股票都已更新到最新日期，无需下载。")
        fini()
        return

    failed_stocks: list[dict[str, object]] = []
    processed_count = 0
    touched_partitions: set[tuple[int, int]] = set()

    print(f"需更新股票数量: {pending_total}")
    print("=" * 60)

    try:
        for stock_num, (start_date, code) in enumerate(tasks, start=1):
            print(f"\n[股票 {stock_num}/{pending_total}] {code}")
            print(f"  下载区间: {start_date.date()} ~ {time_end_date.date()}")

            try:
                result = fetch_single_stock_with_retry(code, start_date, time_end_date)
                if result is None or result.empty:
                    print(f"  ⚠️ {code} 返回空数据，已记录")
                    failed_stocks.append(
                        {
                            "code": code,
                            "start_date": start_date.strftime("%Y-%m-%d"),
                            "error": "返回空数据",
                            "stock_num": stock_num,
                        }
                    )
                    time.sleep(args.sleep_sec)
                    continue

                result_pl = pl.from_pandas(result)
                touched = save_partitioned_parquet(result_pl, base_dir)
                touched_partitions.update(touched)

                processed_count += 1
                print(f"  ✓ 成功处理 {code}，累计 {processed_count}/{pending_total}")
                time.sleep(args.sleep_sec)
            except Exception as exc:
                error_msg = str(exc)
                print(f"  ✗ {code} 最终失败: {error_msg}")
                failed_stocks.append(
                    {
                        "code": code,
                        "start_date": start_date.strftime("%Y-%m-%d"),
                        "error": error_msg,
                        "stock_num": stock_num,
                    }
                )
                time.sleep(args.sleep_sec)
    finally:
        print("\n" + "=" * 60)
        print("处理完成，释放连接...")
        fini()

    print("\n" + "=" * 60)
    print("📊 执行统计")
    print("=" * 60)
    print(f"成功处理: {processed_count}/{pending_total} 个股票")
    print(f"更新到的分区数: {len(touched_partitions)}")
    print(f"失败股票: {len(failed_stocks)} 只")

    if touched_partitions:
        rebuilt_files = rebuild_merged_parquets(
            base_dir, touched_partitions, transform_merged=transform_daily_htsc_time_merged
        )
        print(f"重建 merged.parquet 数量: {len(rebuilt_files)}")
    else:
        print("本次无新增数据写入，跳过 merged.parquet 重建。")

    if failed_stocks:
        print("\n⚠️ 以下股票失败，可后续补跑:")
        for fail in failed_stocks:
            print(
                f"  - 序号 {fail['stock_num']}: {fail['code']} | "
                f"起始日期: {fail['start_date']} | 原因: {fail['error']}"
            )

        fail_file = f"failed_stocks_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(fail_file, "w", encoding="utf-8") as f:
            for fail in failed_stocks:
                f.write(
                    f"stock_num={fail['stock_num']},code={fail['code']},"
                    f"start_date={fail['start_date']},error={fail['error']}\n"
                )
        print(f"\n失败记录已保存到: {fail_file}")

    print("=" * 60)


if __name__ == "__main__":
    main()
