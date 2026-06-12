#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""全市场 1 分钟 K 线实时订阅：股票池来自 universe.parquet，持续 5 分钟，按分钟落 CSV。"""

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
from insight_python.com.insight.subscribe import subscribe_kline_by_type

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = Path(__file__).resolve().parent
UNIVERSE_PATH = ROOT_DIR / "全市场股票代码" / "universe.parquet"
TYPE_QUERY = [("XSHG", "stock"), ("XSHE", "stock")]
KLINE_FREQUENCY = ["1min"]
DURATION_SEC = 300
FLUSH_INTERVAL_SEC = 60

USER = "MDIL1_01042"
PASSWORD = "weS._+7atE4Vdr"


class KlineCollector:
    def __init__(self, allowed_codes: set[str]) -> None:
        self._lock = Lock()
        self._allowed_codes = allowed_codes
        self._rows: list[dict] = []
        self._total_received = 0
        self._total_kept = 0

    def on_kline(self, result) -> None:
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

    def pop_all(self) -> list[dict]:
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


COLLECTOR: KlineCollector | None = None
UNIVERSE_DF: pd.DataFrame | None = None


class InsightMarketService(market_service):
    def on_subscribe_kline(self, result):
        if COLLECTOR is not None:
            COLLECTOR.on_kline(result)


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
    # subscribe.sync() 会阻塞等待 stdin，批量采集结束后直接释放连接即可
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
    parser = argparse.ArgumentParser(description="全市场 1 分钟 K 线实时订阅测试")
    parser.add_argument("--universe", type=Path, default=UNIVERSE_PATH, help="股票池 parquet")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="CSV 输出目录")
    parser.add_argument("--duration-sec", type=int, default=DURATION_SEC, help="采集时长（秒）")
    parser.add_argument("--flush-interval-sec", type=int, default=FLUSH_INTERVAL_SEC, help="按分钟落盘间隔（秒）")
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

    COLLECTOR = KlineCollector(allowed_codes)
    append_log(
        f"run_subscribe_market_1min.py 启动 run_tag={run_tag}, universe={len(allowed_codes)} 只"
    )
    print(common.get_version())
    print(f"[universe] {args.universe} -> {len(allowed_codes)} 只")
    print(f"[plan] 1min kline, duration={args.duration_sec}s, flush={args.flush_interval_sec}s")

    login()
    common.config(False, False, False)

    subscribe_kline_by_type(query=TYPE_QUERY, frequency=KLINE_FREQUENCY, mode="coverage")
    print("[subscribe] subscribe_kline_by_type 已发起 (XSHG/XSHE stock, 1min)")

    start = time.time()
    next_flush = start + args.flush_interval_sec
    part_idx = 1
    all_rows: list[dict] = []
    part_files: list[dict] = []

    while True:
        now = time.time()
        elapsed = now - start
        if elapsed >= args.duration_sec:
            break

        if now >= next_flush:
            part_rows = COLLECTOR.pop_all()
            all_rows.extend(part_rows)
            part_name = f"market_1min_kline_{run_tag}_part{part_idx:02d}.csv"
            part_path = OUTPUT_DIR / part_name
            n = save_csv(part_rows, part_path)
            stats = COLLECTOR.snapshot_stats()
            msg = (
                f"part{part_idx:02d}: rows={n}, elapsed={int(elapsed)}s, "
                f"total_kept={stats['total_kept']}, file={part_name}"
            )
            print(msg)
            append_log(msg)
            part_files.append({"part": part_idx, "rows": n, "file": str(part_path)})
            part_idx += 1
            next_flush += args.flush_interval_sec

        time.sleep(1)

    tail_rows = COLLECTOR.pop_all()
    all_rows.extend(tail_rows)
    if tail_rows:
        part_name = f"market_1min_kline_{run_tag}_part{part_idx:02d}.csv"
        part_path = OUTPUT_DIR / part_name
        n = save_csv(tail_rows, part_path)
        part_files.append({"part": part_idx, "rows": n, "file": str(part_path)})
        print(f"[tail] part{part_idx:02d}: rows={n}, file={part_name}")
        append_log(f"tail part{part_idx:02d}: rows={n}, file={part_name}")

    all_path = OUTPUT_DIR / f"market_1min_kline_{run_tag}_all.csv"
    all_count = save_csv(all_rows, all_path)
    stats = COLLECTOR.snapshot_stats()

    summary = {
        "run_tag": run_tag,
        "universe_file": str(args.universe.resolve()),
        "universe_count": len(allowed_codes),
        "duration_sec": args.duration_sec,
        "total_rows_saved": all_count,
        "total_received": stats["total_received"],
        "total_kept": stats["total_kept"],
        "all_csv": str(all_path),
        "part_files": part_files,
    }
    summary_path = OUTPUT_DIR / f"market_1min_kline_{run_tag}_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"\n[done] all_rows={all_count}, unique_codes="
        f"{rows_to_dataframe(all_rows)['htsc_code'].nunique() if all_rows else 0}, file={all_path.name}"
    )
    print(f"[done] summary -> {summary_path.name}")
    append_log(f"done all_rows={all_count}, file={all_path.name}")

    fini()
    return 0


if __name__ == "__main__":
    sys.exit(main())
