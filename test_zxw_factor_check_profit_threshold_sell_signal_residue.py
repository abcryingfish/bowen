from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

BT_DIR = Path(__file__).parent / "backtrader"
if str(BT_DIR) not in sys.path:
    sys.path.append(str(BT_DIR))

from models.zxw_factor_check_base_threshold import runner as base_runner  # noqa: E402
from models.zxw_factor_check_profit_threshold_dual_assumption import runner as profit_runner  # noqa: E402
from models.zxw_factor_check_profit_threshold_dual_assumption.profit_threshold_strategy import (  # noqa: E402
    FactorCheckProfitThresholdDualAssumptionZxwStrategy,
)


class FakeLine:
    def __init__(self, value: float) -> None:
        self.value = value

    def __getitem__(self, index: int) -> float:
        assert index == 0
        return self.value


class FakeData:
    _name = "000001.SZ"

    def __init__(self) -> None:
        self.close = FakeLine(10.0)


class FakeBroker:
    def getcash(self) -> float:
        return 100.0


def test_profit_threshold_strategy_ignores_sell_signal_for_cash_and_emergency() -> None:
    strategy = FactorCheckProfitThresholdDualAssumptionZxwStrategy.__new__(
        FactorCheckProfitThresholdDualAssumptionZxwStrategy
    )
    data = FakeData()
    strategy.broker = FakeBroker()
    strategy._bar_planned_buy_value = {}
    strategy._buy_locked_after_partial_sell = set()
    strategy._half_profit_sold_codes = set()
    strategy._strong_sell_hit = lambda d: True
    strategy.getposition = lambda d: SimpleNamespace(size=10)
    strategy._planned_buy_value = lambda d: 0.0

    assert strategy._estimated_post_normal_cash([data]) == 100.0
    assert strategy._held_for_emergency([data]) == [data]


class FakeRuleModule:
    BuyAndHoldBenchmarkStrategy = object

    @staticmethod
    def create_cerebro(*args, **kwargs):
        return None

    @staticmethod
    def build_zxw_rule_bt_dataframe_for_range(*args, **kwargs):
        return (
            pd.DataFrame(
                [
                    {
                        "time": pd.Timestamp("2026-01-01"),
                        "htsc_code": "000001.SZ",
                        "strong_buy_signal": 1.0,
                        "strong_sell_signal": 1.0,
                    }
                ]
            ),
            ["000001.SZ"],
        )


def _patch_common_runner(monkeypatch, module, captured: dict[str, object]) -> None:
    monkeypatch.setattr(module, "_load_zxw", lambda: FakeRuleModule)
    monkeypatch.setattr(
        module,
        "template_from_frontend",
        lambda rules: [SimpleNamespace(factor="buy", threshold=1)],
    )
    monkeypatch.setattr(
        module,
        "normalize_rules",
        lambda rules, side: [SimpleNamespace(factor="sell", threshold=1)],
    )
    monkeypatch.setattr(module, "merge_strong_buy_signal", lambda df, rules, op: df)
    monkeypatch.setattr(module, "merge_strong_sell_signal", lambda df, rules, op: df)

    def capture_init_weights(df, *args, **kwargs):
        captured["init_sell_sum"] = float(df["strong_sell_signal"].sum())
        return {}

    def capture_backtest(**kwargs):
        captured["backtest_sell_sum"] = float(kwargs["df_multi"]["strong_sell_signal"].sum())
        return {"summary_payload": {}, "saved_paths": {}, "curve_info": {}, "run_tag": "demo"}

    monkeypatch.setattr(module, "compute_backscan_initial_weights", capture_init_weights)
    monkeypatch.setattr(module, "run_zxw_backtest", capture_backtest)


def _run(module):
    return module.run(
        codes=["000001.SZ"],
        start_date="2026-01-01",
        end_date="2026-02-01",
        run_name="demo",
        frontend_buy_rules=[{"factor": "buy", "threshold": 1}],
        frontend_sell_rules=[{"factor": "sell", "threshold": 1}],
        frontend_buy_operator="and",
        frontend_sell_operator="or",
        progress=None,
    )


def test_profit_threshold_runner_neutralizes_sell_signal_before_init_and_backtest(monkeypatch):
    captured: dict[str, object] = {}
    _patch_common_runner(monkeypatch, profit_runner, captured)

    _run(profit_runner)

    assert captured["init_sell_sum"] == 0.0
    assert captured["backtest_sell_sum"] == 0.0


def test_base_threshold_runner_neutralizes_sell_signal_before_init_and_backtest(monkeypatch):
    captured: dict[str, object] = {}
    _patch_common_runner(monkeypatch, base_runner, captured)
    monkeypatch.setattr(
        base_runner,
        "load_base_threshold_frames",
        lambda *args, **kwargs: (pd.DataFrame({"x": [1]}), pd.DataFrame({"x": [1]})),
    )
    monkeypatch.setattr(
        base_runner,
        "apply_base_threshold_filter",
        lambda df, valuation_df, indicator_df: (df, {"kept": 1}),
    )

    _run(base_runner)

    assert captured["init_sell_sum"] == 0.0
    assert captured["backtest_sell_sum"] == 0.0
