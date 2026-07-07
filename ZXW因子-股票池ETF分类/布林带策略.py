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


def build_boll_strategy_factor_bundle(
    C: pd.DataFrame,
    window: int = 20,
    k: float = 2.0,
) -> dict[str, dict[str, pd.DataFrame]]:
    """
    布林带策略（默认 20 日）:
    - 中轨 = MA(C, window)
    - 上轨 = 中轨 + k * STD(C, window)
    - 下轨 = 中轨 - k * STD(C, window)
    - 上穿上轨 / 下穿上轨 / 上穿下轨 / 下穿下轨：均为 1/0 信号
    """
    index, columns = C.index, C.columns
    C = _to_frame(C, index=index, columns=columns).astype(float)
    window = max(int(window), 1)
    k = float(k)

    boll_mid = C.rolling(window=window, min_periods=1).mean()
    boll_std = C.rolling(window=window, min_periods=1).std(ddof=0)
    boll_upper = boll_mid + k * boll_std
    boll_lower = boll_mid - k * boll_std

    prev_c = C.shift(1)
    prev_upper = boll_upper.shift(1)
    prev_lower = boll_lower.shift(1)

    cross_up_upper = ((prev_c <= prev_upper) & (C > boll_upper)).astype(float)
    cross_down_upper_raw = ((prev_c >= prev_upper) & (C < boll_upper)).astype(float)
    # 下穿上布林带信号延长1个单位（出现后保持1多一天）
    cross_down_upper = ((cross_down_upper_raw == 1) | (cross_down_upper_raw.shift(1) == 1)).astype(float)
    cross_up_lower = ((prev_c <= prev_lower) & (C > boll_lower)).astype(float)
    cross_down_lower = ((prev_c >= prev_lower) & (C < boll_lower)).astype(float)

    factor_dfs: dict[str, pd.DataFrame] = {
        "boll_upper": boll_upper,
        "boll_mid": boll_mid,
        "boll_lower": boll_lower,
        "cross_up_boll_upper": cross_up_upper,
        "cross_down_boll_upper": cross_down_upper,
        "cross_up_boll_lower": cross_up_lower,
        "cross_down_boll_lower": cross_down_lower,
    }

    factor_name_map: dict[str, str] = {
        "布林上轨": "boll_upper",
        "布林中轨": "boll_mid",
        "布林下轨": "boll_lower",
        "上穿上布林带": "cross_up_boll_upper",
        "下穿上布林带": "cross_down_boll_upper",
        "上穿下布林带": "cross_up_boll_lower",
        "下穿下布林带": "cross_down_boll_lower",
    }

    return {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }


BUNDLE_ID = "boll_strategy"
_DEFAULT_LOOKBACK_DAYS = 60

FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    "boll_upper": 20,
    "boll_mid": 20,
    "boll_lower": 20,
    "cross_up_boll_upper": 21,
    "cross_down_boll_upper": 21,
    "cross_up_boll_lower": 21,
    "cross_down_boll_lower": 21,
}


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
