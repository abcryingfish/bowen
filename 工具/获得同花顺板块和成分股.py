#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""获取同花顺软件一级指数日线并增量写入 index_data_daily。"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path

import duckdb
import polars as pl
from pypinyin import Style, lazy_pinyin


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


BASE_DIR = r"D:\database\index_data_daily"
STOCKNAME_FILE = Path(r"D:\同花顺\同花顺\stockname\stockname_48_0.txt")
DEFAULT_START_DATE = "2010-01-01"
LEVEL1_PREFIX_COUNTS = {"881": 90, "882": 33, "885": 293, "886": 96}
OUTPUT_COLUMNS = [
    "htsc_code", "time", "exchange", "security_type", "security_id", "frequency",
    "open", "close", "high", "low", "volume", "value",
]
API_TEMPLATE = "https://d.10jqka.com.cn/v6/line/48_{security_id}/01/{year}.js"


def load_level1_indices(stockname_file: str | Path = STOCKNAME_FILE) -> list[dict[str, str]]:
    path = Path(stockname_file)
    text = path.read_bytes().decode("gb18030")
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        if "=" not in line:
            continue
        security_id, index_name = line.split("=", 1)
        security_id = security_id.strip()
        index_name = index_name.strip()
        if len(security_id) != 6 or security_id[:3] not in LEVEL1_PREFIX_COUNTS:
            continue
        rows.append(
            {
                "security_id": security_id,
                "htsc_code": f"{security_id}.THS",
                "index_name": index_name,
                "index_prefix": security_id[:3],
            }
        )
    rows.sort(key=lambda row: row["security_id"])
    counts = Counter(row["index_prefix"] for row in rows)
    if counts != Counter(LEVEL1_PREFIX_COUNTS) or len(rows) != 512:
        raise ValueError(
            f"同花顺软件一级口径异常：期望 {LEVEL1_PREFIX_COUNTS} 合计512，实际 {dict(counts)} 合计{len(rows)}"
        )
    if len({row["security_id"] for row in rows}) != len(rows):
        raise ValueError("同花顺软件一级指数代码存在重复")
    return rows


def write_level1_universe(indices: list[dict[str, str]], base_dir: str | Path) -> Path:
    output_path = Path(base_dir) / "_meta" / "ths_level1_universe.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "htsc_code": row["htsc_code"],
            "name": row["index_name"],
            "pinyin_initials": "".join(
                lazy_pinyin(row["index_name"], style=Style.FIRST_LETTER)
            ).upper(),
            "security_type": "index",
            "security_id": row["security_id"],
            "exchange": "THS",
        }
        for row in indices
    ]
    frame = pl.DataFrame(records).sort("htsc_code")
    temp_path = output_path.parent / f"{output_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    frame.write_parquet(temp_path, compression="zstd")
    _atomic_replace_with_retry(temp_path, output_path)
    return output_path


def _empty_daily_frame() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "htsc_code": pl.String,
            "time": pl.Datetime("us"),
            "exchange": pl.String,
            "security_type": pl.String,
            "security_id": pl.String,
            "frequency": pl.String,
            "open": pl.Float64,
            "close": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "volume": pl.Float64,
            "value": pl.Float64,
        }
    )


def parse_year_jsonp(text: str, security_id: str) -> pl.DataFrame:
    left = text.find("{")
    right = text.rfind("}")
    if left < 0 or right < left:
        raise ValueError(f"{security_id} 年度接口返回不是有效JSONP")
    payload = json.loads(text[left : right + 1])
    records: list[dict[str, object]] = []
    for raw_record in str(payload.get("data", "")).split(";"):
        fields = raw_record.split(",")
        if len(fields) < 7 or not re.fullmatch(r"\d{8}", fields[0]):
            continue
        try:
            record_time = datetime.strptime(fields[0], "%Y%m%d")
            open_price = float(fields[1])
            high_price = float(fields[2])
            low_price = float(fields[3])
            close_price = float(fields[4])
            volume = float(fields[5])
            value = float(fields[6])
        except (TypeError, ValueError):
            continue
        records.append(
            {
                "htsc_code": f"{security_id}.THS",
                "time": record_time,
                "exchange": "THS",
                "security_type": "index",
                "security_id": security_id,
                "frequency": "daily",
                "open": open_price,
                "close": close_price,
                "high": high_price,
                "low": low_price,
                "volume": volume,
                "value": value,
            }
        )
    if not records:
        return _empty_daily_frame()
    return pl.DataFrame(records).select(OUTPUT_COLUMNS).with_columns(
        pl.col("time").cast(pl.Datetime("us"))
    )


