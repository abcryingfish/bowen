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


def LLV(X: Any, N: int, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    window = max(int(N), 1)
    return frame.rolling(window=window, min_periods=1).min()


def REF(X: Any, N: int, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    step = max(int(N), 0)
    return frame.shift(step)


def build_donchian_lower_channel_factor_bundle(
    C: pd.DataFrame,
    n: int = 10,
) -> dict[str, dict[str, pd.DataFrame]]:
    """
    唐奇安下通道:
    - 唐奇安下轨 = REF(LLV(C, n), 1)  （不包含当日）
    - 唐奇安下破 = C < 唐奇安下轨      （严格小于，等于不触发）
    """
    index, columns = C.index, C.columns
    C = _to_frame(C, index=index, columns=columns).astype(float)

    donchian_lower = REF(LLV(C, n, index, columns), 1, index, columns)
    donchian_break_down = (C < donchian_lower).astype(float)

    factor_dfs: dict[str, pd.DataFrame] = {
        "donchian_lower": donchian_lower,
        "donchian_break_down": donchian_break_down,
    }

    factor_name_map: dict[str, str] = {
        "唐奇安下轨": "donchian_lower",
        "唐奇安下破": "donchian_break_down",
    }

    return {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }


BUNDLE_ID = "donchian_lower"
_DEFAULT_LOOKBACK_DAYS = 30

FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    "donchian_lower": 20,
    "donchian_break_down": 20,
}


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
