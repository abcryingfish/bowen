#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""提取同花顺板块及成分股，并更新板块日线和板块研究快照。

板块研究直接使用本次从同花顺本地文件解析出的内存数据；CSV 仅作为最新
导出结果，每次运行覆盖，不作为研究和成分快照的数据源。
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import polars as pl
from pypinyin import Style, lazy_pinyin


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from sector_type_adapter import classify_sector, semantic_publish_decision


INDEX_BASE_DIR = Path(r"D:\database\index_data_daily")
SECTOR_BASE_DIR = Path(r"D:\database\sector_information")
THS_ROOT = Path(r"D:\同花顺\同花顺")
EXPORT_DIR = PROJECT_ROOT / "temp" / "同花顺软件板块导出"
STOCKNAME_FILE = THS_ROOT / "stockname" / "stockname_48_0.txt"
SECONDARY_EXPORT = EXPORT_DIR / "Table.xlsx"
AUDIT_PATH = PROJECT_ROOT / "temp" / "ths512_full_audit" / "sector_audit.parquet"
VALUATION_GLOB = r"D:\database\qmt_company_data\table=factor_fundamental_valuation\year=*\month=*\merged.parquet"
DEFAULT_START_DATE = "2010-01-01"
LEVEL1_PREFIX_COUNTS = {"881": 90, "882": 33, "885": 293, "886": 96}
LEVEL_FILES = {
    "同花顺软件一级": "同花顺软件一级板块.csv",
    "同花顺软件二级": "同花顺软件二级板块.csv",
}
CONSTITUENT_FILE = "同花顺软件板块成分股.csv"
OUTPUT_COLUMNS = [
    "htsc_code", "time", "exchange", "security_type", "security_id", "frequency",
    "open", "close", "high", "low", "volume", "value",
]
API_TEMPLATE = "https://d.10jqka.com.cn/v6/line/48_{security_id}/01/{year}.js"


def read_ths_text(path: str | Path) -> str:
    return Path(path).read_bytes().decode("gb18030")


def load_index_names(stockname_file: str | Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    code_to_name: dict[str, str] = {}
    name_to_codes: dict[str, list[str]] = defaultdict(list)
    for line in read_ths_text(stockname_file).splitlines():
        if "=" not in line:
            continue
        code, name = line.split("=", 1)
        code, name = code.strip(), name.strip()
        if re.fullmatch(r"\d{6}", code) and name:
            code_to_name[code] = name
            name_to_codes[name].append(code)
    return code_to_name, name_to_codes


def load_secondary_codes(
    secondary_export: str | Path,
    name_to_codes: dict[str, list[str]],
) -> list[str]:
    # 同花顺导出的 xlsx 实际是 GB18030 编码、TAB 分隔、CR 换行的文本。
    text = read_ths_text(secondary_export)
    rows = [row for row in re.split(r"\r\n|\r|\n", text) if row]
    names = [row.split("\t", 1)[0].strip() for row in rows[1:]]
    codes: list[str] = []
    for name in names:
        matches = [code for code in name_to_codes.get(name, []) if code.startswith("884")]
        if len(matches) != 1:
            raise ValueError(f"软件二级名称无法唯一映射到 884 指数：{name!r} -> {matches}")
        codes.append(matches[0])
    if len(codes) != 230 or len(set(codes)) != 230:
        raise ValueError(f"软件二级客户端导出应为 230 个唯一板块，实际为 {len(codes)}")
    return codes


def parse_block_library(ths_root: str | Path) -> tuple[dict[str, set[str]], dict[str, list[tuple[int, str]]]]:
    root = Path(ths_root)
    block_names: dict[str, set[str]] = defaultdict(set)
    block_members: dict[str, list[tuple[int, str]]] = defaultdict(list)
    name_sections = {"BLOCK_NAME_MAP_TABLE", "SUBDIVISION_BLOCK_NAME_MAP_TABLE"}
    for path in sorted((root / "BlockUpdate").glob("block_*.ini")):
        section = ""
        for raw_line in read_ths_text(path).splitlines():
            line = raw_line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if section in name_sections and key and value:
                block_names[value].add(key)
            elif section in {"BLOCK_STOCK_CONTEXT", "SUBDIVISION_BLOCK_STOCK_CONTEXT"} and key and value:
                members = [(int(market), code) for market, code in re.findall(r"(-?\d+):(\d{6})", value)]
                if len(members) > len(block_members[key]):
                    block_members[key] = members
    return block_names, block_members


def inferred_market_id(code: str) -> int:
    if code.startswith("6"):
        return 17
    if code.startswith(("0", "1", "2", "3")):
        return 33
    if code.startswith(("4", "8", "9")):
        return -105
    return 0


def load_industry_members(ths_root: str | Path) -> dict[str, list[tuple[int, str]]]:
    members: dict[str, list[tuple[int, str]]] = {}
    for line in read_ths_text(Path(ths_root) / "industry.ini").splitlines():
        if "=" not in line:
            continue
        index_code, value = line.split("=", 1)
        index_code = index_code.strip()
        if not index_code.startswith("881"):
            continue
        codes = re.findall(r"\d{6}", value)
        parsed = [(inferred_market_id(code), code) for code in codes]
        # 文件后半部会再次出现同一指数的空配置，保留实际成分更完整的一组。
        if len(parsed) > len(members.get(index_code, [])):
            members[index_code] = parsed
    return members


def fetch_jsonp(url: str, retries: int = 3) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Referer": "https://q.10jqka.com.cn/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
    )
    error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                text = response.read().decode("utf-8")
            return json.loads(text[text.index("{") : text.rindex("}") + 1])
        except Exception as exc:
            error = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(str(error))


