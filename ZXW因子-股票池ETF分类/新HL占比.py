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


def build_new_hl_ratio_factor_bundle(
    C: pd.DataFrame,
    window: int = 20,
) -> dict[str, dict[str, pd.DataFrame]]:
    """
    20日新高/新低天数占比（包含当日）:
    - 新高判定: C == rolling_max(C, window)
    - 新低判定: C == rolling_min(C, window)
    - 占比: 过去 window 天判定为 True 的比例（0~1）
    """
    index, columns = C.index, C.columns
    C = _to_frame(C, index=index, columns=columns).astype(float)
    window = max(int(window), 1)

    rolling_max = C.rolling(window=window, min_periods=1).max()
    rolling_min = C.rolling(window=window, min_periods=1).min()

    new_high_flag = (C == rolling_max).astype(float)
    new_low_flag = (C == rolling_min).astype(float)

    new_high_ratio = new_high_flag.rolling(window=window, min_periods=1).mean()
    new_low_ratio = new_low_flag.rolling(window=window, min_periods=1).mean()

    factor_dfs: dict[str, pd.DataFrame] = {
        "new_high_ratio_20d": new_high_ratio,
        "new_low_ratio_20d": new_low_ratio,
    }

    factor_name_map: dict[str, str] = {
        "20日新高占比": "new_high_ratio_20d",
        "20日新低占比": "new_low_ratio_20d",
    }

    return {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }


BUNDLE_ID = "new_hl_ratio"
_DEFAULT_LOOKBACK_DAYS = 60

FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    "new_high_ratio_20d": 40,
    "new_low_ratio_20d": 40,
}


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
