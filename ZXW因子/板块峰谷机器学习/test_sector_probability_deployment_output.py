from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest


MODULE_PATH = Path(__file__).with_name("sector_probability_deployment_output.py")
SPEC = importlib.util.spec_from_file_location("sector_probability_deployment_output", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _fixture() -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "htsc_code": ["881001.THS", "881002.THS"],
            "time": ["2024-01-02", "2024-01-02"],
            "sector_family": ["881", "881"],
        }
    )
    for horizon in MODULE.HORIZONS:
        for index, state in enumerate(MODULE.STATE_CODES):
            frame[f"prob_{horizon}_{state}"] = [0.1 + index * 0.1, 0.4 - index * 0.1]
        columns = MODULE.probability_columns(horizon)
        frame[columns] = frame[columns].div(frame[columns].sum(axis=1), axis=0)
        frame[f"prob_{horizon}_bullish"] = frame[f"prob_{horizon}_valley_bullish"] + frame[f"prob_{horizon}_sideways_bullish"]
        frame[f"prob_{horizon}_bearish"] = frame[f"prob_{horizon}_peak_bearish"] + frame[f"prob_{horizon}_sideways_bearish"]
        frame[f"prob_{horizon}_high_volatility"] = frame[f"prob_{horizon}_two_sided_high_volatility"]
        frame[f"prob_{horizon}_up"] = frame[f"prob_{horizon}_bullish"] + 0.5 * frame[f"prob_{horizon}_high_volatility"]
        frame[f"prob_{horizon}_down"] = frame[f"prob_{horizon}_bearish"] + 0.5 * frame[f"prob_{horizon}_high_volatility"]
    return frame


def test_probability_validation_accepts_normalized_rows() -> None:
    result = MODULE.validate_probability_frame(_fixture())
    assert set(result) == set(MODULE.HORIZONS)


def test_probability_validation_rejects_non_normalized_rows() -> None:
    frame = _fixture()
    frame.loc[0, "prob_consensus_valley_bullish"] = 0.9
    with pytest.raises(ValueError, match="未归一化"):
        MODULE.validate_probability_frame(frame)
