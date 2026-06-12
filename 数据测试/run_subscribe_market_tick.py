#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""全市场 Tick 实时订阅：股票池来自 universe.parquet，持续 2 分钟，合并为一个 CSV。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Lock

import pandas as pd
import polars as pl
from insight_python.com.insight import common
from insight_python.com.insight.market_service import market_service
from insight_python.com.insight.subscribe import subscribe_tick_by_type

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = Path(__file__).resolve().parent
UNIVERSE_PATH = ROOT_DIR / "全市场股票代码" / "universe.parquet"
TYPE_QUERY = [("XSHG", "stock"), ("XSHE", "stock")]
DURATION_SEC = 120
PROGRESS_INTERVAL_SEC = 30

USER = "MDIL1_01042"
PASSWORD = "weS._+7atE4Vdr"


class TickCollector:
    def __init__(self, allowed_codes: set[str]) -> None:
        self._lock = Lock()
        self._allowed_codes = allowed_codes
        self._rows: list[dict] = []
        self._total_received = 0
        self._total_kept = 0

    def on_tick(self, result) -> None:
        if result is None:
            return
        items = result if isinstance(result, list) else [result]
        with self._lock:
            for item in items:
                if not isinstance(item, dict):
                    continue
                self._total_received += 1
                code = str(item.get("htsc_code") or item.get("HTSC_CODE") or "")
                if code in self._allowed_codes:
                    self._rows.append(item)
                    self._total_kept += 1

    def take_all(self) -> list[dict]:
        with self._lock:
            rows = list(self._rows)
            self._rows.clear()
            return rows

    def snapshot_stats(self) -> dict:
        with self._lock:
            return {
                "buffer_rows": len(self._rows),
                "total_received": self._total_received,
                "total_kept": self._total_kept,
            }


COLLECTOR: TickCollector | None = None
UNIVERSE_DF: pd.DataFrame | None = None


class InsightMarketService(market_service):
    def on_subscribe_tick(self, result):
        if COLLECTOR is not None:
            COLLECTOR.on_tick(result)


def load_universe(path: Path, only_listed: bool) -> tuple[set[str], pd.DataFrame]:
    if not path.exists():
        raise FileNotFoundError(f"universe 文件不存在: {path}")
    df = pl.read_parquet(path)
    if "htsc_code" not in df.columns:
        raise ValueError("universe.parquet 缺少 htsc_code 列")
    if only_listed and "listing_state" in df.columns:
        df = df.filter(pl.col("listing_state") == "上市交易")
    pdf = df.to_pandas()
    codes = {str(c).strip().upper() for c in pdf["htsc_code"].tolist() if c}
    return codes, pdf


def login() -> None:
    markets = InsightMarketService()
    result = common.login(markets, USER, PASSWORD, login_log=False)
    print(f"[login] {result}")


def fini() -> None:
    try:
        common.fini()
    except Exception as exc:
        print(f"[fini] common.fini: {exc}")


def rows_to_dataframe(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    try:
        df = pd.json_normalize(rows, sep="_")
    except Exception:
        df = pd.DataFrame(rows)
    if UNIVERSE_DF is not None and not df.empty and "htsc_code" in df.columns:
        meta = UNIVERSE_DF.drop_duplicates(subset=["htsc_code"]).copy()
        meta["htsc_code"] = meta["htsc_code"].astype(str).str.upper()
        df["htsc_code"] = df["htsc_code"].astype(str).str.upper()
        df = df.merge(meta, on="htsc_code", how="left", suffixes=("", "_universe"))
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.sort_values(["time", "htsc_code"], na_position="last")
    return df


def save_csv(rows: list[dict], csv_path: Path) -> int:
    df = rows_to_dataframe(rows)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return len(df)


def append_log(line: str) -> None:
    log_path = OUTPUT_DIR / "run_log.txt"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {line}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="全市场 Tick 实时订阅测试")
    parser.add_argument("--universe", type=Path, default=UNIVERSE_PATH, help="股票池 parquet")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="CSV 输出目录")
    parser.add_argument("--duration-sec", type=int, default=DURATION_SEC, help="采集时长（秒）")
    parser.add_argument(
        "--include-delisted",
        action="store_true",
        help="包含 universe 中终止上市股票（默认仅上市交易）",
    )
    return parser.parse_args()


def main() -> int:
    global COLLECTOR, UNIVERSE_DF, OUTPUT_DIR

    args = parse_args()
    OUTPUT_DIR = args.output_dir.resolve()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    only_listed = not args.include_delisted
    allowed_codes, universe_pdf = load_universe(args.universe.resolve(), only_listed=only_listed)
    UNIVERSE_DF = universe_pdf

    COLLECTOR = TickCollector(allowed_codes)
    append_log(f"run_subscribe_market_tick.py 启动 run_tag={run_tag}, universe={len(allowed_codes)} 只")
    print(common.get_version())
    print(f"[universe] {args.universe} -> {len(allowed_codes)} 只")
    print(f"[plan] tick, duration={args.duration_sec}s, 单文件输出")

    login()
    common.config(False, False, False)

    subscribe_tick_by_type(query=TYPE_QUERY, mode="coverage")
    print("[subscribe] subscribe_tick_by_type 已发起 (XSHG/XSHE stock)")

    start = time.time()
    next_progress = start + PROGRESS_INTERVAL_SEC
    while True:
        now = time.time()
        elapsed = now - start
        if elapsed >= args.duration_sec:
            break
        if now >= next_progress:
            stats = COLLECTOR.snapshot_stats()
            print(
                f"[progress] elapsed={int(elapsed)}s, "
                f"buffer={stats['buffer_rows']}, total_kept={stats['total_kept']}"
            )
            next_progress += PROGRESS_INTERVAL_SEC
        time.sleep(1)

    all_rows = COLLECTOR.take_all()
    csv_path = OUTPUT_DIR / f"market_tick_{run_tag}.csv"
    row_count = save_csv(all_rows, csv_path)
    stats = COLLECTOR.snapshot_stats()

    summary = {
        "run_tag": run_tag,
        "universe_file": str(args.universe.resolve()),
        "universe_count": len(allowed_codes),
        "duration_sec": args.duration_sec,
        "total_rows_saved": row_count,
        "total_received": stats["total_received"],
        "total_kept": stats["total_kept"],
        "csv": str(csv_path),
    }
    summary_path = OUTPUT_DIR / f"market_tick_{run_tag}_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    unique_codes = rows_to_dataframe(all_rows)["htsc_code"].nunique() if all_rows else 0
    print(f"\n[done] rows={row_count}, unique_codes={unique_codes}, file={csv_path.name}")
    print(f"[done] summary -> {summary_path.name}")
    append_log(f"done tick rows={row_count}, file={csv_path.name}")

    fini()
    return 0


if __name__ == "__main__":
    sys.exit(main())
