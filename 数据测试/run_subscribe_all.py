#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""华泰 Insight 实时订阅 7 接口联调：登录 → 逐接口订阅 → 等待回调 → 落 CSV。"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread

import pandas as pd
from insight_python.com.interface.mdc_gateway_base_define import GateWayServerConfig
from insight_python.com.insight import common, subscribe
from insight_python.com.insight.market_service import market_service
from insight_python.com.insight.subscribe import (
    subscribe_derived,
    subscribe_kline_by_id,
    subscribe_kline_by_type,
    subscribe_tick_by_id,
    subscribe_tick_by_type,
    subscribe_trans_and_order_by_id,
    subscribe_trans_and_order_by_type,
)

OUTPUT_DIR = Path(__file__).resolve().parent
WAIT_SEC = 30
MAX_ROWS_BY_TYPE = 500
STOCK_CODES = ["601688.SH", "000001.SZ"]
STOCK_CODE_SET = set(STOCK_CODES)
TYPE_QUERY = [("XSHG", "stock"), ("XSHE", "stock")]
KLINE_FREQUENCY = ["15s", "1min"]
DERIVED_TYPE = "north_bound"
DERIVED_CODES = ["SCHKSBSH.HT", "SCHKSBSZ.HT", "SCSHNBHK.HT", "SCSZNBHK.HT"]

USER = "MDIL1_01042"
PASSWORD = "weS._+7atE4Vdr"


class SubscribeCollector:
    def __init__(self) -> None:
        self._lock = Lock()
        self._buffers: dict[str, list[dict]] = {
            "tick": [],
            "kline": [],
            "trans_and_order": [],
            "derived": [],
        }
        self._active_case = ""

    def set_active_case(self, case_name: str) -> None:
        with self._lock:
            self._active_case = case_name
            for key in self._buffers:
                self._buffers[key] = []

    def _append(self, bucket: str, result) -> None:
        if result is None:
            return
        items = result if isinstance(result, list) else [result]
        with self._lock:
            for item in items:
                if isinstance(item, dict):
                    self._buffers[bucket].append(item)

    def snapshot(self, bucket: str, *, filter_codes: set[str] | None = None, max_rows: int | None = None) -> list[dict]:
        with self._lock:
            rows = list(self._buffers[bucket])
        if filter_codes:
            filtered: list[dict] = []
            for row in rows:
                code = str(row.get("htsc_code") or row.get("HTSC_CODE") or row.get("security_id") or "")
                if code in filter_codes:
                    filtered.append(row)
            rows = filtered
        if max_rows is not None and len(rows) > max_rows:
            rows = rows[:max_rows]
        return rows

    def on_tick(self, result) -> None:
        self._append("tick", result)

    def on_kline(self, result) -> None:
        self._append("kline", result)

    def on_trans_and_order(self, result) -> None:
        self._append("trans_and_order", result)

    def on_derived(self, result) -> None:
        self._append("derived", result)


COLLECTOR = SubscribeCollector()


class InsightMarketService(market_service):
    def on_subscribe_tick(self, result):
        COLLECTOR.on_tick(result)

    def on_subscribe_kline(self, result):
        COLLECTOR.on_kline(result)

    def on_subscribe_trans_and_order(self, result):
        COLLECTOR.on_trans_and_order(result)

    def on_subscribe_derived(self, result):
        COLLECTOR.on_derived(result)


def login() -> None:
    markets = InsightMarketService()
    result = common.login(markets, USER, PASSWORD, login_log=False)
    print(f"[login] {result}")


def fini() -> None:
    def _sync() -> None:
        try:
            if GateWayServerConfig.IsRealTimeData:
                subscribe.sync()
        except Exception as exc:
            print(f"[fini] subscribe.sync: {exc}")

    sync_thread = Thread(target=_sync, daemon=True)
    sync_thread.start()
    sync_thread.join(timeout=5)
    if sync_thread.is_alive():
        print("[fini] subscribe.sync 超时，跳过")

    try:
        common.fini()
    except Exception as exc:
        print(f"[fini] common.fini: {exc}")


