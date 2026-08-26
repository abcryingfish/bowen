from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
from sector_long_short_eval import add_forward_returns, assign_groups, evaluate_return_groups


def test_assign_groups_has_expected_bounds() -> None:
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(["2024-01-01"] * 10),
            "prediction": np.arange(10, dtype=float),
        }
    )
    grouped = assign_groups(frame, 5)
    assert grouped["group"].min() == 1
    assert grouped["group"].max() == 5
    assert grouped.groupby("group").size().tolist() == [2, 2, 2, 2, 2]


def test_forward_return_uses_future_close() -> None:
    market = pd.DataFrame(
        {
            "htsc_code": ["881001.THS"] * 4,
            "time": pd.date_range("2024-01-01", periods=4, freq="D"),
            "close": [100.0, 105.0, 110.0, 120.0],
        }
    )
    result = add_forward_returns(market, horizons=(1, 2))
    assert np.isclose(result.loc[0, "forward_return_1d"], 0.05)
    assert np.isclose(result.loc[0, "forward_return_2d"], 0.10)
    assert pd.isna(result.loc[3, "forward_return_1d"])


def test_long_short_spread_is_positive_for_monotonic_returns() -> None:
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(["2024-01-01"] * 10),
            "htsc_code": [f"881{i:03d}.THS" for i in range(10)],
            "prediction": np.arange(10, dtype=float),
            "forward_return_1d": np.linspace(-0.05, 0.05, 10),
        }
    )
    _, summary = evaluate_return_groups(frame, group_count=5, horizon=1)
    assert summary["long_mean_return"] > summary["short_mean_return"]
    assert summary["long_short_mean_return"] > 0
    assert summary["reverse_long_short_mean_return"] < 0
