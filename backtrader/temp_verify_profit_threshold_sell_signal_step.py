from __future__ import annotations

import sys
from pathlib import Path

import backtrader as bt
import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from models.zxw_factor_check_sell_signal_step_position.profit_threshold_strategy import (  # noqa: E402
    FactorCheckSellSignalStepPositionZxwStrategy,
)
from models.zxw_data_pipeline.zxw_view_results_full import COMMISSION, FactorPandasData  # noqa: E402


INITIAL_CASH = 1_000_000.0


def _make_feed(code: str, closes: list[float], sell_signals: list[float]) -> bt.feeds.PandasData:
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


def run_case(code: str, closes: list[float], sell_signals: list[float]) -> list[dict[str, object]]:
    cerebro = bt.Cerebro()
    cerebro.broker.set_coc(True)
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)
    cerebro.adddata(_make_feed(code, closes, sell_signals))
    cerebro.addstrategy(
        FactorCheckSellSignalStepPositionZxwStrategy,
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


def _completed_rows(code: str, closes: list[float], sell_signals: list[float]) -> list[dict[str, object]]:
    return [
        row
        for row in run_case(code, closes, sell_signals)
        if row.get("status") == "Completed" and row.get("code") == code
    ]


def _assert_cumulative_sold(rows: list[dict[str, object]], expected_sold: list[float]) -> None:
    sells = [r for r in rows if r.get("signal") == "FACTOR_CHECK_SELL_SIGNAL_STEP_POSITION"]
    assert len(sells) == len(expected_sold), f"expected {len(expected_sold)} step sells, got {len(sells)}"
    initial_buy = next(r for r in rows if r.get("side") == "BUY")
    base_size = abs(float(initial_buy["executed_size"]))
    cumulative = 0.0
    for sell, expected_ratio in zip(sells, expected_sold):
        cumulative += abs(float(sell["executed_size"]))
        actual_ratio = cumulative / base_size
        assert abs(actual_ratio - expected_ratio) < 0.02, (
            f"expected cumulative sold near {expected_ratio:.0%}, got {actual_ratio:.2%}; "
            f"base_size={base_size}, sell={sell}"
        )


def verify_cross_thresholds() -> None:
    rows = [
        row
        for row in _completed_rows(
            "STEP.SZ",
            [10.0, 10.0, 10.2, 10.4, 15.2, 20.2, 20.5, 20.6, 10.0, 10.0],
            [0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0],
        )
        if row.get("status") == "Completed" and row.get("code") == "STEP.SZ"
    ]
    print("cross_threshold_orders=", rows)
    _assert_cumulative_sold(rows, [0.1, 0.2, 0.3, 0.8, 0.9])


def verify_below_50pct_caps_at_30pct() -> None:
    rows = _completed_rows(
        "LOW.SZ",
        [10.0, 10.0, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8],
        [0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0],
    )
    print("below_50pct_orders=", rows)
    _assert_cumulative_sold(rows, [0.1, 0.2, 0.3])


def verify_between_50pct_and_100pct_caps_at_80pct() -> None:
    rows = _completed_rows(
        "MID.SZ",
        [10.0, 10.0, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 15.8, 15.9, 16.0],
        [0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0],
    )
    print("between_50_100pct_orders=", rows)
    _assert_cumulative_sold(rows, [0.3, 0.4, 0.5, 0.6, 0.7, 0.8])


if __name__ == "__main__":
    verify_cross_thresholds()
    verify_below_50pct_caps_at_30pct()
    verify_between_50pct_and_100pct_caps_at_80pct()
