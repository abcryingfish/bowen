"""六组因子与三周期 V2 变化目标审计器的确定性测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


_MODULE_PATH = Path(__file__).with_name("sector_change_target_audit.py")
_SPEC = importlib.util.spec_from_file_location("sector_change_target_audit", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

compute_daily_rank_ic = _MODULE.compute_daily_rank_ic
compute_quintile_monotonicity = _MODULE.compute_quintile_monotonicity
load_targets = _MODULE.load_targets
summarise_annual_ic = _MODULE.summarise_annual_ic
summarise_family_ic = _MODULE.summarise_family_ic
summarise_hot_rank_change_short = _MODULE.summarise_hot_rank_change_short


def test_daily_rank_ic_uses_future_change_target_and_counts_over_127() -> None:
    rows = []
    for time in pd.to_datetime(["2025-01-02", "2025-01-03"]):
        for value in range(200):
            rows.append(
                {
                    "time": time,
                    "sector_family": "881",
                    "factor": float(value),
                    "delta_peak_5d": float(value),
                }
            )
    result = compute_daily_rank_ic(
        pd.DataFrame(rows), ["factor"], ["delta_peak_5d"], min_count=20
    )
    assert result["time"].map(type).eq(pd.Timestamp).all()
    assert np.allclose(result["rank_ic"], 1.0)
    assert result["sample_count"].eq(200).all()


def test_annual_and_family_ic_are_separate_daily_ic_aggregations() -> None:
    rows = []
    for time in pd.to_datetime(["2024-12-31", "2025-01-02"]):
        for family, sign in (("881", 1.0), ("885", -1.0)):
            for value in range(20):
                rows.append(
                    {
                        "time": time,
                        "sector_family": family,
                        "factor": float(value),
                        "target": sign * value,
                    }
                )
    frame = pd.DataFrame(rows)
    daily = compute_daily_rank_ic(frame, ["factor"], ["target"], min_count=20)
    annual = summarise_annual_ic(daily)
    assert set(annual["year"]) == {2024, 2025}

    family_daily = compute_daily_rank_ic(
        frame, ["factor"], ["target"], min_count=20, by_family=True
    )
    family = summarise_family_ic(family_daily).set_index("sector_family")
    assert np.isclose(family.loc["881", "ic_mean"], 1.0)
    assert np.isclose(family.loc["885", "ic_mean"], -1.0)


def test_quintile_monotonicity_detects_increasing_target() -> None:
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(["2025-01-02"] * 100),
            "factor": np.arange(100, dtype=float),
            "target": np.arange(100, dtype=float),
        }
    )
    result = compute_quintile_monotonicity(
        frame, ["factor"], ["target"], min_count=20
    ).iloc[0]
    assert result["increasing_steps"] == 4
    assert result["monotonicity_ratio"] == 1.0
    assert result["q5_mean"] > result["q1_mean"]


def test_load_targets_rejects_duplicate_keys(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "htsc_code": ["881001", "881001"],
            "time": pd.to_datetime(["2025-01-02", "2025-01-02"]),
        }
    )
    for columns in _MODULE.TARGETS_BY_HORIZON.values():
        for column in columns:
            frame[column] = 0.1
    path = tmp_path / "targets.parquet"
    frame.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="重复主键"):
        load_targets(path)


def test_hot_rank_change_short_summary_filters_short_targets_and_features() -> None:
    frame = pd.DataFrame(
        [
            {"sample": "train", "feature": "popularity_rank_improvement_1d_mean", "target": "delta_peak_5d", "ic_mean": 0.1},
            {"sample": "test", "feature": "popularity_rank_improvement_5d_mean", "target": "delta_valley_ultra_short", "ic_mean": 0.2},
            {"sample": "test", "feature": "popularity_strength_mean", "target": "delta_peak_5d", "ic_mean": 0.3},
            {"sample": "test", "feature": "popularity_rank_improvement_1d_mean", "target": "delta_peak_20d", "ic_mean": 0.4},
        ]
    )
    result = summarise_hot_rank_change_short(frame)
    assert len(result) == 2
    assert set(result["feature"]) == {
        "popularity_rank_improvement_1d_mean",
        "popularity_rank_improvement_5d_mean",
    }
