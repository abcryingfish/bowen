import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _load_chip_module():
    path = Path(__file__).with_name("筹码结构因子.py")
    module_name = "chip_structure_factor_under_test"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_chip_structure_does_not_wrap_all_cost_percentiles_as_frames(monkeypatch):
    mod = _load_chip_module()

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
