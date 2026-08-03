from __future__ import annotations

import numpy as np
import pandas as pd
import json
from pathlib import Path

from 低波因子 import build_low_volatility_factor_bundle, get_factor_lookback_config


def test_new_factor_groups_are_registered_in_utf8_catalog() -> None:
    catalog = json.loads(
        (Path(__file__).resolve().parents[1] / "因子分类" / "factor_catalog.json")
        .read_text(encoding="utf-8")
    )
    groups = {item["group_id"]: item for item in catalog["groups"]}
    assert groups["low_volatility"]["group_name"] == "低波因子"
    assert groups["liquidity"]["group_name"] == "流动性因子"
    assert "60日最大回撤" in groups["low_volatility"]["children"]
    assert "20日平均成交额" in groups["liquidity"]["children"]


def test_return_based_low_volatility_lookbacks_include_price_warmup_bar() -> None:
    lookbacks = get_factor_lookback_config()["factor_lookback_days"]

    assert lookbacks["annual_vol_20d"] == 21
    assert lookbacks["annual_vol_60d"] == 61
    assert lookbacks["annual_vol_252d"] == 253
    assert lookbacks["downside_vol_20d"] == 21
    assert lookbacks["downside_vol_60d"] == 61
    assert lookbacks["atr_volatility_14d"] == 15


def test_low_volatility_bundle_matches_vectorized_formulas() -> None:
    index = pd.date_range("2024-01-01", periods=90, freq="D")
    close = pd.DataFrame(
        {"000001.SZ": 100.0 * np.cumprod(1.0 + np.linspace(-0.01, 0.015, len(index)))},
        index=index,
    )
    high = close * 1.01
    low = close * 0.99

    factors = build_low_volatility_factor_bundle(C=close, H=high, L=low)["factor_dfs"]
    returns = close.pct_change()
    expected_vol_20 = returns.rolling(20, min_periods=20).std() * np.sqrt(252.0)
    expected_downside_20 = (
        returns.clip(upper=0.0).pow(2).rolling(20, min_periods=20).mean().pow(0.5)
        * np.sqrt(252.0)
    )
    def max_drawdown(window: np.ndarray) -> float:
        peak = np.maximum.accumulate(window)
        return float(np.min(window / peak - 1.0))

    expected_drawdown = close.rolling(60, min_periods=60).apply(max_drawdown, raw=True)

    pd.testing.assert_frame_equal(factors["annual_vol_20d"], expected_vol_20)
    pd.testing.assert_frame_equal(factors["downside_vol_20d"], expected_downside_20)
    pd.testing.assert_frame_equal(factors["max_drawdown_60d"], expected_drawdown)
    assert factors["annual_vol_252d"].isna().iloc[:252].all().all()


def test_low_volatility_bundle_preserves_invalid_price_bars() -> None:
    index = pd.date_range("2024-01-01", periods=70, freq="D")
    close = pd.DataFrame({"000001.SZ": 100.0}, index=index)
    close.iloc[40, 0] = np.nan
    high = close * 1.01
    low = close * 0.99

    factors = build_low_volatility_factor_bundle(C=close, H=high, L=low)["factor_dfs"]

    assert pd.isna(factors["annual_vol_20d"].iloc[40, 0])
    assert pd.isna(factors["atr_volatility_14d"].iloc[40, 0])


def test_low_volatility_bundle_rejects_nonpositive_prices() -> None:
    index = pd.date_range("2024-01-01", periods=70, freq="D")
    close = pd.DataFrame({"000001.SZ": 100.0}, index=index)
    close.iloc[40, 0] = 0.0
    high = close * 1.01
    low = close * 0.99

    factors = build_low_volatility_factor_bundle(C=close, H=high, L=low)["factor_dfs"]

    assert pd.isna(factors["annual_vol_20d"].iloc[40, 0])
    assert pd.isna(factors["annual_vol_20d"].iloc[60, 0])
    assert pd.isna(factors["max_drawdown_60d"].iloc[60, 0])


def test_max_drawdown_is_limited_to_the_trailing_window() -> None:
    index = pd.date_range("2024-01-01", periods=120, freq="D")
    values = np.full(len(index), 100.0)
    values[59] = 80.0
    close = pd.DataFrame({"000001.SZ": values}, index=index)

    factors = build_low_volatility_factor_bundle(C=close)["factor_dfs"]

    assert factors["max_drawdown_60d"].iloc[-1, 0] == 0.0
