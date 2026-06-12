#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""股票 1 分钟 K 线下载。

每次运行：先扫描本地 parquet 得到全库最新分钟；再用 xtquant 板块数据读取
“沪深A股”股票池；用 xtquant 先下载本地缓存，再读取 1m K 线，转换为现有
parquet schema 后落盘，全部完成后统一重建 merged.parquet。

数据写入 ``D:\\database\\stock_basic_data_mins``（可通过 ``--base-dir`` 覆盖），
分区：``year=YYYY/month=MM/day=DD/*.parquet`` + ``merged.parquet``。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import polars as pl
from xtquant import xtdata

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


BASE_DIR = r"D:\database\stock_basic_data_mins"
DAILY_BASE_DIR = r"D:\database\stock_basic_data_daily"
SIGNAL_DAILY_DIR = r"D:\database\signal_daily"
SIGNAL_REFERENCE_FACTOR = "总买入信号"
DEFAULT_SECTOR_NAME = "\u6caa\u6df1A\u80a1"
DEFAULT_START_DATE = "2010-01-01"
MIN_PARQUET_BYTES = 12
MERGED_FILE_NAME = "merged.parquet"
DATA_FREQUENCY = "1m"
MAX_RETRIES = 3
REQUEST_SLEEP_SECONDS = 0.1
DEFAULT_MAX_YEAR = 2026
DEFAULT_END_DATETIME = ""
LOOKBACK_DAYS = 7


def normalize_code(code: str) -> str:
    return str(code).strip().upper()


def normalize_pandas_minute(value: pd.Series) -> pd.Series:
    return pd.to_datetime(value).dt.floor("min")


def normalize_polars_minute_expr(column_name: str = "time") -> pl.Expr:
    return pl.col(column_name).cast(pl.Datetime, strict=False).dt.truncate("1m")


def format_dt(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def format_day(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def year_window(year: int, range_start: datetime, range_end: datetime, now: datetime) -> tuple[datetime, datetime]:
    start_dt = max(range_start, datetime(year, 1, 1))
    end_dt = min(range_end, datetime(year, 12, 31, 23, 59, 59))
    current_minute = now.replace(second=0, microsecond=0)
    if end_dt > current_minute:
        end_dt = current_minute
    if start_dt > end_dt:
        return start_dt, start_dt
    return start_dt, end_dt


def save_partitioned_parquet(
    df: pl.DataFrame,
    base_dir: str,
    code: str,
    max_save_time: datetime | None = None,
) -> list[tuple[int, int]]:
    if df.is_empty():
        return []

    normalized_df = (
        df.with_columns(normalize_polars_minute_expr().alias("time"))
        .drop_nulls(["time", "htsc_code"])
        .unique(subset=["htsc_code", "time"], keep="last")
        .sort(["htsc_code", "time"])
    )
    if max_save_time is not None:
        normalized_df = normalized_df.filter(pl.col("time") <= max_save_time)
        if normalized_df.is_empty():
            return []

    normalized_df = normalized_df.with_columns(
        pl.col("time").dt.year().alias("year"),
        pl.col("time").dt.month().alias("month"),
        pl.col("time").dt.day().alias("day"),
    )

    touched_partitions: list[tuple[int, int, int]] = []
    safe_code = normalize_code(code).replace(".", "_")

    for partition_df in normalized_df.partition_by(["year", "month", "day"], maintain_order=True):
        year = int(partition_df["year"][0])
        month = int(partition_df["month"][0])
        day = int(partition_df["day"][0])
        partition_dir = Path(base_dir) / f"year={year}" / f"month={month:02d}" / f"day={day:02d}"
        partition_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{timestamp}_{safe_code}_year_{year}_month_{month:02d}_day_{day:02d}.parquet"
        file_path = partition_dir / file_name

        save_df = partition_df.drop(["year", "month", "day"])
        save_df.write_parquet(str(file_path), compression="zstd")
        touched_partitions.append((year, month, day))
        print(f"[OK] 已保存: {file_path} (共 {save_df.height} 条记录)")

    return touched_partitions


def _transform_minute_merged(df: pl.DataFrame) -> pl.DataFrame:
    if "time" not in df.columns or "htsc_code" not in df.columns:
        return df
    return (
        df.with_columns(normalize_polars_minute_expr().alias("time"))
        .drop_nulls(["time", "htsc_code"])
        .unique(subset=["htsc_code", "time"], keep="last")
        .sort(["htsc_code", "time"])
    )


def _is_readable_parquet(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= MIN_PARQUET_BYTES and not pl.read_parquet(str(path), n_rows=1).is_empty()
    except Exception:
        return False


def rebuild_merged_parquets(
    base_dir: str,
    touched_partitions: set[tuple[int, int, int]],
    transform_merged=None,
) -> list[Path]:
    rebuilt_files: list[Path] = []
    for year, month, day in sorted(touched_partitions):
        partition_dir = Path(base_dir) / f"year={year}" / f"month={month:02d}" / f"day={day:02d}"
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
            print(f"[WARN] 分区 {year}-{month:02d}-{day:02d} 无有效 parquet，跳过 merged 重建。")
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
            print(f"[WARN] 分区 {year}-{month:02d}-{day:02d} merged 重建失败: {exc}")
            continue

        deleted_count = 0
        for raw_file in raw_files:
            try:
                raw_file.unlink()
                deleted_count += 1
            except OSError as exc:
                print(f"[WARN] 删除原始文件失败，保留到下次合并: {raw_file.name} | {exc}")
        if deleted_count:
            print(f"[OK] 已删除原始 parquet 文件数: {deleted_count} | 分区: {year}-{month:02d}-{day:02d}")
    return rebuilt_files


def format_xtquant_time(value: datetime) -> str:
    return value.strftime("%Y%m%d%H%M%S")


def _empty_minute_frame() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "htsc_code": pl.String,
            "time": pl.Datetime,
            "close": pl.Float64,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "volume": pl.Float64,
            "amount": pl.Float64,
            "date": pl.String,
            "pre_close": pl.Float32,
            "change": pl.Float32,
            "pct_chg": pl.Float32,
            "__index_level_0__": pl.Int64,
        }
    )


def _normalize_xtquant_dataframe(
    raw_df: pd.DataFrame,
    code: str,
    prior_close: float | None = None,
) -> pl.DataFrame:
    if raw_df is None or raw_df.empty:
        return _empty_minute_frame()

    df = raw_df.copy()
    if "time" not in df.columns and df.index.name == "stime":
        df = df.reset_index()
        df["time"] = df["stime"]
    elif "time" not in df.columns:
        df = df.reset_index()
        first_col = df.columns[0]
        df["time"] = df[first_col]

    required_columns = ["time", "open", "high", "low", "close", "volume"]
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise ValueError(f"xtquant 返回缺少必要列: {missing_columns}")
    if "amount" not in df.columns:
        df["amount"] = pd.NA
    if "pvolume" not in df.columns:
        df["pvolume"] = pd.NA

    raw_time = df["time"]
    if pd.api.types.is_numeric_dtype(raw_time):
        max_abs = pd.to_numeric(raw_time, errors="coerce").abs().max()
        unit = "ms" if pd.notna(max_abs) and max_abs > 10_000_000_000 else "s"
        df["time"] = (
            pd.to_datetime(raw_time, unit=unit, errors="coerce", utc=True)
            .dt.tz_convert("Asia/Shanghai")
            .dt.tz_localize(None)
            .dt.floor("min")
        )
    else:
        text_time = raw_time.astype(str).str.replace(r"\.0$", "", regex=True)
        parsed_time = pd.to_datetime(text_time, format="%Y%m%d%H%M%S", errors="coerce")
        fallback_time = pd.to_datetime(raw_time, errors="coerce")
        df["time"] = parsed_time.fillna(fallback_time).dt.floor("min")

    df["htsc_code"] = normalize_code(code)
    df = df.dropna(subset=["time", "htsc_code", "open", "high", "low", "close"])
    if df.empty:
        return _empty_minute_frame()

    for column in ["open", "high", "low", "close", "volume", "pvolume", "amount"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["volume"] = df["pvolume"].fillna(df["volume"] * 100)

    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df.drop_duplicates(subset=["htsc_code", "time"], keep="last")
    df = df.sort_values(["htsc_code", "time"]).reset_index(drop=True)
    df["date"] = df["time"].dt.strftime("%Y-%m-%d")
    df["pre_close"] = df.groupby("htsc_code", sort=False)["close"].shift(1)
    if prior_close is not None and not df.empty:
        df.loc[df.index[0], "pre_close"] = prior_close
    df["change"] = df["close"] - df["pre_close"]
    df["pct_chg"] = (df["change"] / df["pre_close"] * 100).where(df["pre_close"] != 0)
    df["__index_level_0__"] = range(len(df))

    ordered_columns = [
        "htsc_code",
        "time",
        "close",
        "open",
        "high",
        "low",
        "volume",
        "amount",
        "date",
        "pre_close",
        "change",
        "pct_chg",
        "__index_level_0__",
    ]
    return pl.from_pandas(df[ordered_columns], include_index=False).with_columns(
        pl.col("time").cast(pl.Datetime).dt.truncate("1m"),
        pl.col("htsc_code").cast(pl.String),
        pl.col("close").cast(pl.Float64),
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("volume").cast(pl.Float64),
        pl.col("amount").cast(pl.Float64),
        pl.col("date").cast(pl.String),
        pl.col("pre_close").cast(pl.Float32),
        pl.col("change").cast(pl.Float32),
        pl.col("pct_chg").cast(pl.Float32),
        pl.col("__index_level_0__").cast(pl.Int64),
    )


def download_xtquant_history(code: str, time_start_date: datetime, time_end_date: datetime) -> None:
    start_text = format_xtquant_time(time_start_date)
    end_text = format_xtquant_time(time_end_date)
    xtdata.download_history_data(normalize_code(code), period=DATA_FREQUENCY, start_time=start_text, end_time=end_text)


def read_xtquant_history(
    code: str,
    time_start_date: datetime,
    time_end_date: datetime,
    prior_close: float | None = None,
) -> pl.DataFrame:
    start_text = format_xtquant_time(time_start_date)
    end_text = format_xtquant_time(time_end_date)
    data = xtdata.get_market_data_ex(
        field_list=["time", "open", "high", "low", "close", "volume", "amount"],
        stock_list=[normalize_code(code)],
        period=DATA_FREQUENCY,
        start_time=start_text,
        end_time=end_text,
        dividend_type="none",
        fill_data=False,
    )
    if not isinstance(data, dict):
        raise ValueError(f"xtquant get_market_data_ex 返回类型异常: {type(data).__name__}")
    raw_df = data.get(normalize_code(code))
    if raw_df is None:
        return _empty_minute_frame()
    return _normalize_xtquant_dataframe(raw_df, code, prior_close=prior_close)


def _collect_scan_parquet_paths(base_dir: str, scan_months: int = 3) -> list[str]:
    base_path = Path(base_dir)
    merged_files = sorted(base_path.glob("**/merged.parquet"))
    if merged_files:
        return [str(p).replace("\\", "/") for p in merged_files]
    return []


