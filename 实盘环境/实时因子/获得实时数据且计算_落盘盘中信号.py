# -*- coding: utf-8 -*-
"""盘中读取行情缓存并独立落盘 ZXW 最终信号。

行情采集由 工具/实时行情写入SQLite.py 独占；本脚本只读 market_cache。
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

from intraday_signal_service import (
    append_run_log,
    append_signal_transitions,
    build_default_factor_registry,
    daily_event_path,
    daily_snapshot_path,
    load_factor_builder,
    read_event_signal_state,
    read_final_signal_state,
    read_last_round_id,
    replace_snapshot,
)
from realtime_factor_core import RealtimeFactorEngine, quote_rows_from_market_db


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="读取实时行情并独立落盘盘中 ZXW 信号")
    parser.add_argument("--market-db", default="", help="行情 SQLite，默认当天 market_cache")
    parser.add_argument("--state-db", default="", help="盘前状态 SQLite，默认读取当天 factor_state 文件")
    parser.add_argument("--trading-day", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--empty-sleep-sec", type=float, default=1.0)
    parser.add_argument("--error-sleep-sec", type=float, default=3.0)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def _default_market_db(day: str) -> Path:
    return Path(r"D:\database\temp_today_data") / f"market_cache_{day}.sqlite"


def _state_path(day: str) -> Path:
    return Path(r"D:\database\realtime_factor_state\factor_state.sqlite")


def _after_realtime_stop(now: datetime | None = None, trading_day: str | None = None) -> bool:
    current = now or datetime.now()
    if trading_day and current.strftime("%Y-%m-%d") != str(trading_day):
        return False
    return (current.hour, current.minute) >= (15, 5)


def run_once(engine: RealtimeFactorEngine, market_db: Path, trading_day: str, round_id: int, registry=None) -> tuple[int, dict]:
    quotes = quote_rows_from_market_db(market_db)
    if not quotes:
        return 0, {"quotes": 0, "signals": 0}
    calc_started = datetime.now()
    events, stats = engine.evaluate_round(quotes=quotes, now=calc_started)
    calc_finished = datetime.now()
    final_values = []
    current_state = {}
    for event in events:
        key = (str(event["htsc_code"]), str(event["signal_name"]))
        current_state[key] = 1.0
    quote_codes = {str(q.get("htsc_code", "")).strip().upper() for q in quotes}
    event_path = daily_event_path(trading_day)
    previous = read_event_signal_state(event_path)
    if previous is None:
        previous = read_final_signal_state(daily_snapshot_path(trading_day))
    # 本轮没有行情的股票不参与状态转换，保留上一轮值，避免误发 cleared。
    current_state = {
        key: value for key, value in current_state.items() if key[0] in quote_codes
    }
    event_current_state = dict(current_state)
    for key, value in previous.items():
        if key[0] not in quote_codes:
            event_current_state[key] = value
    snapshot_map = {
        key: value for key, value in dict(stats.get("snapshot_values", {})).items()
        if key[0] in quote_codes
    }
    for key, value in previous.items():
        if key[0] not in quote_codes:
            snapshot_map[key] = value
    registry = list(registry or build_default_factor_registry())
    final_signal_names = {item.key for item in registry if item.is_final_signal}
    for code in sorted(quote_codes):
        for signal_name in sorted(final_signal_names):
            snapshot_map[(code, signal_name)] = float(current_state.get((code, signal_name), 0.0))
    for (code, factor_name), value in sorted(snapshot_map.items()):
        final_values.append({
            "htsc_code": code,
            "factor_name": factor_name,
            "value": value,
            "is_final_signal": int(factor_name in final_signal_names),
        })
    cutoff = max((str(q.get("ts") or "") for q in quotes), default=calc_started.strftime("%Y-%m-%d %H:%M:%S"))
    replace_snapshot(
        daily_snapshot_path(trading_day), trading_day=trading_day, round_id=round_id,
        quote_cutoff_time=cutoff, values=final_values,
        bars=quotes, calc_started_at=calc_started.strftime("%Y-%m-%d %H:%M:%S"),
        calc_finished_at=calc_finished.strftime("%Y-%m-%d %H:%M:%S"),
        calc_elapsed_ms=(calc_finished - calc_started).total_seconds() * 1000.0,
        registry=registry,
    )
    append_signal_transitions(event_path, trading_day, round_id, previous, event_current_state, event_time=calc_finished.strftime("%Y-%m-%d %H:%M:%S"), quote_by_code={str(q["htsc_code"]): q for q in quotes})
    return len(quotes), stats


def main() -> None:
    args = _parse_args()
    day = str(args.trading_day)
    market_db = Path(args.market_db) if args.market_db.strip() else _default_market_db(day)
    state_db = Path(args.state_db) if args.state_db.strip() else _state_path(day)
    registry = build_default_factor_registry()
    for spec in registry:
        load_factor_builder(spec)
    while True:
        try:
            if _after_realtime_stop(trading_day=day):
                print("[OK] 已到 15:05，盘中信号脚本退出。", flush=True)
                return
            if not market_db.exists():
                raise FileNotFoundError(f"行情缓存不存在: {market_db}")
            if not state_db.exists():
                raise FileNotFoundError(f"盘前状态库不存在，请先运行盘前状态准备.py: {state_db}")
            engine = RealtimeFactorEngine.from_state_db(state_db)
            round_id = read_last_round_id(daily_snapshot_path(day))
            while True:
                round_id += 1
                started = time.perf_counter()
                quote_count, stats = run_once(engine, market_db, day, round_id, registry=registry)
                append_run_log(daily_snapshot_path(day), round_id, "success")
                print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] round={round_id} quotes={quote_count} signals={stats.get('signal_count', 0)} elapsed={time.perf_counter() - started:.2f}s", flush=True)
                if args.once:
                    return
                if _after_realtime_stop(trading_day=day):
                    print("[OK] 已到 15:05，盘中信号脚本退出。", flush=True)
                    return
                if quote_count == 0:
                    time.sleep(max(args.empty_sleep_sec, 0.1))
        except Exception as exc:  # 因子失败不影响行情写入进程
            print(f"[ERROR] 盘中因子本轮失败: {exc}", flush=True)
            try:
                append_run_log(daily_snapshot_path(day), round_id if "round_id" in locals() else 0, "failed", str(exc))
            except Exception:
                pass
            if args.once:
                raise
            time.sleep(max(args.error_sleep_sec, 0.1))


if __name__ == "__main__":
    main()