def _previous_weekday(value: date) -> date:
    result = value
    while result.weekday() >= 5:
        result -= timedelta(days=1)
    return result


def resolve_completed_end_date(now: datetime | None = None) -> date:
    current = now or datetime.now()
    candidate = current.date()
    if current.time() < dt_time(15, 30):
        candidate -= timedelta(days=1)
    return _previous_weekday(candidate)


def resolve_fetch_start(latest_time: datetime | date | None, default_start: str | date) -> date:
    if latest_time is not None:
        if isinstance(latest_time, datetime):
            return latest_time.date()
        return latest_time
    if isinstance(default_start, date):
        return default_start
    return datetime.strptime(str(default_start), "%Y-%m-%d").date()


def _atomic_replace_with_retry(temp_path: Path, final_path: Path) -> None:
    last_error: OSError | None = None
    for attempt in range(20):
        try:
            temp_path.replace(final_path)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.1 * (attempt + 1))
    if last_error is not None:
        raise last_error


def _normalize_daily_frame(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty():
        return _empty_daily_frame()
    missing = [column for column in OUTPUT_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"日线数据缺少字段：{missing}")
    result = (
        frame.select(OUTPUT_COLUMNS)
        .with_columns(
            pl.col("htsc_code").cast(pl.String).str.to_uppercase(),
            pl.col("time").cast(pl.Datetime("us"), strict=False).dt.truncate("1d"),
            *[pl.col(column).cast(pl.Float64, strict=False) for column in ("open", "close", "high", "low", "volume", "value")],
        )
        .drop_nulls(["htsc_code", "time", "open", "close", "high", "low"])
        .unique(subset=["htsc_code", "time"], keep="last")
        .sort(["time", "htsc_code"])
    )
    is_ths = pl.col("htsc_code").str.ends_with(".THS")
    result = result.with_columns(
        pl.when(is_ths)
        .then(pl.max_horizontal("high", "open", "close"))
        .otherwise(pl.col("high"))
        .alias("high"),
        pl.when(is_ths)
        .then(pl.min_horizontal("low", "open", "close"))
        .otherwise(pl.col("low"))
        .alias("low"),
    )
    invalid = result.filter(
        (pl.col("high") < pl.max_horizontal("open", "close"))
        | (pl.col("low") > pl.min_horizontal("open", "close"))
        | (pl.col("volume") < 0)
        | (pl.col("value") < 0)
    )
    if not invalid.is_empty():
        sample = invalid.select(["htsc_code", "time", "open", "close", "high", "low"]).head(3)
        raise ValueError(f"发现非法OHLCV记录：\n{sample}")
    return result


def _merge_month_partition(month_dir: Path, part_path: Path) -> Path:
    merged_path = month_dir / "merged.parquet"
    frames = []
    if merged_path.is_file() and merged_path.stat().st_size >= 12:
        frames.append(pl.read_parquet(merged_path))
    frames.append(pl.read_parquet(part_path))
    merged = _normalize_daily_frame(pl.concat(frames, how="diagonal_relaxed", rechunk=True))
    temp_path = month_dir / f"merged.parquet.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    merged.write_parquet(temp_path, compression="zstd")
    _atomic_replace_with_retry(temp_path, merged_path)
    part_path.unlink(missing_ok=True)
    return merged_path


def save_partitioned_parquet(frame: pl.DataFrame, base_dir: str | Path) -> list[Path]:
    normalized = _normalize_daily_frame(frame)
    if normalized.is_empty():
        return []
    partitioned = normalized.with_columns(
        pl.col("time").dt.year().alias("_year"),
        pl.col("time").dt.month().alias("_month"),
    )
    rebuilt: list[Path] = []
    for keys, month_frame in partitioned.partition_by(["_year", "_month"], as_dict=True).items():
        year, month = int(keys[0]), int(keys[1])
        month_dir = Path(base_dir) / f"year={year:04d}" / f"month={month:02d}"
        month_dir.mkdir(parents=True, exist_ok=True)
        part_path = month_dir / f"part_ths_{os.getpid()}_{time.time_ns()}_{uuid.uuid4().hex}.parquet"
        month_frame.drop(["_year", "_month"]).write_parquet(part_path, compression="zstd")
        rebuilt.append(_merge_month_partition(month_dir, part_path))
    return rebuilt


def scan_latest_downloaded_times(base_dir: str | Path) -> dict[str, datetime]:
    paths = sorted(Path(base_dir).glob("year=*/month=*/merged.parquet"))
    if not paths:
        return {}
    path_list = "[" + ",".join("'" + str(path).replace("\\", "/").replace("'", "''") + "'" for path in paths) + "]"
    query = f"""
    SELECT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
           MAX(CAST(time AS TIMESTAMP)) AS latest_time
    FROM read_parquet({path_list}, union_by_name=true)
    WHERE UPPER(TRIM(CAST(htsc_code AS VARCHAR))) LIKE '%.THS'
    GROUP BY 1
    """
    frame = duckdb.connect(database=":memory:").execute(query).df()
    return {
        str(row.htsc_code): row.latest_time.to_pydatetime() if hasattr(row.latest_time, "to_pydatetime") else row.latest_time
        for row in frame.itertuples(index=False)
    }


def _request_year(security_id: str, year: int, timeout: float, retries: int) -> str | None:
    url = API_TEMPLATE.format(security_id=security_id, year=year)
    request = urllib.request.Request(
        url,
        headers={
            "Referer": "https://q.10jqka.com.cn/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
    )
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            last_error = exc
        except Exception as exc:
            last_error = exc
        time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"{security_id} {year} 请求失败：{last_error}")


def fetch_code_range(
    security_id: str,
    start_date: date,
    end_date: date,
    *,
    timeout: float = 20.0,
    retries: int = 3,
) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    for year in range(start_date.year, end_date.year + 1):
        text = _request_year(security_id, year, timeout, retries)
        if not text:
            continue
        frame = parse_year_jsonp(text, security_id)
        if not frame.is_empty():
            frames.append(frame)
    if not frames:
        return _empty_daily_frame()
    start_dt = datetime.combine(start_date, dt_time.min)
    end_dt = datetime.combine(end_date, dt_time.max)
    return _normalize_daily_frame(pl.concat(frames, how="vertical_relaxed").filter(
        pl.col("time").is_between(start_dt, end_dt, closed="both")
    ))


def purge_existing_ths_rows(base_dir: str | Path) -> dict[str, int]:
    root = Path(base_dir).resolve()
    removed_rows = 0
    touched_partitions = 0
    for merged_path in sorted(root.glob("year=*/month=*/merged.parquet")):
        before = pl.read_parquet(merged_path)
        if "htsc_code" not in before.columns:
            continue
        after = before.filter(~pl.col("htsc_code").cast(pl.String).str.to_uppercase().str.ends_with(".THS"))
        removed = len(before) - len(after)
        if removed <= 0:
            continue
        temp_path = merged_path.parent / f"merged.parquet.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        after.write_parquet(temp_path, compression="zstd")
        _atomic_replace_with_retry(temp_path, merged_path)
        removed_rows += removed
        touched_partitions += 1
    return {"removed_rows": removed_rows, "touched_partitions": touched_partitions}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同花顺软件一级512指数日线增量下载")
    parser.add_argument("--base-dir", default=BASE_DIR, help="目标 index_data_daily 根目录")
    parser.add_argument("--stockname-file", default=str(STOCKNAME_FILE), help="同花顺 stockname_48_0.txt")
    parser.add_argument("--default-start", default=DEFAULT_START_DATE, help="无本地数据时的起点 YYYY-MM-DD")
    parser.add_argument("--end", default="", help="显式截止日 YYYY-MM-DD；默认按15:30边界")
    parser.add_argument("--codes", nargs="*", default=None, help="可选六位同花顺指数代码，用于补跑/验证")
    parser.add_argument("--workers", type=int, default=10, help="指数并行数")
    parser.add_argument("--timeout", type=float, default=20.0, help="单次HTTP超时秒数")
    parser.add_argument("--retries", type=int, default=3, help="单年度请求重试次数")
    parser.add_argument("--dry-run", action="store_true", help="只输出增量计划")
    parser.add_argument("--purge-existing", action="store_true", help="只清除目标仓中 .THS 指数行")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_dir = Path(args.base_dir)
    if args.purge_existing:
        result = purge_existing_ths_rows(base_dir)
        print(f"定向清理完成：移除 {result['removed_rows']} 行，重写 {result['touched_partitions']} 个月分区")
        return

    all_indices = load_level1_indices(args.stockname_file)
    indices = all_indices
    if args.codes:
        requested = {str(code).strip().upper().removesuffix(".THS") for code in args.codes}
        indices = [row for row in indices if row["security_id"] in requested]
        missing = requested - {row["security_id"] for row in indices}
        if missing:
            raise ValueError(f"指定代码不属于同花顺软件一级：{sorted(missing)}")

    default_start = datetime.strptime(args.default_start, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else resolve_completed_end_date()
    if default_start > end_date:
        raise ValueError(f"default-start 晚于截止日：{default_start} > {end_date}")
    latest_map = scan_latest_downloaded_times(base_dir)
    plans = []
    for row in indices:
        start_date = resolve_fetch_start(latest_map.get(row["htsc_code"]), default_start)
        if start_date <= end_date:
            plans.append((row, start_date, end_date))

    print(f"同花顺软件一级指数：{len(indices)} 个")
    print(f"需要请求：{len(plans)} 个 | 截止日：{end_date} | workers={max(1, args.workers)}")
    if args.dry_run:
        for row, start_date, plan_end in plans[:20]:
            print(f"- {row['htsc_code']} {row['index_name']}: {start_date} ~ {plan_end}")
        if len(plans) > 20:
            print(f"... 其余 {len(plans) - 20} 个")
        return

    universe_path = write_level1_universe(all_indices, base_dir)
    print(f"指数名称元数据：{universe_path}")

    frames: list[pl.DataFrame] = []
    failures: list[tuple[str, str]] = []
    workers = min(max(1, int(args.workers)), max(1, len(plans)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                fetch_code_range,
                row["security_id"],
                start_date,
                plan_end,
                timeout=max(1.0, float(args.timeout)),
                retries=max(1, int(args.retries)),
            ): row
            for row, start_date, plan_end in plans
        }
        for number, future in enumerate(as_completed(futures), start=1):
            row = futures[future]
            try:
                frame = future.result()
                if not frame.is_empty():
                    frames.append(frame)
            except Exception as exc:
                failures.append((row["htsc_code"], str(exc)))
            if number % 25 == 0 or number == len(futures):
                print(f"下载进度：{number}/{len(futures)} | 失败：{len(failures)}")

    if frames:
        combined = _normalize_daily_frame(pl.concat(frames, how="vertical_relaxed", rechunk=True))
        rebuilt = save_partitioned_parquet(combined, base_dir)
        print(f"写入记录：{len(combined)} | 重建月份：{len(rebuilt)}")
    else:
        print("本次没有新增或修订记录")

    if failures:
        meta_dir = base_dir / "_meta"
        meta_dir.mkdir(parents=True, exist_ok=True)
        failure_path = meta_dir / f"ths_level1_failed_{datetime.now():%Y%m%d_%H%M%S}.txt"
        failure_path.write_text(
            "\n".join(f"{code}\t{error}" for code, error in failures) + "\n",
            encoding="utf-8-sig",
        )
        print(f"失败代码：{len(failures)}，详情：{failure_path}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
