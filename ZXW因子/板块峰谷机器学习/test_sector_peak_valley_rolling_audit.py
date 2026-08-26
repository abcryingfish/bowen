"""滚动市场中性审计的快速单元测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).with_name("sector_peak_valley_rolling_audit.py")
_SPEC = importlib.util.spec_from_file_location("sector_peak_valley_rolling_audit", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
build_daily_spreads = _MODULE.build_daily_spreads
hac_t_stat = _MODULE.hac_t_stat
summarize = _MODULE.summarize
pooled_summary = _MODULE.pooled_summary
select_non_overlapping_20d = _MODULE.select_non_overlapping_20d


def test_hac_t_stat_constant_series_is_nan() -> None:
    assert np.isnan(hac_t_stat(pd.Series([1.0, 1.0, 1.0]), max_lag=2))


def test_hac_t_stat_positive_mean_is_positive() -> None:
    value = hac_t_stat(pd.Series([0.01, 0.02, 0.03, 0.02, 0.01]), max_lag=2)
    assert np.isfinite(value)
    assert value > 0


def test_build_daily_spreads_long_short_direction() -> None:
    predictions = pd.DataFrame(
        {
            "year": [2020] * 4,
            "time": pd.to_datetime(["2020-01-02"] * 4),
            "htsc_code": ["881001", "881002", "881003", "881004"],
            "prediction": [0.1, 0.2, 0.8, 0.9],
        }
    )
    market = pd.DataFrame(
        {
            "time": pd.to_datetime(["2020-01-02"] * 6),
            "htsc_code": ["881001", "881002", "881003", "881004", "000001.SH", "399001.SZ"],
            "forward_return_20d": [0.01, 0.02, 0.08, 0.09, 0.03, 0.03],
            "trailing_return_60d": [0.0] * 6,
        }
    )
    daily = build_daily_spreads(predictions, market, group_count=2)
    assert len(daily) == 1
    assert daily.loc[0, "spread"] > 0


def test_summarize_beta_and_residual() -> None:
    daily = pd.DataFrame(
        {
            "year": [2020] * 6,
            "time": pd.date_range("2020-01-01", periods=6),
            "spread": [0.02, 0.04, 0.06, 0.08, 0.10, 0.12],
            "broad_forward_return_20d": [0.01, 0.02, 0.03, 0.04, 0.05, 0.06],
            "sector_forward_return_20d": [0.00, 0.01, 0.02, 0.03, 0.04, 0.05],
            "broad_trailing_return_60d": [1.0, 1.0, -1.0, -1.0, 1.0, -1.0],
        }
    )
    result = summarize(daily)
    broad = result[result["benchmark"] == "broad_forward_return_20d"].iloc[0]
    assert np.isclose(broad["beta"], 2.0)
    assert abs(broad["residual_mean"]) < 1e-12


def test_non_overlapping_selection_and_pooled_summary() -> None:
    daily = pd.DataFrame(
        {
            "year": [2019] * 41 + [2020] * 21,
            "time": pd.date_range("2019-01-01", periods=62),
            "spread": np.arange(62, dtype=float),
        }
    )
    selected = select_non_overlapping_20d(daily)
    assert len(selected) == 5
    result = pooled_summary(selected, hac_lag=0)
    assert result["days"] == 5
    assert np.isfinite(result["spread_mean"])
