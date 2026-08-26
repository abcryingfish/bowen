from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).with_name("sector_state_label_stability_filter.py")
SPEC = importlib.util.spec_from_file_location("sector_state_label_stability_filter", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_change_requires_two_consecutive_observations() -> None:
    frame = pd.DataFrame({"htsc_code": ["A"] * 5, "time": pd.date_range("2024-01-01", periods=5), "state": ["X", "Y", "X", "Y", "Y"]})
    result = MODULE.confirm_two_days(frame, "state")
    assert result.tolist() == ["X", "X", "X", "X", "Y"]
