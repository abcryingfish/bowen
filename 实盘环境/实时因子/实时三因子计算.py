#!/usr/bin/python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parents[1]
VIS_DIR = ROOT_DIR / "可视化"
if str(CURRENT_DIR) not in sys.path:
    sys.path.append(str(CURRENT_DIR))
if str(VIS_DIR) not in sys.path:
    sys.path.append(str(VIS_DIR))

from realtime_factor_core import (  # noqa: E402
    RealtimeFactorEngine,
    append_signal_events,
    ensure_signal_schema,
    factor_state_db_path,
    quote_rows_from_market_db,
    signal_db_path,
)
from temp_today_market_cache import today_cache_path  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="实时三因子计算：只读行情 SQLite，输出 signal SQLite")
    parser.add_argument("--market-db", default="", help="行情 SQLite，默认 D:\\database\\temp_today_data\\market_cache_YYYY-MM-DD.sqlite")
    parser.add_argument("--state-db", default="", help="盘前滚动状态 SQLite，默认 D:\\database\\realtime_factor_state\\factor_state.sqlite")
    parser.add_argument("--signal-db", default="", help="信号 SQLite，默认 D:\\database\\temp_today_data\\realtime_signal_YYYY-MM-DD.sqlite")
    parser.add_argument("--trading-day", default=datetime.now().strftime("%Y-%m-%d"), help="交易日")
    parser.add_argument("--once", action="store_true", help="只跑一轮")
    parser.add_argument("--empty-sleep-sec", type=float, default=1.0, help="无行情时等待秒数")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    market_db = Path(args.market_db) if str(args.market_db).strip() else today_cache_path(args.trading_day)
    state_db = Path(args.state_db) if str(args.state_db).strip() else factor_state_db_path(args.trading_day)
    signal_db = Path(args.signal_db) if str(args.signal_db).strip() else signal_db_path(args.trading_day)
    if not state_db.exists():
        raise FileNotFoundError(f"盘前状态库不存在，请先运行盘前状态准备.py: {state_db}")
    if not market_db.exists():
        raise FileNotFoundError(f"行情缓存库不存在，请先运行实时行情写入SQLite.py: {market_db}")

    engine = RealtimeFactorEngine.from_state_db(state_db)
    print(f"[OK] state_db={state_db}")
    print(f"[OK] market_db={market_db}")
    print(f"[OK] signal_db={signal_db}")
    print(f"[OK] states={len(engine.code_order)}")
    ensure_signal_schema(signal_db)

    round_id = 0
    while True:
        round_id += 1
        loop_start = time.perf_counter()
        read_start = time.perf_counter()
        quotes = quote_rows_from_market_db(market_db)
        read_ms = (time.perf_counter() - read_start) * 1000.0
        if not quotes:
            print(f"[WARN] round={round_id} latest_quote empty read={read_ms:.2f}ms")
            if args.once:
                break
            time.sleep(max(float(args.empty_sleep_sec), 0.1))
            continue

        now = datetime.now()
        calc_start = time.perf_counter()
        events, stats = engine.evaluate_round(quotes=quotes, now=now)
        calc_ms = (time.perf_counter() - calc_start) * 1000.0
        for event in events:
            event["calc_round_id"] = round_id
            event["trading_day"] = args.trading_day

        write_start = time.perf_counter()
        written = append_signal_events(signal_db, events)
        write_ms = (time.perf_counter() - write_start) * 1000.0
        elapsed_ms = (time.perf_counter() - loop_start) * 1000.0
        print(
            f"[{now:%Y-%m-%d %H:%M:%S}] round={round_id} quotes={len(quotes)} "
            f"fast={stats['fast_signal_count']} total_buy_candidates={stats['total_buy_candidate_count']} "
            f"tdx_candidates={stats['tdx_candidate_count']} sell_candidates={stats['sell_candidate_count']} "
            f"chip_candidates={stats['chip_candidate_count']} signals={written} "
            f"read={read_ms:.2f}ms calc={calc_ms:.2f}ms write={write_ms:.2f}ms elapsed={elapsed_ms:.2f}ms"
        )
        if args.once:
            break


if __name__ == "__main__":
    main()
