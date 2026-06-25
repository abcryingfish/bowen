import importlib.util
import concurrent.futures
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _load_chip_module():
    path = Path(__file__).with_name("筹码结构因子.py")
    module_name = "筹码结构因子"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules.pop(module_name, None)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_module(filename: str, module_name: str):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_chip_structure_does_not_wrap_all_cost_percentiles_as_frames(monkeypatch):
    mod = _load_chip_module()
    monkeypatch.setenv("ZXW_CHIP_STATE_CACHE", "0")

    index = pd.date_range("2024-01-01", periods=6, freq="D")
    columns = pd.Index(["000001.SZ", "000002.SZ"])
    base = np.array(
        [
            [10.0, 20.0],
            [10.2, 19.8],
            [10.4, 20.1],
            [10.3, 20.3],
            [10.5, 20.2],
            [10.7, 20.5],
        ],
        dtype=float,
    )
    C = pd.DataFrame(base, index=index, columns=columns)
    H = pd.DataFrame(base + 0.30, index=index, columns=columns)
    L = pd.DataFrame(base - 0.25, index=index, columns=columns)
    V = pd.DataFrame(1000000.0, index=index, columns=columns)
    T = pd.DataFrame(5.0, index=index, columns=columns)

    original_dataframe = mod.pd.DataFrame
    frame_calls = 0

    class CountingDataFrame(original_dataframe):
        def __init__(self, *args, **kwargs):
            nonlocal frame_calls
            frame_calls += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(mod.pd, "DataFrame", CountingDataFrame)
    monkeypatch.setattr(mod, "_NUMBA_AVAILABLE", False)

    out = mod.build_chip_structure_factor_bundle(H=H, L=L, C=C, V=V, T=T)

    assert "factor_dfs" in out
    assert out["factor_dfs"]["cost_99pct"].shape == C.shape
    assert frame_calls < 50


def test_chip_structure_reuses_same_input_in_process_cache(monkeypatch):
    mod = _load_chip_module()
    monkeypatch.setenv("ZXW_CHIP_STATE_CACHE", "0")

    index = pd.date_range("2024-01-01", periods=5, freq="D")
    columns = pd.Index(["000001.SZ", "000002.SZ"])
    base = np.array(
        [
            [10.0, 20.0],
            [10.2, 19.8],
            [10.4, 20.1],
            [10.3, 20.3],
            [10.5, 20.2],
        ],
        dtype=float,
    )
    C = pd.DataFrame(base, index=index, columns=columns)
    H = pd.DataFrame(base + 0.30, index=index, columns=columns)
    L = pd.DataFrame(base - 0.25, index=index, columns=columns)
    V = pd.DataFrame(1000000.0, index=index, columns=columns)
    T = pd.DataFrame(5.0, index=index, columns=columns)

    calls = 0

    def fake_cost_matrix(high, low, close, volume, turnover, percentiles, *args):
        nonlocal calls
        calls += 1
        return np.zeros((len(percentiles), high.shape[0], high.shape[1]), dtype=np.float64)

    monkeypatch.setattr(mod, "_NUMBA_AVAILABLE", True)
    monkeypatch.setattr(mod, "_compute_chouma_cost_matrix_numba", fake_cost_matrix)
    monkeypatch.setattr(mod, "_tdx_relative_concentration", lambda abs_conc: np.zeros_like(abs_conc))
    monkeypatch.setattr(mod, "load_turnover_wide", lambda index, columns, base_dir=mod.DEFAULT_TURNOVER_BASE_DIR: T)

    first = mod.build_chip_structure_factor_bundle(H=H, L=L, C=C, V=V, T=T)
    second = mod.build_chip_structure_factor_bundle(H=H, L=L, C=C, V=V, T=T)
    third = mod.build_chip_structure_factor_bundle(H=H, L=L, C=C, V=V, T=T, min_d=0.02)

    assert calls == 2
    pd.testing.assert_frame_equal(
        first["factor_dfs"]["chip_peak_score"],
        second["factor_dfs"]["chip_peak_score"],
    )
    assert third["factor_dfs"]["chip_peak_score"].shape == C.shape


