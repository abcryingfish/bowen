#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""ETF 日频历史数据下载。

从 xtquant ETF 板块分类获取 ETF 产品代码，按批逐只补齐本地历史缓存，
再批量读取 1d K 线并写入 D:\\database\\ETF_basic_data_daily。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import polars as pl
from pypinyin import Style, lazy_pinyin
from xtquant import xtdata

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


BASE_DIR = r"D:\database\ETF_basic_data_daily"
UNIVERSE_DIR = r"D:\database\ETF_sector_members"
CSV_DIR = str(Path(__file__).resolve().parent.parent / "华泰数据获取")
DEFAULT_START_DATE = "2010-01-01"
DEFAULT_END_DATE = ""
DEFAULT_BATCH_SIZE = 50
DATA_FREQUENCY = "1d"
MAX_RETRIES = 3
REQUEST_SLEEP_SECONDS = 0.2
MIN_PARQUET_BYTES = 12
MERGED_FILE_NAME = "merged.parquet"
ETF_UNIVERSE_FILE_NAME = "etf_universe.parquet"
ETF_SECTOR_MEMBERS_FILE_NAME = "etf_sector_members.parquet"
CSV_COLUMNS = [
    "snapshot_date",
    "snapshot_time",
    "sector_name",
    "rank_in_return",
    "etf_code",
    "market",
    "source_api",
]
DEFAULT_ETF_SECTOR_NAMES = [
    "沪深ETF",
    "沪市ETF",
    "深市ETF",
    "ETF股票型",
    "ETF行业指数",
    "ETF主题指数",
    "ETF跨境型",
]


def normalize_code(code: Any) -> str:
    return str(code or "").strip().upper()


def format_xtquant_day(value: datetime) -> str:
    return value.strftime("%Y%m%d")


def name_to_pinyin_initials(name: str) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    parts = lazy_pinyin(text, style=Style.FIRST_LETTER)
    return "".join(str(part).upper() for part in parts if part)


def chunk_codes(codes: list[str], batch_size: int = DEFAULT_BATCH_SIZE):
    if batch_size <= 0:
        raise ValueError("batch_size 必须大于 0")
    for idx in range(0, len(codes), batch_size):
        yield codes[idx : idx + batch_size]


