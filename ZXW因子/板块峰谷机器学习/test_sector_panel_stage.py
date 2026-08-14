from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
from sector_panel_stage import (
    audit_feature,
    build_causal_market_features,
    factor_ic_summary,
    load_factor_values,
)


def test_causal_market_features_do_not_change_when_future_rows_change() -> None:
    dates = pd.bdate_range("2024-01-01", periods=100)
    base = pd.DataFrame(
        {
            "htsc_code": "881001.THS",
            "time": dates,
            "close": np.arange(100.0, 200.0),
            "high": np.arange(101.0, 201.0),
            "low": np.arange(99.0, 199.0),
        }
    )
    changed = base.copy()
    changed.loc[changed.index >= 80, ["close", "high", "low"]] *= 10

    left = build_causal_market_features(base).loc[:79]
    right = build_causal_market_features(changed).loc[:79]

    pd.testing.assert_frame_equal(left, right)


def test_factor_ic_summary_detects_monotonic_cross_sectional_relation() -> None:
    rows = []
    for date in pd.bdate_range("2024-01-01", periods=80):
        for index in range(30):
            rows.append(
                {
                    "time": date,
                    "htsc_code": f"881{index:03d}.THS",
                    "factor": float(index),
                    "peak_strength_ex_post": float(index),
                }
            )
    panel = pd.DataFrame(rows)

    result = factor_ic_summary(panel, "factor", "peak_strength_ex_post")

    assert result["cross_sectional_ic_mean"] == 1.0
    assert result["cross_sectional_days"] == 80


def test_audit_rejects_future_label_name() -> None:
    panel = pd.DataFrame(
        {
            "time": pd.bdate_range("2024-01-01", periods=80),
            "htsc_code": "881001.THS",
            "future_label_feature": np.arange(80),
            "peak_strength_ex_post": np.arange(80),
            "valley_strength_ex_post": np.arange(80)[::-1],
        }
    )

    result = audit_feature(panel, "future_label_feature")

    assert result["forbidden_name"] is True
    assert result["eligible"] is False


def test_load_factor_values_treats_empty_factor_directory_as_no_data(tmp_path: Path) -> None:
    (tmp_path / "factor=空目录因子").mkdir()

    result = load_factor_values(
        tmp_path,
        "空目录因子",
        start_date="2024-01-01",
        end_date="2024-12-31",
    )

    assert result.empty
    assert list(result.columns) == ["htsc_code", "time", "空目录因子"]