def test_chip_structure_cache_is_shared_by_dependent_bundles(monkeypatch):
    mod = _load_chip_module()
    monkeypatch.setenv("ZXW_CHIP_STATE_CACHE", "0")

    index = pd.date_range("2024-01-01", periods=6, freq="D")
    columns = pd.Index(["000001.SZ", "000002.SZ"])
    base = np.array(
        [
            [10.0, 20.0],
            [10.2, 19.8],
            [10.4, 20.1],
            [10.3, 20.3],
            [10.5, 20.2],
            [10.7, 20.5],
        ],
        dtype=float,
    )
    C = pd.DataFrame(base, index=index, columns=columns)
    H = pd.DataFrame(base + 0.30, index=index, columns=columns)
    L = pd.DataFrame(base - 0.25, index=index, columns=columns)
    O = pd.DataFrame(base - 0.05, index=index, columns=columns)
    V = pd.DataFrame(1000000.0, index=index, columns=columns)
    T = pd.DataFrame(5.0, index=index, columns=columns)

    calls = 0

    def fake_cost_matrix(high, low, close, volume, turnover, percentiles, *args):
        nonlocal calls
        calls += 1
        return np.zeros((len(percentiles), high.shape[0], high.shape[1]), dtype=np.float64)

    monkeypatch.setattr(mod, "_NUMBA_AVAILABLE", True)
    monkeypatch.setattr(mod, "_compute_chouma_cost_matrix_numba", fake_cost_matrix)
    monkeypatch.setattr(mod, "_tdx_relative_concentration", lambda abs_conc: np.zeros_like(abs_conc))
    monkeypatch.setattr(mod, "load_turnover_wide", lambda index, columns, base_dir=mod.DEFAULT_TURNOVER_BASE_DIR: T)

    total_buy = _load_module("总买入信号_独立全量.py", "total_buy_under_test")
    tdx_bottom = _load_module("通达信强底信号.py", "tdx_bottom_under_test")
    monkeypatch.setattr(total_buy, "_ext_build_chip_structure_factor_bundle", mod.build_chip_structure_factor_bundle)
    monkeypatch.setattr(tdx_bottom, "_build_chip_structure_factor_bundle", mod.build_chip_structure_factor_bundle)
    monkeypatch.setattr(tdx_bottom, "MIN_BARSCOUNT", 1)

    total_buy.build_total_buy_signal_bundle(O=O, H=H, L=L, C=C, V=V)
    tdx_bottom.build_tdx_bottom_alert_bundle(O=O, H=H, L=L, C=C, V=V, valid_bar=None)
    mod.build_chip_structure_factor_bundle(H=H, L=L, C=C, V=V, T=T)

    assert calls == 1


def test_chip_state_cache_replays_incremental_tail_like_full_run(tmp_path, monkeypatch):
    mod = _load_chip_module()
    monkeypatch.setenv("ZXW_CHIP_BUNDLE_CACHE", "0")
    monkeypatch.setattr(mod, "CHIP_STATE_CACHE_PATH", str(tmp_path / "latest_state.parquet"))

    index = pd.date_range("2024-01-01", periods=18, freq="D")
    columns = pd.Index(["000001.SZ", "000002.SZ"])
    base = np.array(
        [[10.0 + i * 0.08, 20.0 + np.sin(i / 3.0) * 0.4] for i in range(len(index))],
        dtype=float,
    )
    C = pd.DataFrame(base, index=index, columns=columns)
    H = pd.DataFrame(base + 0.35, index=index, columns=columns)
    L = pd.DataFrame(base - 0.25, index=index, columns=columns)
    V = pd.DataFrame(1000000.0, index=index, columns=columns)
    T = pd.DataFrame(5.0, index=index, columns=columns)
    H.iloc[10:12, 0] = np.nan
    L.iloc[10:12, 0] = np.nan
    T.iloc[10:12, 0] = np.nan
    H.iloc[-2:, 1] = np.nan
    L.iloc[-2:, 1] = np.nan
    T.iloc[-2:, 1] = np.nan

    monkeypatch.setenv("ZXW_CHIP_STATE_CACHE", "0")
    full = mod.build_chip_structure_factor_bundle(H=H, L=L, C=C, V=V, T=T)

    split = 9
    monkeypatch.setenv("ZXW_CHIP_STATE_CACHE", "1")
    mod.clear_chip_structure_bundle_cache()
    mod.build_chip_structure_factor_bundle(
        H=H.iloc[:split],
        L=L.iloc[:split],
        C=C.iloc[:split],
        V=V.iloc[:split],
        T=T.iloc[:split],
    )
    tail = mod.build_chip_structure_factor_bundle(
        H=H.iloc[split:],
        L=L.iloc[split:],
        C=C.iloc[split:],
        V=V.iloc[split:],
        T=T.iloc[split:],
    )

    for factor_name, tail_frame in tail["factor_dfs"].items():
        expected = full["factor_dfs"][factor_name].loc[tail_frame.index, tail_frame.columns]
        pd.testing.assert_frame_equal(tail_frame, expected)

    assert (tmp_path / "latest_state.parquet").exists()
    assert not (tmp_path / "latest_state.tmp.parquet").exists()


