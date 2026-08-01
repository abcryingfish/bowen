#!/usr/bin/python3
# -*- coding: utf-8 -*-
r"""同花顺软件一级板块 1 分钟 K 线全量与增量下载。

标的每次从同花顺客户端 ``stockname_48_0.txt`` 动态读取，只包含
881/882/885/886 四类软件一级板块。行情按代码、自然月请求，写入
``D:\database\index_data_mins\year=YYYY\month=MM\day=DD\merged.parquet``。
完成状态保存为 Parquet，用于无 SQLite 的断点续跑。
"""
from __future__ import annotations

import argparse
import calendar
import os
import sys
import time
import errno
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Iterable

import duckdb
import polars as pl
from pypinyin import Style, lazy_pinyin


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


BASE_DIR = Path(r"D:\database\index_data_mins")
THS_ROOT = Path(r"D:\同花顺\同花顺")
STOCKNAME_FILE = THS_ROOT / "stockname" / "stockname_48_0.txt"
SOFTWARE_LEVEL1_PREFIXES = ("881", "882", "885", "886")
DEFAULT_START_DATE = "2010-01-01"
MERGED_FILE_NAME = "merged.parquet"

OUTPUT_COLUMNS = [
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
OUTPUT_SCHEMA = {
    "htsc_code": pl.String,
    "time": pl.Datetime("us"),
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
STATE_SCHEMA = {
    "htsc_code": pl.String,
    "year_month": pl.String,
    "status": pl.String,
    "row_count": pl.Int64,
    "first_time": pl.Datetime("us"),
    "last_time": pl.Datetime("us"),
    "updated_at": pl.Datetime("us"),
    "error": pl.String,
}
UNIVERSE_SCHEMA = {
    "htsc_code": pl.String,
    "name": pl.String,
    "pinyin_initials": pl.String,
    "security_type": pl.String,
    "security_id": pl.String,
    "exchange": pl.String,
    "is_active": pl.Boolean,
    "first_seen_at": pl.Datetime("us"),
    "last_seen_at": pl.Datetime("us"),
}


class ClientExportError(RuntimeError):
    """客户端导出文件无法读取或字段不完整。"""


@dataclass(frozen=True)
class DownloadState:
    htsc_code: str
    year_month: str
    status: str
    row_count: int
    first_time: datetime | None
    last_time: datetime | None
    updated_at: datetime
    error: str


def should_request_window(existing: DownloadState | None, retry_empty: bool) -> bool:
    if existing is None or existing.status == "failed":
        return True
    return retry_empty and existing.status == "empty"


def iter_month_windows(start: date, end: date) -> list[tuple[date, date]]:
    if start > end:
        return []
    result: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        month_end = date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1])
        result.append((cursor, min(month_end, end)))
        cursor = month_end + timedelta(days=1)
    return result


def _previous_weekday(value: date) -> date:
    result = value
    while result.weekday() >= 5:
        result -= timedelta(days=1)
    return result


def resolve_end_date(now: datetime | None = None, include_current_day: bool = False) -> date:
    current = now or datetime.now()
    if include_current_day:
        return current.date()
    candidate = current.date()
    if current.time() < dt_time(15, 30):
        candidate -= timedelta(days=1)
    return _previous_weekday(candidate)


def load_client_universe(path: Path = STOCKNAME_FILE) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"同花顺客户端名称表不存在: {path}")
    found: dict[str, str] = {}
    for raw_line in path.read_bytes().decode("gb18030").splitlines():
        if "=" not in raw_line:
            continue
        code, name = (part.strip() for part in raw_line.split("=", 1))
        if not (len(code) == 6 and code.isdigit() and code.startswith(SOFTWARE_LEVEL1_PREFIXES)):
            continue
        if not name:
            raise ValueError(f"同花顺软件一级板块名称为空: {code}")
        if code in found:
            raise ValueError(f"同花顺软件一级板块代码重复: {code}")
        found[code] = name
    if not found:
        raise ValueError(f"未从客户端名称表发现软件一级板块: {path}")
    return [
        {"security_id": code, "htsc_code": f"{code}.THS", "name": found[code]}
        for code in sorted(found)
    ]


def _pinyin_initials(name: str) -> str:
    return "".join(lazy_pinyin(name, style=Style.FIRST_LETTER)).upper()


