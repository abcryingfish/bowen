"""开发期技术子组审计器的确定性测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


_MODULE_PATH = Path(__file__).with_name("sector_technical_subgroup_audit.py")
_SPEC = importlib.util.spec_from_file_location(
    "sector_technical_subgroup_audit", _MODULE_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

compute_daily_ic = _MODULE.compute_daily_ic
compute_quintile_monotonicity = _MODULE.compute_quintile_monotonicity


def test_vectorized_rank_ic_handles_missing_and_family_isolation() -> None:
    rows = []
    for family, sign in (("881", 1.0), ("885", -1.0)):
        for value in range(30):
            rows.append(
                {
                    "time": pd.Timestamp("2022-01-04"),
                    "sector_family": family,
                    "factor": float(value),
                    "target": sign * value,
                }
            )
    frame = pd.DataFrame(rows)
    family = compute_daily_ic(
        frame, ["factor"], ["target"], min_count=20, by_family=True
    ).set_index("sector_family")
    assert np.isclose(family.loc["881", "rank_ic"], 1.0)
    assert np.isclose(family.loc["885", "rank_ic"], -1.0)
    assert family["sample_count"].eq(30).all()


def test_vectorized_quintiles_are_monotonic() -> None:
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(["2022-01-04"] * 100),
            "factor": np.arange(100, dtype=float),
            "up": np.arange(100, dtype=float),
            "down": -np.arange(100, dtype=float),
        }
    )
    result = compute_quintile_monotonicity(
        frame, ["factor"], ["up", "down"], min_count=20
    ).set_index("target")
    assert result.loc["up", "increasing_steps"] == 4
    assert result.loc["down", "decreasing_steps"] == 4
    assert result["monotonicity_ratio"].eq(1.0).all()
