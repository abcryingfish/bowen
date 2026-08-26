from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
from sector_lgbm_demo import make_splits, rank_ic_metrics


def test_make_splits_produces_three_purged_folds() -> None:
    dates = pd.bdate_range("2018-01-01", "2025-12-31")
    frame = pd.DataFrame({"time": np.repeat(dates, 2)})
    splits = make_splits(frame)
    assert len(splits) == 3
    for split in splits:
        train_dates = frame.loc[split["train"], "time"]
        valid_dates = frame.loc[split["validation"], "time"]
        test_dates = frame.loc[split["test"], "time"]
        assert train_dates.max() < valid_dates.min() < valid_dates.max() < test_dates.min()


def test_rank_ic_metrics_perfect_prediction() -> None:
    rows = []
    for day in pd.bdate_range("2024-01-01", periods=80):
        for index in range(30):
            rows.append(
                {
                    "time": day,
                    "htsc_code": f"881{index:03d}.THS",
                    "sector_family": "881",
                }
            )
    metadata = pd.DataFrame(rows)
    actual = np.tile(np.arange(30, dtype=float) / 29.0, 80)
    metrics = rank_ic_metrics(metadata, actual, actual)
    assert metrics["cross_sectional_rank_ic"] == 1.0
    assert metrics["top10_lift"] == 10.0