def scan_latest_downloaded_state(
    base_dir: str,
    scan_months: int = 3,
) -> tuple[dict[str, datetime], dict[str, float]]:
    """扫描本地 parquet，返回每只股票最新分钟与该分钟 close。"""
    latest_time_map: dict[str, datetime] = {}
    latest_close_map: dict[str, float] = {}
    if not os.path.exists(base_dir):
        return latest_time_map, latest_close_map

    parquet_paths = _collect_scan_parquet_paths(base_dir, scan_months=scan_months)
    if not parquet_paths:
        print("未发现本地 parquet，将按默认起始日处理新股票。")
        return latest_time_map, latest_close_map

    try:
        print(f"正在扫描已下载的数据（{len(parquet_paths)} 个 parquet），请稍候...")
        if len(parquet_paths) == 1:
            from_clause = f"read_parquet('{parquet_paths[0]}', union_by_name=true)"
        else:
            quoted = ", ".join(f"'{path}'" for path in parquet_paths)
            from_clause = f"read_parquet([{quoted}], union_by_name=true)"
        query = f"""
        WITH normalized AS (
            SELECT
                UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                CAST(time AS TIMESTAMP) AS time,
                TRY_CAST(close AS DOUBLE) AS close
            FROM {from_clause}
            WHERE htsc_code IS NOT NULL
              AND time IS NOT NULL
        )
        SELECT
            htsc_code,
            MAX(time) AS latest_time,
            ARG_MAX(close, time) AS latest_close
        FROM normalized
        GROUP BY 1
        """
        latest_df = duckdb.query(query).df()
        if latest_df.empty:
            print("扫描完成，但未发现有效历史记录。")
            return latest_time_map, latest_close_map

        latest_df["latest_time"] = pd.to_datetime(latest_df["latest_time"]).dt.floor("min")
        for _, row in latest_df.iterrows():
            code = normalize_code(row["htsc_code"])
            latest_time_map[code] = row["latest_time"].to_pydatetime()
            if pd.notna(row.get("latest_close")):
                latest_close_map[code] = float(row["latest_close"])

        print(f"发现已下载 {len(latest_time_map)} 个股票的分钟历史数据。")
    except Exception as exc:
        print(f"[WARN] 扫描本地历史数据失败，将按默认起始日处理: {exc}")

    return latest_time_map, latest_close_map


