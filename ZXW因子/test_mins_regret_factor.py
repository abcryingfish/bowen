from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


def _load_module():
    module_path = Path(__file__).with_name("遗憾规避因子.py")
    spec = importlib.util.spec_from_file_location("mins_regret_factor_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_mins_regret_factor_bundle_uses_tail_window_and_drops_flat_minutes():
    mod = _load_module()
    minute_data = pd.DataFrame(
        [
            # Outside tail window, contributes only to all-day denominator and close candidate.
            ("000001.SZ", "2024-01-02 14:29:00", 10.0, 11.0, 100.0),
            # Buy-like and losing versus day close.
            ("000001.SZ", "2024-01-02 14:30:00", 10.0, 12.0, 200.0),
            # Flat minute is excluded from numerator but still counts in denominators.
            ("000001.SZ", "2024-01-02 14:31:00", 13.0, 13.0, 300.0),
            # Sell-like and rebounded versus day close.
            ("000001.SZ", "2024-01-02 14:32:00", 14.0, 9.0, 400.0),
            # Last valid minute supplies day close, outside paper tail window.
            ("000001.SZ", "2024-01-02 14:57:00", 12.0, 10.0, 500.0),
            # Second stock has no tail volume, should stay NaN for tail-denominator factors.
            ("000002.SZ", "2024-01-02 14:29:00", 20.0, 21.0, 100.0),
            ("000002.SZ", "2024-01-02 14:57:00", 21.0, 22.0, 100.0),
        ],
        columns=["htsc_code", "time", "open", "close", "volume"],
    )

    out = mod.build_mins_regret_factor_bundle(minute_data)

    factor_dfs = out["factor_dfs"]
    idx = pd.Timestamp("2024-01-02")
    code = "000001.SZ"

    assert set(factor_dfs) == {
        "mins_regret_factor_HCVOLE1",
        "mins_regret_factor_HCVOLE2",
        "mins_regret_factor_LCVOLE1",
        "mins_regret_factor_LCVOLE2",
        "mins_regret_factor_HCPE",
        "mins_regret_factor_LCPE",
    }
    assert np.isclose(factor_dfs["mins_regret_factor_HCVOLE1"].loc[idx, code], 200.0 / 1500.0)
    assert np.isclose(factor_dfs["mins_regret_factor_HCVOLE2"].loc[idx, code], 200.0 / 900.0)
    assert np.isclose(factor_dfs["mins_regret_factor_LCVOLE1"].loc[idx, code], 400.0 / 1500.0)
    assert np.isclose(factor_dfs["mins_regret_factor_LCVOLE2"].loc[idx, code], 400.0 / 900.0)
    assert np.isclose(factor_dfs["mins_regret_factor_HCPE"].loc[idx, code], 12.0 / 10.0 - 1.0)
    assert np.isclose(factor_dfs["mins_regret_factor_LCPE"].loc[idx, code], 9.0 / 10.0 - 1.0)
    assert np.isnan(factor_dfs["mins_regret_factor_HCVOLE2"].loc[idx, "000002.SZ"])


def test_factor_name_map_uses_required_prefixes():
    mod = _load_module()
    out = mod.build_mins_regret_factor_bundle(
        pd.DataFrame(
            [("000001.SZ", "2024-01-02 14:30:00", 10.0, 11.0, 100.0)],
            columns=["htsc_code", "time", "open", "close", "volume"],
        )
    )

    assert out["factor_name_map"] == {
        "分钟级别遗憾规避因子_HCVOLE1": "mins_regret_factor_HCVOLE1",
        "分钟级别遗憾规避因子_HCVOLE2": "mins_regret_factor_HCVOLE2",
        "分钟级别遗憾规避因子_LCVOLE1": "mins_regret_factor_LCVOLE1",
        "分钟级别遗憾规避因子_LCVOLE2": "mins_regret_factor_LCVOLE2",
        "分钟级别遗憾规避因子_HCPE": "mins_regret_factor_HCPE",
        "分钟级别遗憾规避因子_LCPE": "mins_regret_factor_LCPE",
    }
