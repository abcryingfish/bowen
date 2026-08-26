from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
from sector_lgbm_blend import (
    TARGETS,
    baseline_prediction,
    candidate_weights,
    make_splits,
    resolve_target_settings,
    select_blend_weights,
)


def test_candidate_weights_form_simplex() -> None:
    weights = candidate_weights(0.1)
    assert len(weights) == 66
    assert all(np.isclose(sum(item), 1.0) for item in weights)
    assert (1.0, 0.0, 0.0) in weights
    assert (0.0, 1.0, 0.0) in weights
    assert (0.0, 0.0, 1.0) in weights


def test_blend_weight_selection_uses_validation_signal() -> None:
    rows = []
    actual = []
    lgbm = []
    elastic = []
    momentum = []
    for day in pd.bdate_range("2024-01-01", periods=80):
        for index in range(30):
            rows.append(
                {
                    "time": day,
                    "htsc_code": f"881{index:03d}.THS",
                    "sector_family": "881",
                }
            )
            value = index / 29.0
            actual.append(value)
            lgbm.append(value)
            elastic.append(1.0 - value)
            # 非常量噪声基准，避免所有正的 LightGBM 权重都产生完全相同的排序。
            momentum.append(((index * 7) % 30) / 29.0)
    metadata = pd.DataFrame(rows)
    selected, score = select_blend_weights(
        metadata,
        np.asarray(actual),
        np.asarray(lgbm),
        np.asarray(elastic),
        np.asarray(momentum),
        step=0.1,
    )
    assert selected[0] >= 0.5
    assert score > 0.99


def test_make_splits_has_purge_gap() -> None:
    dates = pd.bdate_range("2018-01-01", "2025-12-31")
    frame = pd.DataFrame({"time": np.repeat(dates, 2)})
    splits = make_splits(frame)
    assert len(splits) == 3
    for split in splits:
        train_dates = frame.loc[split["train"], "time"]
        valid_dates = frame.loc[split["validation"], "time"]
        test_dates = frame.loc[split["test"], "time"]
        assert train_dates.max() < valid_dates.min() < valid_dates.max() < test_dates.min()


def test_valley_baseline_reverses_momentum_rank() -> None:
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(["2024-01-01"] * 3),
            "mkt_momentum_5d": [1.0, 2.0, 3.0],
        }
    )
    valley = baseline_prediction(frame, TARGETS["valley"])
    assert np.allclose(valley, [2 / 3, 1 / 3, 0.0])


def test_target_settings_use_separate_valley_paths() -> None:
    target, model_root, report_root, experiment = resolve_target_settings("valley", None, None)
    assert target == TARGETS["valley"]
    assert model_root.name == "valley"
    assert report_root.name.endswith("valley")
    assert experiment == "sector_peak_valley_lgbm_valley_blend_v1"
