#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""xtquant get_full_tick 实时写入今日 SQLite 临时行情缓存。"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from xtquant import xtdata

ROOT_DIR = Path(__file__).resolve().parent.parent
VIS_DIR = ROOT_DIR / "可视化"
if str(VIS_DIR) not in sys.path:
    sys.path.append(str(VIS_DIR))

from temp_today_market_cache import ensure_schema, today_cache_path, upsert_tick_snapshots  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


DEFAULT_SECTOR_NAME = "沪深A股"
DEFAULT_INTERVAL_SECONDS = 3.0


class SnapshotFlushWorker:
    def __init__(self, db_path: Path, flush_interval_seconds: float) -> None:
        self.db_path = db_path
        self.flush_interval_seconds = max(float(flush_interval_seconds), 0.1)
        self._rows: list[dict[str, Any]] = []
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
            self._rows.extend(dict(row) for row in rows)
        self._wake_event.set()

    def pending_count(self) -> int:
        with self._lock:
            return len(self._rows)

    def flush_once(self) -> int:
        with self._lock:
            rows = self._rows
            self._rows = []
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
                self._rows = rows + self._rows
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
    parser.add_argument("--snapshot-interval-sec", type=float, default=15.0, help="tick_snapshot 写入间隔秒数；0 表示每轮都写，默认 15")
    parser.add_argument("--once", action="store_true", help="只获取并写入一轮，用于测试")
    parser.add_argument("--codes", nargs="*", default=None, help="手动指定股票代码；不传则取 xtquant 板块 沪深A股")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db_path) if str(args.db_path).strip() else today_cache_path()
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
