from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


MODULE_PATH = Path(__file__).with_name("sector_state_probability_output.py")
SPEC = importlib.util.spec_from_file_location("sector_state_probability_output", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_classify_quadrant_matches_five_states() -> None:
    peak = pd.Series([0.2, 0.8, 0.8, 0.2, 0.1])
    valley = pd.Series([0.8, 0.2, 0.8, 0.2, 0.4])
    assert MODULE.classify_quadrant(peak, valley).tolist() == [
        "波谷看涨",
        "波峰看跌",
        "双向高波",
        "横盘看跌",
        "横盘看涨",
    ]


def test_probability_columns_sum_to_one() -> None:
    features = pd.DataFrame(
        {
            "peak": [0.2, 0.8, 0.8, 0.2, 0.1] * 4,
            "valley": [0.8, 0.2, 0.8, 0.2, 0.4] * 4,
            "direction": [0.6, -0.6, 0.0, 0.0, 0.3] * 4,
            "level": [0.0, 0.0, 0.3, -0.3, -0.2] * 4,
        }
    )
    labels = MODULE.classify_quadrant(features["peak"], features["valley"])
    model = MODULE._fit_calibrator(features, labels)
    probabilities = MODULE._predict_all_states(model, features)
    assert list(probabilities.columns) == list(MODULE.STATE_NAMES)
    assert (probabilities.sum(axis=1) - 1.0).abs().max() < 1e-10


def test_consensus_features_cover_all_horizons() -> None:
    frame = pd.DataFrame(
        {
            "peak_rank_ultra_short": [0.2], "valley_rank_ultra_short": [0.8],
            "direction_ultra_short": [0.6], "level_ultra_short": [0.0],
            "peak_rank_5d": [0.2], "valley_rank_5d": [0.8],
            "direction_5d": [0.6], "level_5d": [0.0],
            "peak_rank_20d": [0.2], "valley_rank_20d": [0.8],
            "direction_20d": [0.6], "level_20d": [0.0],
        }
    )
    result = MODULE._consensus_calibration_features(frame)
    assert result.shape == (1, 12)
    assert "20d_direction" in result.columns


def test_direction_probabilities_aggregate_five_states() -> None:
    frame = pd.DataFrame(
        {
            "prob_x_valley_bullish": [0.20],
            "prob_x_peak_bearish": [0.15],
            "prob_x_two_sided_high_volatility": [0.10],
            "prob_x_sideways_bullish": [0.25],
            "prob_x_sideways_bearish": [0.30],
        }
    )
    result = MODULE.add_direction_probabilities(frame, prefix="prob_x")
    assert np.isclose(result.loc[0, "prob_x_bullish"], 0.45)
    assert np.isclose(result.loc[0, "prob_x_bearish"], 0.45)
    assert np.isclose(result.loc[0, "prob_x_high_volatility"], 0.10)
    assert np.isclose(result.loc[0, "prob_x_up"], 0.50)
    assert np.isclose(result.loc[0, "prob_x_down"], 0.50)
    assert abs(
        result.loc[0, ["prob_x_bullish", "prob_x_bearish", "prob_x_high_volatility"]].sum()
        - 1.0
    ) < 1e-12
