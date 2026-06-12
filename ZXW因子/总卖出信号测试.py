from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from KDJ因子 import build_kdj_factor_bundle
from RSI import build_rsi_factor_bundle
from 总卖出信号 import build_total_sell_signal_bundle
from 抄底因子 import build_bottom_fishing_factor_bundle
from 均线因子 import build_moving_average_factor_bundle


def _align(df: pd.DataFrame, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    return df.reindex(index=index, columns=columns)


def _to_binary_positive(df: pd.DataFrame) -> pd.DataFrame:
    # 统一规则：>0 记为 1，否则 0
    return (df.fillna(0.0).astype(float) > 0.0).astype(float)


def build_total_sell_pair_test_bundle(
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    V: pd.DataFrame,
) -> dict[str, Any]:
    """构建卖出组合信号（含 ZXW 因子）。

    另含「ZXW因子+破30/60日均线」：收盘价低于对应均线（弱势区）且当日 ZXW=1 时为 1。
    """
    index, columns = C.index, C.columns

    total_sell_bundle = build_total_sell_signal_bundle(C=C)
    rsi_bundle = build_rsi_factor_bundle(C=C)
    top_escape_bundle = build_bottom_fishing_factor_bundle(O=O, H=H, L=L, C=C)
    kdj_bundle = build_kdj_factor_bundle(O=O, H=H, L=L, C=C)

    total_sell_signal = _align(total_sell_bundle["factor_dfs"]["total_sell_signal"], index, columns)
    top_escape_score = _align(top_escape_bundle["factor_dfs"]["top_escape_score"], index, columns)
    j_overbought_factor = _align(kdj_bundle["factor_dfs"]["j_overbought_factor"], index, columns)
    rsi_cross_down = _align(rsi_bundle["factor_dfs"]["rsi_6_cross_down_rsi_12"], index, columns)
    rsi_overbought = _align(rsi_bundle["factor_dfs"]["rsi_6_overbought"], index, columns)

    factor_dfs: dict[str, pd.DataFrame] = {}
    factor_name_map: dict[str, str] = {}

    combo_1_en = "total_sell_signal__top_escape_score__j_overbought_factor"
    combo_1_cn = "总卖出信号+逃顶总分+J值超买因子"
    combo_1_signal = (
        _to_binary_positive(total_sell_signal)
        * _to_binary_positive(top_escape_score)
        * _to_binary_positive(j_overbought_factor)
    ).astype(float)
    factor_dfs[combo_1_en] = combo_1_signal
    factor_name_map[combo_1_cn] = combo_1_en

    combo_2_en = "rsi_cross_down__rsi_overbought"
    combo_2_cn = "RSI死叉+RSI超买"
    combo_2_signal = (_to_binary_positive(rsi_cross_down) * _to_binary_positive(rsi_overbought)).astype(float)
    factor_dfs[combo_2_en] = combo_2_signal
    factor_name_map[combo_2_cn] = combo_2_en

    # ZXW因子：
    # (RSI死叉 AND RSI超买>=1) OR (逃顶总分>=1 AND J值超买因子>=1) 时信号为 1
    zxw_en = "zxw_factor"
    zxw_cn = "ZXW因子"
    rsi_pair_signal = (_to_binary_positive(rsi_cross_down) * _to_binary_positive(rsi_overbought)).astype(float)
    top_j_pair_signal = (_to_binary_positive(top_escape_score) * _to_binary_positive(j_overbought_factor)).astype(float)
    zxw_signal = ((rsi_pair_signal > 0.0) | (top_j_pair_signal > 0.0)).astype(float)
    factor_dfs[zxw_en] = zxw_signal
    factor_name_map[zxw_cn] = zxw_en

    # ZXW + 弱势均线：收盘价在 MA30/MA60 下方（弱势区）且当日 ZXW=1，比「仅下穿当日」更易出可统计样本。
    close_f = _align(C.astype(float), index, columns)
    ma_bundle = build_moving_average_factor_bundle(C=C, windows=(30, 60))
    ma30 = _align(ma_bundle["factor_dfs"]["ma_30"], index, columns).astype(float)
    ma60 = _align(ma_bundle["factor_dfs"]["ma_60"], index, columns).astype(float)
    below_ma30 = close_f < ma30
    below_ma60 = close_f < ma60
    zxw_bin = _to_binary_positive(zxw_signal)

    zxw_break30_en = "zxw_factor_below_ma30"
    zxw_break30_cn = "ZXW因子+破30日均线"
    factor_dfs[zxw_break30_en] = (below_ma30 & (zxw_bin > 0.0)).astype(float)
    factor_name_map[zxw_break30_cn] = zxw_break30_en

    zxw_break60_en = "zxw_factor_below_ma60"
    zxw_break60_cn = "ZXW因子+破60日均线"
    factor_dfs[zxw_break60_en] = (below_ma60 & (zxw_bin > 0.0)).astype(float)
    factor_name_map[zxw_break60_cn] = zxw_break60_en

    return {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }


if __name__ == "__main__":
    idx = pd.date_range("2020-01-01", periods=40, freq="B")
    cols = ["000001.SZ", "000002.SZ"]
    rng = np.random.default_rng(0)

    C = pd.DataFrame(rng.uniform(8, 12, size=(len(idx), len(cols))), index=idx, columns=cols)
    O = C * rng.uniform(0.99, 1.01, size=C.shape)
    H = np.maximum(O, C) * rng.uniform(1.0, 1.03, size=C.shape)
    L = np.minimum(O, C) * rng.uniform(0.97, 1.0, size=C.shape)
    V = pd.DataFrame(rng.uniform(1e6, 1e7, size=C.shape), index=idx, columns=cols)
    H = pd.DataFrame(H, index=idx, columns=cols)
    L = pd.DataFrame(L, index=idx, columns=cols)

    out = build_total_sell_pair_test_bundle(O=O, H=H, L=L, C=C, V=V)
    print("组合因子数量:", len(out["factor_dfs"]))
    all_mapping = list(out["factor_name_map"].items())
    print("组合映射:", all_mapping)
    if all_mapping:
        sample_en = all_mapping[0][1]
        print("示例组合信号（前5行）:\n", out["factor_dfs"][sample_en].head())


BUNDLE_ID = "total_sell_pair_test"
_DEFAULT_LOOKBACK_DAYS = 1300

FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    # 组合因子由多个基础卖出因子耦合而来，回看窗口取统一大值避免样本边界不一致。
    "total_sell_pair_test": 1300,
    "total_sell_signal__top_escape_score__j_overbought_factor": 1300,
    "rsi_cross_down__rsi_overbought": 1300,
    "zxw_factor": 1300,
    "zxw_factor_below_ma30": 1300,
    "zxw_factor_below_ma60": 1300,
}


def get_factor_catalog() -> dict[str, Any]:
    """供 notebook 预查询因子目录（零计算）。"""
    return {
        "bundle_id": BUNDLE_ID,
        "factor_name_map": {
            "总卖出信号+逃顶总分+J值超买因子": "total_sell_signal__top_escape_score__j_overbought_factor",
            "RSI死叉+RSI超买": "rsi_cross_down__rsi_overbought",
            "ZXW因子": "zxw_factor",
            "ZXW因子+破30日均线": "zxw_factor_below_ma30",
            "ZXW因子+破60日均线": "zxw_factor_below_ma60",
        },
    }


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
