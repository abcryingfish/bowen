#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""xtquant get_full_tick 实时写入今日 SQLite 临时行情缓存。"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from xtquant import xtdata

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


TEMP_TODAY_DATA_DIR = Path(r"D:\database\temp_today_data")
SQLITE_TIMEOUT_SECONDS = 30.0
SQLITE_BUSY_TIMEOUT_MS = 30000
DEFAULT_SECTOR_NAME = "沪深A股"
DEFAULT_INTERVAL_SECONDS = 3.0
DEFAULT_SNAPSHOT_INTERVAL_SECONDS = 60.0
REALTIME_STOP_TIME = (15, 5)


def today_cache_path(trading_day: str | None = None) -> Path:
    day = trading_day or datetime.now().strftime("%Y-%m-%d")
    return TEMP_TODAY_DATA_DIR / f"market_cache_{day}.sqlite"


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=SQLITE_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA wal_autocheckpoint = 10000")
    return conn


def ensure_schema(db_path: str | Path) -> None:
    conn = _connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tick_snapshot (
                htsc_code TEXT NOT NULL,
                ts TEXT NOT NULL,
                last_price REAL,
                open REAL,
                high REAL,
                low REAL,
                last_close REAL,
                amount REAL,
                volume REAL,
                pvolume REAL,
                PRIMARY KEY (htsc_code, ts)
            );

            CREATE TABLE IF NOT EXISTS latest_quote (
                htsc_code TEXT PRIMARY KEY,
                ts TEXT NOT NULL,
                last_price REAL,
                open REAL,
                high REAL,
                low REAL,
                last_close REAL,
                amount REAL,
                volume REAL,
                pvolume REAL,
                ask_price TEXT,
                bid_price TEXT,
                ask_vol TEXT,
                bid_vol TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS today_daily_bar (
                htsc_code TEXT PRIMARY KEY,
                trading_day TEXT NOT NULL,
                time INTEGER NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                last_close REAL,
                amount REAL,
                volume REAL,
                pvolume REAL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cache_meta (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            );

            DROP INDEX IF EXISTS idx_tick_snapshot_code_ts;
            DROP INDEX IF EXISTS idx_tick_snapshot_ts;
            DROP INDEX IF EXISTS idx_today_daily_day;
            """
        )
        conn.commit()
    finally:
        conn.close()


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric:
        return None
    return numeric


def _normalize_ts(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("ts is required")
    if len(text) == 14 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    return text


def _json_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _prepare_tick_payload(row: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    code = normalize_code(row.get("htsc_code") or row.get("code"))
    ts_text = _normalize_ts(row.get("ts") or row.get("time") or row.get("timetag"))
    if not code:
        raise ValueError("htsc_code is required")
    payload = {
        "htsc_code": code,
        "ts": ts_text,
        "last_price": _safe_float(row.get("last_price", row.get("lastPrice"))),
        "open": _safe_float(row.get("open")),
        "high": _safe_float(row.get("high")),
        "low": _safe_float(row.get("low")),
        "last_close": _safe_float(row.get("last_close", row.get("lastClose"))),
        "amount": _safe_float(row.get("amount")),
        "volume": _safe_float(row.get("volume")),
        "pvolume": _safe_float(row.get("pvolume")),
    }
    return code, ts_text, payload


def upsert_tick_snapshots(
    db_path: str | Path,
    rows: list[dict[str, Any]],
    *,
    ensure: bool = True,
    update_existing_snapshots: bool = True,
    write_snapshots: bool = True,
    write_latest: bool = True,
    collect_stats: bool = False,
) -> int | tuple[int, dict[str, float]]:
    if ensure:
        ensure_schema(db_path)
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tick_payloads: list[dict[str, Any]] = []
    latest_quote_params: list[tuple[Any, ...]] = []
    for row in rows:
        code, ts_text, payload = _prepare_tick_payload(row)
        tick_payloads.append(payload)
        latest_quote_params.append(
            (
                code,
                ts_text,
                payload["last_price"],
                payload["open"],
                payload["high"],
                payload["low"],
                payload["last_close"],
                payload["amount"],
                payload["volume"],
                payload["pvolume"],
                _json_text(row.get("ask_price", row.get("askPrice"))),
                _json_text(row.get("bid_price", row.get("bidPrice"))),
                _json_text(row.get("ask_vol", row.get("askVol"))),
                _json_text(row.get("bid_vol", row.get("bidVol"))),
                updated_at,
            )
        )
    if not tick_payloads:
        empty_stats = {"snapshot_sec": 0.0, "latest_sec": 0.0, "commit_sec": 0.0}
        return (0, empty_stats) if collect_stats else 0
    conn = _connect(db_path)
    stats = {"snapshot_sec": 0.0, "latest_sec": 0.0, "commit_sec": 0.0}
    try:
        conn.execute("BEGIN")
        if write_snapshots:
            snapshot_start = datetime.now()
            snapshot_conflict_clause = (
                """
                ON CONFLICT(htsc_code, ts) DO UPDATE SET
                    last_price = excluded.last_price,
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    last_close = excluded.last_close,
                    amount = excluded.amount,
                    volume = excluded.volume,
                    pvolume = excluded.pvolume
                """
                if update_existing_snapshots
                else "ON CONFLICT(htsc_code, ts) DO NOTHING"
            )
            conn.executemany(
                f"""
                INSERT INTO tick_snapshot (
                    htsc_code, ts, last_price, open, high, low, last_close,
                    amount, volume, pvolume
                )
                VALUES (
                    :htsc_code, :ts, :last_price, :open, :high, :low, :last_close,
                    :amount, :volume, :pvolume
                )
                {snapshot_conflict_clause}
                """,
                tick_payloads,
            )
            stats["snapshot_sec"] = (datetime.now() - snapshot_start).total_seconds()
        if write_latest:
            latest_start = datetime.now()
            conn.executemany(
                """
                INSERT INTO latest_quote (
                    htsc_code, ts, last_price, open, high, low, last_close,
                    amount, volume, pvolume, ask_price, bid_price, ask_vol,
                    bid_vol, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(htsc_code) DO UPDATE SET
                    ts = excluded.ts,
                    last_price = excluded.last_price,
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    last_close = excluded.last_close,
                    amount = excluded.amount,
                    volume = excluded.volume,
                    pvolume = excluded.pvolume,
                    ask_price = excluded.ask_price,
                    bid_price = excluded.bid_price,
                    ask_vol = excluded.ask_vol,
                    bid_vol = excluded.bid_vol,
                    updated_at = excluded.updated_at
                WHERE excluded.ts >= latest_quote.ts
                  AND excluded.last_price IS NOT NULL
                  AND excluded.last_price > 0
                """,
                latest_quote_params,
            )
            stats["latest_sec"] = (datetime.now() - latest_start).total_seconds()
        commit_start = datetime.now()
        conn.commit()
        stats["commit_sec"] = (datetime.now() - commit_start).total_seconds()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return (len(tick_payloads), stats) if collect_stats else len(tick_payloads)


class SnapshotFlushWorker:
    def __init__(self, db_path: Path, flush_interval_seconds: float) -> None:
        self.db_path = db_path
        self.flush_interval_seconds = max(float(flush_interval_seconds), 0.1)
        self._rows_by_code: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_stats: dict[str, float] = {"snapshot_sec": 0.0, "commit_sec": 0.0, "write_sec": 0.0}
        self.last_flushed_rows = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="snapshot-flush", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread:
            self._thread.join()

    def enqueue(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        with self._lock:
            for row in rows:
                row_copy = dict(row)
                code = normalize_code(row_copy.get("htsc_code") or row_copy.get("code"))
                if not code:
                    continue
                row_copy["htsc_code"] = code
                self._rows_by_code[code] = row_copy
        self._wake_event.set()

    def pending_count(self) -> int:
        with self._lock:
            return len(self._rows_by_code)

    def flush_once(self) -> int:
        with self._lock:
            rows = list(self._rows_by_code.values())
            self._rows_by_code = {}
        if not rows:
            return 0
        start = time.perf_counter()
        try:
            result = upsert_tick_snapshots(
                self.db_path,
                rows,
                ensure=False,
                update_existing_snapshots=False,
                write_snapshots=True,
                write_latest=False,
                collect_stats=True,
            )
            written, stats = result
            self.last_stats = {
                "snapshot_sec": stats["snapshot_sec"],
                "commit_sec": stats["commit_sec"],
                "write_sec": time.perf_counter() - start,
            }
            self.last_flushed_rows = int(written)
            print(
                f"[FLUSH] snapshot_rows={written} "
                f"snapshot={stats['snapshot_sec']:.3f}s "
                f"commit={stats['commit_sec']:.3f}s "
                f"elapsed={self.last_stats['write_sec']:.3f}s"
            )
            return int(written)
        except Exception as exc:
            with self._lock:
                for row in rows:
                    code = normalize_code(row.get("htsc_code") or row.get("code"))
                    if code and code not in self._rows_by_code:
                        self._rows_by_code[code] = row
            print(f"[WARN] 后台快照落盘失败: {exc}")
            return 0

    def _run(self) -> None:
        while not self._stop_event.wait(self.flush_interval_seconds):
            self.flush_once()
        self.flush_once()


def normalize_code(code: Any) -> str:
    return str(code or "").strip().upper()


def load_sector_stocks(sector_name: str = DEFAULT_SECTOR_NAME) -> list[str]:
    xtdata.download_sector_data()
    stock_list = xtdata.get_stock_list_in_sector(sector_name)
    stocks = sorted({normalize_code(code) for code in stock_list if str(code).strip()})
    if not stocks:
        raise RuntimeError(f"xtquant 板块股票池为空: {sector_name}")
    return stocks


def _normalize_timetag(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if len(text) == 17 and text[8] == " ":
        return datetime.strptime(text, "%Y%m%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
    if len(text) == 14 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    return text


def tick_payload_to_cache_row(code: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "htsc_code": normalize_code(code),
        "ts": _normalize_timetag(payload.get("timetag") or payload.get("time")),
        "last_price": payload.get("lastPrice", payload.get("last_price")),
        "open": payload.get("open"),
        "high": payload.get("high"),
        "low": payload.get("low"),
        "last_close": payload.get("lastClose", payload.get("last_close")),
        "amount": payload.get("amount"),
        "volume": payload.get("volume"),
        "pvolume": payload.get("pvolume"),
        "ask_price": payload.get("askPrice", payload.get("ask_price")),
        "bid_price": payload.get("bidPrice", payload.get("bid_price")),
        "ask_vol": payload.get("askVol", payload.get("ask_vol")),
        "bid_vol": payload.get("bidVol", payload.get("bid_vol")),
    }


def fetch_full_tick(stock_list: list[str]) -> dict[str, Any]:
    data = xtdata.get_full_tick(stock_list)
    return data if isinstance(data, dict) else {}


def write_tick_batch(
    db_path: Path,
    tick_data: dict[str, Any],
    stock_set: set[str],
    write_snapshots: bool = True,
    snapshot_worker: SnapshotFlushWorker | None = None,
) -> tuple[int, int, dict[str, float]]:
    build_start = time.perf_counter()
    skipped = 0
    rows: list[dict[str, Any]] = []
    for code, payload in tick_data.items():
        code_u = normalize_code(code)
        if code_u not in stock_set:
            skipped += 1
            continue
        if not isinstance(payload, dict):
            skipped += 1
            continue
        try:
            rows.append(tick_payload_to_cache_row(code_u, payload))
        except Exception as exc:
            skipped += 1
            print(f"[WARN] 数据转换失败: {code_u} | {exc}")
    build_sec = time.perf_counter() - build_start
    written = 0
    write_sec = 0.0
    if rows:
        try:
            queued_snapshot_rows = 0
            write_snapshots_now = write_snapshots
            if write_snapshots and snapshot_worker is not None:
                snapshot_worker.enqueue(rows)
                queued_snapshot_rows = len(rows)
                write_snapshots_now = False
            write_start = time.perf_counter()
            written_result = upsert_tick_snapshots(
                db_path,
                rows,
                ensure=False,
                update_existing_snapshots=False,
                write_snapshots=write_snapshots_now,
                write_latest=True,
                collect_stats=True,
            )
            written, write_stats = written_result
            write_sec = time.perf_counter() - write_start
        except Exception as exc:
            skipped += len(rows)
            print(f"[WARN] 批量写入失败: {exc}")
    else:
        write_stats = {"snapshot_sec": 0.0, "latest_sec": 0.0, "commit_sec": 0.0}
        queued_snapshot_rows = 0
    return written, skipped, {
        "build_sec": build_sec,
        "write_sec": write_sec,
        "snapshot_sec": write_stats["snapshot_sec"],
        "latest_sec": write_stats["latest_sec"],
        "commit_sec": write_stats["commit_sec"],
        "queued_snapshot_rows": float(queued_snapshot_rows),
    }


def is_after_realtime_stop_time(now: datetime | None = None) -> bool:
    current = now or datetime.now()
    hour, minute = REALTIME_STOP_TIME
    return (current.hour, current.minute) >= (hour, minute)


def run_loop(
    db_path: Path,
    stock_list: list[str],
    interval_seconds: float,
    snapshot_interval_seconds: float,
    once: bool = False,
) -> None:
    ensure_schema(db_path)
    snapshot_worker = SnapshotFlushWorker(db_path, snapshot_interval_seconds)
    snapshot_worker.start()
    stock_set = set(stock_list)
    print(f"[OK] SQLite 缓存: {db_path}")
    print(f"[OK] 股票池: {len(stock_list)} 只")
    print(f"[RUN] get_full_tick 轮询间隔: {interval_seconds:.2f}s")
    print(f"[RUN] tick_snapshot 后台落盘间隔: {snapshot_interval_seconds:.2f}s")

    round_no = 0
    try:
        while True:
            round_no += 1
            start = time.perf_counter()
            tick_data = fetch_full_tick(stock_list)
            fetch_sec = time.perf_counter() - start
            fetched = len(tick_data)
            written, skipped, stats = write_tick_batch(
                db_path,
                tick_data,
                stock_set,
                write_snapshots=True,
                snapshot_worker=snapshot_worker,
            )
            elapsed = time.perf_counter() - start
            now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(
                f"[{now_text}] round={round_no} fetched={fetched} "
                f"written={written} skipped={skipped} "
                f"fetch={fetch_sec:.3f}s build={stats['build_sec']:.3f}s "
                f"queued_snapshot={int(stats['queued_snapshot_rows'])} "
                f"pending_snapshot={snapshot_worker.pending_count()} "
                f"latest={stats['latest_sec']:.3f}s commit={stats['commit_sec']:.3f}s "
                f"write={stats['write_sec']:.3f}s elapsed={elapsed:.3f}s"
            )
            if once:
                break
            sleep_sec = max(0.0, interval_seconds - elapsed)
            if sleep_sec:
                time.sleep(sleep_sec)
    finally:
        snapshot_worker.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="xtquant get_full_tick 实时写入今日 SQLite 临时行情缓存")
    parser.add_argument("--sector-name", default=DEFAULT_SECTOR_NAME, help="xtquant 板块名，默认 沪深A股")
    parser.add_argument("--db-path", default="", help="SQLite 路径，默认 D:\\database\\temp_today_data\\market_cache_YYYY-MM-DD.sqlite")
    parser.add_argument("--interval-sec", type=float, default=DEFAULT_INTERVAL_SECONDS, help="轮询间隔秒数，默认 3")
    parser.add_argument(
        "--snapshot-interval-sec",
        type=float,
        default=DEFAULT_SNAPSHOT_INTERVAL_SECONDS,
        help="tick_snapshot 抽样写入间隔秒数；默认 60，只保留每只股票最新快照后批量落盘",
    )
    parser.add_argument("--once", action="store_true", help="只获取并写入一轮，用于测试")
    parser.add_argument("--codes", nargs="*", default=None, help="手动指定股票代码；不传则取 xtquant 板块 沪深A股")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db_path) if str(args.db_path).strip() else today_cache_path()
    if is_after_realtime_stop_time():
        print("[OK] 当前时间已到 15:05 后，实时行情写入脚本自动退出。")
        return

    if args.codes:
        stock_list = sorted({normalize_code(code) for code in args.codes if str(code).strip()})
    else:
        stock_list = load_sector_stocks(args.sector_name)
    run_loop(
        db_path,
        stock_list,
        max(float(args.interval_sec), 0.1),
        max(float(args.snapshot_interval_sec), 0.0),
        once=bool(args.once),
    )


if __name__ == "__main__":
    main()
