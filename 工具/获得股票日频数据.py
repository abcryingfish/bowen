#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""日频数据下载。

每次运行：先扫描本地 parquet 得到全库最新交易日；再用 xtquant 板块数据读取
“沪深A股”股票池；用 xtquant 先下载本地缓存，再读取 1d K 线，转换为现有
parquet schema 后落盘，全部完成后统一重建 merged.parquet。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import polars as pl
from pypinyin import Style, lazy_pinyin
from xtquant import xtdata

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


BASE_DIR = r"D:\database\stock_basic_data_daily"
BATCH_SIZE = 450  # 每批 xtquant 请求的股票数量
DEFAULT_SECTOR_NAME = "\u6caa\u6df1A\u80a1"
DEFAULT_START_DATE = "2010-01-01"
DEFAULT_END_DATE = ""
UNIVERSE_LISTING_START = "2010-01-01"
API_LISTING_START = "1990-01-01"
UNIVERSE_LISTING_STATES = ("上市交易", "终止上市")
DATA_FREQUENCY = "1d"
MAX_RETRIES = 3
REQUEST_SLEEP_SECONDS = 0.5
LOOKBACK_DAYS = 7
MIN_PARQUET_BYTES = 12
MERGED_FILE_NAME = "merged.parquet"
UNIVERSE_OUTPUT_DIR = str(Path(__file__).resolve().parent.parent / "全市场股票代码")
UNIVERSE_FILE_NAME = "universe.parquet"
UNIVERSE_META_NAME = "meta.json"


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
        save_df.write_parquet(file_path, compression="zstd")
        touched_partitions.append((year, month))
        print(f"[OK] 已保存: {file_path} (共 {len(save_df)} 条记录)")

    return touched_partitions


def normalize_code(code: str) -> str:
    return str(code).strip().upper()


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




def name_to_pinyin_initials(name: str) -> str:
    """中文名称 → 拼音首字母大写串（如 贵州茅台 → GZMT）。"""
    text = str(name or "").strip()
    if not text:
        return ""
    parts = lazy_pinyin(text, style=Style.FIRST_LETTER)
    return "".join(str(part).upper() for part in parts if part)


def load_xtquant_sector_universe(sector_name: str) -> list[str]:
    """用 xtquant 板块数据获取股票池。"""
    xtdata.download_sector_data()
    stock_list = xtdata.get_stock_list_in_sector(sector_name)
    if not stock_list:
        raise RuntimeError(f"xtquant 板块股票池为空: {sector_name}")
    return sorted({normalize_code(code) for code in stock_list if str(code).strip()})


def load_xtquant_instrument_meta(code: str) -> dict[str, str]:
    """读取 xtquant 单只股票名称等基础字段；失败时返回空字段。"""
    normalized = normalize_code(code)
    exchange = normalized.split(".")[-1] if "." in normalized else ""
    try:
        detail = xtdata.get_instrument_detail(normalized) or {}
    except Exception as exc:
        print(f"[WARN] 获取股票名称失败: {normalized} | {exc}")
        detail = {}
    name = str(detail.get("InstrumentName") or detail.get("Name") or "").strip()
    exchange = str(detail.get("ExchangeID") or exchange).strip().upper()
    return {
        "name": name,
        "exchange": exchange,
    }


def build_universe_df(codes: list[str]) -> pd.DataFrame:
    rows = []
    for code in sorted({normalize_code(code) for code in codes}):
        meta = load_xtquant_instrument_meta(code)
        name = meta["name"]
        rows.append(
            {
                "htsc_code": code,
                "name": name,
                "pinyin_initials": name_to_pinyin_initials(name),
                "listing_state": "",
                "exchange": meta["exchange"],
            }
        )
    return pd.DataFrame(rows)


