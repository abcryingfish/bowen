from __future__ import annotations

import sys
from pathlib import Path

import backtrader as bt
import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from models.zxw_factor_check_dual_assumption.dual_assumption_strategy import (  # noqa: E402
    FactorCheckDualAssumptionZxwStrategy,
)
from models.zxw_rule_backtest.zxw_view_results_full import COMMISSION, FactorPandasData  # noqa: E402


INITIAL_CASH = 1_000_000.0


def _make_feed(code: str, start: str, periods: int, strong_buy: float) -> bt.feeds.PandasData:
    dates = pd.bdate_range(start=start, periods=periods)
    df = pd.DataFrame(
        {
            "time": dates,
            "open": [10.0] * periods,
            "high": [10.2] * periods,
            "low": [9.8] * periods,
            "close": [10.0] * periods,
            "volume": [1000.0] * periods,
            "strong_buy_signal": [strong_buy] * periods,
            "strong_sell_signal": [0.0] * periods,
            "block_halving_future_buy": [0.0] * periods,
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


def run_case() -> tuple[str | None, list[dict[str, object]]]:
    cerebro = bt.Cerebro()
    cerebro.broker.set_coc(True)
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)

    early = _make_feed("EARLY.SZ", "2022-01-03", 50, 1.0)
    late = _make_feed("LATE.SZ", "2022-02-28", 5, 0.0)
    cerebro.adddata(early)
    cerebro.adddata(late)

    cerebro.addstrategy(
        FactorCheckDualAssumptionZxwStrategy,
        backtest_start="2022-01-01",
        max_weight=0.02,
        cash_ratio_gate=0.1,
        initial_target_weight_by_code={},
        daily_move_limit=0.098,
    )
    results = cerebro.run()
    strat = results[0]
    first_buy = next(
        (
            row["date"]
            for row in strat.order_log
            if row.get("code") == "EARLY.SZ"
            and row.get("side") == "BUY"
            and row.get("status") == "Completed"
        ),
        None,
    )
    return first_buy, strat.order_log


if __name__ == "__main__":
    first_buy, order_log = run_case()
    print("FIRST_BUY_DATE=", first_buy)
    print("ORDER_COUNT=", len(order_log))
    for row in order_log[:10]:
        print(row)