def rows_to_dataframe(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    try:
        return pd.json_normalize(rows, sep="_")
    except Exception:
        return pd.DataFrame(rows)


def save_csv(case_name: str, rows: list[dict]) -> Path:
    csv_path = OUTPUT_DIR / f"{case_name}.csv"
    df = rows_to_dataframe(rows)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path


def append_log(lines: list[str]) -> None:
    log_path = OUTPUT_DIR / "run_log.txt"
    header = f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(lines))
        f.write("\n")


def run_case(
    case_name: str,
    subscribe_fn,
    bucket: str,
    *,
    filter_codes: set[str] | None = None,
    max_rows: int | None = None,
) -> dict:
    print(f"\n[case] {case_name} 开始，等待 {WAIT_SEC}s ...")
    COLLECTOR.set_active_case(case_name)
    try:
        subscribe_fn()
    except Exception as exc:
        msg = f"{case_name}: subscribe 失败 -> {exc}"
        print(msg)
        append_log([msg])
        return {"case": case_name, "status": "subscribe_error", "rows": 0, "error": str(exc)}

    time.sleep(WAIT_SEC)
    rows = COLLECTOR.snapshot(bucket, filter_codes=filter_codes, max_rows=max_rows)
    csv_path = save_csv(case_name, rows)
    status = "ok" if rows else "empty"
    summary = f"{case_name}: {status}, rows={len(rows)}, file={csv_path.name}"
    print(summary)
    append_log([summary])
    return {"case": case_name, "status": status, "rows": len(rows), "file": str(csv_path)}


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    append_log(["run_subscribe_all.py 启动"])
    print(common.get_version())

    login()
    common.config(False, False, False)

    cases = [
        (
            "subscribe_tick_by_id",
            lambda: subscribe_tick_by_id(htsc_code=STOCK_CODES, mode="coverage"),
            "tick",
            {"filter_codes": STOCK_CODE_SET, "max_rows": None},
        ),
        (
            "subscribe_kline_by_id",
            lambda: subscribe_kline_by_id(
                htsc_code=STOCK_CODES, frequency=KLINE_FREQUENCY, mode="coverage"
            ),
            "kline",
            {"filter_codes": STOCK_CODE_SET, "max_rows": None},
        ),
        (
            "subscribe_trans_and_order_by_id",
            lambda: subscribe_trans_and_order_by_id(htsc_code=STOCK_CODES, mode="coverage"),
            "trans_and_order",
            {"filter_codes": STOCK_CODE_SET, "max_rows": None},
        ),
        (
            "subscribe_tick_by_type",
            lambda: subscribe_tick_by_type(query=TYPE_QUERY, mode="coverage"),
            "tick",
            {"filter_codes": STOCK_CODE_SET, "max_rows": MAX_ROWS_BY_TYPE},
        ),
        (
            "subscribe_kline_by_type",
            lambda: subscribe_kline_by_type(
                query=TYPE_QUERY, frequency=KLINE_FREQUENCY, mode="coverage"
            ),
            "kline",
            {"filter_codes": STOCK_CODE_SET, "max_rows": MAX_ROWS_BY_TYPE},
        ),
        (
            "subscribe_trans_and_order_by_type",
            lambda: subscribe_trans_and_order_by_type(query=TYPE_QUERY, mode="coverage"),
            "trans_and_order",
            {"filter_codes": STOCK_CODE_SET, "max_rows": MAX_ROWS_BY_TYPE},
        ),
        (
            "subscribe_derived",
            lambda: subscribe_derived(
                type=DERIVED_TYPE,
                htsc_code=DERIVED_CODES,
                frequency="1min",
                mode="coverage",
            ),
            "derived",
            {"filter_codes": None, "max_rows": MAX_ROWS_BY_TYPE},
        ),
    ]

    results = []
    for case_name, fn, bucket, opts in cases:
        results.append(run_case(case_name, fn, bucket, **opts))

    summary_path = OUTPUT_DIR / "run_summary.json"
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[done] summary -> {summary_path}")

    fini()
    return 0


if __name__ == "__main__":
    sys.exit(main())