def scan_latest_downloaded_times(base_dir: str, scan_months: int = 3) -> dict[str, datetime]:
    """扫描本地 parquet，返回每只股票已下载到的最新分钟。"""
    latest_time_map, _ = scan_latest_downloaded_state(base_dir, scan_months=scan_months)
    return latest_time_map


def load_xtquant_sector_universe(sector_name: str) -> list[str]:
    """用 xtquant 板块数据获取股票池。"""
    xtdata.download_sector_data()
    stock_list = xtdata.get_stock_list_in_sector(sector_name)
    if not stock_list:
        raise RuntimeError(f"xtquant 板块股票池为空: {sector_name}")
    return sorted({normalize_code(code) for code in stock_list if str(code).strip()})


def build_download_plan(
    all_codes: list[str],
    global_latest_time: datetime | None,
    default_start_date: datetime,
    time_end_date: datetime,
) -> tuple[dict[datetime, list[str]], dict[str, int]]:
    stats = {"up_to_date": 0, "incremental": 0, "full_new": 0}
    if global_latest_time is None:
        start_date = default_start_date
        stats["full_new"] = len(all_codes)
    else:
        start_date = global_latest_time - timedelta(days=LOOKBACK_DAYS)
        stats["incremental"] = len(all_codes)

    start_date = start_date.replace(second=0, microsecond=0)
    if start_date > time_end_date:
        stats["up_to_date"] = len(all_codes)
        stats["incremental"] = 0
        stats["full_new"] = 0
        return {}, stats

    return {start_date: [normalize_code(code) for code in all_codes]}, stats