def fetch_history(index_code: str) -> dict[str, object]:
    base = f"https://d.10jqka.com.cn/v6/line/48_{index_code}/01"
    all_url = f"{base}/all.js"
    try:
        all_data = fetch_jsonp(all_url)
        today_data = fetch_jsonp(f"{base}/today.js")
        today_record = today_data.get(f"48_{index_code}", {})
        start = str(all_data.get("start", ""))
        end = str(today_record.get("1", ""))
        total = int(all_data.get("total", 0) or 0)
        if not re.fullmatch(r"\d{8}", end):
            last_data = fetch_jsonp(f"{base}/last.js")
            records = str(last_data.get("data", "")).split(";")
            end = records[-1].split(",", 1)[0] if records and records[-1] else ""
        years: object = ""
        if re.fullmatch(r"\d{8}", start) and re.fullmatch(r"\d{8}", end):
            start_date = datetime.strptime(start, "%Y%m%d")
            end_date = datetime.strptime(end, "%Y%m%d")
            years = round((end_date - start_date).days / 365.2425, 2)
            start = start_date.strftime("%Y-%m-%d")
            end = end_date.strftime("%Y-%m-%d")
        return {
            "history_start_date": start,
            "history_end_date": end,
            "history_trading_days": total,
            "history_years": years,
            "history_source_url": all_url,
            "history_fetch_status": "成功",
        }
    except Exception as exc:
        return {
            "history_start_date": "",
            "history_end_date": "",
            "history_trading_days": "",
            "history_years": "",
            "history_source_url": all_url,
            "history_fetch_status": f"失败：{type(exc).__name__}: {exc}",
        }


def load_history_cache(output_dir: str | Path) -> dict[str, dict[str, object]]:
    cache: dict[str, dict[str, object]] = {}
    fields = {
        "history_start_date", "history_end_date", "history_trading_days", "history_years",
        "history_source_url", "history_fetch_status",
    }
    root = Path(output_dir)
    for filename in LEVEL_FILES.values():
        path = root / filename
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("history_fetch_status") == "成功":
                    cache[row["指数代码"]] = {field: row.get(field, "") for field in fields}
    return cache


def stock_suffix(market_id: int, code: str) -> str:
    if market_id == -105 or code.startswith(("4", "8", "9")):
        return "BJ"
    if market_id in {17, 22} or code.startswith("6"):
        return "SH"
    if market_id in {33, 37} or code.startswith(("0", "1", "2", "3")):
        return "SZ"
    return "UNKNOWN"


