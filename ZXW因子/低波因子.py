"""股票级低波动率和回撤因子。"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

try:
    from numba import njit, prange

    _NUMBA_AVAILABLE = True
except Exception:  # pragma: no cover
    _NUMBA_AVAILABLE = False
    njit = None  # type: ignore
    prange = range  # type: ignore


BUNDLE_ID = "low_volatility"


def _calendar_lookback_days(required_bars: int) -> int:
    """将交易日滚动窗口转换为保守的自然日回看长度。"""
    return (int(required_bars) * 3 + 1) // 2


FACTOR_LOOKBACK_DAYS = {
    "annual_vol_20d": _calendar_lookback_days(21),
    "annual_vol_60d": _calendar_lookback_days(61),
    "annual_vol_252d": _calendar_lookback_days(253),
    "downside_vol_20d": _calendar_lookback_days(21),
    "downside_vol_60d": _calendar_lookback_days(61),
    "max_drawdown_60d": _calendar_lookback_days(60),
    "atr_volatility_14d": _calendar_lookback_days(15),
    "volatility_ratio_20_60d": _calendar_lookback_days(61),
}
FACTOR_NAME_MAP = {
    "20日年化波动率": "annual_vol_20d",
    "60日年化波动率_股票": "annual_vol_60d",
    "252日年化波动率": "annual_vol_252d",
    "20日下行波动率": "downside_vol_20d",
    "60日下行波动率": "downside_vol_60d",
    "60日最大回撤": "max_drawdown_60d",
    "14日ATR波动率": "atr_volatility_14d",
    "20/60日波动率比": "volatility_ratio_20_60d",
}


def get_factor_catalog() -> dict[str, dict[str, str]]:
    return {"factor_name_map": dict(FACTOR_NAME_MAP)}


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(FACTOR_LOOKBACK_DAYS.values()),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }


def _frame(value: pd.DataFrame, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    return value.reindex(index=index, columns=columns).astype(float)


if _NUMBA_AVAILABLE:

    @njit(cache=False, fastmath=False, parallel=True)
    def _rolling_max_drawdown_numba(values: np.ndarray, window: int) -> np.ndarray:
        n_rows, n_cols = values.shape
        output = np.full((n_rows, n_cols), np.nan, dtype=np.float64)
        for col in prange(n_cols):
            for end in range(window - 1, n_rows):
                start = end - window + 1
                peak = values[start, col]
                if not np.isfinite(peak):
                    continue
                max_drawdown = 0.0
                valid = True
                for row in range(start, end + 1):
                    price = values[row, col]
                    if not np.isfinite(price):
                        valid = False
                        break
                    if price > peak:
                        peak = price
                    drawdown = price / peak - 1.0
                    if drawdown < max_drawdown:
                        max_drawdown = drawdown
                if valid:
                    output[end, col] = max_drawdown
        return output
else:
    _rolling_max_drawdown_numba = None


def _rolling_max_drawdown(close: pd.DataFrame, window: int) -> pd.DataFrame:
    """计算严格限定在滚动窗口内的最大回撤；优先使用 NumPy/Numba 矩阵路径。"""
    values = close.to_numpy(dtype=np.float64, copy=False)
    if _NUMBA_AVAILABLE:
        output = _rolling_max_drawdown_numba(values, int(window))
        return pd.DataFrame(output, index=close.index, columns=close.columns)

    def max_drawdown(window_values: np.ndarray) -> float:
        peak = np.maximum.accumulate(window_values)
        return float(np.min(window_values / peak - 1.0))

    return close.rolling(window, min_periods=window).apply(max_drawdown, raw=True)


def build_low_volatility_factor_bundle(
    C: pd.DataFrame,
    H: pd.DataFrame | None = None,
    L: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """从日线 OHLC 生成股票级低波动率因子。"""
    index, columns = C.index, C.columns
    close = _frame(C, index, columns).where(lambda frame: frame > 0.0)
    high = (
        _frame(H, index, columns).where(lambda frame: frame > 0.0)
        if H is not None
        else pd.DataFrame(np.nan, index=index, columns=columns)
    )
    low = (
        _frame(L, index, columns).where(lambda frame: frame > 0.0)
        if L is not None
        else pd.DataFrame(np.nan, index=index, columns=columns)
    )
    returns = close.pct_change(fill_method=None)

    annual_vol_20d = returns.rolling(20, min_periods=20).std() * np.sqrt(252.0)
    annual_vol_60d = returns.rolling(60, min_periods=60).std() * np.sqrt(252.0)
    annual_vol_252d = returns.rolling(252, min_periods=252).std() * np.sqrt(252.0)
    downside_returns = returns.clip(upper=0.0)
    downside_vol_20d = (
        downside_returns.pow(2).rolling(20, min_periods=20).mean().pow(0.5)
        * np.sqrt(252.0)
    )
    downside_vol_60d = (
        downside_returns.pow(2).rolling(60, min_periods=60).mean().pow(0.5)
        * np.sqrt(252.0)
    )

    max_drawdown_60d = _rolling_max_drawdown(close, window=60)

    previous_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()],
        keys=("hl", "hc", "lc"),
    ).groupby(level=1).max()
    atr_volatility_14d = (
        (true_range / previous_close.abs())
        .rolling(14, min_periods=14)
        .mean()
        * np.sqrt(252.0)
    )
    volatility_ratio_20_60d = annual_vol_20d / annual_vol_60d.replace(0.0, np.nan)

    factor_dfs = {
        "annual_vol_20d": annual_vol_20d,
        "annual_vol_60d": annual_vol_60d,
        "annual_vol_252d": annual_vol_252d,
        "downside_vol_20d": downside_vol_20d,
        "downside_vol_60d": downside_vol_60d,
        "max_drawdown_60d": max_drawdown_60d,
        "atr_volatility_14d": atr_volatility_14d,
        "volatility_ratio_20_60d": volatility_ratio_20_60d,
    }
    return {
        "bundle_id": BUNDLE_ID,
        "factor_dfs": factor_dfs,
        "factor_name_map": dict(FACTOR_NAME_MAP),
        "factor_merge_policies": {
            key: {"preserve_columns": True, "preserve_nan": True}
            for key in factor_dfs
        },
    }
