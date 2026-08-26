from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).with_name("sector_market_state_conditioned_stage.py")
SPEC = importlib.util.spec_from_file_location("sector_market_state_conditioned_stage", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_market_state_features_are_not_daily_constants() -> None:
    frame = pd.DataFrame({
        "time": pd.to_datetime(["2024-01-02"] * 3),
        "sector_momentum_20d": [1.0, 2.0, 3.0],
        "market_return_20d": [0.1, 0.1, 0.1],
    })
    frame["conditioned"] = frame["sector_momentum_20d"] * frame["market_return_20d"]
    assert frame.groupby("time")["conditioned"].nunique().iloc[0] == 3
