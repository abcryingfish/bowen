"""通达信口径底部预警：强底、超强底、五日内六级。

对应通达信公式（节选）：
- E := MAC总 > 0
- K := K线底 > 0
- A := 集中总 > 0
- B := 筹码峰 > 0（筹码峰赋值 > 0，即 1/2/3）
- I := 均线类 > 0
- R := KDJ 超卖 R（r_condition）
- 强底 := BARSCOUNT>=250 且 (E+A+B+I)>=3 且 K 且 R
- 超强底 := BARSCOUNT>=250 且 E 且 K 且 A 且 B 且 I 且 R
- 五日内六级 := FINDHIGH(超强底, 0, 5, 1) >= 1  （实现为超强底 5 日滚动 max>=1）
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

try:
    from MACD因子 import build_d_class_factor_bundle as _build_d_class_factor_bundle
    from KDJ因子 import build_kdj_factor_bundle as _build_kdj_factor_bundle
    from 抄底因子 import build_bottom_fishing_factor_bundle as _build_bottom_fishing_factor_bundle
    from 均线因子 import build_ma_class_zxw_bundle as _build_ma_class_zxw_bundle
    from 筹码结构因子 import build_chip_structure_factor_bundle as _build_chip_structure_factor_bundle
except Exception as _import_err:  # pragma: no cover
    _build_d_class_factor_bundle = None  # type: ignore[assignment]
    _build_kdj_factor_bundle = None
    _build_bottom_fishing_factor_bundle = None
    _build_ma_class_zxw_bundle = None
    _build_chip_structure_factor_bundle = None
    _IMPORT_ERR = _import_err
else:
    _IMPORT_ERR = None

MIN_BARSCOUNT = 250
FIVE_DAY_WINDOW = 5

BUNDLE_ID = "tdx_bottom_alert"


def _align(df: pd.DataFrame, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    return df.reindex(index=index, columns=columns)


def _to_signal(df: pd.DataFrame) -> pd.DataFrame:
    return df.fillna(0.0).astype(float)


def build_tdx_bottom_alert_bundle(
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    V: pd.DataFrame | None = None,
    valid_bar: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """合成通达信强底 / 超强底 / 五日内六级。"""
    if _IMPORT_ERR is not None:
        raise ImportError("通达信强底信号依赖 MACD/KDJ/抄底/均线/筹码结构因子模块") from _IMPORT_ERR
    if V is None:
        raise ValueError("通达信强底信号需要成交量矩阵 V（集中总、筹码峰）")

    index, columns = C.index, C.columns
    O = _align(O.astype(float), index, columns)
    H = _align(H.astype(float), index, columns)
    L = _align(L.astype(float), index, columns)
    C = _align(C.astype(float), index, columns)
    V = _align(V.astype(float), index, columns)
    if valid_bar is not None:
        valid = _align(valid_bar, index, columns).fillna(False).astype(bool)
        seen_valid = valid.cumsum().gt(0)
        needs_compact = ((~valid) & seen_valid).any(axis=0)
        if bool(needs_compact.any()):
            return _build_tdx_bottom_alert_bundle_with_valid_bar(
                O=O,
                H=H,
                L=L,
                C=C,
                V=V,
                valid_bar=valid,
                needs_compact=needs_compact,
            )

    d_bundle = _build_d_class_factor_bundle(O=O, H=H, L=L, C=C)
    bottom_bundle = _build_bottom_fishing_factor_bundle(O=O, H=H, L=L, C=C)
    kdj_bundle = _build_kdj_factor_bundle(O=O, H=H, L=L, C=C)
    ma_part = _build_ma_class_zxw_bundle(C=C)
    chip_bundle = _build_chip_structure_factor_bundle(
        H=H,
        L=L,
        C=C,
        V=V,
        window_days=100,
        grid_size=600,
        history_decay=0.95,
    )

    mac_total = _align(d_bundle["factor_dfs"]["mac_total"], index, columns).astype(float)
    kline_bottom = _align(bottom_bundle["factor_dfs"]["kline_bottom"], index, columns).astype(float)
    r_condition = _align(kdj_bundle["factor_dfs"]["r_condition"], index, columns).astype(float)
    ma_class = _align(ma_part["factor_dfs"]["ma_class_zxw"], index, columns).astype(float)
    concentration_total = _align(
        chip_bundle["factor_dfs"]["concentration_total_score"], index, columns
    ).astype(float)
    chip_peak_score = _align(chip_bundle["factor_dfs"]["chip_peak_score"], index, columns).astype(float)

    signal_e = mac_total > 0.0
    signal_k = kline_bottom > 0.0
    signal_a = concentration_total > 0.0
    signal_b = chip_peak_score > 0.0
    signal_i = ma_class > 0.0
    signal_r = r_condition > 0.0

    bar_count = C.notna().cumsum().astype(float)
    enough_bars = bar_count >= float(MIN_BARSCOUNT)

    count_eabi = (
        signal_e.astype(np.int8)
        + signal_a.astype(np.int8)
        + signal_b.astype(np.int8)
        + signal_i.astype(np.int8)
    )
    strong_bottom = (count_eabi >= 3) & signal_k & signal_r & enough_bars
    super_strong_bottom = (
        signal_e & signal_k & signal_a & signal_b & signal_i & signal_r & enough_bars
    )
    super_strong_bottom_no_concentration = (
        signal_e & signal_k & signal_b & signal_i & signal_r & enough_bars
    )
    five_day_level6 = (
        super_strong_bottom.astype(float)
        .rolling(window=FIVE_DAY_WINDOW, min_periods=1)
        .max()
        >= 1.0
    )
    five_day_level6_no_concentration = (
        super_strong_bottom_no_concentration.astype(float)
        .rolling(window=FIVE_DAY_WINDOW, min_periods=1)
        .max()
        >= 1.0
    )

    factor_dfs: dict[str, pd.DataFrame] = {
        "tdx_signal_e": _to_signal(signal_e),
        "tdx_signal_k": _to_signal(signal_k),
        "tdx_signal_a": _to_signal(signal_a),
        "tdx_signal_b": _to_signal(signal_b),
        "tdx_signal_i": _to_signal(signal_i),
        "tdx_signal_r": _to_signal(signal_r),
        "tdx_bar_count": _to_signal(bar_count),
        "tdx_strong_bottom": _to_signal(strong_bottom),
        "tdx_super_strong_bottom": _to_signal(super_strong_bottom),
        "tdx_five_day_level6": _to_signal(five_day_level6),
        "tdx_five_day_level6_no_concentration": _to_signal(five_day_level6_no_concentration),
    }
    factor_name_map: dict[str, str] = {
        "MAC总信号": "tdx_signal_e",
        "K线底信号": "tdx_signal_k",
        "集中总信号": "tdx_signal_a",
        "筹码峰信号": "tdx_signal_b",
        "均线类信号": "tdx_signal_i",
        "KDJ超卖R信号": "tdx_signal_r",
        "K线计数": "tdx_bar_count",
        "强底": "tdx_strong_bottom",
        "超强底": "tdx_super_strong_bottom",
        "五日内六级": "tdx_five_day_level6",
        "五日内六级（去掉集中总）": "tdx_five_day_level6_no_concentration",
    }
    return {"factor_dfs": factor_dfs, "factor_name_map": factor_name_map}


def _build_tdx_bottom_alert_bundle_with_valid_bar(
    *,
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    V: pd.DataFrame,
    valid_bar: pd.DataFrame,
    needs_compact: pd.Series,
) -> dict[str, Any]:
    """Compute gap-affected columns on compact real-bar series.

    The existing factor files are written against continuous per-stock K-line
    sequences. For columns that contain missing bars after the first real bar,
    compacting to valid rows preserves that per-stock sequence without rewriting
    every low-level TDX helper in phase one.
    """
    index, columns = C.index, C.columns
    parts: list[tuple[pd.Index, dict[str, Any]]] = []

    fast_cols = pd.Index([col for col in columns if not bool(needs_compact.get(col, False))])
    if len(fast_cols) > 0:
        parts.append(
            (
                fast_cols,
                build_tdx_bottom_alert_bundle(
                    O=O.loc[:, fast_cols],
                    H=H.loc[:, fast_cols],
                    L=L.loc[:, fast_cols],
                    C=C.loc[:, fast_cols],
                    V=V.loc[:, fast_cols],
                    valid_bar=None,
                ),
            )
        )

    compact_cols = pd.Index([col for col in columns if bool(needs_compact.get(col, False))])
    for col in compact_cols:
        col_valid = valid_bar[col].fillna(False).astype(bool)
        real_index = valid_bar.index[col_valid.to_numpy()]
        if len(real_index) == 0:
            continue
        one_col = pd.Index([col])
        parts.append(
            (
                one_col,
                build_tdx_bottom_alert_bundle(
                    O=O.loc[real_index, one_col],
                    H=H.loc[real_index, one_col],
                    L=L.loc[real_index, one_col],
                    C=C.loc[real_index, one_col],
                    V=V.loc[real_index, one_col],
                    valid_bar=None,
                ),
            )
        )

    if not parts:
        return build_tdx_bottom_alert_bundle(O=O, H=H, L=L, C=C, V=V, valid_bar=None)

    factor_name_map = parts[0][1]["factor_name_map"]
    factor_dfs: dict[str, pd.DataFrame] = {}
    for _, bundle in parts:
        for factor_name in bundle["factor_dfs"].keys():
            if factor_name not in factor_dfs:
                factor_dfs[factor_name] = pd.DataFrame(np.nan, index=index, columns=columns)

    for _, bundle in parts:
        for factor_name, frame in bundle["factor_dfs"].items():
            aligned = frame.reindex(index=index)
            factor_dfs[factor_name].loc[:, aligned.columns] = aligned

    factor_dfs = {name: _to_signal(frame) for name, frame in factor_dfs.items()}
    return {"factor_dfs": factor_dfs, "factor_name_map": factor_name_map}


def get_factor_catalog() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "factor_name_map": {
            "强底": "tdx_strong_bottom",
            "超强底": "tdx_super_strong_bottom",
            "五日内六级": "tdx_five_day_level6",
            "五日内六级（去掉集中总）": "tdx_five_day_level6_no_concentration",
            "MAC总信号": "tdx_signal_e",
            "K线底信号": "tdx_signal_k",
            "集中总信号": "tdx_signal_a",
            "筹码峰信号": "tdx_signal_b",
            "均线类信号": "tdx_signal_i",
            "KDJ超卖R信号": "tdx_signal_r",
            "K线计数": "tdx_bar_count",
        },
    }


def get_factor_lookback_config() -> dict[str, Any]:
    """回看取子模块与 250 根 K 线要求的上界。"""
    lookbacks = [MIN_BARSCOUNT + FIVE_DAY_WINDOW - 1]
    for loader in (
        _build_d_class_factor_bundle,
        _build_bottom_fishing_factor_bundle,
        _build_kdj_factor_bundle,
        _build_ma_class_zxw_bundle,
        _build_chip_structure_factor_bundle,
    ):
        if loader is None:
            continue
        mod = __import__(loader.__module__, fromlist=["get_factor_lookback_config"])
        fn = getattr(mod, "get_factor_lookback_config", None)
        if callable(fn):
            cfg = fn()
            lookbacks.append(int(cfg.get("bundle_lookback_days", 0) or 0))
    bundle_lb = max(lookbacks) if lookbacks else MIN_BARSCOUNT
    factor_days = {k: bundle_lb for k in get_factor_catalog()["factor_name_map"].values()}
    factor_days["tdx_bar_count"] = MIN_BARSCOUNT
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": bundle_lb,
        "factor_lookback_days": factor_days,
    }


if __name__ == "__main__":
    idx = pd.date_range("2020-01-01", periods=400, freq="B")
    cols = ["000001.SZ"]
    rng = np.random.default_rng(0)
    C = pd.DataFrame(100 + np.cumsum(rng.normal(0, 0.5, len(idx))), index=idx, columns=cols)
    O = C * 0.999
    H = C * 1.01
    L = C * 0.99
    V = pd.DataFrame(1e6, index=idx, columns=cols)
    out = build_tdx_bottom_alert_bundle(O=O, H=H, L=L, C=C, V=V)
    print(out["factor_name_map"])
    print(out["factor_dfs"]["tdx_super_strong_bottom"].tail(3))
