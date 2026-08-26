from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).with_name("sector_state_probability_audit.py")
SPEC = importlib.util.spec_from_file_location("sector_state_probability_audit", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_multiclass_brier_is_zero_for_perfect_probabilities() -> None:
    labels = pd.Series(["波谷看涨", "波峰看跌", "双向高波", "横盘看涨", "横盘看跌"])
    probabilities = pd.DataFrame(0.0, columns=MODULE.STATE_NAMES, index=labels.index)
    for index, label in labels.items():
        probabilities.loc[index, label] = 1.0
    assert MODULE.multiclass_brier(probabilities, labels) == 0.0


def test_consensus_state_uses_fixed_weights() -> None:
    states = pd.DataFrame(
        {
            "actual_state_ultra_short": ["波峰看跌"],
            "actual_state_5d": ["波谷看涨"],
            "actual_state_20d": ["波谷看涨"],
        }
    )
    assert MODULE.consensus_state(states).iloc[0] == "波谷看涨"
