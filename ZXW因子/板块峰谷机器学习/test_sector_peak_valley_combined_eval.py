from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
from sector_peak_valley_combined_eval import assign_groups, evaluate_combined_groups


def test_combined_score_groups_valley_up_and_peak_down() -> None:
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(["2024-01-01"] * 10),
            "htsc_code": [f"881{i:03d}.THS" for i in range(10)],
            "prediction": np.arange(10, dtype=float),
            "valley_strength_ex_post_actual": np.linspace(0.1, 0.9, 10),
            "peak_strength_ex_post_actual": np.linspace(0.9, 0.1, 10),
            "forward_return_1d": np.linspace(-0.05, 0.05, 10),
        }
    )
    _, summary = evaluate_combined_groups(frame, group_count=5, horizon=1)
    assert summary["valley_label_high_minus_low"] > 0
    assert summary["peak_label_high_minus_low"] < 0
    assert summary["long_short_mean_return"] > 0


def test_assign_groups_has_five_buckets() -> None:
    frame = pd.DataFrame(
        {"time": pd.to_datetime(["2024-01-01"] * 10), "prediction": np.arange(10, dtype=float)}
    )
    grouped = assign_groups(frame, 5)
    assert grouped["group"].nunique() == 5
    assert grouped.groupby("group").size().tolist() == [2, 2, 2, 2, 2]
