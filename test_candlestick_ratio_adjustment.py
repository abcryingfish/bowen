from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


MODULE_PATH = Path(__file__).resolve().parent / "工具" / "形态蜡烛信号生成_合并保存.py"


def load_module():
    spec = importlib.util.spec_from_file_location("candlestick_signal_gen", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_apply_ratio_backward_adjustment_multiplies_ohlc_only():
    module = load_module()
    rows = pd.DataFrame(
        {
            "htsc_code": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "date_key": [20240102, 20240103, 20240104],
            "open": [10.0, 11.0, 12.0],
            "high": [11.0, 12.0, 13.0],
            "low": [9.0, 10.0, 11.0],
            "close": [10.5, 11.5, 12.5],
            "volume": [100.0, 110.0, 120.0],
        }
    )
    xdy_by_code = {
        "000001.SZ": pd.Series(
            [2.0, 2.0, 3.0],
            index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
        )
    }

    adjusted = module.apply_ratio_backward_adjustment(rows, xdy_by_code)

    np.testing.assert_allclose(adjusted["open"].to_numpy(), [20.0, 22.0, 72.0])
    np.testing.assert_allclose(adjusted["high"].to_numpy(), [22.0, 24.0, 78.0])
    np.testing.assert_allclose(adjusted["low"].to_numpy(), [18.0, 20.0, 66.0])
    np.testing.assert_allclose(adjusted["close"].to_numpy(), [21.0, 23.0, 75.0])
    np.testing.assert_allclose(adjusted["volume"].to_numpy(), [100.0, 110.0, 120.0])


def test_apply_ratio_backward_adjustment_keeps_prior_segment_factor_for_later_window():
    module = load_module()
    rows = pd.DataFrame(
        {
            "htsc_code": ["000001.SZ"],
            "date_key": [20240104],
            "open": [12.0],
            "high": [13.0],
            "low": [11.0],
            "close": [12.5],
            "volume": [120.0],
        }
    )
    xdy_by_code = {
        "000001.SZ": pd.Series(
            [2.0, 2.0, 3.0],
            index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
        )
    }

    adjusted = module.apply_ratio_backward_adjustment(rows, xdy_by_code)

    np.testing.assert_allclose(adjusted["open"].to_numpy(), [72.0])
