from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).with_name("sector_market_state_group_model.py")
SPEC = importlib.util.spec_from_file_location("sector_market_state_group_model", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_purge_end_uses_target_specific_window() -> None:
    dates = pd.date_range("2020-01-01", periods=80, freq="D")
    assert MODULE.purge_train_end(pd.DatetimeIndex(dates), dates[70], 5) == dates[64]
