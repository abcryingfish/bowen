# -*- coding: utf-8 -*-
"""使用统一后复权收盘价重建20日动量因子。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKTRADER_ROOT = PROJECT_ROOT / "backtrader"
if str(BACKTRADER_ROOT) not in sys.path:
    sys.path.append(str(BACKTRADER_ROOT))

from models.style_portfolio_monitor.equal_weight_index import load_adjusted_close  # noqa: E402


MARKET_BASE_DIR = Path(r"D:\database\stock_basic_data_daily")
ADJ_FACTOR_DAILY_DIR = Path(r"D:\database\stock_adj_daily\adj_factor_daily")
WIDE_XDY_DIR = Path(r"D:\database\stock_adj_daily\wide_xdy")
FACTOR_ID = "stock_momentum_20d"
FACTOR_DISPLAY_NAME = "股票20日动量"
OUTPUT_DIR = Path(rf"D:\database\signal_daily\factor={FACTOR_ID}")


def _month_starts(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    cursor = pd.Timestamp(start.year, start.month, 1)
    result: list[pd.Timestamp] = []
    while cursor <= end:
        result.append(cursor)
        cursor += pd.offsets.MonthBegin(1)
    return result


def rebuild_factor(
    *,
    start_date: str | pd.Timestamp = "2010-01-01",
    end_date: str | pd.Timestamp = "2026-08-03",
) -> dict[str, object]:
    start = pd.Timestamp(start_date).floor("D")
    end = pd.Timestamp(end_date).floor("D")
    if start > end:
        raise ValueError("start_date 不能晚于 end_date")

    # 额外读取20个交易日之前的行情，避免区间起点的动量被截断。
    # 本地行情从2010年开始；更早的20个交易日不可用时保留为NaN，
    # 不用未复权价格补齐。
    price_start = max(start - pd.Timedelta(days=90), pd.Timestamp("2010-01-01"))
    prices = load_adjusted_close(
        market_base_dir=MARKET_BASE_DIR,
        adj_factor_daily_dir=ADJ_FACTOR_DAILY_DIR,
        wide_xdy_dir=WIDE_XDY_DIR,
        start_date=price_start,
        end_date=end,
    )
    momentum = prices.div(prices.shift(20)) - 1.0
    output_dates = momentum.index[(momentum.index >= start) & (momentum.index <= end)]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for month in _month_starts(start, end):
        month_end = month + pd.offsets.MonthBegin(1)
        dates = output_dates[(output_dates >= month) & (output_dates < month_end)]
        if len(dates) == 0:
            continue
        frame = momentum.loc[dates].rename_axis("time").stack(future_stack=True).rename("value").reset_index()
        frame.columns = ["time", "htsc_code", "value"]
        frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
        target = OUTPUT_DIR / f"year={month.year}" / f"month={month.month:02d}" / "merged.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(target, index=False)
        written += len(frame)
    return {"start_date": start.date().isoformat(), "end_date": end.date().isoformat(), "rows": written, "months": len(_month_starts(start, end))}


def main() -> None:
    parser = argparse.ArgumentParser(description="重建20日动量后复权因子")
    parser.add_argument("--start-date", default="2010-01-01")
    parser.add_argument("--end-date", default="2026-08-03")
    args = parser.parse_args()
    print(rebuild_factor(start_date=args.start_date, end_date=args.end_date), flush=True)


if __name__ == "__main__":
    main()
