#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""全市场订阅延迟测试：1min 采 1 次，tick 采 5 次，每行记录发令/收包时间与间隔。"""

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
from insight_python.com.insight.subscribe import subscribe_kline_by_type, subscribe_tick_by_type

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = Path(__file__).resolve().parent
UNIVERSE_PATH = ROOT_DIR / "全市场股票代码" / "universe.parquet"
TYPE_QUERY = [("XSHG", "stock"), ("XSHE", "stock")]
KLINE_FREQUENCY = ["1min"]
KLINE_DURATION_SEC = 120
TICK_ROUNDS = 5
TICK_ROUND_DURATION_SEC = 30

USER = "MDIL1_01042"
PASSWORD = "weS._+7atE4Vdr"


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


class LatencyCollector:
    def __init__(self, allowed_codes: set[str]) -> None:
        self._lock = Lock()
        self._allowed_codes = allowed_codes
        self._rows: list[dict] = []
        self._cmd_at: str = ""
        self._ack_at: str = ""
        self._cmd_mono: float = 0.0
        self._ack_mono: float = 0.0
        self._round_no: int = 0
        self._kind: str = ""

    def begin_round(self, kind: str, round_no: int) -> None:
        with self._lock:
            self._rows.clear()
            self._kind = kind
            self._round_no = round_no
            self._cmd_at = ""
            self._ack_at = ""
            self._cmd_mono = 0.0
            self._ack_mono = 0.0

    def mark_cmd_before(self) -> None:
        with self._lock:
            self._cmd_mono = time.perf_counter()
            self._cmd_at = now_iso()

    def mark_cmd_after(self) -> None:
        with self._lock:
            self._ack_mono = time.perf_counter()
            self._ack_at = now_iso()

    def _stamp_row(self, item: dict, recv_mono: float, recv_at: str) -> dict:
        row = dict(item)
        row["data_kind"] = self._kind
        row["round_no"] = self._round_no
        row["subscribe_cmd_at"] = self._cmd_at
        row["subscribe_ack_at"] = self._ack_at
        row["recv_at"] = recv_at
        row["latency_from_cmd_ms"] = round((recv_mono - self._cmd_mono) * 1000, 3) if self._cmd_mono else None
        row["latency_from_ack_ms"] = round((recv_mono - self._ack_mono) * 1000, 3) if self._ack_mono else None
        market_time = row.get("time") or row.get("trading_day")
        row["market_data_time"] = market_time
        return row

    def on_tick(self, result) -> None:
        if result is None:
            return
        recv_mono = time.perf_counter()
        recv_at = now_iso()
        items = result if isinstance(result, list) else [result]
        with self._lock:
            for item in items:
                if not isinstance(item, dict):
                    continue
                code = str(item.get("htsc_code") or item.get("HTSC_CODE") or "")
                if code in self._allowed_codes:
                    self._rows.append(self._stamp_row(item, recv_mono, recv_at))

    def on_kline(self, result) -> None:
        self.on_tick(result)

    def take_all(self) -> list[dict]:
        with self._lock:
            rows = list(self._rows)
            self._rows.clear()
            return rows

    def round_meta(self) -> dict:
        with self._lock:
            return {
                "kind": self._kind,
                "round_no": self._round_no,
                "subscribe_cmd_at": self._cmd_at,
                "subscribe_ack_at": self._ack_at,
            }


COLLECTOR: LatencyCollector | None = None
UNIVERSE_DF: pd.DataFrame | None = None
UNIVERSE_COUNT = 0


class InsightMarketService(market_service):
    def on_subscribe_tick(self, result):
        if COLLECTOR is not None:
            COLLECTOR.on_tick(result)

    def on_subscribe_kline(self, result):
        if COLLECTOR is not None:
            COLLECTOR.on_kline(result)


