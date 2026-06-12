from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _to_frame(x: Any, index: pd.Index, columns: pd.Index, dtype: Any = None) -> pd.DataFrame:
    if isinstance(x, pd.DataFrame):
        result = x.reindex(index=index, columns=columns)
        return result.astype(dtype) if dtype is not None else result
    if np.isscalar(x):
        return pd.DataFrame(x, index=index, columns=columns, dtype=dtype)
    result = pd.DataFrame(x, index=index, columns=columns)
    return result.astype(dtype) if dtype is not None else result


def HHV(X: Any, N: int, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    window = max(int(N), 1)
    return frame.rolling(window=window, min_periods=1).max()


def REF(X: Any, N: int, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    step = max(int(N), 0)
    return frame.shift(step)


def _wilder_atr(H: pd.DataFrame, L: pd.DataFrame, C: pd.DataFrame, n: int) -> pd.DataFrame:
    prev_close = C.shift(1)
    tr = pd.DataFrame(
        np.maximum.reduce(
            [
                (H - L).to_numpy(dtype=float, copy=False),
                (H - prev_close).abs().to_numpy(dtype=float, copy=False),
                (L - prev_close).abs().to_numpy(dtype=float, copy=False),
            ]
        ),
        index=C.index,
        columns=C.columns,
    )
    period = max(int(n), 1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=1).mean()


def build_dynamic_volatility_channel_factor_bundle(
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    high_window: int = 20,
    atr_window: int = 14,
    atr_multiplier: float = 1.5,
) -> dict[str, dict[str, pd.DataFrame]]:
    """
    动态波动率通道:
    - 近期高点(不含当日) = REF(HHV(H, high_window), 1)
    - ATR = Wilder ATR(atr_window)
    - 通道值 = 近期高点 - atr_multiplier * ATR
    - 下破信号 = C < 通道值 (严格小于, 等于不触发)
    """
    index, columns = C.index, C.columns
    H = _to_frame(H, index=index, columns=columns).astype(float)
    L = _to_frame(L, index=index, columns=columns).astype(float)
    C = _to_frame(C, index=index, columns=columns).astype(float)

    recent_high_exclusive = REF(HHV(H, high_window, index, columns), 1, index, columns)
    atr = _wilder_atr(H=H, L=L, C=C, n=atr_window)
    dynamic_vol_channel = recent_high_exclusive - float(atr_multiplier) * atr
    dynamic_vol_break_down = (C < dynamic_vol_channel).astype(float)

    factor_dfs: dict[str, pd.DataFrame] = {
        "dynamic_vol_channel": dynamic_vol_channel,
        "dynamic_vol_break_down": dynamic_vol_break_down,
    }

    factor_name_map: dict[str, str] = {
        "动态波动率通道": "dynamic_vol_channel",
        "动态波动率下破": "dynamic_vol_break_down",
    }

    return {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }


BUNDLE_ID = "dynamic_volatility_channel"
_DEFAULT_LOOKBACK_DAYS = 90

FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    "dynamic_vol_channel": 60,
    "dynamic_vol_break_down": 60,
}


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