def merge_universe_snapshot(
    current_rows: list[dict[str, str]],
    previous: pl.DataFrame | None,
    observed_at: datetime,
) -> pl.DataFrame:
    previous_rows = {} if previous is None or previous.is_empty() else {
        str(row["security_id"]): row for row in previous.to_dicts()
    }
    current_ids = {str(row["security_id"]) for row in current_rows}
    records: list[dict[str, object]] = []
    for row in current_rows:
        security_id = str(row["security_id"])
        old = previous_rows.get(security_id)
        records.append(
            {
                "htsc_code": f"{security_id}.THS",
                "name": str(row["name"]),
                "pinyin_initials": _pinyin_initials(str(row["name"])),
                "security_type": "index",
                "security_id": security_id,
                "exchange": "THS",
                "is_active": True,
                "first_seen_at": old.get("first_seen_at") if old else observed_at,
                "last_seen_at": observed_at,
            }
        )
    for security_id, old in previous_rows.items():
        if security_id in current_ids:
            continue
        records.append(
            {
                "htsc_code": str(old["htsc_code"]),
                "name": str(old["name"]),
                "pinyin_initials": str(old.get("pinyin_initials") or _pinyin_initials(str(old["name"]))),
                "security_type": str(old.get("security_type") or "index"),
                "security_id": security_id,
                "exchange": str(old.get("exchange") or "THS"),
                "is_active": False,
                "first_seen_at": old.get("first_seen_at") or observed_at,
                "last_seen_at": old.get("last_seen_at") or observed_at,
            }
        )
    return pl.DataFrame(records, schema=UNIVERSE_SCHEMA, strict=False).sort("security_id")


def _atomic_write_parquet(frame: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        frame.write_parquet(temp, compression="zstd")
        last_error: OSError | None = None
        for attempt in range(5):
            try:
                temp.replace(path)
                last_error = None
                break
            except PermissionError as exc:
                last_error = exc
                if attempt == 4:
                    raise
                time.sleep(0.25 * (attempt + 1))
        if last_error is not None:
            raise last_error
    finally:
        temp.unlink(missing_ok=True)


def read_universe_snapshot(path: Path) -> pl.DataFrame | None:
    if not path.is_file():
        return None
    return pl.read_parquet(path).select(list(UNIVERSE_SCHEMA)).cast(UNIVERSE_SCHEMA)


def write_universe_snapshot(frame: pl.DataFrame, path: Path) -> None:
    _atomic_write_parquet(frame.select(list(UNIVERSE_SCHEMA)).cast(UNIVERSE_SCHEMA), path)


def _decode_export_bytes(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ClientExportError("客户端导出文件不是 UTF-8/GB18030 可解码文本")


def _normalise_export_header(value: object) -> str:
    return "".join(str(value or "").strip().lower().replace("_", "").replace(" ", ""))


def parse_client_export(path: str | Path, *, expected_code: str | None = None) -> pl.DataFrame:
    """解析同花顺客户端“数据导出”产生的行情文本，不访问任何网络源。"""
    import csv
    from io import StringIO

    text = _decode_export_bytes(Path(path).read_bytes())
    sample = text[:4096]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters="\t,;").delimiter
    except csv.Error:
        delimiter = "\t" if "\t" in sample else ","
    rows = list(csv.DictReader(StringIO(text), delimiter=delimiter))
    if not rows:
        return _empty_output_frame()
    aliases = {
        "code": {"代码", "证券代码", "code", "stockcode"},
        "time": {"时间", "日期", "datetime", "time", "date"},
        "open": {"开盘", "开盘价", "open"},
        "high": {"最高", "最高价", "high"},
        "low": {"最低", "最低价", "low"},
        "close": {"收盘", "收盘价", "close"},
        "volume": {"成交量", "volume", "vol"},
        "amount": {"成交额", "成交金额", "amount", "turnover"},
    }
    header_map = {_normalise_export_header(key): key for key in rows[0]}
    columns: dict[str, str] = {}
    for target, names in aliases.items():
        for name in names:
            key = header_map.get(_normalise_export_header(name))
            if key is not None:
                columns[target] = key
                break
    required = {"code", "time", "open", "high", "low", "close"}
    if not required.issubset(columns):
        raise ClientExportError(f"客户端导出缺少字段: {sorted(required - set(columns))}")
    expected = expected_code.upper().removesuffix(".THS") if expected_code else None
    records: list[dict[str, object]] = []
    for row in rows:
        code = str(row.get(columns["code"], "")).strip().upper().removesuffix(".THS")
        if expected and code != expected:
            raise ValueError(f"客户端导出代码不匹配: expected={expected}, actual={code}")
        moment = pl.Series([row.get(columns["time"])], dtype=pl.String).str.to_datetime(strict=False).item()
        if moment is None:
            raise ClientExportError(f"客户端导出时间无法解析: {row.get(columns['time'])}")
        records.append(
            {
                "htsc_code": f"{code}.THS",
                "time": moment.replace(second=0, microsecond=0),
                "open": row.get(columns["open"]),
                "high": row.get(columns["high"]),
                "low": row.get(columns["low"]),
                "close": row.get(columns["close"]),
                "volume": row.get(columns.get("volume", "")),
                "amount": row.get(columns.get("amount", "")),
            }
        )
    return normalize_rows(records, expected or records[0]["htsc_code"].split(".", 1)[0], None, 0)[0]


def _empty_output_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=OUTPUT_SCHEMA)


