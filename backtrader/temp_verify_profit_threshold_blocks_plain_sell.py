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
from models.zxw_rule_backtest.zxw_view_results_full import COMMISSION, FactorPandasData  # noqa: E402


def _make_feed() -> bt.feeds.PandasData:
    dates = pd.bdate_range(start="2022-01-03", periods=5)
    df = pd.DataFrame(
        {
            "time": dates,
            "open": [10.0, 10.0, 11.0, 16.0, 16.5],
            "high": [10.1, 10.1, 11.1, 16.1, 16.6],
            "low": [9.9, 9.9, 10.9, 15.9, 16.4],
            "close": [10.0, 10.0, 11.0, 16.0, 16.5],
            "volume": [1000.0] * 5,
            "strong_buy_signal": [1.0, 0.0, 0.0, 0.0, 0.0],
            "strong_sell_signal": [0.0, 0.0, 1.0, 1.0, 0.0],
            "block_halving_future_buy": [0.0] * 5,
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
    data._name = "THRESH.SZ"
    return data


def run_case() -> list[dict[str, object]]:
    cerebro = bt.Cerebro()
    cerebro.broker.set_coc(True)
    cerebro.broker.setcash(1_000_000.0)
    cerebro.broker.setcommission(commission=COMMISSION)
    cerebro.adddata(_make_feed())
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
    return [
        row
        for row in strat.order_log
        if row.get("status") == "Completed" and row.get("code") == "THRESH.SZ"
    ]


if __name__ == "__main__":
    rows = run_case()
    plain_sells = [row for row in rows if row.get("signal") == "FACTOR_CHECK_SELL_SIGNAL_FULL_CLOSE"]
    threshold_sells = [row for row in rows if row.get("signal") == "PROFIT_GT_150_SELL_HALF_LOCK_BUY"]
    print("completed_orders=", rows)
    assert not plain_sells, f"plain sell signal should not bypass profit threshold: {plain_sells}"
    assert len(threshold_sells) == 1, f"expected one threshold half sell, got {threshold_sells}"