def scan_distinct_codes_from_parquet(base_dir: str, min_date: str = UNIVERSE_LISTING_START) -> list[str]:
    """扫描本地日频 parquet，返回 min_date 以来出现过的 htsc_code。"""
    if not os.path.exists(base_dir):
        return []

    parquet_pattern = os.path.join(base_dir, "**", "merged.parquet").replace("\\", "/")
    if not any(Path(base_dir).glob("**/merged.parquet")):
        parquet_pattern = os.path.join(base_dir, "**", "*.parquet").replace("\\", "/")

    try:
        query = f"""
        SELECT DISTINCT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code
        FROM read_parquet('{parquet_pattern}', union_by_name=true)
        WHERE htsc_code IS NOT NULL
          AND TRIM(CAST(htsc_code AS VARCHAR)) <> ''
          AND CAST(time AS TIMESTAMP) >= TIMESTAMP '{min_date}'
        ORDER BY htsc_code
        """
        rows = duckdb.query(query).df()
        if rows.empty:
            return []
        return [normalize_code(str(v)) for v in rows["htsc_code"].tolist() if str(v).strip()]
    except Exception as exc:
        print(f"[WARN] 扫描 parquet 代码失败: {exc}")
        return []


def export_stock_universe(
    base_dir: str,
    api_df: pd.DataFrame,
    output_dir: str = UNIVERSE_OUTPUT_DIR,
    min_date: str = UNIVERSE_LISTING_START,
    listing_states: list[str] | tuple[str, ...] | None = None,
) -> Path | None:
    """导出 parquet 2010 至今出现过的 code，LEFT JOIN API 名称与拼音首字母。"""
    codes = scan_distinct_codes_from_parquet(base_dir, min_date=min_date)
    if not codes:
        print("[WARN] 未扫描到 parquet 中的股票代码，跳过 universe 导出。")
        return None

    states = list(listing_states or UNIVERSE_LISTING_STATES)
    code_df = pd.DataFrame({"htsc_code": codes})
    if api_df is not None and not api_df.empty:
        api_part = api_df.copy()
        api_part["htsc_code"] = api_part["htsc_code"].map(normalize_code)
        keep_cols = [c for c in ("htsc_code", "name", "listing_state", "exchange", "pinyin_initials") if c in api_part.columns]
        api_part = api_part[keep_cols].drop_duplicates(subset=["htsc_code"], keep="last")
        out = code_df.merge(api_part, on="htsc_code", how="left")
    else:
        out = code_df.copy()
        out["name"] = ""
        out["listing_state"] = ""

    if "name" not in out.columns:
        out["name"] = ""
    out["name"] = out["name"].fillna("").astype(str).str.strip()
    out["pinyin_initials"] = out["name"].map(name_to_pinyin_initials)
    if "listing_state" in out.columns:
        out["listing_state"] = out["listing_state"].fillna("").astype(str)
    else:
        out["listing_state"] = ""

    out = out.sort_values("htsc_code").reset_index(drop=True)
    os.makedirs(output_dir, exist_ok=True)
    out_path = Path(output_dir) / UNIVERSE_FILE_NAME
    pl.from_pandas(out).write_parquet(str(out_path), compression="zstd")

    meta = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "count": int(len(out)),
        "listing_date_from": min_date,
        "listing_date_to": datetime.now().strftime("%Y-%m-%d"),
        "listing_states": states,
        "source_parquet": base_dir,
        "source_api": "xtquant.get_stock_list_in_sector",
    }
    meta_path = Path(output_dir) / UNIVERSE_META_NAME
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 已导出全市场股票代码: {out_path}（{len(out)} 条）")
    return out_path


def scan_latest_downloaded_times(base_dir: str) -> dict[str, datetime]:
    """扫描本地 parquet，返回每只股票已下载到的最新交易日。"""
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

        print(f"发现已下载 {len(latest_time_map)} 个股票的历史数据。")
    except Exception:
        print("未发现有效历史数据或读取异常，将按全量起始日处理。")

    return latest_time_map


