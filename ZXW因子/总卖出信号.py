from __future__ import annotations

import os
from typing import Any

import numpy as np
import pandas as pd

try:
    from 布林带策略 import build_boll_strategy_factor_bundle
    from 新HL占比 import build_new_hl_ratio_factor_bundle

    _EXT_BUNDLES_AVAILABLE = True
except Exception:  # pragma: no cover
    _EXT_BUNDLES_AVAILABLE = False


def _align(
    df: pd.DataFrame,
    index: pd.Index,
    columns: pd.Index,
) -> pd.DataFrame:
    return df.reindex(index=index, columns=columns)


def build_total_sell_signal_bundle(
    C: pd.DataFrame,
) -> dict[str, Any]:
    """当 下穿上布林带 且 20日新高占比不变或降低 时，生成单一布尔矩阵 总卖出信号。

    - 下穿上布林带 ``cross_down_boll_upper``：延长后信号，1 表示在延长触发期内
    - 20日新高占比 ``new_high_ratio_20d``：当天 <= 前一天 视为不变或降低
    """
    index, columns = C.index, C.columns
    debug_timing = os.getenv("ZXW_FACTOR_DEBUG_TIMING", "0") == "1"
    t0 = time.perf_counter() if debug_timing else 0.0

    boll_bundle = build_boll_strategy_factor_bundle(C)
    hl_bundle = build_new_hl_ratio_factor_bundle(C)
    t1 = time.perf_counter() if debug_timing else 0.0

    cross_down_upper = _align(
        boll_bundle["factor_dfs"]["cross_down_boll_upper"], index, columns
    ).astype(float)
    new_high_ratio = _align(
        hl_bundle["factor_dfs"]["new_high_ratio_20d"], index, columns
    ).astype(float)

    # 下穿上布林带信号 == 1（使用延长后的信号）
    boll_signal = cross_down_upper == 1.0

    # 20日新高占比不变或降低：当天 <= 前一天
    new_high_ratio_prev = new_high_ratio.shift(1)
    hl_signal = new_high_ratio <= new_high_ratio_prev

    # 两个条件同时满足时出卖出信号
    total_sell_signal = boll_signal & hl_signal

    factor_dfs: dict[str, pd.DataFrame] = {
        "total_sell_signal": total_sell_signal.astype(float),
    }
    factor_name_map: dict[str, str] = {
        "总卖出信号": "total_sell_signal",
    }

    result = {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }
    if debug_timing:
        t2 = time.perf_counter()
        print(
            f"[总卖出信号] factors={((t1 - t0) * 1000):.2f}ms combine={((t2 - t1) * 1000):.2f}ms "
            f"total={((t2 - t0) * 1000):.2f}ms"
        )
    return result


if __name__ == '__main__':
    idx = pd.date_range('2020-01-01', periods=20, freq='B')
    cols = ['000001.SZ', '000002.SZ']
    rng = np.random.default_rng(0)
    C = pd.DataFrame(rng.uniform(8, 12, size=(len(idx), len(cols))), index=idx, columns=cols)
    out = build_total_sell_signal_bundle(C)
    print('factor_name_map:', out['factor_name_map'])
    print('total_sell_signal sample:\n', out['factor_dfs']['total_sell_signal'].iloc[:5])


BUNDLE_ID = "total_sell_signal"
_DEFAULT_LOOKBACK_DAYS = 60

FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    "total_sell_signal": 21,
}


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
