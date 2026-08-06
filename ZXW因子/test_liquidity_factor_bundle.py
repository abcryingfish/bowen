from __future__ import annotations

import numpy as np
import pandas as pd

from 流动性因子 import build_liquidity_factor_bundle, get_factor_lookback_config


def test_liquidity_bundle_calculates_amount_turnover_and_amihud(tmp_path) -> None:
    index = pd.date_range("2024-01-01", periods=25, freq="D")
    close = pd.DataFrame({"000001.SZ": np.arange(100.0, 125.0)}, index=index)
    source = pd.DataFrame(
        {
            "htsc_code": "000001.SZ",
            "time": index,
            "value": np.arange(1000.0, 1025.0),
            "turnover_rate": np.linspace(1.0, 2.0, len(index)),
        }
    )
    source_path = tmp_path / "turnover.parquet"
    source.to_parquet(source_path, index=False)

    factors = build_liquidity_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_glob=str(source_path),
    )["factor_dfs"]
    expected_return = close.pct_change()
    expected_amount = source.set_index("time")["value"].rolling(20, min_periods=20).mean()
    expected_amihud = (
        expected_return["000001.SZ"].abs()
        / source.set_index("time")["value"]
    ).rolling(20, min_periods=20).mean()

    pd.testing.assert_series_equal(
        factors["avg_trading_value_20d"]["000001.SZ"],
        expected_amount,
        check_names=False,
    )
    pd.testing.assert_series_equal(
        factors["amihud_20d"]["000001.SZ"],
        expected_amihud,
        check_names=False,
        check_freq=False,
    )
    assert factors["zero_trading_value_ratio_20d"]["000001.SZ"].iloc[-1] == 0.0


def test_amihud_lookback_includes_return_warmup_bar() -> None:
    lookbacks = get_factor_lookback_config()["factor_lookback_days"]

    assert lookbacks["amihud_20d"] == 21


def test_zero_trading_value_ratio_does_not_treat_missing_amount_as_zero(tmp_path) -> None:
    index = pd.date_range("2024-01-01", periods=25, freq="D")
    close = pd.DataFrame({"000001.SZ": np.arange(100.0, 125.0)}, index=index)
    source = pd.DataFrame(
        {
            "htsc_code": "000001.SZ",
            "time": index,
            "value": np.arange(1000.0, 1025.0),
            "turnover_rate": 1.0,
        }
    )
    source.loc[source.index[-1], "value"] = np.nan
    source_path = tmp_path / "turnover_missing.parquet"
    source.to_parquet(source_path, index=False)

    factors = build_liquidity_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_glob=str(source_path),
    )["factor_dfs"]

    assert pd.isna(factors["zero_trading_value_ratio_20d"].iloc[-1, 0])
