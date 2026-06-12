from __future__ import annotations

from typing import Any

import pandas as pd

from KDJ因子 import build_kdj_factor_bundle
from MACD因子 import build_d_class_factor_bundle
from 抄底因子 import build_bottom_fishing_factor_bundle

RECENT_VOLUME_DAYS = 5

# (中文名, 英文列名, 倍数 A, 基准窗口 B 个交易日)
SELL_FACTOR_VOLUME_SPECS: tuple[tuple[str, str, float, int], ...] = (
    ("卖出因子（1.5-60）", "sell_factor_1_5_60", 1.5, 60),
    ("卖出因子（2-60）", "sell_factor_2_60", 2.0, 60),
    ("卖出因子（1.5-120）", "sell_factor_1_5_120", 1.5, 120),
    ("卖出因子（2-120）", "sell_factor_2_120", 2.0, 120),
)


def _align(df: pd.DataFrame, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    return df.reindex(index=index, columns=columns)


def _to_binary_positive(df: pd.DataFrame) -> pd.DataFrame:
    return (df.fillna(0.0).astype(float) > 0.0).astype(float)


def _volume_recent_vs_prior_surge(
    volume: pd.DataFrame,
    *,
    multiplier: float,
    prior_days: int,
    recent_days: int = RECENT_VOLUME_DAYS,
) -> pd.DataFrame:
    """最近 recent_days 日均量 > 前 prior_days 日均量 × multiplier（二值 0/1）。"""
    prior_days = max(int(prior_days), 1)
    recent_days = max(int(recent_days), 1)
    total_days = prior_days + recent_days

    vol = volume.fillna(0.0).astype(float)
    vol_sum_total = vol.rolling(window=total_days, min_periods=total_days).sum()
    vol_sum_recent = vol.rolling(window=recent_days, min_periods=recent_days).sum()
    vol_sum_prior = vol_sum_total - vol_sum_recent
    recent_avg = vol_sum_recent / float(recent_days)
    prior_avg = vol_sum_prior / float(prior_days)
    return _to_binary_positive(recent_avg > prior_avg * float(multiplier))


def _build_mac_top_j_base_signal(
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    index: pd.Index,
    columns: pd.Index,
) -> pd.DataFrame:
    """MAC总 ∩ 逃顶总分 ∩ J值超买因子（与现有三因子 AND 组合一致）。"""
    mac_bundle = build_d_class_factor_bundle(O=O, H=H, L=L, C=C)
    top_bundle = build_bottom_fishing_factor_bundle(O=O, H=H, L=L, C=C)
    kdj_bundle = build_kdj_factor_bundle(O=O, H=H, L=L, C=C)

    mac_total = _align(mac_bundle["factor_dfs"]["mac_total"], index, columns)
    top_escape_score = _align(top_bundle["factor_dfs"]["top_escape_score"], index, columns)
    j_overbought_factor = _align(kdj_bundle["factor_dfs"]["j_overbought_factor"], index, columns)

    return (
        _to_binary_positive(mac_total)
        * _to_binary_positive(top_escape_score)
        * _to_binary_positive(j_overbought_factor)
    ).astype(float)


def build_sell_factor_volume_bundle(
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    V: pd.DataFrame,
) -> dict[str, Any]:
    """卖出因子（A-B）：(MAC总∩逃顶∩J超买) AND 近5日均量 > A×前B日均量。"""
    index, columns = C.index, C.columns
    volume = _align(V, index, columns).astype(float)

    base_signal = _build_mac_top_j_base_signal(O, H, L, C, index, columns)

    factor_dfs: dict[str, pd.DataFrame] = {}
    factor_name_map: dict[str, str] = {}

    for cn_name, en_name, multiplier, prior_days in SELL_FACTOR_VOLUME_SPECS:
        volume_signal = _volume_recent_vs_prior_surge(
            volume,
            multiplier=multiplier,
            prior_days=prior_days,
            recent_days=RECENT_VOLUME_DAYS,
        )
        combo_signal = (base_signal * volume_signal).astype(float)
        factor_dfs[en_name] = combo_signal
        factor_name_map[cn_name] = en_name

    return {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }


BUNDLE_ID = "sell_factor_volume"
_DEFAULT_LOOKBACK_DAYS = 1300

FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    BUNDLE_ID: _DEFAULT_LOOKBACK_DAYS,
    **{en_name: max(_DEFAULT_LOOKBACK_DAYS, prior_days + RECENT_VOLUME_DAYS)
       for _, en_name, _, prior_days in SELL_FACTOR_VOLUME_SPECS},
}


def get_factor_catalog() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "factor_name_map": {cn: en for cn, en, _, _ in SELL_FACTOR_VOLUME_SPECS},
    }


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }


if __name__ == "__main__":
    import numpy as np

    idx = pd.date_range("2020-01-01", periods=200, freq="B")
    cols = ["000001.SZ"]
    rng = np.random.default_rng(0)
    C = pd.DataFrame(rng.uniform(8, 12, size=(len(idx), len(cols))), index=idx, columns=cols)
    O = C * rng.uniform(0.99, 1.01, size=C.shape)
    H = pd.DataFrame(np.maximum(O, C) * rng.uniform(1.0, 1.03, size=C.shape), index=idx, columns=cols)
    L = pd.DataFrame(np.minimum(O, C) * rng.uniform(0.97, 1.0, size=C.shape), index=idx, columns=cols)
    V = pd.DataFrame(rng.uniform(1e6, 1e7, size=C.shape), index=idx, columns=cols)

    out = build_sell_factor_volume_bundle(O=O, H=H, L=L, C=C, V=V)
    print("因子:", list(out["factor_name_map"].keys()))
    for en in out["factor_dfs"]:
        print(en, "sum=", float(out["factor_dfs"][en].sum().sum()))