def test_chip_state_cache_uses_tail_when_input_contains_lookback_overlap(tmp_path, monkeypatch):
    mod = _load_chip_module()
    monkeypatch.setenv("ZXW_CHIP_BUNDLE_CACHE", "0")
    monkeypatch.setattr(mod, "CHIP_STATE_CACHE_PATH", str(tmp_path / "latest_state.parquet"))
    monkeypatch.setattr(mod, "_NUMBA_AVAILABLE", False)

    index = pd.date_range("2024-01-01", periods=80, freq="D")
    columns = pd.Index(["000001.SZ", "000002.SZ"])
    rng = np.random.default_rng(42)
    base = 10.0 + rng.normal(0.0, 0.2, (len(index), len(columns))).cumsum(axis=0)
    C = pd.DataFrame(base, index=index, columns=columns)
    H = pd.DataFrame(base + 0.35, index=index, columns=columns)
    L = pd.DataFrame(base - 0.25, index=index, columns=columns)
    V = pd.DataFrame(1000000.0, index=index, columns=columns)
    T = pd.DataFrame(5.0, index=index, columns=columns)

    monkeypatch.setenv("ZXW_CHIP_STATE_CACHE", "0")
    full = mod.build_chip_structure_factor_bundle(H=H, L=L, C=C, V=V, T=T)

    split = 60
    monkeypatch.setenv("ZXW_CHIP_STATE_CACHE", "1")
    mod.clear_chip_structure_bundle_cache()
    mod.build_chip_structure_factor_bundle(
        H=H.iloc[:split],
        L=L.iloc[:split],
        C=C.iloc[:split],
        V=V.iloc[:split],
        T=T.iloc[:split],
    )
    mod.clear_chip_structure_bundle_cache()
    overlap_start = 45
    overlap = mod.build_chip_structure_factor_bundle(
        H=H.iloc[overlap_start:],
        L=L.iloc[overlap_start:],
        C=C.iloc[overlap_start:],
        V=V.iloc[overlap_start:],
        T=T.iloc[overlap_start:],
    )

    for factor_name, frame in overlap["factor_dfs"].items():
        got = frame.loc[index[split:]]
        expected = full["factor_dfs"][factor_name].loc[index[split:]]
        pd.testing.assert_frame_equal(got, expected)