def _is_readable_parquet(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= MIN_PARQUET_BYTES and not pl.read_parquet(str(path), n_rows=1).is_empty()
    except Exception:
        return False


def transform_daily_htsc_time_merged(df: pl.DataFrame) -> pl.DataFrame:
    if "time" not in df.columns or "htsc_code" not in df.columns:
        return df
    return (
        df.with_columns(pl.col("time").cast(pl.Datetime, strict=False).dt.truncate("1d").alias("time"))
        .drop_nulls(["time", "htsc_code"])
        .unique(subset=["htsc_code", "time"], keep="last")
        .sort(["time", "htsc_code"])
    )


def save_partitioned_parquet(df: pl.DataFrame, base_dir: str) -> list[tuple[int, int]]:
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
    for partition_df in df.partition_by(["year", "month"]):
        year = int(partition_df["year"][0])
        month = int(partition_df["month"][0])
        dir_path = Path(base_dir) / f"year={year}" / f"month={month:02d}"
        dir_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        file_path = dir_path / f"{timestamp}_{os.getpid()}_year_{year}_month_{month:02d}.parquet"
        save_df = partition_df.drop(["year", "month"])
        save_df.write_parquet(str(file_path), compression="zstd")
        touched_partitions.append((year, month))
        print(f"[OK] 已保存: {file_path} (共 {len(save_df)} 条记录)")

    return touched_partitions


def rebuild_merged_parquets(base_dir: str, touched_partitions: set[tuple[int, int]]) -> list[Path]:
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
            merged_df = transform_daily_htsc_time_merged(merged_df)
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


def scan_global_latest_time(base_dir: str) -> datetime | None:
    if not os.path.exists(base_dir):
        return None

    base_path = Path(base_dir)
    merged_files = list(base_path.glob("**/merged.parquet"))
    parquet_pattern = (
        str(base_path / "**" / "merged.parquet")
        if merged_files
        else str(base_path / "**" / "*.parquet")
    ).replace("\\", "/")

    try:
        query = f"""
        SELECT MAX(CAST(time AS TIMESTAMP)) AS latest_time
        FROM read_parquet('{parquet_pattern}', union_by_name=true)
        WHERE time IS NOT NULL
        """
        latest_df = duckdb.query(query).df()
        if latest_df.empty or pd.isna(latest_df.loc[0, "latest_time"]):
            return None
        return pd.Timestamp(latest_df.loc[0, "latest_time"]).floor("D").to_pydatetime()
    except Exception:
        return None


def resolve_download_start_date(
    base_dir: str,
    default_start_date: datetime,
    no_incremental: bool = False,
) -> datetime:
    if no_incremental:
        return default_start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    latest_time = scan_global_latest_time(base_dir)
    if latest_time is None:
        return default_start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    return (latest_time + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def load_etf_sector_map(sector_names: list[str]) -> dict[str, list[str]]:
    xtdata.download_sector_data()
    available = set(xtdata.get_sector_list())
    sector_map: dict[str, list[str]] = {}
    for sector_name in sector_names:
        if sector_name not in available:
            print(f"[WARN] ETF 分类不存在，跳过: {sector_name}")
            sector_map[sector_name] = []
            continue
        codes = xtdata.get_stock_list_in_sector(sector_name) or []
        sector_map[sector_name] = sorted({normalize_code(code) for code in codes if normalize_code(code)})
        print(f"[SECTOR] {sector_name}: {len(sector_map[sector_name])} 只")
    return sector_map


def load_xtquant_instrument_meta(code: str) -> dict[str, str]:
    normalized = normalize_code(code)
    exchange = normalized.split(".")[-1] if "." in normalized else ""
    try:
        detail = xtdata.get_instrument_detail(normalized) or {}
    except Exception as exc:
        print(f"[WARN] 获取 ETF 名称失败: {normalized} | {exc}")
        detail = {}
    name = str(detail.get("InstrumentName") or detail.get("Name") or "").strip()
    exchange = str(detail.get("ExchangeID") or exchange).strip().upper()
    return {"name": name, "exchange": exchange}


def build_etf_universe_rows(
    sector_map: dict[str, list[str]],
    detail_by_code: dict[str, dict[str, str]] | None = None,
) -> dict[str, pl.DataFrame]:
    sector_by_code: dict[str, set[str]] = defaultdict(set)
    member_rows: list[dict[str, Any]] = []
    snapshot_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for sector_name in sorted(sector_map):
        for rank, code in enumerate(sorted({normalize_code(c) for c in sector_map[sector_name] if normalize_code(c)}), 1):
            sector_by_code[code].add(sector_name)
            member_rows.append(
                {
                    "snapshot_time": snapshot_time,
                    "sector_name": sector_name,
                    "rank_in_sector": rank,
                    "htsc_code": code,
                    "market": code.split(".")[-1] if "." in code else "",
                    "source_api": "xtdata.get_stock_list_in_sector",
                }
            )

    details = detail_by_code or {}
    universe_rows: list[dict[str, Any]] = []
    for code in sorted(sector_by_code):
        meta = details.get(code) or load_xtquant_instrument_meta(code)
        name = str(meta.get("name") or "").strip()
        exchange = str(meta.get("exchange") or (code.split(".")[-1] if "." in code else "")).strip().upper()
        universe_rows.append(
            {
                "htsc_code": code,
                "name": name,
                "pinyin_initials": name_to_pinyin_initials(name),
                "security_type": "etf",
                "exchange": exchange,
                "sector_names": ",".join(sorted(sector_by_code[code])),
                "source_api": "xtdata.get_stock_list_in_sector",
                "snapshot_time": snapshot_time,
            }
        )

    return {
        "universe": pl.DataFrame(universe_rows),
        "members": pl.DataFrame(member_rows),
    }



def build_sector_csv_frame(
    sector_name: str,
    codes: list[str],
    *,
    snapshot_time: str,
) -> pd.DataFrame:
    snapshot_date = str(snapshot_time)[:10]
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    rank = 0
    for raw_code in codes:
        code = normalize_code(raw_code)
        if not code or code in seen:
            continue
        seen.add(code)
        rank += 1
        rows.append(
            {
                "snapshot_date": snapshot_date,
                "snapshot_time": snapshot_time,
                "sector_name": sector_name,
                "rank_in_return": rank,
                "etf_code": code,
                "market": code.split(".")[-1] if "." in code else "",
                "source_api": "xtdata.get_stock_list_in_sector",
            }
        )
    return pd.DataFrame(rows, columns=CSV_COLUMNS)


def write_sector_csvs(
    sector_map: dict[str, list[str]],
    csv_dir: str | Path,
    *,
    snapshot_time: str,
) -> list[Path]:
    out_dir = Path(csv_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for sector_name in DEFAULT_ETF_SECTOR_NAMES:
        frame = build_sector_csv_frame(
            sector_name,
            sector_map.get(sector_name, []),
            snapshot_time=snapshot_time,
        )
        out_path = out_dir / f"{sector_name}.csv"
        frame.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"[CSV] {sector_name}: {len(frame)} 行 -> {out_path}")
        written.append(out_path)
    return written

def save_etf_universe(rows: dict[str, pl.DataFrame], universe_dir: str) -> None:
    out_dir = Path(universe_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows["universe"].write_parquet(str(out_dir / ETF_UNIVERSE_FILE_NAME), compression="zstd")
    rows["members"].write_parquet(str(out_dir / ETF_SECTOR_MEMBERS_FILE_NAME), compression="zstd")
    print(f"[OK] ETF universe: {out_dir / ETF_UNIVERSE_FILE_NAME} | {len(rows['universe'])} 只")
    print(f"[OK] ETF sector members: {out_dir / ETF_SECTOR_MEMBERS_FILE_NAME} | {len(rows['members'])} 行")


def normalize_xtquant_etf_daily_dataframe(raw_df: pd.DataFrame, code: str) -> pd.DataFrame:
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
    df["exchange"] = code.split(".")[-1] if "." in code else ""
    df["security_type"] = "etf"
    df["security_id"] = code.split(".")[0]
    df["frequency"] = "daily"
    df["value"] = pd.to_numeric(df["amount"], errors="coerce")
    for column in ["open", "high", "low", "close", "volume", "pvolume", "value"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["volume"] = df["pvolume"].fillna(df["volume"] * 100)

    ordered_columns = [
        "htsc_code",
        "time",
        "exchange",
        "security_type",
        "security_id",
        "frequency",
        "open",
        "close",
        "high",
        "low",
        "volume",
        "value",
    ]
    df = df.dropna(subset=["time", "htsc_code", "open", "high", "low", "close"])
    df = df.drop_duplicates(subset=["htsc_code", "time"], keep="last")
    df = df.sort_values(["time", "htsc_code"]).reset_index(drop=True)
    return df[ordered_columns]


def download_one_code_with_retry(code: str, start_date: datetime, end_date: datetime) -> bool:
    start_text = format_xtquant_day(start_date)
    end_text = format_xtquant_day(end_date)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            xtdata.download_history_data(
                stock_code=code,
                period=DATA_FREQUENCY,
                start_time=start_text,
                end_time=end_text,
            )
            return True
        except Exception as exc:
            print(f"    [FAIL] {code} 下载第 {attempt} 次失败: {exc}")
            if attempt >= MAX_RETRIES:
                return False
            time.sleep(2 * attempt)
    return False


def fetch_batch_after_download(batch: list[str], start_date: datetime, end_date: datetime) -> pd.DataFrame | None:
    start_text = format_xtquant_day(start_date)
    end_text = format_xtquant_day(end_date)
    data = xtdata.get_market_data_ex(
        field_list=["time", "open", "high", "low", "close", "volume", "amount", "pvolume"],
        stock_list=batch,
        period=DATA_FREQUENCY,
        start_time=start_text,
        end_time=end_text,
        dividend_type="none",
        fill_data=False,
    )
    if not isinstance(data, dict) or not data:
        return None

    frames = [
        normalize_xtquant_etf_daily_dataframe(data.get(code), code)
        for code in batch
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return None
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["htsc_code", "time"], keep="last")
    return out.sort_values(["time", "htsc_code"]).reset_index(drop=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ETF CSV、板块 parquet 与日频数据合并更新")
    parser.add_argument("--base-dir", default=BASE_DIR, help="ETF 日频 parquet 根目录")
    parser.add_argument("--universe-dir", default=UNIVERSE_DIR, help="ETF universe 和分类明细输出目录")
    parser.add_argument("--csv-dir", default=CSV_DIR, help="ETF 分类 CSV 输出目录")
    parser.add_argument("--default-start", default=DEFAULT_START_DATE, help="本地无数据时的起始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=DEFAULT_END_DATE, help="结束日期 YYYY-MM-DD；默认今天")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="每批处理 ETF 数量，默认 50")
    parser.add_argument("--no-incremental", action="store_true", help="忽略本地最大日期，从 default-start 开始补拉")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_dir = str(args.base_dir)
    universe_dir = str(args.universe_dir)
    default_start_date = datetime.strptime(args.default_start, "%Y-%m-%d")
    end_s = (args.end or "").strip()
    end_date = datetime.now() if not end_s else datetime.strptime(end_s, "%Y-%m-%d")
    end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    snapshot_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sector_map = load_etf_sector_map(DEFAULT_ETF_SECTOR_NAMES)
    write_sector_csvs(sector_map, args.csv_dir, snapshot_time=snapshot_time)
    rows = build_etf_universe_rows(sector_map)
    save_etf_universe(rows, universe_dir)
    codes = rows["universe"]["htsc_code"].to_list() if not rows["universe"].is_empty() else []

    if not codes:
        raise RuntimeError("ETF 代码池为空")

    start_date = resolve_download_start_date(base_dir, default_start_date, bool(args.no_incremental))
    if start_date > end_date:
        print(f"[OK] 已最新：全库最大日期已覆盖到 {end_date.date()}，无需更新。")
        return

    print("=" * 60)
    print(f"ETF 数量: {len(codes)} | 批大小: {args.batch_size}")
    print(f"下载区间: {start_date.date()} ~ {end_date.date()}")
    print(f"CSV 目录: {args.csv_dir}")
    print(f"数据目录: {base_dir}")
    print("=" * 60)

    touched_partitions: set[tuple[int, int]] = set()
    failed_codes: list[str] = []
    processed_batches = 0
    processed_codes = 0

    for batch_idx, batch in enumerate(chunk_codes(codes, int(args.batch_size)), 1):
        print(f"\n[BATCH {batch_idx}] ETF {len(batch)} 只")
        downloaded: list[str] = []
        for code in batch:
            ok = download_one_code_with_retry(code, start_date, end_date)
            if ok:
                downloaded.append(code)
            else:
                failed_codes.append(code)
            time.sleep(REQUEST_SLEEP_SECONDS)

        if not downloaded:
            print(f"[WARN] BATCH {batch_idx} 无成功下载代码，跳过读取")
            continue

        result = fetch_batch_after_download(downloaded, start_date, end_date)
        if result is None or result.empty:
            print(f"[WARN] BATCH {batch_idx} 读取为空")
            failed_codes.extend(downloaded)
            continue

        touched = save_partitioned_parquet(pl.from_pandas(result), base_dir)
        touched_partitions.update(touched)
        processed_batches += 1
        processed_codes += len(set(result["htsc_code"].astype(str)))
        print(f"[OK] BATCH {batch_idx} 写入 {len(result)} 行 | 覆盖 ETF {result['htsc_code'].nunique()} 只")

    print("\n" + "=" * 60)
    print("[STATS] 执行统计")
    print(f"成功批次: {processed_batches} | 有数据 ETF 数: {processed_codes} | 失败/空数据记录: {len(failed_codes)}")
    print(f"更新到的分区数: {len(touched_partitions)}")

    if touched_partitions:
        rebuilt_files = rebuild_merged_parquets(base_dir, touched_partitions)
        print(f"重建 merged.parquet 数量: {len(rebuilt_files)}")
    else:
        print("本次无新增数据写入，跳过 merged.parquet 重建。")

    if failed_codes:
        failed_unique = sorted(set(failed_codes))
        print("\n[WARN] 以下 ETF 下载失败或读取为空，可后续补跑:")
        for code in failed_unique[:200]:
            print(f"  - {code}")
        if len(failed_unique) > 200:
            print(f"  ... 其余 {len(failed_unique) - 200} 只省略")
    print("=" * 60)


if __name__ == "__main__":
    main()
