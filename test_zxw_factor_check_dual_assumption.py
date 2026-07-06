from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

BT_DIR = Path(__file__).parent / "backtrader"
if str(BT_DIR) not in sys.path:
    sys.path.append(str(BT_DIR))

from models.zxw_factor_check_dual_assumption import runner  # noqa: E402


def test_dual_assumption_runner_requests_backward_ratio_adjustment(monkeypatch):
    captured: dict[str, object] = {}

    class FakeRuleModule:
        BuyAndHoldBenchmarkStrategy = object

        @staticmethod
        def create_cerebro(*args, **kwargs):
            return None

        @staticmethod
        def build_zxw_rule_bt_dataframe_for_range(*args, **kwargs):
            captured["adj_mode"] = kwargs.get("adj_mode")
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

    monkeypatch.setattr(runner, "_load_zxw", lambda: FakeRuleModule)
    monkeypatch.setattr(runner, "template_from_frontend", lambda rules: [SimpleNamespace(factor="买入", threshold=1)])
    monkeypatch.setattr(runner, "normalize_rules", lambda rules, side: [SimpleNamespace(factor="卖出", threshold=1)])
    monkeypatch.setattr(runner, "merge_strong_buy_signal", lambda df, rules, op: df)
    monkeypatch.setattr(runner, "merge_strong_sell_signal", lambda df, rules, op: df)
    monkeypatch.setattr(runner, "compute_backscan_initial_weights", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        runner,
        "run_zxw_backtest",
        lambda **kwargs: {"summary_payload": {}, "saved_paths": {}, "curve_info": {}, "run_tag": "demo"},
    )

    result = runner.run(
        codes=["000001.SZ"],
        start_date="2026-01-01",
        end_date="2026-02-01",
        run_name="demo",
        frontend_buy_rules=[{"factor": "买入", "threshold": 1}],
        frontend_sell_rules=[{"factor": "卖出", "threshold": 1}],
        frontend_buy_operator="and",
        frontend_sell_operator="or",
        progress=None,
    )

    assert captured["adj_mode"] == "backward_ratio"
    assert result["config"]["adj_mode"] == "backward_ratio"