def normalize_rows(
    rows: list[dict[str, object]],
    security_id: str,
    prior_close: float | None,
    index_offset: int,
) -> tuple[pl.DataFrame, float | None, int]:
    if not rows:
        return _empty_output_frame(), prior_close, index_offset
    ordered = sorted(rows, key=lambda row: row["time"])
    deduped: list[dict[str, object]] = []
    seen: set[datetime] = set()
    for row in ordered:
        moment = row["time"]
        if not isinstance(moment, datetime):
            raise ValueError(f"分钟时间类型异常: {moment!r}")
        if moment in seen:
            continue
        seen.add(moment)
        open_ = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        volume = None if row.get("volume") is None else float(row["volume"])
        amount = None if row.get("amount") is None else float(row["amount"])
        high = max(high, open_, close)
        low = min(low, open_, close)
        if volume is not None and volume < 0:
            volume = None
        if amount is not None and amount < 0:
            amount = None
        deduped.append(
            {
                "time": moment.replace(second=0, microsecond=0),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": amount,
            }
        )
    closes = [float(row["close"]) for row in deduped]
    pre_closes = [prior_close, *closes[:-1]]
    records: list[dict[str, object]] = []
    for offset, (row, pre_close) in enumerate(zip(deduped, pre_closes, strict=True)):
        close = float(row["close"])
        change = None if pre_close is None else close - float(pre_close)
        pct_chg = None if pre_close in (None, 0) else change / float(pre_close) * 100
        records.append(
            {
                "htsc_code": f"{security_id}.THS",
                "time": row["time"],
                "close": close,
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "volume": row["volume"],
                "amount": row["amount"],
                "date": row["time"].strftime("%Y-%m-%d"),
                "pre_close": pre_close,
                "change": change,
                "pct_chg": pct_chg,
                "__index_level_0__": index_offset + offset,
            }
        )
    frame = pl.DataFrame(records, schema=OUTPUT_SCHEMA, strict=False).select(OUTPUT_COLUMNS)
    return frame, closes[-1], index_offset + len(records)


