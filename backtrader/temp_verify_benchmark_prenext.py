from __future__ import annotations

import sys
from pathlib import Path

import backtrader as bt
import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from models.zxw_rule_backtest.zxw_view_results_full import (  # noqa: E402
    BuyAndHoldBenchmarkStrategy,
    COMMISSION,
    FactorPandasData,
)


INITIAL_CASH = 1_000_000.0


def _make_feed(code: str, start: str, periods: int, close_values: list[float]) -> bt.feeds.PandasData:
    dates = pd.bdate_range(start=start, periods=periods)
    values = close_values[:periods]
    if len(values) < periods:
        values.extend([values[-1]] * (periods - len(values)))
    df = pd.DataFrame(
        {
            "time": dates,
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": [1000.0] * periods,
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
        timeframe=bt.TimeFrame.Days,
    )
    data._name = code
    return data


def run_case() -> tuple[float, float, float, list[dict[str, float]]]:
    cerebro = bt.Cerebro()
    cerebro.broker.set_coc(True)
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)

    early = _make_feed("EARLY.SZ", "2022-01-03", 50, [10.0, 11.0, 12.0])
    late = _make_feed("LATE.SZ", "2022-02-28", 10, [20.0] * 10)
    cerebro.adddata(early)
    cerebro.adddata(late)
    cerebro.addstrategy(BuyAndHoldBenchmarkStrategy)

    strat = cerebro.run()[0]
    early_size = float(strat.getposition(strat.datas[0]).size)
    late_size = float(strat.getposition(strat.datas[1]).size)
    value_before_late = max(
        float(row["portfolio_value"])
        for row in strat.daily_value_log
        if str(row["date"]) < "2022-02-28"
    )
    return early_size, late_size, value_before_late, strat.daily_value_log


if __name__ == "__main__":
    early_size, late_size, value_before_late, daily_value_log = run_case()
    print("EARLY_SIZE=", early_size)
    print("LATE_SIZE=", late_size)
    print("VALUE_BEFORE_LATE=", value_before_late)
    print("FIRST_LOGS=", daily_value_log[:5])
    assert early_size > 0, "benchmark should buy the early available stock"
    assert late_size == 0, "late stock should not be added after benchmark pool is fixed"
    assert value_before_late > INITIAL_CASH, "benchmark value should move before late stock appears"