def load_universe(path: Path, only_listed: bool) -> tuple[set[str], pd.DataFrame]:
    if not path.exists():
        raise FileNotFoundError(f"universe 文件不存在: {path}")
    df = pl.read_parquet(path)
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
        print(f"[fini] {exc}")


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
    sort_cols = [c for c in ["data_kind", "round_no", "recv_at", "htsc_code"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols, na_position="last")
    return df


def save_csv(rows: list[dict], path: Path) -> int:
    df = rows_to_dataframe(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return len(df)


def build_round_summary(rows: list[dict], meta: dict) -> dict:
    if not rows:
        return {**meta, "rows": 0, "unique_codes": 0}

    df = pd.DataFrame(rows)
    lat = df["latency_from_cmd_ms"].dropna()
    codes = df["htsc_code"].nunique() if "htsc_code" in df.columns else 0

    first_idx = lat.idxmin() if not lat.empty else None
    last_idx = lat.idxmax() if not lat.empty else None

    summary = {
        **meta,
        "rows": len(df),
        "unique_codes": int(codes),
        "universe_count": UNIVERSE_COUNT,
        "coverage_ratio": round(codes / UNIVERSE_COUNT, 4) if UNIVERSE_COUNT else None,
        "latency_from_cmd_ms_min": float(lat.min()) if not lat.empty else None,
        "latency_from_cmd_ms_max": float(lat.max()) if not lat.empty else None,
        "latency_from_cmd_ms_mean": round(float(lat.mean()), 3) if not lat.empty else None,
        "latency_from_cmd_ms_median": round(float(lat.median()), 3) if not lat.empty else None,
        "first_recv_at": df.loc[first_idx, "recv_at"] if first_idx is not None else None,
        "last_recv_at": df.loc[last_idx, "recv_at"] if last_idx is not None else None,
        "full_market_span_ms": round(float(lat.max() - lat.min()), 3) if len(lat) > 1 else None,
    }
    return summary


def wait_collect(duration_sec: int, label: str) -> None:
    start = time.time()
    while time.time() - start < duration_sec:
        elapsed = int(time.time() - start)
        if elapsed > 0 and elapsed % 15 == 0:
            print(f"  [{label}] elapsed={elapsed}s ...")
        time.sleep(1)


def run_kline_round() -> tuple[list[dict], dict]:
    assert COLLECTOR is not None
    COLLECTOR.begin_round("1min", 1)
    print(f"\n[1min] round=1, collect={KLINE_DURATION_SEC}s")
    COLLECTOR.mark_cmd_before()
    subscribe_kline_by_type(query=TYPE_QUERY, frequency=KLINE_FREQUENCY, mode="coverage")
    COLLECTOR.mark_cmd_after()
    meta = COLLECTOR.round_meta()
    print(f"  cmd_at={meta['subscribe_cmd_at']}, ack_at={meta['subscribe_ack_at']}")
    wait_collect(KLINE_DURATION_SEC, "1min")
    rows = COLLECTOR.take_all()
    summary = build_round_summary(rows, meta)
    print(
        f"  done rows={summary['rows']}, codes={summary['unique_codes']}, "
        f"latency_ms min/mean/max={summary['latency_from_cmd_ms_min']}/"
        f"{summary['latency_from_cmd_ms_mean']}/{summary['latency_from_cmd_ms_max']}, "
        f"full_market_span_ms={summary['full_market_span_ms']}"
    )
    return rows, summary


def run_tick_round(round_no: int) -> tuple[list[dict], dict]:
    assert COLLECTOR is not None
    COLLECTOR.begin_round("tick", round_no)
    print(f"\n[tick] round={round_no}/{TICK_ROUNDS}, collect={TICK_ROUND_DURATION_SEC}s")
    COLLECTOR.mark_cmd_before()
    subscribe_tick_by_type(query=TYPE_QUERY, mode="coverage")
    COLLECTOR.mark_cmd_after()
    meta = COLLECTOR.round_meta()
    print(f"  cmd_at={meta['subscribe_cmd_at']}, ack_at={meta['subscribe_ack_at']}")
    wait_collect(TICK_ROUND_DURATION_SEC, f"tick-{round_no}")
    rows = COLLECTOR.take_all()
    summary = build_round_summary(rows, meta)
    print(
        f"  done rows={summary['rows']}, codes={summary['unique_codes']}, "
        f"latency_ms min/mean/max={summary['latency_from_cmd_ms_min']}/"
        f"{summary['latency_from_cmd_ms_mean']}/{summary['latency_from_cmd_ms_max']}, "
        f"full_market_span_ms={summary['full_market_span_ms']}"
    )
    return rows, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="全市场订阅延迟测试")
    parser.add_argument("--universe", type=Path, default=UNIVERSE_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--kline-duration-sec", type=int, default=KLINE_DURATION_SEC)
    parser.add_argument("--tick-rounds", type=int, default=TICK_ROUNDS)
    parser.add_argument("--tick-round-duration-sec", type=int, default=TICK_ROUND_DURATION_SEC)
    return parser.parse_args()


def main() -> int:
    global COLLECTOR, UNIVERSE_DF, UNIVERSE_COUNT, OUTPUT_DIR
    global KLINE_DURATION_SEC, TICK_ROUNDS, TICK_ROUND_DURATION_SEC

    args = parse_args()
    OUTPUT_DIR = args.output_dir.resolve()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    KLINE_DURATION_SEC = args.kline_duration_sec
    TICK_ROUNDS = args.tick_rounds
    TICK_ROUND_DURATION_SEC = args.tick_round_duration_sec

    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    allowed_codes, universe_pdf = load_universe(args.universe.resolve(), only_listed=True)
    UNIVERSE_DF = universe_pdf
    UNIVERSE_COUNT = len(allowed_codes)
    COLLECTOR = LatencyCollector(allowed_codes)

    print(common.get_version())
    print(f"[universe] {UNIVERSE_COUNT} 只")
    print(f"[plan] 1min x1 ({KLINE_DURATION_SEC}s), tick x{TICK_ROUNDS} ({TICK_ROUND_DURATION_SEC}s/round)")

    login()
    common.config(False, False, False)

    all_rows: list[dict] = []
    summaries: list[dict] = []

    kline_rows, kline_summary = run_kline_round()
    all_rows.extend(kline_rows)
    summaries.append(kline_summary)

    for i in range(1, TICK_ROUNDS + 1):
        tick_rows, tick_summary = run_tick_round(i)
        all_rows.extend(tick_rows)
        summaries.append(tick_summary)
        if i < TICK_ROUNDS:
            time.sleep(2)

    merged_csv = OUTPUT_DIR / f"subscribe_latency_{run_tag}.csv"
    row_count = save_csv(all_rows, merged_csv)

    summary_path = OUTPUT_DIR / f"subscribe_latency_{run_tag}_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "run_tag": run_tag,
                "universe_count": UNIVERSE_COUNT,
                "total_rows": row_count,
                "merged_csv": str(merged_csv),
                "rounds": summaries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n[done] merged rows={row_count}, file={merged_csv.name}")
    print(f"[done] summary -> {summary_path.name}")
    fini()
    return 0


if __name__ == "__main__":
    sys.exit(main())
