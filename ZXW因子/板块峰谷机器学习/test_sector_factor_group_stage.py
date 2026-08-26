"""板块六组因子构建器的确定性测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


_MODULE_PATH = Path(__file__).with_name("sector_factor_group_stage.py")
_SPEC = importlib.util.spec_from_file_location("sector_factor_group_stage", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def _relative_panel() -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=70)
    rows = []
    for family, code, multiplier in (
        ("881", "881001.THS", 1.0),
        ("881", "881002.THS", 2.0),
        ("885", "885001.THS", 3.0),
    ):
        for index, time in enumerate(dates):
            base = index / 1000.0
            rows.append(
                {
                    "htsc_code": code,
                    "time": time,
                    "sector_family": family,
                    "mkt_return_1d": multiplier * (0.0005 + index * 0.00001),
                    "mkt_momentum_5d": multiplier * base,
                    "mkt_momentum_20d": multiplier * base,
                    "mkt_momentum_60d": multiplier * base,
                }
            )
    return pd.DataFrame(rows)


def test_relative_strength_is_cross_sectional_and_causal() -> None:
    result = _MODULE.build_relative_strength(_relative_panel())
    date = result["time"].max()
    latest = result[result["time"] == date].set_index("htsc_code")
    assert latest.loc["885001.THS", "strength_pct_all_20d"] == 1.0
    assert latest.loc["881001.THS", "rs_vs_family_20d"] < 0
    assert latest.loc["881002.THS", "rs_vs_family_20d"] > 0
    assert np.isfinite(latest["residual_strength_20d"]).all()


def test_hot_streak_resets_after_no_hot_stock() -> None:
    frame = pd.DataFrame(
        {
            "htsc_code": ["881001.THS"] * 5,
            "time": pd.date_range("2020-01-01", periods=5),
            "hot_stock_ratio_top100": [0.1, 0.2, 0.0, np.nan, 0.3],
        }
    )
    result = _MODULE.add_hot_streak(frame)
    assert result["hot_streak_days"].tolist() == [1, 2, 0, 0, 1]


def test_hot_rank_one_gets_highest_popularity_strength() -> None:
    ranks = pd.Series([1.0, 2.0, 10.0, np.nan])
    result = _MODULE.popularity_strength_from_rank(ranks)
    assert result.iloc[0] == 1.0
    assert result.iloc[1] > result.iloc[2]
    assert pd.isna(result.iloc[3])


def test_group_validation_reports_coverage() -> None:
    frame = pd.DataFrame(
        {
            "htsc_code": ["881001.THS", "881002.THS"],
            "time": pd.to_datetime(["2020-01-01", "2020-01-01"]),
            "factor": [1.0, np.nan],
        }
    )
    result = _MODULE.validate_group(frame, "demo", ["factor"])
    assert result["rows"] == 2
    assert result["valid_rows"] == 1
    assert result["coverage"] == 0.5
