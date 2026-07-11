from __future__ import annotations

import sys
from pathlib import Path

import backtrader as bt
import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from models.zxw_factor_check_sell_signal_profit20_step_position.profit_threshold_strategy import (  # noqa: E402
    FactorCheckSellSignalProfit20StepPositionZxwStrategy,
)
from models.zxw_data_pipeline.zxw_view_results_full import COMMISSION, FactorPandasData  # noqa: E402


INITIAL_CASH = 1_000_000.0


def _make_feed(code: str) -> bt.feeds.PandasData:
    closes = [10.0, 10.0, 11.5, 12.5, 13.0, 15.2, 20.2, 20.5, 20.6]
    sell_signals = [0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    dates = pd.bdate_range(start="2022-01-03", periods=len(closes))
    df = pd.DataFrame(
        {
            "time": dates,
            "open": closes,
            "high": [x * 1.01 for x in closes],
            "low": [x * 0.99 for x in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
            "strong_buy_signal": [1.0] * len(closes),
            "strong_sell_signal": sell_signals,
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
    cerebro.adddata(_make_feed("P20.SZ"))
    cerebro.addstrategy(
        FactorCheckSellSignalProfit20StepPositionZxwStrategy,
        backtest_start="2022-01-01",
        max_weight=0.02,
        cash_ratio_gate=1.0,
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
        if row.get("status") == "Completed" and row.get("code") == "P20.SZ"
    ]
    sells = [r for r in rows if r.get("signal") == "FACTOR_CHECK_SELL_SIGNAL_PROFIT20_STEP_POSITION"]
    print("completed_orders=", rows)
    assert len(sells) == 5, f"expected five profit-gated step sells, got {len(sells)}"
    assert str(sells[0]["date"]) == "2022-01-06", f"first valid sell should wait for >20% profit: {sells[0]}"

    initial_buy = next(r for r in rows if r.get("side") == "BUY")
    base_size = abs(float(initial_buy["executed_size"]))
    expected_sold = [0.1, 0.2, 0.3, 0.8, 0.9]
    cumulative = 0.0
    for sell, expected_ratio in zip(sells, expected_sold):
        cumulative += abs(float(sell["executed_size"]))
        actual_ratio = cumulative / base_size
        assert abs(actual_ratio - expected_ratio) < 0.02, (
            f"expected cumulative sold near {expected_ratio:.0%}, got {actual_ratio:.2%}; "
            f"base_size={base_size}, sell={sell}"
        )
