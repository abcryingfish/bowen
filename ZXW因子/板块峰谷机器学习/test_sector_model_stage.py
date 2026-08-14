from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
from sector_model_stage import evaluate_predictions, make_rolling_splits, select_blend_weight


def test_rolling_splits_have_purged_non_overlapping_dates() -> None:
    dates = pd.bdate_range("2018-01-01", "2025-12-31")
    frame = pd.DataFrame({"time": np.repeat(dates, 2)})

    splits = make_rolling_splits(frame)

    assert len(splits) == 3
    for split in splits:
        train_dates = frame.loc[split["train"], "time"]
        validation_dates = frame.loc[split["validation"], "time"]
        test_dates = frame.loc[split["test"], "time"]
        assert train_dates.max() < validation_dates.min() < validation_dates.max() < test_dates.min()
        all_dates = pd.DatetimeIndex(frame["time"].unique()).sort_values()
        assert all_dates.get_loc(validation_dates.min()) - all_dates.get_loc(train_dates.max()) > 40
        assert all_dates.get_loc(test_dates.min()) - all_dates.get_loc(validation_dates.max()) > 40


def test_evaluate_predictions_rewards_perfect_ranking() -> None:
    rows = []
    for date in pd.bdate_range("2024-01-01", periods=80):
        for index in range(30):
            rows.append(
                {
                    "time": date,
                    "htsc_code": f"881{index:03d}.THS",
                    "sector_family": "881",
                    "actual": index / 29,
                }
            )
    data = pd.DataFrame(rows)

    metrics, daily, temporal = evaluate_predictions(
        data, data["actual"].to_numpy(), data["actual"].to_numpy()
    )

    assert metrics["cross_sectional_rank_ic"] == 1.0
    assert metrics["top10_lift"] == 10.0
    assert metrics["temporal_rank_ic"] != metrics["temporal_rank_ic"]  # 每个代码为常数
    assert len(daily) == 80
    assert temporal.empty


def test_select_blend_weight_uses_validation_ranking() -> None:
    rows = []
    for date in pd.bdate_range("2024-01-01", periods=20):
        for index in range(30):
            rows.append(
                {
                    "time": date,
                    "htsc_code": f"881{index:03d}.THS",
                    "sector_family": "881",
                    "actual": index / 29,
                }
            )
    data = pd.DataFrame(rows)
    actual = data["actual"].to_numpy()
    model_prediction = actual.copy()
    baseline_prediction = 1.0 - actual

    weight, ic = select_blend_weight(
        data, actual, model_prediction, baseline_prediction
    )

    assert weight > 0.5
    assert ic == 1.0
