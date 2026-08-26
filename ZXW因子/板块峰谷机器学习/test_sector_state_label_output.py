from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).with_name("sector_state_label_output.py")
SPEC = importlib.util.spec_from_file_location("sector_state_label_output", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_five_state_quadrants_and_low_low_bias() -> None:
    peak = pd.Series([0.2, 0.8, 0.8, 0.2, 0.1])
    valley = pd.Series([0.8, 0.2, 0.8, 0.2, 0.4])
    assert MODULE.classify_state(peak, valley).tolist() == [
        "波谷看涨",
        "波峰看跌",
        "双向高波",
        "横盘看跌",
        "横盘看涨",
    ]


def test_consensus_is_reproducible() -> None:
    states = pd.DataFrame({
        "state_ultra_short": ["波谷看涨"],
        "state_5d": ["波谷看涨"],
        "state_20d": ["波峰看跌"],
    })
    assert MODULE.weighted_consensus(states).iloc[0] == "波谷看涨"
