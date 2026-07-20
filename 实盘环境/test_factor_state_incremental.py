# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
REALTIME_DIR = ROOT / "实盘环境" / "实时因子"
PREP_PATH = REALTIME_DIR / "盘前状态准备.py"
if str(REALTIME_DIR) not in sys.path:
    sys.path.insert(0, str(REALTIME_DIR))


def load_prep():
    spec = importlib.util.spec_from_file_location("factor_state_prep_test", PREP_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_default_state_path_is_single_rolling_file():
    prep = load_prep()
    assert prep.DEFAULT_STATE_DB == Path(r"D:\database\realtime_factor_state\factor_state.sqlite")


def test_prep_cli_writes_utf8_chinese_help():
    result = subprocess.run(
        [sys.executable, str(PREP_PATH), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0
    assert "盘前准备实时三因子状态缓存" in result.stdout


def test_fill_adj_factor_uses_last_known_value_per_code():
    prep = load_prep()
    daily = pd.DataFrame({
        "htsc_code": ["000001.SZ"] * 3,
        "time": pd.to_datetime(["2026-07-15", "2026-07-16", "2026-07-17"]),
        "close": [10.0, 11.0, 12.0],
    })
    factors = pd.DataFrame({
        "htsc_code": ["000001.SZ"],
        "time": pd.to_datetime(["2026-07-15"]),
        "adj_factor": [2.5],
    })
    result = prep.apply_backward_adjustment(daily, factors)
    assert result["adj_factor"].tolist() == [2.5, 2.5, 2.5]
    assert result["adj_factor_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-07-15",
        "2026-07-15",
        "2026-07-15",
    ]
    assert result["close"].tolist() == [25.0, 27.5, 30.0]


def test_fill_adj_factor_skips_invalid_latest_factor():
    prep = load_prep()
    daily = pd.DataFrame({
        "htsc_code": ["000001.SZ"],
        "time": pd.to_datetime(["2026-07-17"]),
        "close": [12.0],
    })
    factors = pd.DataFrame({
        "htsc_code": ["000001.SZ", "000001.SZ"],
        "time": pd.to_datetime(["2026-07-15", "2026-07-16"]),
        "adj_factor": [2.5, np.nan],
    })

    result = prep.apply_backward_adjustment(daily, factors)

    assert result.loc[0, "adj_factor"] == 2.5
    assert result.loc[0, "adj_factor_date"] == pd.Timestamp("2026-07-15")


def test_incremental_quote_converts_adjusted_prices_back_to_raw():
    prep = load_prep()
    row = SimpleNamespace(
        htsc_code="000001.SZ",
        close=30.0,
        open=25.0,
        high=32.5,
        low=22.5,
        volume=1000.0,
        adj_factor=2.5,
    )

    quote = prep._quote_from_adjusted_row(row, pd.Timestamp("2026-07-17"))

    assert quote["last_price"] == 12.0
    assert quote["open"] == 10.0
    assert quote["high"] == 13.0
    assert quote["low"] == 9.0
    assert quote["volume"] == 1000.0


def test_append_history_keeps_only_latest_limit():
    prep = load_prep()
    values = np.arange(5, dtype=np.float64)
    dates, trimmed = prep.append_history(["1", "2", "3", "4", "5"], values, "6", 5.0, limit=5)
    assert dates == ["2", "3", "4", "5", "6"]
    assert trimmed.tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_incremental_lookback_covers_long_state_gap():
    prep = load_prep()
    assert prep.incremental_lookback_days(
        pd.Timestamp("2026-05-01"),
        "2026-07-17",
    ) >= 78


def test_chip_state_calculation_works_after_loading_prep_module():
    prep = load_prep()
    costs, state, _ = prep._compute_chouma_cost_series_with_state(
        np.asarray([10.0, 11.0, 12.0]),
        np.asarray([9.0, 10.0, 11.0]),
        np.asarray([9.5, 10.5, 11.5]),
        np.asarray([100.0, 110.0, 120.0]),
        np.asarray([1.0, 1.0, 1.0]),
        prep._COST_PERCENTILES,
        pd.date_range("2026-01-01", periods=3),
        state=None,
        min_d=prep.CHOUMA_MIN_D,
        ac=prep.CHOUMA_AC,
        use_volume=prep.CHOUMA_USE_VOLUME,
    )

    assert costs.shape == (99, 3)
    assert state["n_bins"] > 0


def test_full_state_build_keeps_effective_adjustment_factor_date():
    prep = load_prep()
    dates = pd.bdate_range("2025-06-02", periods=270)
    raw_close = np.linspace(10.0, 15.0, len(dates))
    daily = pd.DataFrame({
        "htsc_code": "000001.SZ",
        "time": dates,
        "open": raw_close - 0.1,
        "high": raw_close + 0.2,
        "low": raw_close - 0.2,
        "close": raw_close,
        "volume": np.full(len(dates), 1_000_000.0),
    })
    factors = pd.DataFrame({
        "htsc_code": ["000001.SZ"],
        "time": [dates[0]],
        "adj_factor": [2.0],
    })
    adjusted = prep.apply_backward_adjustment(daily, factors)
    equity = pd.DataFrame({
        "htsc_code": "000001.SZ",
        "time": dates,
        "turnover_rate": np.full(len(dates), 1.0),
        "floating_market_val": raw_close * 100_000_000.0,
        "close": raw_close,
    })

    prior = prep.compute_prior_states_wide(adjusted, equity)
    states = prep.build_states(
        adjusted,
        equity,
        dates[-1].strftime("%Y-%m-%d"),
        prior_by_code=prior,
    )

    assert len(states) == 1
    assert states[0].chip_n_bins > 0
    assert len(states[0].prior_super_strong_no_concentration) == 4
    assert states[0].last_adj_factor == 2.0
    assert states[0].last_adj_factor_date == dates[0].strftime("%Y-%m-%d")
