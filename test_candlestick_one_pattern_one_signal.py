from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parent
PATTERN_FILE = ROOT / "形态趋势通道因子" / "蜡烛图无成交量.py"
META_FILE = ROOT / "形态趋势通道因子" / "morph_candlestick_meta.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _crows_ohlc():
    dates = pd.date_range("2026-01-01", periods=12, freq="D")
    open_prices = pd.DataFrame(
        {
            "TWO.SZ": [1, 1, 1, 2, 2, 3, 3, 4, 5, 6, 8, 9],
            "THREE.SZ": [1, 1, 1, 2, 2, 3, 3, 4, 5, 8, 7, 6],
        },
        index=dates,
        dtype=float,
    )
    close_prices = pd.DataFrame(
        {
            "TWO.SZ": [1, 1, 1, 2, 2, 3, 3, 4, 5, 7, 6.5, 6],
            "THREE.SZ": [1, 1, 1, 2, 2, 3, 3, 4, 5, 7, 6, 5],
        },
        index=dates,
        dtype=float,
    )
    high_prices = pd.DataFrame(
        np.maximum(open_prices.to_numpy(), close_prices.to_numpy()) + 0.5,
        index=dates,
        columns=open_prices.columns,
    )
    low_prices = pd.DataFrame(
        np.minimum(open_prices.to_numpy(), close_prices.to_numpy()) - 0.5,
        index=dates,
        columns=open_prices.columns,
    )
    return open_prices, high_prices, low_prices, close_prices


def test_crows_pattern_returns_each_pattern_as_an_independent_signal():
    pattern_module = _load_module("candlestick_patterns", PATTERN_FILE)
    pattern = pattern_module.Pattern()
    open_prices, high_prices, low_prices, close_prices = _crows_ohlc()

    result = pattern.crows_pattern(open_prices, high_prices, low_prices, close_prices)

    assert set(result) == {"two_crows", "three_crows"}
    assert result["two_crows"].iloc[-1]["TWO.SZ"] == pytest.approx(-0.6)
    assert result["three_crows"].iloc[-1]["THREE.SZ"] == pytest.approx(-0.7)


def test_multi_index_matrix_keeps_crows_as_independent_columns():
    pattern_module = _load_module("candlestick_patterns_matrix", PATTERN_FILE)
    pattern = pattern_module.Pattern()
    open_prices, high_prices, low_prices, close_prices = _crows_ohlc()
    volume = pd.DataFrame(0.0, index=close_prices.index, columns=close_prices.columns)

    result = pattern.get_multi_index_signal_matrix(
        open_prices,
        high_prices,
        low_prices,
        close_prices,
        volume,
        enabled_signals=["crows"],
    )

    assert list(result.columns) == ["two_crows", "three_crows"]
    assert result.loc[(20260112, "TWO.SZ"), "two_crows"] == pytest.approx(-0.6)
    assert result.loc[(20260112, "THREE.SZ"), "three_crows"] == pytest.approx(-0.7)


def test_total_signal_matrix_accumulates_both_crows_patterns():
    pattern_module = _load_module("candlestick_patterns_total", PATTERN_FILE)
    pattern = pattern_module.Pattern()
    open_prices, high_prices, low_prices, close_prices = _crows_ohlc()
    volume = pd.DataFrame(0.0, index=close_prices.index, columns=close_prices.columns)

    buy, sell = pattern.get_total_signal_matrix(
        open_prices,
        high_prices,
        low_prices,
        close_prices,
        volume,
        enabled_signals=["crows"],
    )

    assert buy.iloc[-1]["TWO.SZ"] == pytest.approx(0.0)
    assert sell.iloc[-1]["TWO.SZ"] == pytest.approx(-0.6)
    assert sell.iloc[-1]["THREE.SZ"] == pytest.approx(-0.7)


def test_pattern_names_match_strength_and_span_metadata():
    pattern_module = _load_module("candlestick_patterns_metadata", PATTERN_FILE)
    meta_module = _load_module("candlestick_metadata", META_FILE)

    assert set(pattern_module.Pattern().signal_strength) == set(meta_module.SIGNAL_BAR_SPAN)