def test_chip_state_cache_handles_calendar_gap_after_cached_date(tmp_path, monkeypatch):
    mod = _load_chip_module()
    monkeypatch.setenv("ZXW_CHIP_BUNDLE_CACHE", "0")
    monkeypatch.setattr(mod, "CHIP_STATE_CACHE_PATH", str(tmp_path / "latest_state.parquet"))
    monkeypatch.setattr(mod, "_NUMBA_AVAILABLE", False)

    index = pd.bdate_range("2024-01-01", periods=40)
    columns = pd.Index(["000001.SZ"])
    base = np.linspace(10.0, 12.0, len(index)).reshape(-1, 1)
    C = pd.DataFrame(base, index=index, columns=columns)
    H = pd.DataFrame(base + 0.25, index=index, columns=columns)
    L = pd.DataFrame(base - 0.20, index=index, columns=columns)
    V = pd.DataFrame(1000000.0, index=index, columns=columns)
    T = pd.DataFrame(5.0, index=index, columns=columns)

    monkeypatch.setenv("ZXW_CHIP_STATE_CACHE", "0")
    full = mod.build_chip_structure_factor_bundle(H=H, L=L, C=C, V=V, T=T)

    split = 25
    assert index[split - 1].weekday() == 4
    assert index[split].weekday() == 0
    monkeypatch.setenv("ZXW_CHIP_STATE_CACHE", "1")
    mod.clear_chip_structure_bundle_cache()
    mod.build_chip_structure_factor_bundle(
        H=H.iloc[:split],
        L=L.iloc[:split],
        C=C.iloc[:split],
        V=V.iloc[:split],
        T=T.iloc[:split],
    )
    mod.clear_chip_structure_bundle_cache()
    tail = mod.build_chip_structure_factor_bundle(
        H=H.iloc[split:],
        L=L.iloc[split:],
        C=C.iloc[split:],
        V=V.iloc[split:],
        T=T.iloc[split:],
    )

    for factor_name, frame in tail["factor_dfs"].items():
        expected = full["factor_dfs"][factor_name].loc[frame.index, frame.columns]
        pd.testing.assert_frame_equal(frame, expected)


def test_chip_state_cache_param_mismatch_falls_back_to_full(tmp_path, monkeypatch):
    mod = _load_chip_module()
    monkeypatch.setenv("ZXW_CHIP_BUNDLE_CACHE", "0")
    monkeypatch.setattr(mod, "CHIP_STATE_CACHE_PATH", str(tmp_path / "latest_state.parquet"))

    index = pd.date_range("2024-02-01", periods=10, freq="D")
    columns = pd.Index(["000001.SZ"])
    base = np.linspace(10.0, 11.0, len(index)).reshape(-1, 1)
    C = pd.DataFrame(base, index=index, columns=columns)
    H = pd.DataFrame(base + 0.2, index=index, columns=columns)
    L = pd.DataFrame(base - 0.2, index=index, columns=columns)
    V = pd.DataFrame(1000000.0, index=index, columns=columns)
    T = pd.DataFrame(5.0, index=index, columns=columns)

    mod.build_chip_structure_factor_bundle(H=H.iloc[:5], L=L.iloc[:5], C=C.iloc[:5], V=V.iloc[:5], T=T.iloc[:5])
    out = mod.build_chip_structure_factor_bundle(
        H=H.iloc[5:],
        L=L.iloc[5:],
        C=C.iloc[5:],
        V=V.iloc[5:],
        T=T.iloc[5:],
        min_d=0.02,
    )

    assert out["factor_dfs"]["chip_peak_score"].shape == (5, 1)


def test_chip_state_cache_concurrent_writes_merge_without_losing_codes(tmp_path):
    mod = _load_chip_module()
    cache_path = str(tmp_path / "latest_state.parquet")
    base_state = {
        "last_dt": pd.Timestamp("2024-01-01"),
        "chip": np.array([1.0, 2.0], dtype=np.float64),
        "base_low": 1.0,
        "n_bins": 2,
        "cum_high": 2.0,
        "cum_low": 1.0,
        "abs_conc_tail": np.array([3.0], dtype=np.float64),
        "min_d": 0.01,
        "ac": 1.0,
    }

    def write_one(i: int) -> int:
        if i % 3 == 0:
            mod._load_chip_state_cache(cache_path)
        state = dict(base_state)
        state["last_dt"] = base_state["last_dt"] + pd.Timedelta(days=i)
        mod._save_chip_state_cache({f"{i:06d}.SZ": state}, path=cache_path)
        return i

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        assert len(list(executor.map(write_one, range(40)))) == 40

    states = mod._load_chip_state_cache(cache_path)
    assert len(states) == 40
    assert not list(tmp_path.glob("*.tmp.parquet"))
