"""板块因子 V2 审计器的确定性测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


_MODULE_PATH = Path(__file__).with_name("sector_factor_v2_audit.py")
_SPEC = importlib.util.spec_from_file_location("sector_factor_v2_audit", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

add_forward_returns = _MODULE.add_forward_returns
compute_daily_ic = _MODULE.compute_daily_ic
compute_quintile_monotonicity = _MODULE.compute_quintile_monotonicity
summarize_ic_breakdown = _MODULE.summarize_ic_breakdown


def test_add_forward_returns_uses_each_sectors_own_trading_sequence() -> None:
    times = pd.date_range("2020-01-01", periods=4)
    panel = pd.DataFrame(
        {
            "htsc_code": ["881001"] * 4 + ["885001"] * 4,
            "time": list(times) * 2,
        }
    )
    market = panel.copy()
    market["close"] = [10.0, 11.0, 12.0, 13.0, 20.0, 18.0, 16.0, 14.0]
    result, targets = add_forward_returns(panel, market, horizons=(2,))
    assert targets == ["forward_return_2d"]
    assert np.isclose(result.loc[0, "forward_return_2d"], 0.2)
    assert np.isclose(result.loc[4, "forward_return_2d"], -0.2)
    assert result.groupby("htsc_code")["forward_return_2d"].apply(lambda x: x.tail(2).isna().all()).all()


def test_daily_rank_ic_handles_positive_negative_and_family_isolation() -> None:
    rows = []
    for time in pd.to_datetime(["2020-01-02", "2021-01-04"]):
        for family, sign in (("881", 1.0), ("885", -1.0)):
            for value in range(1, 6):
                rows.append(
                    {
                        "time": time,
                        "sector_family": family,
                        "factor": float(value),
                        "target": sign * value,
                    }
                )
    frame = pd.DataFrame(rows)
    family = compute_daily_ic(
        frame, ["factor"], ["target"], min_count=5, by_family=True
    )
    assert np.allclose(family.loc[family["sector_family"] == "881", "rank_ic"], 1.0)
    assert np.allclose(family.loc[family["sector_family"] == "885", "rank_ic"], -1.0)

    overall = compute_daily_ic(frame, ["factor"], ["target"], min_count=5)
    breakdown = summarize_ic_breakdown(overall, family)
    years = breakdown.loc[breakdown["breakdown_type"] == "year", "breakdown_value"]
    assert set(years) == {"2020", "2021"}


def test_rank_ic_returns_nan_for_constant_or_insufficient_cross_section() -> None:
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(["2020-01-02"] * 5),
            "sector_family": ["881"] * 5,
            "constant": [1.0] * 5,
            "target": np.arange(5, dtype=float),
        }
    )
    constant = compute_daily_ic(frame, ["constant"], ["target"], min_count=5)
    assert constant["rank_ic"].isna().all()
    insufficient = compute_daily_ic(frame, ["constant"], ["target"], min_count=6)
    assert insufficient["rank_ic"].isna().all()


def test_quintile_monotonicity_detects_both_directions() -> None:
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(["2020-01-02"] * 100),
            "factor": np.arange(100, dtype=float),
            "up": np.arange(100, dtype=float),
            "down": -np.arange(100, dtype=float),
        }
    )
    result = compute_quintile_monotonicity(
        frame, ["factor"], ["up", "down"], min_count=20
    ).set_index("target")
    assert result.loc["up", "increasing_steps"] == 4
    assert result.loc["up", "monotonicity_ratio"] == 1.0
    assert result.loc["down", "decreasing_steps"] == 4
    assert result.loc["down", "monotonicity_ratio"] == 1.0


def test_duplicate_panel_keys_are_rejected(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "htsc_code": ["881001", "881001"],
            "time": pd.to_datetime(["2020-01-02", "2020-01-02"]),
            "sector_family": ["881", "881"],
            "bars_to_end": [40, 40],
            "peak_strength_ex_post": [0.1, 0.1],
            "valley_strength_ex_post": [0.2, 0.2],
            "factor": [1.0, 1.0],
        }
    )
    path = tmp_path / "panel.parquet"
    frame.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="重复主键"):
        _MODULE.load_panel(path)
