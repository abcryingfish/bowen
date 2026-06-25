from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _load_module(filename: str, module_name: str):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_valid_bar_compact_batch_matches_single_stock_compaction():
    mod = _load_module("valid_bar_utils.py", "valid_bar_utils_under_test")

    index = pd.date_range("2024-01-01", periods=7, freq="D")
    columns = pd.Index(["000001.SZ", "000002.SZ", "000003.SZ"])
    base = np.arange(len(index) * len(columns), dtype=float).reshape(len(index), len(columns))
    C = pd.DataFrame(base + 10.0, index=index, columns=columns)
    O = C - 0.1
    H = C + 0.2
    L = C - 0.3
    V = C * 1000.0
    valid_bar = pd.DataFrame(True, index=index, columns=columns)
    valid_bar.loc[index[[2, 5]], "000001.SZ"] = False
    valid_bar.loc[index[[1, 4]], "000002.SZ"] = False

    calls = []

    def raw_compute(*, O, H, L, C, V, selected_bundles, T, enable_bottom_cache, valid_bar):
        calls.append(tuple(C.columns))
        signal = (C - C.shift(1)).fillna(0.0)
        rolling = C.rolling(3, min_periods=1).mean()
        return set(selected_bundles), [
            {
                "factor_dfs": {"signal": signal, "rolling": rolling},
                "factor_name_map": {"信号": "signal", "滚动": "rolling"},
            }
        ]

    batch_result = mod.compute_bundles_with_valid_bar(
        raw_compute,
        O=O,
        H=H,
        L=L,
        C=C,
        V=V,
        selected_bundles=["demo"],
        T=None,
        valid_bar=valid_bar,
    )[1][0]["factor_dfs"]
    production_calls = list(calls)

    expected = {name: pd.DataFrame(0.0, index=index, columns=columns) for name in batch_result}
    for col in columns:
        real_index = index[valid_bar[col].to_numpy()]
        one = raw_compute(
            O=O.loc[real_index, [col]],
            H=H.loc[real_index, [col]],
            L=L.loc[real_index, [col]],
            C=C.loc[real_index, [col]],
            V=V.loc[real_index, [col]],
            selected_bundles=["demo"],
            T=None,
            enable_bottom_cache=False,
            valid_bar=valid_bar.loc[real_index, [col]],
        )[1][0]["factor_dfs"]
        for name, frame in one.items():
            expected[name].loc[real_index, col] = frame[col].to_numpy()

    for name in batch_result:
        pd.testing.assert_frame_equal(batch_result[name], expected[name])
    assert len(production_calls) == 2
    assert production_calls[-1] == ("000001.SZ", "000002.SZ")


def test_total_buy_uses_precomputed_chip_without_recomputing(monkeypatch):
    mod = _load_module("总买入信号_独立全量.py", "total_buy_precompute_under_test")

    index = pd.date_range("2024-01-01", periods=6, freq="D")
    columns = pd.Index(["000001.SZ", "000002.SZ"])
    ones = pd.DataFrame(1.0, index=index, columns=columns)
    zeros = pd.DataFrame(0.0, index=index, columns=columns)

    def fail_chip(*args, **kwargs):
        raise AssertionError("chip bundle should be reused from precomputed_factors")

    monkeypatch.setattr(mod, "_ext_build_chip_structure_factor_bundle", fail_chip)
    out = mod.build_total_buy_signal_bundle(
        O=ones,
        H=ones,
        L=ones,
        C=ones,
        V=ones,
        precomputed_factors={
            "bottom_fishing_score": ones,
            "r_condition": ones,
            "mac_total": ones,
            "concentration_total_score": ones,
            "chip_peak_score": ones,
            "single_peak_best": ones,
        },
    )

    assert out["factor_dfs"]["total_buy_signal"].equals(ones)
    assert out["factor_dfs"]["super_strong_bottom"].equals(ones)
    assert out["factor_dfs"]["total_buy_signal_adjusted_no_concentration"].iloc[0, 0] == 1.0
