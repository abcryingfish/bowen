from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

BT_DIR = Path(__file__).parent / "backtrader"
if str(BT_DIR) not in sys.path:
    sys.path.append(str(BT_DIR))

from models.zxw_factor_check_base_threshold import runner as base_runner  # noqa: E402


class FakeRuleModule:
    BuyAndHoldBenchmarkStrategy = object

    def __init__(self, captured: dict[str, object]) -> None:
        self.captured = captured

    @staticmethod
    def create_cerebro(*args, **kwargs):
        return None

    def build_zxw_rule_bt_dataframe_for_range(self, *args, **kwargs):
        self.captured["adj_mode"] = kwargs.get("adj_mode")
        return (
            pd.DataFrame(
                [
                    {
                        "time": pd.Timestamp("2026-01-01"),
                        "htsc_code": "000001.SZ",
                        "strong_buy_signal": 1.0,
                        "strong_sell_signal": 0.0,
                    }
                ]
            ),
            ["000001.SZ"],
        )


def _patch_common(monkeypatch, module, captured: dict[str, object]) -> None:
    monkeypatch.setattr(module, "_load_zxw", lambda: FakeRuleModule(captured))
    monkeypatch.setattr(module, "template_from_frontend", lambda rules: [SimpleNamespace(factor="buy", threshold=1)])
    monkeypatch.setattr(module, "normalize_rules", lambda rules, side: [SimpleNamespace(factor="sell", threshold=1)])
    monkeypatch.setattr(module, "merge_strong_buy_signal", lambda df, rules, op: df)
    monkeypatch.setattr(module, "merge_strong_sell_signal", lambda df, rules, op: df)
    monkeypatch.setattr(module, "compute_backscan_initial_weights", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        module,
        "run_zxw_backtest",
        lambda **kwargs: {"summary_payload": {}, "saved_paths": {}, "curve_info": {}, "run_tag": "demo"},
    )


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


def test_base_threshold_runner_requests_backward_ratio_adjustment(monkeypatch):
    captured: dict[str, object] = {}
    _patch_common(monkeypatch, base_runner, captured)
    monkeypatch.setattr(base_runner, "load_base_threshold_frames", lambda *args, **kwargs: (pd.DataFrame({"x": [1]}), pd.DataFrame({"x": [1]})))
    monkeypatch.setattr(base_runner, "apply_base_threshold_filter", lambda df, valuation_df, indicator_df: (df, {"kept": 1}))

    result = _run(base_runner)

    assert captured["adj_mode"] == "backward_ratio"
    assert result["config"]["adj_mode"] == "backward_ratio"
