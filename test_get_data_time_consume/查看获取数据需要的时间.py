#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""测试 xtquant 不同接口获取全市场数据的耗时，并导出 Excel。"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from xtquant import xtdata

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


OUTPUT_DIR = Path(__file__).resolve().parent
DEFAULT_SECTOR_NAME = "\u6caa\u6df1A\u80a1"
DEFAULT_MARKETS = ["SH", "SZ"]
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_TARGET_RATIO = 0.95
MARKET_DATA_FIELDS = ["time", "open", "high", "low", "close", "volume", "amount"]


def normalize_code(code: str) -> str:
    return str(code).strip().upper()


def load_sector_stocks(sector_name: str) -> list[str]:
    start = time.perf_counter()
    xtdata.download_sector_data()
    stock_list = xtdata.get_stock_list_in_sector(sector_name)
    elapsed = time.perf_counter() - start
    stocks = sorted({normalize_code(code) for code in stock_list if str(code).strip()})
    if not stocks:
        raise RuntimeError(f"xtquant 板块股票池为空: {sector_name}")
    print(f"[OK] 股票池 {sector_name}: {len(stocks)} 只 | 耗时 {elapsed:.3f}s")
    return stocks


def _json_safe(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def flatten_mapping(mapping: Any, max_rows: int | None = None) -> pd.DataFrame:
    if not isinstance(mapping, dict):
        return pd.DataFrame([{"key": "", "payload": _json_safe(mapping)}])

    rows: list[dict[str, Any]] = []
    for key, payload in mapping.items():
        row: dict[str, Any] = {"code": normalize_code(key)}
        if isinstance(payload, dict):
            for field, value in payload.items():
                if isinstance(value, (list, tuple, dict)):
                    row[str(field)] = _json_safe(value)
                else:
                    row[str(field)] = value
        else:
            row["payload"] = _json_safe(payload)
        rows.append(row)
        if max_rows is not None and len(rows) >= max_rows:
            break
    return pd.DataFrame(rows)


def flatten_market_data_ex(data: Any, max_rows: int | None = None) -> pd.DataFrame:
    if not isinstance(data, dict):
        return pd.DataFrame([{"code": "", "payload": _json_safe(data)}])

    frames: list[pd.DataFrame] = []
    for code, frame in data.items():
        if frame is None:
            continue
        if isinstance(frame, pd.DataFrame):
            part = frame.copy()
        else:
            part = pd.DataFrame(frame)
        if part.empty:
            continue
        part = part.reset_index()
        part.insert(0, "code", normalize_code(code))
        frames.append(part)
        if max_rows is not None and sum(len(x) for x in frames) >= max_rows:
            break
    if not frames:
        return pd.DataFrame(columns=["code"])
    out = pd.concat(frames, ignore_index=True)
    if max_rows is not None:
        out = out.head(max_rows)
    return out


def run_subscribe_whole_quote(
    markets: list[str],
    stock_list: list[str],
    expected_stock_count: int,
    timeout_seconds: float,
    target_ratio: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    received: dict[str, Any] = {}
    stock_set = set(stock_list)
    first_callback_at: float | None = None
    reached_target_at: float | None = None
    done = threading.Event()
    target_count = max(1, int(expected_stock_count * target_ratio))

    def callback(datas):
        nonlocal first_callback_at, reached_target_at
        now = time.perf_counter()
        if first_callback_at is None:
            first_callback_at = now
        if isinstance(datas, dict):
            received.update(
                {
                    normalize_code(code): payload
                    for code, payload in datas.items()
                    if normalize_code(code) in stock_set
                }
            )
        else:
            received["__payload__"] = datas
        if len(received) >= target_count and reached_target_at is None:
            reached_target_at = now
            done.set()

    start = time.perf_counter()
    seq = xtdata.subscribe_whole_quote(markets, callback)
    runner = threading.Thread(target=xtdata.run, daemon=True)
    runner.start()
    done.wait(timeout_seconds)
    end = reached_target_at or time.perf_counter()

    try:
        xtdata.unsubscribe_quote(seq)
    except Exception as exc:
        print(f"[WARN] unsubscribe_quote 失败: {exc}")

    meta = {
        "method": "subscribe_whole_quote",
        "markets": ",".join(markets),
        "scope": "沪深A股过滤后",
        "subscription_seq": seq,
        "timeout_seconds": timeout_seconds,
        "target_ratio": target_ratio,
        "target_count": target_count,
        "expected_stock_count": expected_stock_count,
        "received_count": len(received),
        "elapsed_seconds": end - start,
        "first_callback_seconds": None if first_callback_at is None else first_callback_at - start,
        "reached_target": reached_target_at is not None,
    }
    return received, meta


def run_get_full_tick(stock_list: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    start = time.perf_counter()
    data = xtdata.get_full_tick(stock_list)
    elapsed = time.perf_counter() - start
    count = len(data) if isinstance(data, dict) else 0
    meta = {
        "method": "get_full_tick",
        "scope": "沪深A股",
        "stock_count": len(stock_list),
        "received_count": count,
        "elapsed_seconds": elapsed,
    }
    return data, meta


def run_get_market_data_ex(stock_list: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    start = time.perf_counter()
    data = xtdata.get_market_data_ex(
        field_list=MARKET_DATA_FIELDS,
        stock_list=stock_list,
        period="1d",
        start_time="",
        end_time="",
        count=1,
        dividend_type="none",
        fill_data=False,
    )
    elapsed = time.perf_counter() - start
    count = len(data) if isinstance(data, dict) else 0
    meta = {
        "method": "get_market_data_ex",
        "period": "1d",
        "field_list": ",".join(MARKET_DATA_FIELDS),
        "stock_count": len(stock_list),
        "received_count": count,
        "elapsed_seconds": elapsed,
    }
    return data, meta


def write_excel(
    output_path: Path,
    stock_list: list[str],
    subscribe_data: dict[str, Any],
    subscribe_meta: dict[str, Any],
    full_tick_data: dict[str, Any],
    full_tick_meta: dict[str, Any],
    market_data_ex: dict[str, Any],
    market_data_meta: dict[str, Any],
    max_rows_per_sheet: int | None,
) -> None:
    stock_df = pd.DataFrame({"htsc_code": stock_list})
    summary_df = pd.DataFrame([subscribe_meta, full_tick_meta, market_data_meta])
    subscribe_df = flatten_mapping(subscribe_data, max_rows=max_rows_per_sheet)
    full_tick_df = flatten_mapping(full_tick_data, max_rows=max_rows_per_sheet)
    market_df = flatten_market_data_ex(market_data_ex, max_rows=max_rows_per_sheet)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="summary", index=False)
        stock_df.to_excel(writer, sheet_name="stock_list", index=False)
        subscribe_df.to_excel(writer, sheet_name="subscribe_whole_quote", index=False)
        full_tick_df.to_excel(writer, sheet_name="get_full_tick", index=False)
        market_df.to_excel(writer, sheet_name="get_market_data_ex", index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="测试 xtquant 全市场数据接口耗时并导出 Excel")
    parser.add_argument("--sector-name", default=DEFAULT_SECTOR_NAME, help="xtquant 板块名称，默认 沪深A股")
    parser.add_argument("--timeout-sec", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="订阅等待超时秒数")
    parser.add_argument("--target-ratio", type=float, default=DEFAULT_TARGET_RATIO, help="订阅达到股票池数量比例后停止等待")
    parser.add_argument("--max-rows-per-sheet", type=int, default=0, help="每个数据 sheet 最多写入行数，0 表示不限制")
    parser.add_argument("--skip-subscribe", action="store_true", help="跳过 subscribe_whole_quote")
    parser.add_argument("--skip-full-tick", action="store_true", help="跳过 get_full_tick")
    parser.add_argument("--skip-market-data-ex", action="store_true", help="跳过 get_market_data_ex")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    max_rows = None if args.max_rows_per_sheet <= 0 else args.max_rows_per_sheet
    output_path = OUTPUT_DIR / f"xtquant_data_time_consume_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    stock_list = load_sector_stocks(args.sector_name)

    if args.skip_subscribe:
        subscribe_data, subscribe_meta = {}, {"method": "subscribe_whole_quote", "skipped": True}
    else:
        print("[RUN] subscribe_whole_quote...")
        subscribe_data, subscribe_meta = run_subscribe_whole_quote(
            DEFAULT_MARKETS,
            stock_list,
            expected_stock_count=len(stock_list),
            timeout_seconds=args.timeout_sec,
            target_ratio=args.target_ratio,
        )
        print(f"[OK] subscribe_whole_quote: {subscribe_meta}")

    if args.skip_full_tick:
        full_tick_data, full_tick_meta = {}, {"method": "get_full_tick", "skipped": True}
    else:
        print("[RUN] get_full_tick...")
        full_tick_data, full_tick_meta = run_get_full_tick(stock_list)
        print(f"[OK] get_full_tick: {full_tick_meta}")

    if args.skip_market_data_ex:
        market_data, market_meta = {}, {"method": "get_market_data_ex", "skipped": True}
    else:
        print("[RUN] get_market_data_ex...")
        market_data, market_meta = run_get_market_data_ex(stock_list)
        print(f"[OK] get_market_data_ex: {market_meta}")

    write_excel(
        output_path,
        stock_list,
        subscribe_data,
        subscribe_meta,
        full_tick_data,
        full_tick_meta,
        market_data,
        market_meta,
        max_rows_per_sheet=max_rows,
    )
    print(f"[OK] Excel 已保存: {output_path}")


if __name__ == "__main__":
    main()