def iter_year_windows(range_start: datetime, range_end: datetime, now: datetime) -> list[tuple[int, datetime, datetime]]:
    windows: list[tuple[int, datetime, datetime]] = []
    for year in range(range_start.year, range_end.year + 1):
        win_start, win_end = year_window(year, range_start, range_end, now)
        if win_start <= win_end:
            windows.append((year, win_start, win_end))
    return windows


def fetch_codes_with_retry(
    codes: list[str],
    time_start_date: datetime,
    time_end_date: datetime,
    prior_close: float | None = None,
) -> pl.DataFrame | None:
    if len(codes) != 1:
        raise ValueError("xtquant 分钟下载当前按 1 票 × 1 窗口串行执行")

    code = normalize_code(codes[0])
    retry_count = 0
    while retry_count < MAX_RETRIES:
        try:
            download_xtquant_history(code, time_start_date, time_end_date)
            result = read_xtquant_history(code, time_start_date, time_end_date, prior_close=prior_close)
            if result is None or result.is_empty():
                return None
            return result
        except Exception as exc:
            retry_count += 1
            error_msg = str(exc)
            print(f"  [FAIL] 第 {retry_count} 次尝试失败: {error_msg}")
            if retry_count >= MAX_RETRIES:
                raise

            wait_time = 2 * retry_count
            print(f"  [WAIT] 等待 {wait_time} 秒后重试...")
            time.sleep(wait_time)

    return None

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="分钟 K 线下载：xtquant 沪深A股股票池 + 本地缓存串行增量"
    )
    parser.add_argument(
        "--signal-dir",
        default=SIGNAL_DAILY_DIR,
        help="兼容旧参数，xtquant 板块股票池版本不使用",
    )
    parser.add_argument(
        "--signal-factor",
        default=SIGNAL_REFERENCE_FACTOR,
        help="兼容旧参数，xtquant 板块股票池版本不使用",
    )
    parser.add_argument(
        "--daily-dir",
        default=DAILY_BASE_DIR,
        help="兼容旧参数，xtquant 板块股票池版本不使用",
    )
    parser.add_argument(
        "--use-api-universe",
        action="store_true",
        help="兼容旧参数，当前始终使用 xtquant 板块股票池",
    )
    parser.add_argument(
        "--sector-name",
        default=DEFAULT_SECTOR_NAME,
        help="xtquant 板块名称，用于获取股票池（默认 沪深A股）",
    )
    parser.add_argument(
        "--listing-start",
        default="1990-01-01",
        help="兼容旧参数，xtquant 版本不使用",
    )
    parser.add_argument(
        "--listing-end",
        default="",
        help="listing_date 右端，默认今天；格式 YYYY-MM-DD",
    )
    parser.add_argument(
        "--listing-state",
        default="上市交易",
        help="兼容旧参数，xtquant 版本不使用",
    )
    parser.add_argument(
        "--base-dir",
        default=BASE_DIR,
        help="分钟 parquet 根目录",
    )
    parser.add_argument(
        "--default-start",
        default=DEFAULT_START_DATE,
        help="本地尚无该票时，分钟数据从该日起拉",
    )
    parser.add_argument(
        "--end",
        default=DEFAULT_END_DATETIME,
        help="分钟数据结束时刻，默认当前分钟；格式 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS",
    )
    parser.add_argument(
        "--max-year",
        type=int,
        default=DEFAULT_MAX_YEAR,
        help="下载/落盘的最大年份（含该年，默认 2026）",
    )
    parser.add_argument(
        "--sleep-sec",
        type=float,
        default=REQUEST_SLEEP_SECONDS,
        help="请求间隔秒数",
    )
    parser.add_argument(
        "--scan-months",
        type=int,
        default=3,
        help="兼容旧参数，当前仅扫描日级 merged.parquet",
    )
    parser.add_argument(
        "--skip-rebuild",
        action="store_true",
        help="下载完成后不重建 merged.parquet",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_dir = str(args.base_dir)
    os.makedirs(base_dir, exist_ok=True)
    default_start_date = datetime.strptime(args.default_start, "%Y-%m-%d")
    now = datetime.now().replace(second=0, microsecond=0)
    max_save_time = datetime(args.max_year, 12, 31, 23, 59, 0)
    end_s = (args.end or "").strip()
    if not end_s:
        time_end_date = min(now, max_save_time)
    elif len(end_s) > 10:
        time_end_date = datetime.strptime(end_s, "%Y-%m-%d %H:%M:%S").replace(second=0, microsecond=0)
    else:
        time_end_date = datetime.strptime(end_s, "%Y-%m-%d").replace(hour=23, minute=59, second=0, microsecond=0)
    time_end_date = min(time_end_date, max_save_time)

    print(f"数据目录: {base_dir}")
    print(f"下载上限: {args.max_year} 年末 ({format_dt(max_save_time)})")
    latest_time_map, latest_close_map = scan_latest_downloaded_state(base_dir, scan_months=args.scan_months)
    global_latest_time = max(latest_time_map.values()) if latest_time_map else None
    if global_latest_time is None:
        print("全库最新分钟: 无本地历史，将按默认起始日处理。")
    else:
        print(f"全库最新分钟: {format_dt(global_latest_time)}")

    if args.use_api_universe:
        print("[WARN] --use-api-universe 为兼容旧参数保留，当前始终使用 xtquant 板块股票池。")

    print("=" * 60)
    print(f"从 xtquant 板块加载股票池: {args.sector_name}")
    all_codes = load_xtquant_sector_universe(args.sector_name)
    print(f"股票池（xtquant/{args.sector_name}）: {len(all_codes)} 只")
    print("=" * 60)
    download_plan, plan_stats = build_download_plan(
        all_codes, global_latest_time, default_start_date, time_end_date
    )
    pending_codes = sum(len(codes) for codes in download_plan.values())
    print(
        "增量计划: "
        f"已最新 {plan_stats['up_to_date']} 只 | "
        f"增量补拉 {plan_stats['incremental']} 只 | "
        f"首次全量 {plan_stats['full_new']} 只"
    )
    if download_plan:
        plan_preview = ", ".join(
            f"{start.strftime('%Y-%m-%d %H:%M')}({len(codes)}只)"
            for start, codes in list(download_plan.items())[:5]
        )
        print(f"下载起点分组(前5): {plan_preview}")
    if pending_codes == 0:
        print("所有股票都已更新到最新分钟，无需下载。")
        return

    failed_requests: list[dict[str, object]] = []
    processed_requests = 0
    total_rows_written = 0
    touched_partitions: set[tuple[int, int, int]] = set()

    print(f"需更新股票数量: {pending_codes}")
    print(f"结束时刻: {format_dt(time_end_date)}")
    print("=" * 60)

    try:
        for plan_idx, (range_start, codes) in enumerate(download_plan.items(), start=1):
            print(
                f"\n[计划 {plan_idx}/{len(download_plan)}] 起点 {format_dt(range_start)} | "
                f"股票 {len(codes)} 只"
            )
            for code_idx, code in enumerate(codes, start=1):
                code_windows = iter_year_windows(range_start, time_end_date, now)
                print(f"  [{code_idx}/{len(codes)}] {code} | 年窗口 {len(code_windows)} 个")
                code_prior_close = latest_close_map.get(normalize_code(code))
                for year, win_start, win_end in code_windows:
                    print(f"    年 {year}: {format_dt(win_start)} ~ {format_dt(win_end)}")
                    try:
                        code_df = fetch_codes_with_retry(
                            [code],
                            win_start,
                            win_end,
                            code_prior_close,
                        )
                        if code_df is None or code_df.is_empty():
                            print(f"    [WARN] 无数据: {code}")
                        else:
                            total_rows_written += code_df.height
                            code_prior_close = float(code_df.sort("time")["close"][-1])
                            touched_partitions.update(
                                save_partitioned_parquet(code_df, base_dir, code, max_save_time=max_save_time)
                            )
                        processed_requests += 1
                        time.sleep(args.sleep_sec)
                    except Exception as exc:
                        error_msg = str(exc)
                        print(f"    [FAIL] 失败: {error_msg}")
                        failed_requests.append(
                            {
                                "range_start": format_dt(range_start),
                                "code": code,
                                "year": year,
                                "window_start": format_dt(win_start),
                                "window_end": format_dt(win_end),
                                "error": error_msg,
                            }
                        )
                        time.sleep(args.sleep_sec)
    finally:
        print("\n" + "=" * 60)
        print("处理完成。")
    print("\n" + "=" * 60)
    print("执行统计")
    print("=" * 60)
    print(f"成功请求: {processed_requests}")
    print(f"累计写入行数: {total_rows_written}")
    print(f"更新到的分区数: {len(touched_partitions)}")
    print(f"失败请求: {len(failed_requests)}")

    if touched_partitions and not args.skip_rebuild:
        rebuilt_files = rebuild_merged_parquets(
            base_dir, touched_partitions, transform_merged=_transform_minute_merged
        )
        print(f"重建 merged.parquet 数量: {len(rebuilt_files)}")
    elif not touched_partitions:
        print("本次无新增数据写入，跳过 merged.parquet 重建。")

    if failed_requests:
        fail_file = Path(base_dir).parent / f"failed_minute_requests_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with fail_file.open("w", encoding="utf-8") as f:
            for fail in failed_requests:
                f.write(
                    f"range_start={fail['range_start']},code={fail['code']},year={fail['year']},"
                    f"window={fail['window_start']}~{fail['window_end']},error={fail['error']}\n"
                )
        print(f"失败记录已保存到: {fail_file}")

    print("=" * 60)


if __name__ == "__main__":
    main()