def choose_block(
    name: str,
    block_names: dict[str, set[str]],
    block_members: dict[str, list[tuple[int, str]]],
) -> tuple[str, list[tuple[int, str]], str]:
    candidates = sorted(block_names.get(name, set()))
    with_members = [block_id for block_id in candidates if block_members.get(block_id)]
    if not with_members:
        status = "未找到同名成分块" if not candidates else "找到名称但无成分股"
        return "", [], status
    selected = max(with_members, key=lambda block_id: len(block_members[block_id]))
    status = "精确名称匹配"
    if len(with_members) > 1:
        status = f"精确名称匹配；{len(with_members)}个候选中选成分最多者"
    return selected, block_members[selected], status


def _atomic_write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        _atomic_replace_with_retry(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def extract_ths_sector_data(
    *,
    ths_root: str | Path = THS_ROOT,
    output_dir: str | Path = EXPORT_DIR,
    secondary_export: str | Path = SECONDARY_EXPORT,
    history_workers: int = 10,
) -> dict[str, object]:
    root = Path(ths_root)
    stockname_file = root / "stockname" / "stockname_48_0.txt"
    code_to_name, name_to_codes = load_index_names(stockname_file)
    levels = {
        "同花顺软件一级": sorted(
            code for code in code_to_name if code.startswith(tuple(LEVEL1_PREFIX_COUNTS))
        ),
        "同花顺软件二级": load_secondary_codes(secondary_export, name_to_codes),
    }
    if len(levels["同花顺软件一级"]) != 512:
        raise ValueError(f"软件一级应为 512 个板块，实际为 {len(levels['同花顺软件一级'])}")

    block_names, block_members = parse_block_library(root)
    industry_members = load_industry_members(root)
    all_codes = [code for codes in levels.values() for code in codes]
    history = load_history_cache(output_dir)
    pending_codes = [code for code in all_codes if code not in history]
    workers = min(max(1, int(history_workers)), max(1, len(pending_codes)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_history, code): code for code in pending_codes}
        for number, future in enumerate(as_completed(futures), start=1):
            code = futures[future]
            history[code] = future.result()
            if number % 50 == 0 or number == len(futures):
                print(f"历史覆盖进度：{number}/{len(futures)}", flush=True)

    snapshot_now = datetime.now().astimezone()
    snapshot_time = snapshot_now.isoformat(timespec="seconds")
    level_rows: dict[str, list[dict[str, object]]] = defaultdict(list)
    constituent_rows: list[dict[str, object]] = []
    for level, codes in levels.items():
        for code in codes:
            name = code_to_name[code]
            constituent_source = str(root / "BlockUpdate")
            if code.startswith("881") and industry_members.get(code):
                block_id, members, mapping_status = code, industry_members[code], "指数代码直接匹配"
                constituent_source = str(root / "industry.ini")
            else:
                block_id, members, mapping_status = choose_block(name, block_names, block_members)
            level_rows[level].append(
                {
                    "软件级别": level,
                    "指数代码": code,
                    "板块名称": name,
                    "指数前缀": code[:3],
                    "成分股数量": len(members),
                    "成分块ID": block_id,
                    "成分映射状态": mapping_status,
                    "成分来源": constituent_source,
                    "数据快照时间": snapshot_time,
                    "板块来源": str(stockname_file),
                    **history[code],
                }
            )
            if not members:
                constituent_rows.append(
                    {
                        "软件级别": level,
                        "指数代码": code,
                        "板块名称": name,
                        "成分块ID": block_id,
                        "股票代码": "",
                        "市场": "",
                        "本地市场ID": "",
                        "成分排序": "",
                        "成分映射状态": mapping_status,
                        "数据快照时间": snapshot_time,
                        "来源": constituent_source,
                    }
                )
                continue
            for rank, (market_id, stock_code) in enumerate(members, start=1):
                market = stock_suffix(market_id, stock_code)
                constituent_rows.append(
                    {
                        "软件级别": level,
                        "指数代码": code,
                        "板块名称": name,
                        "成分块ID": block_id,
                        "股票代码": f"{stock_code}.{market}" if market != "UNKNOWN" else stock_code,
                        "市场": market,
                        "本地市场ID": market_id,
                        "成分排序": rank,
                        "成分映射状态": mapping_status,
                        "数据快照时间": snapshot_time,
                        "来源": constituent_source,
                    }
                )

    level1_indices = [
        {
            "security_id": str(row["指数代码"]),
            "htsc_code": f"{row['指数代码']}.THS",
            "index_name": str(row["板块名称"]),
            "index_prefix": str(row["指数代码"])[:3],
        }
        for row in level_rows["同花顺软件一级"]
    ]
    return {
        "level_rows": dict(level_rows),
        "constituent_rows": constituent_rows,
        "level1_indices": level1_indices,
        "snapshot_date": snapshot_now.date().isoformat(),
    }


def write_sector_exports(result: dict[str, object], output_dir: str | Path = EXPORT_DIR) -> None:
    level_fields = [
        "软件级别", "指数代码", "板块名称", "指数前缀", "成分股数量", "成分块ID", "成分映射状态", "成分来源",
        "history_start_date", "history_end_date", "history_trading_days", "history_years",
        "history_source_url", "history_fetch_status", "数据快照时间", "板块来源",
    ]
    constituent_fields = [
        "软件级别", "指数代码", "板块名称", "成分块ID", "股票代码", "市场", "本地市场ID",
        "成分排序", "成分映射状态", "数据快照时间", "来源",
    ]
    root = Path(output_dir)
    level_rows = result["level_rows"]
    for level, filename in LEVEL_FILES.items():
        _atomic_write_csv(root / filename, level_rows[level], level_fields)
    _atomic_write_csv(root / CONSTITUENT_FILE, result["constituent_rows"], constituent_fields)
    for level, rows in level_rows.items():
        success = sum(row["history_fetch_status"] == "成功" for row in rows)
        mapped = sum(bool(row["成分股数量"]) for row in rows)
        print(f"{level}：{len(rows)} 个；历史成功 {success}；成分映射成功 {mapped}")
    print(f"成分股长表：{len(result['constituent_rows'])} 行")


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


def score_high(value: float, low: float, high: float) -> float:
    if pd.isna(value):
        return np.nan
    return float(np.clip((value - low) / (high - low) * 10, 0, 10))


def score_low(value: float, low: float, high: float) -> float:
    if pd.isna(value):
        return np.nan
    return float(np.clip((high - value) / (high - low) * 10, 0, 10))


def dimension_scores(row: pd.Series) -> dict[str, float]:
    technical_parts = [
        score_high(row.get("return_20d_pct"), -15, 15),
        score_high(row.get("close_vs_ma20_pct"), -10, 10),
        score_high(row.get("close_vs_ma60_pct"), -20, 20),
        score_high(row.get("positive_return_20d_pct"), 0, 100),
    ]
    risk_pressure = [
        score_high(abs(row.get("max_drawdown_60d_pct")), 0, 35),
        score_high(row.get("volatility_20d_annualized_pct"), 10, 60),
        score_high(row.get("max_stock_sector_memberships"), 5, 100),
    ]
    capital_parts = [
        score_high(row.get("market_coverage_pct"), 80, 100),
        score_high(row.get("volume_5d_vs_20d_pct"), -30, 30),
        score_high(row.get("positive_return_20d_pct"), 0, 100),
    ]
    valuation_parts = [
        score_low(row.get("median_positive_pe_ttm"), 5, 100),
        score_low(row.get("median_pb"), 0.5, 10),
        score_low(row.get("loss_or_invalid_pe_pct"), 0, 60),
    ]
    fundamental_parts = [
        score_high(row.get("median_revenue_yoy_pct"), -20, 30),
        score_high(row.get("median_profit_yoy_pct"), -50, 50),
        score_high(row.get("median_roe_pct"), 0, 20),
        score_high(row.get("median_net_margin_pct"), -10, 20),
        score_high(row.get("profitable_member_pct"), 20, 100),
    ]

    def mean(values: list[float]) -> float:
        valid = [value for value in values if not pd.isna(value)]
        return float(np.mean(valid)) if valid else np.nan

    technical = mean(technical_parts)
    pressure = mean(risk_pressure)
    return {
        "technical": technical,
        "risk": 10 - pressure if not pd.isna(pressure) else np.nan,
        "capital": mean(capital_parts),
        "valuation": mean(valuation_parts),
        "fundamental": mean(fundamental_parts),
        "policy": row.get("policy_score", np.nan),
    }


def load_fundamental_features(members: pd.DataFrame, analysis_date: str) -> pd.DataFrame:
    cutoff = pd.Timestamp(analysis_date).date()
    valuation_paths = sorted(glob.glob(VALUATION_GLOB))
    if not valuation_paths:
        raise FileNotFoundError(f"未找到财务估值数据：{VALUATION_GLOB}")
    valuation_schema = pl.read_parquet_schema(valuation_paths[-1])
    reports = (
        pl.scan_parquet(valuation_paths, schema=valuation_schema)
        .select(
            "htsc_code",
            pl.col("income_report_date").cast(pl.Date, strict=False).alias("report_date"),
            pl.col("income_announce_date").cast(pl.Date, strict=False).alias("announce_date"),
            pl.col("time").cast(pl.Date, strict=False).alias("observation_date"),
            "revenue_ttm", "net_profit_parent_ttm", "roe", "net_roe",
        )
        .filter(
            pl.col("report_date").is_not_null()
            & pl.col("announce_date").is_not_null()
            & (pl.col("announce_date") <= cutoff)
        )
        .collect()
        .sort("observation_date")
        .unique(["htsc_code", "report_date"], keep="last")
    )
    current = reports.sort("report_date").unique("htsc_code", keep="last")
    previous = reports.select(
        "htsc_code",
        pl.col("report_date").dt.offset_by("1y").alias("report_date"),
        pl.col("revenue_ttm").alias("previous_revenue_ttm"),
        pl.col("net_profit_parent_ttm").alias("previous_profit_ttm"),
    )
    stock = (
        current.join(previous, on=["htsc_code", "report_date"], how="left")
        .with_columns(
            pl.when(pl.col("previous_revenue_ttm") > 0)
            .then((pl.col("revenue_ttm") / pl.col("previous_revenue_ttm") - 1) * 100)
            .alias("revenue_yoy_pct"),
            pl.when(pl.col("previous_profit_ttm") > 0)
            .then((pl.col("net_profit_parent_ttm") / pl.col("previous_profit_ttm") - 1) * 100)
            .alias("profit_yoy_pct"),
            pl.when(pl.col("revenue_ttm") != 0)
            .then(pl.col("net_profit_parent_ttm") / pl.col("revenue_ttm") * 100)
            .alias("net_margin_pct"),
            pl.coalesce("net_roe", "roe").alias("roe_pct"),
        )
        .to_pandas()
    )
    member_map = members[["指数代码", "股票代码"]].rename(
        columns={"指数代码": "sector_id", "股票代码": "htsc_code"}
    )
    joined = member_map.merge(stock, on="htsc_code", how="left")
    joined["profitable"] = np.where(
        joined["net_profit_parent_ttm"].notna(),
        (joined["net_profit_parent_ttm"] > 0) * 100.0,
        np.nan,
    )
    return joined.groupby("sector_id", as_index=False).agg(
        median_revenue_yoy_pct=("revenue_yoy_pct", "median"),
        median_profit_yoy_pct=("profit_yoy_pct", "median"),
        median_roe_pct=("roe_pct", "median"),
        median_net_margin_pct=("net_margin_pct", "median"),
        profitable_member_pct=("profitable", "mean"),
        fundamental_covered_members=("net_profit_parent_ttm", "count"),
        revenue_yoy_covered_members=("revenue_yoy_pct", "count"),
        profit_yoy_covered_members=("profit_yoy_pct", "count"),
    )


def load_policy_features(base: Path) -> pd.DataFrame:
    path = base / "current" / "evidence.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["sector_code", "policy_score", "policy_evidence_count"])
    all_evidence = pl.read_parquet(path).filter(pl.col("entity_id").is_not_null())
    direct = (
        all_evidence.group_by("entity_id")
        .agg(
            pl.len().alias("classification_evidence_count"),
            pl.col("content_hash").first().alias("classification_evidence_id"),
        )
        .rename({"entity_id": "sector_code"})
        .to_pandas()
    )
    evidence = all_evidence.filter(pl.col("evidence_type") == "policy").to_pandas()
    positive = ("支持", "推动", "鼓励", "规划", "补贴", "加快", "促进", "获批", "落地", "利好", "扩大", "振兴")
    negative = ("限制", "禁止", "收紧", "处罚", "退坡", "下调", "风险", "整治", "取消", "暂停")
    values: list[dict[str, object]] = []
    for _, row in evidence.iterrows():
        text = f"{row.get('title') or ''} {row.get('summary') or ''}"
        pos = sum(word in text for word in positive)
        neg = sum(word in text for word in negative)
        if pos == neg:
            continue
        values.append(
            {
                "sector_code": row["entity_id"],
                "signal": 1.0 if pos > neg else -1.0,
                "source": row.get("source"),
            }
        )
    if not values:
        return direct.assign(policy_score=np.nan, policy_evidence_count=np.nan)
    frame = pd.DataFrame(values).drop_duplicates(["sector_code", "source", "signal"])
    grouped = (
        frame.groupby("sector_code")
        .agg(policy_signal=("signal", "mean"), policy_evidence_count=("signal", "size"))
        .reset_index()
    )
    grouped["policy_score"] = (5 + 3 * grouped["policy_signal"]).clip(0, 10)
    return direct.merge(grouped, on="sector_code", how="left")


def write_partition(df: pd.DataFrame, root: Path, name: str, date_value: str) -> Path:
    out = root / name / f"analysis_date={date_value}" / "part-000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out.parent / f"{out.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    pl.from_pandas(df).write_parquet(temp_path, compression="zstd")
    _atomic_replace_with_retry(temp_path, out)
    return out


def run_sector_research(
    *,
    sectors: pd.DataFrame,
    members: pd.DataFrame,
    base_dir: str | Path = SECTOR_BASE_DIR,
    audit_path: str | Path = AUDIT_PATH,
    analysis_date: str | None = None,
    constituent_snapshot_date: str | None = None,
) -> None:
    required_sector_columns = {"软件级别", "指数代码", "板块名称"}
    required_member_columns = {"软件级别", "指数代码", "板块名称", "股票代码", "市场"}
    if missing := required_sector_columns - set(sectors.columns):
        raise ValueError(f"板块数据缺少字段：{sorted(missing)}")
    if missing := required_member_columns - set(members.columns):
        raise ValueError(f"成分股数据缺少字段：{sorted(missing)}")

    base = Path(base_dir)
    audit = pl.read_parquet(audit_path).to_pandas()
    members = members[members["软件级别"].eq("同花顺软件一级")].copy()
    raw_date = analysis_date or str(audit["local_end_date"].max())
    resolved_date = pd.Timestamp(raw_date).strftime("%Y-%m-%d")
    resolved_snapshot_date = pd.Timestamp(
        constituent_snapshot_date or datetime.now().date()
    ).strftime("%Y-%m-%d")
    run_id = f"run_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"

    fundamentals = load_fundamental_features(members, resolved_date)
    fundamentals["sector_code"] = fundamentals["sector_id"].astype(str).str.zfill(6) + ".THS"
    audit = audit.merge(fundamentals.drop(columns=["sector_id"]), on="sector_code", how="left")
    policies = load_policy_features(base)
    audit = audit.merge(policies, on="sector_code", how="left")

    rows: list[dict[str, object]] = []
    dim_rows: list[dict[str, object]] = []
    for _, audit_row in audit.iterrows():
        code = str(audit_row["sector_code"])
        sector_name = str(audit_row["sector_name"])
        members_one = members[members["指数代码"].astype(str).str.zfill(6).eq(code[:6])]
        classification_evidence = []
        if not pd.isna(audit_row.get("classification_evidence_id")):
            classification_evidence = [
                {
                    "evidence_id": str(audit_row["classification_evidence_id"]),
                    "kind": "direct",
                    "source": "东方财富公开检索",
                }
            ]
        result = classify_sector(
            code,
            sector_name,
            members_one["股票代码"].tolist(),
            evidence=classification_evidence,
        )
        scores = dimension_scores(audit_row)
        decision = semantic_publish_decision(result)
        required = ("fundamental", "technical", "risk")
        required_valid = all(not pd.isna(scores[name]) for name in required)
        available = {
            key: value
            for key, value in scores.items()
            if not pd.isna(value)
            and (decision.publish_semantic_dimensions or key not in {"policy", "fundamental", "valuation"})
        }
        weights = {"policy": .20, "fundamental": .25, "capital": .15, "technical": .15, "valuation": .15, "risk": .10}
        usable_weight = sum(weights[key] for key in available)
        overall = (
            float(sum(available[key] * weights[key] for key in available) / usable_weight)
            if required_valid and usable_weight >= .80
            else np.nan
        )
        status = "needs_review" if result.review_required else (
            "ready" if required_valid and usable_weight >= .80 else "blocked"
        )
        rows.append(
            {
                "run_id": run_id,
                "analysis_date": resolved_date,
                "sector_code": code,
                "sector_name": sector_name,
                "analysis_archetype": result.analysis_archetype,
                "analysis_archetype_version": result.type_version,
                "classification_facets_json": json.dumps(result.facets, ensure_ascii=False),
                "classification_confidence": result.classification_confidence,
                "review_required": result.review_required,
                "status": status,
                "overall_score": overall,
                "source_member_count": audit_row["source_member_count"],
                "excluded_bj_count": audit_row["excluded_bj_count"],
                "eligible_member_count": audit_row["eligible_member_count"],
                "market_coverage_pct": audit_row["market_coverage_pct"],
                "valuation_coverage_pct": audit_row["valuation_coverage_pct"],
                "state_regime": audit_row["state_regime"],
                "data_freshness_days": audit_row["data_freshness_days"],
            }
        )
        for dimension, score in scores.items():
            dim_rows.append(
                {
                    "run_id": run_id,
                    "analysis_date": resolved_date,
                    "sector_code": code,
                    "dimension_name": dimension,
                    "score": score,
                    "published": decision.publish_semantic_dimensions or dimension in {"technical", "capital", "risk"},
                    "status": status,
                }
            )

    result_df = pd.DataFrame(rows)
    dim_df = pd.DataFrame(dim_rows)
    write_partition(result_df, base, "assessments", resolved_date)
    write_partition(dim_df, base, "dimension_scores", resolved_date)
    write_partition(audit, base, "market_features", resolved_date)
    member_df = members.rename(
        columns={
            "指数代码": "sector_code",
            "板块名称": "sector_name",
            "股票代码": "stock_code",
            "市场": "exchange",
        }
    ).copy()
    member_df["sector_code"] = member_df["sector_code"].astype(str).str.zfill(6) + ".THS"
    member_df["snapshot_id"] = f"snapshot_{resolved_snapshot_date.replace('-', '')}_{run_id[-8:]}"
    member_df["analysis_date"] = resolved_snapshot_date
    member_df["eligible"] = ~member_df["stock_code"].astype(str).str.upper().str.endswith(".BJ")
    member_df["exclusion_reason"] = np.where(member_df["eligible"], None, "北交所强制排除")
    write_partition(member_df, base, "constituent_snapshots_raw", resolved_snapshot_date)
    write_partition(
        member_df[member_df["eligible"]].copy(),
        base,
        "constituent_snapshots_eligible",
        resolved_snapshot_date,
    )
    manifest = pd.DataFrame(
        [
            {
                "run_id": run_id,
                "analysis_date": resolved_date,
                "sector_count": len(result_df),
                "ready_count": int((result_df.status == "ready").sum()),
                "needs_review_count": int((result_df.status == "needs_review").sum()),
                "blocked_count": int((result_df.status == "blocked").sum()),
            }
        ]
    )
    write_partition(manifest, base, "run_manifest", resolved_date)
    current = base / "current"
    current.mkdir(parents=True, exist_ok=True)
    pl.from_pandas(result_df).write_parquet(current / "assessments.parquet", compression="zstd")
    pl.from_pandas(dim_df).write_parquet(current / "dimension_scores.parquet", compression="zstd")
    print(json.dumps(manifest.iloc[0].to_dict(), ensure_ascii=False, indent=2))


def run_level1_daily_update(args: argparse.Namespace, indices: list[dict[str, str]]) -> None:
    base_dir = Path(args.index_base_dir)
    all_indices = indices
    requested_indices = all_indices
    if args.codes:
        requested = {str(code).strip().upper().removesuffix(".THS") for code in args.codes}
        requested_indices = [row for row in all_indices if row["security_id"] in requested]
        missing = requested - {row["security_id"] for row in requested_indices}
        if missing:
            raise ValueError(f"指定代码不属于同花顺软件一级：{sorted(missing)}")

    default_start = datetime.strptime(args.default_start, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else resolve_completed_end_date()
    if default_start > end_date:
        raise ValueError(f"default-start 晚于截止日：{default_start} > {end_date}")
    latest_map = scan_latest_downloaded_times(base_dir)
    plans = []
    for row in requested_indices:
        start_date = resolve_fetch_start(latest_map.get(row["htsc_code"]), default_start)
        if start_date <= end_date:
            plans.append((row, start_date, end_date))

    print(f"同花顺软件一级指数：{len(requested_indices)} 个")
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


def run_pipeline(args: argparse.Namespace) -> None:
    extracted = extract_ths_sector_data(
        ths_root=args.ths_root,
        output_dir=args.output_dir,
        secondary_export=args.secondary_export,
        history_workers=args.history_workers,
    )
    if not getattr(args, "dry_run", False):
        write_sector_exports(extracted, args.output_dir)

    run_level1_daily_update(args, extracted["level1_indices"])
    if getattr(args, "dry_run", False):
        print("dry-run：跳过 CSV 覆盖和板块研究入库")
        return

    level_rows = extracted["level_rows"]
    sectors = pd.DataFrame(level_rows["同花顺软件一级"])
    members = pd.DataFrame(extracted["constituent_rows"])
    run_sector_research(
        sectors=sectors,
        members=members,
        base_dir=args.sector_base_dir,
        audit_path=args.audit_path,
        analysis_date=args.analysis_date,
        constituent_snapshot_date=extracted["snapshot_date"],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从同花顺本地文件提取板块和成分股，并更新一级板块日线及研究快照"
    )
    parser.add_argument("--ths-root", default=str(THS_ROOT), help="同花顺安装数据根目录")
    parser.add_argument("--output-dir", default=str(EXPORT_DIR), help="最新板块和成分股 CSV 输出目录")
    parser.add_argument("--secondary-export", default=str(SECONDARY_EXPORT), help="同花顺软件二级板块导出文件")
    parser.add_argument("--history-workers", type=int, default=10, help="板块历史覆盖信息并行数")
    parser.add_argument(
        "--index-base-dir", "--base-dir",
        dest="index_base_dir",
        default=str(INDEX_BASE_DIR),
        help="板块日线 index_data_daily 根目录",
    )
    parser.add_argument("--sector-base-dir", default=str(SECTOR_BASE_DIR), help="板块研究和成分快照根目录")
    parser.add_argument("--audit-path", default=str(AUDIT_PATH), help="板块市场审计数据")
    parser.add_argument("--analysis-date", default=None, help="成分快照日期；默认采用审计数据最新日期")
    parser.add_argument("--default-start", default=DEFAULT_START_DATE, help="无本地日线时的起点 YYYY-MM-DD")
    parser.add_argument("--end", default="", help="板块日线截止日 YYYY-MM-DD；默认按15:30边界")
    parser.add_argument("--codes", nargs="*", default=None, help="可选六位同花顺一级指数代码，用于补跑/验证")
    parser.add_argument("--workers", type=int, default=10, help="板块日线下载并行数")
    parser.add_argument("--timeout", type=float, default=20.0, help="单次HTTP超时秒数")
    parser.add_argument("--retries", type=int, default=3, help="单年度请求重试次数")
    parser.add_argument("--dry-run", action="store_true", help="只输出日线增量计划，不覆盖 CSV 或运行研究")
    parser.add_argument("--purge-existing", action="store_true", help="只清除日线仓中的 .THS 指数行")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.purge_existing:
        result = purge_existing_ths_rows(args.index_base_dir)
        print(f"定向清理完成：移除 {result['removed_rows']} 行，重写 {result['touched_partitions']} 个月分区")
        return
    run_pipeline(args)


if __name__ == "__main__":
    main()