def build_download_plan(
    all_codes: list[str],
    global_latest_time: datetime | None,
    default_start_date: datetime,
    time_end_date: datetime,
) -> tuple[dict[datetime, list[str]], dict[str, int]]:
    """按全库最新交易日统一增量，避免单票缺失触发长区间回补。"""
    stats = {"up_to_date": 0, "incremental": 0, "full_new": 0}
    if global_latest_time is None:
        start_date = default_start_date
        stats["full_new"] = len(all_codes)
    else:
        start_date = global_latest_time - timedelta(days=LOOKBACK_DAYS)
        stats["incremental"] = len(all_codes)

    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    if start_date > time_end_date:
        stats["up_to_date"] = len(all_codes)
        stats["incremental"] = 0
        stats["full_new"] = 0
        return {}, stats

    return {start_date: [normalize_code(code) for code in all_codes]}, stats


def format_xtquant_day(value: datetime) -> str:
    return value.strftime("%Y%m%d")


def _normalize_xtquant_daily_dataframe(raw_df: pd.DataFrame, code: str) -> pd.DataFrame:
    if raw_df is None or raw_df.empty:
        return pd.DataFrame()

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
            .dt.floor("D")
        )
    else:
        text_time = raw_time.astype(str).str.replace(r"\.0$", "", regex=True)
        parsed_time = pd.to_datetime(text_time, format="%Y%m%d", errors="coerce")
        fallback_time = pd.to_datetime(raw_time, errors="coerce")
        df["time"] = parsed_time.fillna(fallback_time).dt.floor("D")

    code = normalize_code(code)
    df["htsc_code"] = code
    df["security_id"] = code.split(".")[0]
    df["frequency"] = "daily"
    df["num_trades"] = float("nan")
    df["value"] = pd.to_numeric(df["amount"], errors="coerce")
    df["security_type"] = ""
    df["exchange"] = ""
    for column in ["open", "high", "low", "close", "volume", "pvolume", "value"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["volume"] = df["pvolume"].fillna(df["volume"] * 100)

    ordered_columns = [
        "htsc_code",
        "time",
        "security_id",
        "frequency",
        "open",
        "close",
        "high",
        "low",
        "num_trades",
        "volume",
        "value",
        "security_type",
        "exchange",
    ]
    df = df.dropna(subset=["time", "htsc_code", "open", "high", "low", "close"])
    df = df.drop_duplicates(subset=["htsc_code", "time"], keep="last")
    df = df.sort_values(["time", "htsc_code"]).reset_index(drop=True)
    return df[ordered_columns]


def fetch_batch_with_retry(
    batch: list[str],
    time_start_date: datetime,
    time_end_date: datetime,
    max_retries: int = MAX_RETRIES,
) -> pd.DataFrame | None:
    retry_count = 0
    normalized_batch = [normalize_code(code) for code in batch]
    start_text = format_xtquant_day(time_start_date)
    end_text = format_xtquant_day(time_end_date)
    while retry_count < max_retries:
        try:
            xtdata.download_history_data2(
                stock_list=normalized_batch,
                period=DATA_FREQUENCY,
                start_time=start_text,
                end_time=end_text,
            )
            data = xtdata.get_market_data_ex(
                field_list=["time", "open", "high", "low", "close", "volume", "amount"],
                stock_list=normalized_batch,
                period=DATA_FREQUENCY,
                start_time=start_text,
                end_time=end_text,
                dividend_type="none",
                fill_data=False,
            )
            if not isinstance(data, dict) or not data:
                return None

            frames = [
                _normalize_xtquant_daily_dataframe(raw_df, code)
                for code, raw_df in data.items()
            ]
            frames = [frame for frame in frames if not frame.empty]
            if not frames:
                return None
            result = pd.concat(frames, ignore_index=True)
            result = result.drop_duplicates(subset=["htsc_code", "time"], keep="last")
            return result
        except Exception as exc:
            retry_count += 1
            error_msg = str(exc)
            print(f"  [FAIL] 第 {retry_count} 次尝试失败: {error_msg}")
            if retry_count >= max_retries:
                raise

            wait_time = 2 * retry_count
            print(f"  [WAIT] 等待 {wait_time} 秒后重试...")
            time.sleep(wait_time)

    return None


def split_returned_and_missing_codes(result: pd.DataFrame, batch: list[str]) -> tuple[pd.DataFrame, list[str], list[str]]:
    """拆分批次中已返回和缺失的股票代码。"""
    if result is None or result.empty:
        return pd.DataFrame(), [], [normalize_code(code) for code in batch]

    result = result.copy()
    result["htsc_code"] = result["htsc_code"].map(normalize_code)
    returned_codes = sorted(set(result["htsc_code"].tolist()))
    expected_codes = [normalize_code(code) for code in batch]
    missing_codes = sorted(set(expected_codes) - set(returned_codes))
    return result, returned_codes, missing_codes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="日频下载：xtquant 沪深A股股票池 + 1d 本地缓存增量"
    )
    parser.add_argument(
        "--sector-name",
        default=DEFAULT_SECTOR_NAME,
        help="xtquant 板块名称，用于获取股票池（默认 沪深A股）",
    )
    parser.add_argument(
        "--listing-start",
        default=API_LISTING_START,
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
        help="日频 parquet 根目录",
    )
    parser.add_argument(
        "--default-start",
        default=DEFAULT_START_DATE,
        help="本地尚无该票时，日频从该日起拉（默认与 DEFAULT_START_DATE 一致）",
    )
    parser.add_argument(
        "--end",
        default=DEFAULT_END_DATE,
        help="日频结束日，默认今天；格式 YYYY-MM-DD",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_dir = str(args.base_dir)
    default_start_date = datetime.strptime(args.default_start, "%Y-%m-%d")
    end_s = (args.end or "").strip()
    time_end_date = datetime.now() if not end_s else datetime.strptime(end_s, "%Y-%m-%d")
    time_end_date = time_end_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    latest_time_map = scan_latest_downloaded_times(base_dir)
    global_latest_time = max(latest_time_map.values()) if latest_time_map else None
    if global_latest_time is None:
        print("全库最新交易日: 无本地历史，将按默认起始日处理。")
    else:
        print(f"全库最新交易日: {global_latest_time.strftime('%Y-%m-%d')}")

    print("=" * 60)
    print(f"从 xtquant 板块加载股票池: {args.sector_name}")
    print("=" * 60)
    all_codes = load_xtquant_sector_universe(args.sector_name)
    api_df = build_universe_df(all_codes)
    print(f"股票池（xtquant/{args.sector_name}）: {len(all_codes)} 只")
    print("=" * 60)

    download_plan, plan_stats = build_download_plan(all_codes, global_latest_time, default_start_date, time_end_date)
    pending_total = sum(len(codes) for codes in download_plan.values())
    print(
        "增量计划: "
        f"已最新 {plan_stats['up_to_date']} 只 | "
        f"增量补拉 {plan_stats['incremental']} 只 | "
        f"首次全量 {plan_stats['full_new']} 只"
    )
    if download_plan:
        plan_preview = ", ".join(
            f"{start.strftime('%Y-%m-%d')}({len(codes)}只)"
            for start, codes in list(download_plan.items())[:5]
        )
        print(f"下载起点分组(前5): {plan_preview}")
    failed_batches: list[dict[str, object]] = []
    processed_count = 0
    touched_partitions: set[tuple[int, int]] = set()

    if pending_total == 0:
        print("所有股票都已更新到最新日期，无需下载。")
    else:
        print(f"需更新股票数量: {pending_total}")
        print("=" * 60)

        try:
            group_items = list(download_plan.items())
            total_batches = sum((len(codes) + BATCH_SIZE - 1) // BATCH_SIZE for _, codes in group_items)
            batch_num = 0

            for start_date, codes in group_items:
                for i in range(0, len(codes), BATCH_SIZE):
                    batch_num += 1
                    batch = codes[i : i + BATCH_SIZE]
                    print(f"\n[批次 {batch_num}/{total_batches}] 处理: {batch}")
                    print(f"  下载区间: {start_date.date()} ~ {time_end_date.date()}")

                    try:
                        result = fetch_batch_with_retry(batch, start_date, time_end_date)
                        if result is None or result.empty:
                            print(f"  [WARN] 批次 {batch} 返回空数据，已记录")
                            failed_batches.append(
                                {
                                    "batch": batch,
                                    "start_date": start_date.strftime("%Y-%m-%d"),
                                    "error": "返回空数据",
                                    "batch_num": batch_num,
                                }
                            )
                            continue

                        result, returned_codes, missing_codes = split_returned_and_missing_codes(result, batch)
                        if missing_codes:
                            print(f"  [WARN] 以下股票本批次未返回数据: {missing_codes}")
                            failed_batches.append(
                                {
                                    "batch": missing_codes,
                                    "start_date": start_date.strftime("%Y-%m-%d"),
                                    "error": "批次部分股票未返回数据",
                                    "batch_num": batch_num,
                                }
                            )

                        result_pl = pl.from_pandas(result)
                        touched = save_partitioned_parquet(result_pl, base_dir)
                        touched_partitions.update(touched)

                        processed_count += len(returned_codes)
                        print(f"  [OK] 成功处理 {len(returned_codes)} 个股票，累计 {processed_count}/{pending_total}")
                        time.sleep(REQUEST_SLEEP_SECONDS)
                    except Exception as exc:
                        error_msg = str(exc)
                        print(f"  [FAIL] 批次最终失败: {error_msg}")
                        failed_batches.append(
                            {
                                "batch": batch,
                                "start_date": start_date.strftime("%Y-%m-%d"),
                                "error": error_msg,
                                "batch_num": batch_num,
                            }
                        )
        finally:
            print("\n" + "=" * 60)
            print("处理完成。")

    print("\n" + "=" * 60)
    print("执行统计")
    print("=" * 60)
    print(f"成功处理: {processed_count}/{pending_total} 个股票")
    print(f"更新到的分区数: {len(touched_partitions)}")
    print(f"失败批次: {len(failed_batches)} 个")

    if touched_partitions:
        rebuilt_files = rebuild_merged_parquets(
            base_dir, touched_partitions, transform_merged=transform_daily_htsc_time_merged
        )
        print(f"重建 merged.parquet 数量: {len(rebuilt_files)}")
    else:
        rebuilt_files = []
        print("本次无新增数据写入，跳过 merged.parquet 重建。")

    if failed_batches:
        print("\n[WARN] 以下批次失败，可后续补跑:")
        for fail in failed_batches:
            print(
                f"  - 批次 {fail['batch_num']}: {fail['batch']} | 起始日期: {fail['start_date']} | 原因: {fail['error']}"
            )

        fail_file = f"failed_batches_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(fail_file, "w", encoding="utf-8") as f:
            for fail in failed_batches:
                f.write(
                    f"batch_num={fail['batch_num']},start_date={fail['start_date']},codes={fail['batch']},error={fail['error']}\n"
                )
        print(f"\n失败批次已保存到: {fail_file}")

    try:
        export_stock_universe(
            base_dir=base_dir,
            api_df=api_df,
            output_dir=UNIVERSE_OUTPUT_DIR,
            min_date=UNIVERSE_LISTING_START,
            listing_states=list(UNIVERSE_LISTING_STATES),
        )
    except Exception as exc:
        print(f"[WARN] 导出全市场股票代码失败: {exc}")

    print("=" * 60)


if __name__ == "__main__":
    main()
