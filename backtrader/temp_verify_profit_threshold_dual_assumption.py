from __future__ import annotations

import sys
from pathlib import Path

import backtrader as bt
import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from models.zxw_factor_check_profit_threshold_dual_assumption.profit_threshold_strategy import (  # noqa: E402
    FactorCheckProfitThresholdDualAssumptionZxwStrategy,
)
from models.zxw_data_pipeline.zxw_view_results_full import COMMISSION, FactorPandasData  # noqa: E402


INITIAL_CASH = 1_000_000.0


def _make_feed(code: str) -> bt.feeds.PandasData:
    dates = pd.bdate_range(start="2022-01-03", periods=9)
    closes = [10.0, 10.0, 15.1, 16.0, 17.0, 17.5, 20.1, 10.0, 10.0]
    df = pd.DataFrame(
        {
            "time": dates,
            "open": closes,
            "high": [x * 1.01 for x in closes],
            "low": [x * 0.99 for x in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
            "strong_buy_signal": [1.0] * len(closes),
            "strong_sell_signal": [0.0] * len(closes),
            "block_halving_future_buy": [0.0] * len(closes),
        }
    )
    data = FactorPandasData(
        dataname=df,
        datetime="time",
        open="open",
        high="high",
        low="low",
        close="close",
        volume="volume",
        openinterest=-1,
        strong_buy_signal="strong_buy_signal",
        strong_sell_signal="strong_sell_signal",
        block_halving_future_buy="block_halving_future_buy",
        timeframe=bt.TimeFrame.Days,
    )
    data._name = code
    return data


def run_case() -> list[dict[str, object]]:
    cerebro = bt.Cerebro()
    cerebro.broker.set_coc(True)
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)
    cerebro.adddata(_make_feed("THRESH.SZ"))
    cerebro.addstrategy(
        FactorCheckProfitThresholdDualAssumptionZxwStrategy,
        backtest_start="2022-01-01",
        max_weight=0.02,
        cash_ratio_gate=0.0,
        initial_target_weight_by_code={},
        daily_move_limit=2.0,
        half_profit_multiplier=1.5,
        full_profit_multiplier=2.0,
    )
    strat = cerebro.run()[0]
    return strat.order_log


if __name__ == "__main__":
    rows = [
        row
        for row in run_case()
        if row.get("status") == "Completed" and row.get("code") == "THRESH.SZ"
    ]
    half_sells = [r for r in rows if r.get("signal") == "PROFIT_GT_150_SELL_HALF_LOCK_BUY"]
    full_sells = [r for r in rows if r.get("signal") == "PROFIT_GT_200_FULL_CLOSE_UNLOCK_BUY"]
    buys_after_half = [
        r
        for r in rows
        if r.get("side") == "BUY" and str(r.get("date")) > str(half_sells[0].get("date"))
    ] if half_sells else []
    buys_after_full = [
        r
        for r in rows
        if full_sells and r.get("side") == "BUY" and str(r.get("date")) > str(full_sells[0].get("date"))
    ]
    print("completed_orders=", rows)
    assert len(half_sells) == 1, f"expected one half sell, got {len(half_sells)}"
    assert len(full_sells) == 1, f"expected one full close, got {len(full_sells)}"
    assert buys_after_full, "expected buy to unlock after full close"
    forbidden_buys = [
        r
        for r in buys_after_half
        if str(r.get("date")) < str(full_sells[0].get("date"))
    ]
    assert not forbidden_buys, f"expected no buy after half sell before full close, got {forbidden_buys}"
