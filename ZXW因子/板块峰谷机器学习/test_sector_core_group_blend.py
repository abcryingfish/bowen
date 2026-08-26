"""五组Ridge合成的基本测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

_PATH = Path(__file__).with_name("sector_core_group_blend.py")
_SPEC = importlib.util.spec_from_file_location("sector_core_group_blend", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_M = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_M)


def test_quintile_summary_is_monotonic_for_ordered_prediction():
    frame = pd.DataFrame({"time": pd.to_datetime(["2023-01-03"] * 100), "actual": np.arange(100.), "prediction": np.arange(100.)})
    result = _M.evaluate_quintiles(frame, "actual", "prediction")
    assert result.iloc[-1]["mean"] > result.iloc[0]["mean"]


def test_purge_train_end_excludes_target_horizon_before_boundary():
    dates = pd.date_range("2022-01-03", periods=100, freq="D")
    boundary = dates[90]
    assert _M.purge_train_end(pd.DatetimeIndex(dates), boundary, 5) == dates[84]


def test_group_selection_audit_marks_test_ic_as_report_only():
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(["2023-01-03"] * 20),
            "delta_peak_5d": np.arange(20.0),
            "score_technical_delta_peak_5d": np.arange(20.0),
            "score_sideways_volatility_delta_peak_5d": np.arange(20.0)[::-1],
            "score_relative_strength_delta_peak_5d": np.arange(20.0),
            "score_constituent_breadth_delta_peak_5d": np.arange(20.0),
            "score_leader_diffusion_delta_peak_5d": np.arange(20.0),
            "score_market_state_conditioned_delta_peak_5d": np.arange(20.0),
        }
    )
    result = _M.build_group_selection_audit(
        oof=frame,
        test=frame,
        target="delta_peak_5d",
        active_groups=("technical",),
        coefficients=np.array([0.2]),
        purge_bars=45,
    )
    selected = result.set_index("group")
    assert bool(selected.loc["technical", "selected"])
    assert not bool(selected.loc["technical", "automatic_test_selection"])
    assert not bool(selected.loc["technical", "test_used_for_selection"])
    assert pd.isna(selected.loc["sideways_volatility", "ridge_coefficient"])