def _normalize_merged(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty():
        return _empty_output_frame()
    missing = [column for column in OUTPUT_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"分钟 Parquet 缺少字段: {missing}")
    return (
        frame.select(OUTPUT_COLUMNS)
        .cast(OUTPUT_SCHEMA, strict=False)
        .drop_nulls(["htsc_code", "time", "open", "high", "low", "close"])
        .unique(["htsc_code", "time"], keep="last")
        .sort(["htsc_code", "time"])
    )


def write_daily_parts(frame: pl.DataFrame, base_dir: str | Path) -> set[tuple[int, int, int]]:
    normalized = _normalize_merged(frame)
    if normalized.is_empty():
        return set()
    partitioned = normalized.with_columns(
        pl.col("time").dt.year().alias("_year"),
        pl.col("time").dt.month().alias("_month"),
        pl.col("time").dt.day().alias("_day"),
    )
    touched: set[tuple[int, int, int]] = set()
    for keys, day_frame in partitioned.partition_by(["_year", "_month", "_day"], as_dict=True).items():
        year, month, day = map(int, keys)
        directory = Path(base_dir) / f"year={year:04d}" / f"month={month:02d}" / f"day={day:02d}"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"part_ths_{os.getpid()}_{time.time_ns()}_{uuid.uuid4().hex}.parquet"
        day_frame.drop(["_year", "_month", "_day"]).write_parquet(path, compression="zstd")
        touched.add((year, month, day))
    return touched


def rebuild_daily_partitions(base_dir: str | Path, touched: Iterable[tuple[int, int, int]]) -> list[Path]:
    rebuilt: list[Path] = []
    for year, month, day in sorted(set(touched)):
        directory = Path(base_dir) / f"year={year:04d}" / f"month={month:02d}" / f"day={day:02d}"
        merged_path = directory / MERGED_FILE_NAME
        parts = sorted(directory.glob("part_*.parquet"))
        inputs = ([merged_path] if merged_path.is_file() else []) + parts
        if not inputs:
            continue
        frames = [pl.read_parquet(path) for path in inputs if path.stat().st_size >= 12]
        if not frames:
            continue
        merged = _normalize_merged(pl.concat(frames, how="diagonal_relaxed", rechunk=True))
        try:
            _atomic_write_parquet(merged, merged_path)
        except (PermissionError, OSError) as exc:
            # 可视化服务可能短暂持有 merged.parquet；跳过该日，其他分区继续。
            if getattr(exc, "errno", None) not in (errno.EACCES, errno.EPERM, None) and not isinstance(exc, PermissionError):
                raise
            print(f"跳过被占用分区: {merged_path} | {exc}", file=sys.stderr, flush=True)
            continue
        for part in parts:
            part.unlink(missing_ok=True)
        rebuilt.append(merged_path)
    return rebuilt


def find_unmerged_partitions(base_dir: str | Path) -> set[tuple[int, int, int]]:
    touched: set[tuple[int, int, int]] = set()
    for part in Path(base_dir).glob("year=*/month=*/day=*/part_*.parquet"):
        try:
            year = int(part.parents[2].name.split("=", 1)[1])
            month = int(part.parents[1].name.split("=", 1)[1])
            day = int(part.parent.name.split("=", 1)[1])
        except (IndexError, ValueError):
            continue
        touched.add((year, month, day))
    return touched


def write_download_state(rows: Iterable[DownloadState], path: Path) -> None:
    records = [asdict(row) for row in rows]
    frame = pl.DataFrame(records, schema=STATE_SCHEMA, strict=False) if records else pl.DataFrame(schema=STATE_SCHEMA)
    frame = frame.unique(["htsc_code", "year_month"], keep="last").sort(["htsc_code", "year_month"])
    _atomic_write_parquet(frame, path)


def read_download_state(path: Path) -> dict[tuple[str, str], DownloadState]:
    if not path.is_file():
        return {}
    frame = pl.read_parquet(path).select(list(STATE_SCHEMA)).cast(STATE_SCHEMA, strict=False)
    result: dict[tuple[str, str], DownloadState] = {}
    for row in frame.to_dicts():
        state = DownloadState(**row)
        result[(state.htsc_code, state.year_month)] = state
    return result


def _save_state_map(state: dict[tuple[str, str], DownloadState], path: Path) -> None:
    write_download_state(state.values(), path)


def scan_latest_local_state(base_dir: str | Path) -> tuple[dict[str, float], dict[str, int], dict[str, datetime]]:
    paths = sorted(Path(base_dir).glob("year=*/month=*/day=*/merged.parquet"))
    if not paths:
        return {}, {}, {}
    pattern = str(Path(base_dir) / "year=*" / "month=*" / "day=*" / "merged.parquet").replace("\\", "/")
    query = f"""
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            ARG_MAX(TRY_CAST(close AS DOUBLE), CAST(time AS TIMESTAMP)) AS last_close,
            MAX(TRY_CAST(__index_level_0__ AS BIGINT)) AS last_index,
            MAX(CAST(time AS TIMESTAMP)) AS last_time
        FROM read_parquet('{pattern}', union_by_name=true)
        GROUP BY 1
    """
    rows = duckdb.query(query).fetchall()
    return (
        {str(code): float(close) for code, close, _, _ in rows if close is not None},
        {str(code): int(index) + 1 for code, _, index, _ in rows if index is not None},
        {str(code): moment for code, _, _, moment in rows if moment is not None},
    )


def scan_prior_local_values(
    base_dir: str | Path,
    htsc_code: str,
    before_time: datetime,
) -> tuple[float | None, int]:
    """读取某代码窗口开始前的最后 close 和序号，允许修复旧失败月份。"""
    pattern = str(Path(base_dir) / "year=*" / "month=*" / "day=*" / "merged.parquet").replace("\\", "/")
    try:
        query = f"""
            SELECT close, __index_level_0__
            FROM read_parquet('{pattern}', union_by_name=true)
            WHERE UPPER(TRIM(CAST(htsc_code AS VARCHAR))) = ?
              AND CAST(time AS TIMESTAMP) < ?
            ORDER BY CAST(time AS TIMESTAMP) DESC
            LIMIT 1
        """
        row = duckdb.execute(query, [htsc_code, before_time]).fetchone()
    except Exception:
        return None, 0
    if not row:
        return None, 0
    close = float(row[0]) if row[0] is not None else None
    offset = int(row[1]) + 1 if row[1] is not None else 0
    return close, offset


def scan_prior_local_values_many(
    base_dir: str | Path,
    htsc_codes: Iterable[str],
    before_time: datetime,
) -> dict[str, tuple[float | None, int]]:
    """一次读取多个代码窗口开始前的最后值，避免逐代码重复扫描全库。"""
    codes = [str(code).upper().strip() for code in htsc_codes]
    result = {code: (None, 0) for code in codes}
    if not codes:
        return result
    pattern = str(Path(base_dir) / "year=*" / "month=*" / "day=*" / "merged.parquet").replace("\\", "/")
    try:
        query = f"""
            SELECT htsc_code, close, __index_level_0__
            FROM (
                SELECT
                    UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                    TRY_CAST(close AS DOUBLE) AS close,
                    TRY_CAST(__index_level_0__ AS BIGINT) AS __index_level_0__,
                    ROW_NUMBER() OVER (
                        PARTITION BY UPPER(TRIM(CAST(htsc_code AS VARCHAR)))
                        ORDER BY CAST(time AS TIMESTAMP) DESC
                    ) AS rn
                FROM read_parquet('{pattern}', union_by_name=true)
                WHERE UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN ({','.join('?' for _ in codes)})
                  AND CAST(time AS TIMESTAMP) < ?
            )
            WHERE rn = 1
        """
        rows = duckdb.execute(query, [*codes, before_time]).fetchall()
    except Exception:
        return result
    for code, close, index in rows:
        result[str(code)] = (
            float(close) if close is not None else None,
            int(index) + 1 if index is not None else 0,
        )
    return result


def _failure_file(base_dir: Path, failures: list[tuple[str, str, str]]) -> Path:
    path = base_dir / "_meta" / f"failed_ths_minute_requests_{datetime.now():%Y%m%d_%H%M%S}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{code}\t{year_month}\t{error}" for code, year_month, error in failures]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同花顺软件一级板块 1 分钟 K 线全量与增量下载")
    parser.add_argument("--base-dir", default=str(BASE_DIR), help="分钟 Parquet 根目录")
    parser.add_argument("--stockname-file", default=str(STOCKNAME_FILE), help="同花顺客户端 stockname_48_0.txt")
    parser.add_argument("--default-start", default=DEFAULT_START_DATE, help="首次回溯起点 YYYY-MM-DD")
    parser.add_argument("--end", default="", help="截止日期 YYYY-MM-DD；默认最近完整交易日")
    parser.add_argument("--codes", nargs="*", default=None, help="仅处理指定六位代码或 .THS 代码")
    parser.add_argument(
        "--client-export-dir",
        default=str(THS_ROOT / "output"),
        help="同花顺客户端原生数据导出目录；不会访问网络",
    )
    parser.add_argument("--include-current-day", action="store_true", help="允许写入当日未完成分钟")
    parser.add_argument("--retry-empty", action="store_true", help="重新请求已记录为空的月份")
    parser.add_argument("--dry-run", action="store_true", help="只输出计划，不请求和写入")
    parser.add_argument("--rebuild-only", action="store_true", help="只合并残留 part 文件")
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    base_dir = Path(args.base_dir)
    if args.rebuild_only:
        touched = find_unmerged_partitions(base_dir)
        rebuilt = rebuild_daily_partitions(base_dir, touched)
        print(f"残留分区: {len(touched)} | 已重建: {len(rebuilt)}")
        return 0

    start = datetime.strptime(args.default_start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else resolve_end_date(
        include_current_day=bool(args.include_current_day)
    )
    if start > end:
        raise ValueError(f"回溯起点晚于截止日: {start} > {end}")

    current_rows = load_client_universe(Path(args.stockname_file))
    requested = None
    if args.codes:
        requested = {str(code).strip().upper().removesuffix(".THS") for code in args.codes}
        available = {row["security_id"] for row in current_rows}
        missing = requested - available
        if missing:
            raise ValueError(f"指定代码不属于当前同花顺软件一级: {sorted(missing)}")
        current_rows = [row for row in current_rows if row["security_id"] in requested]

    meta_dir = base_dir / "_meta"
    universe_path = meta_dir / "ths_level1_universe.parquet"
    state_path = meta_dir / "ths_minute_download_state.parquet"
    source_marker = meta_dir / "ths_minute_source_client_export.txt"
    previous_universe = read_universe_snapshot(universe_path)
    universe = merge_universe_snapshot(load_client_universe(Path(args.stockname_file)), previous_universe, datetime.now())
    windows = iter_month_windows(start, end)
    state = (
        read_download_state(state_path)
        if source_marker.is_file() and source_marker.read_text(encoding="utf-8").strip() == "client-export-only-v1"
        else {}
    )
    pending_count = sum(
        should_request_window(
            state.get((f"{row['htsc_code']}", f"{window_start:%Y-%m}")),
            retry_empty=bool(args.retry_empty),
        )
        for window_start, _ in windows
        for row in current_rows
    )
    print(f"软件一级板块: {len(current_rows)} | 月窗口: {len(windows)} | 待请求: {pending_count}")
    print(f"范围: {start} ~ {end} | 目录: {base_dir}")
    if args.dry_run:
        return 0

    base_dir.mkdir(parents=True, exist_ok=True)
    source_marker.parent.mkdir(parents=True, exist_ok=True)
    source_marker.write_text("client-export-only-v1\n", encoding="utf-8")
    write_universe_snapshot(universe, universe_path)
    residual = find_unmerged_partitions(base_dir)
    if residual:
        print(f"发现残留 part 分区 {len(residual)} 个，先重建。")
        rebuild_daily_partitions(base_dir, residual)

    failures: list[tuple[str, str, str]] = []
    export_dir = Path(args.client_export_dir)
    if not export_dir.is_dir():
        raise FileNotFoundError(f"同花顺客户端导出目录不存在: {export_dir}")

    for window_number, (window_start, window_end) in enumerate(windows, start=1):
        year_month = f"{window_start:%Y-%m}"
        month_states: list[DownloadState] = []
        for row in current_rows:
            htsc_code = str(row["htsc_code"])
            existing = state.get((htsc_code, year_month))
            if not should_request_window(existing, retry_empty=bool(args.retry_empty)):
                continue
            matches = [path for path in export_dir.rglob("*") if path.is_file() and htsc_code.removesuffix(".THS") in path.name]
            if not matches:
                month_states.append(
                    DownloadState(
                        htsc_code, year_month, "needs_history_replay", 0, None, None, datetime.now(),
                        "客户端未提供该窗口的导出文件；需要在同花顺历史分时窗口触发",
                    )
                )
                continue
            try:
                frame = pl.concat(
                    [parse_client_export(path, expected_code=htsc_code) for path in matches],
                    how="vertical_relaxed",
                ).filter(
                    (pl.col("time") >= datetime.combine(window_start, dt_time.min))
                    & (pl.col("time") < datetime.combine(window_end + timedelta(days=1), dt_time.min))
                )
                if frame.is_empty():
                    raise ClientExportError("导出文件不包含请求窗口")
                touched = write_daily_parts(frame, base_dir)
                rebuild_daily_partitions(base_dir, touched)
                month_states.append(
                    DownloadState(htsc_code, year_month, "success", frame.height, frame["time"].min(), frame["time"].max(), datetime.now(), "")
                )
            except Exception as exc:  # noqa: BLE001
                failures.append((htsc_code, year_month, str(exc)))
                month_states.append(DownloadState(htsc_code, year_month, "failed", 0, None, None, datetime.now(), str(exc)))
        for item in month_states:
            state[(item.htsc_code, item.year_month)] = item
            if item.status == "needs_history_replay":
                failures.append((item.htsc_code, item.year_month, item.error))
        _save_state_map(state, state_path)
        success_count = sum(item.status == "success" for item in month_states)
        empty_count = sum(item.status == "empty" for item in month_states)
        failed_count = sum(item.status == "failed" for item in month_states)
        print(
            f"[{year_month}] 有数据 {success_count} | 空窗口 {empty_count} | 失败 {failed_count} | "
            f"待历史回放/失败 {sum(item.status != 'success' for item in month_states)}",
            flush=True,
        )

    if failures:
        failure_path = _failure_file(base_dir, failures)
        print(f"失败窗口: {len(failures)} | 详情: {failure_path}")
        return 1
    print("同花顺客户端导出处理完成；仍需历史回放的窗口已保留在状态文件。")
    return 0


def main() -> None:
    raise SystemExit(run(parse_args()))


if __name__ == "__main__":
    main()
