# -*- coding: utf-8 -*-
# 总买入信号及相关因子 — 单文件独立运行版（合并自 MACD因子 / KDJ因子 / 抄底因子 / 总买入信号）
# 不依赖同目录其它 py 模块；请勿与旧模块混用同名文件同时 import 冲突。

from __future__ import annotations

import os
import time
from typing import Any

import numpy as np
import pandas as pd
try:
    from KDJ因子 import build_kdj_factor_bundle as _ext_build_kdj_factor_bundle
    from MACD因子 import build_d_class_factor_bundle as _ext_build_d_class_factor_bundle
    from 抄底因子 import build_bottom_fishing_factor_bundle as _ext_build_bottom_fishing_factor_bundle
    _EXT_BUNDLES_AVAILABLE = True
except Exception:  # pragma: no cover
    _EXT_BUNDLES_AVAILABLE = False

try:
    from 筹码结构因子 import build_chip_structure_factor_bundle as _ext_build_chip_structure_factor_bundle
    _CHIP_BUNDLE_AVAILABLE = True
except Exception:  # pragma: no cover
    _CHIP_BUNDLE_AVAILABLE = False

# === MACD因子 及 D 类 ===

def _to_frame(x: Any, index: pd.Index, columns: pd.Index, dtype: Any = None) -> pd.DataFrame:
    if isinstance(x, pd.DataFrame):
        result = x.reindex(index=index, columns=columns)
        return result.astype(dtype) if dtype is not None else result
    if np.isscalar(x):
        return pd.DataFrame(x, index=index, columns=columns, dtype=dtype)
    result = pd.DataFrame(x, index=index, columns=columns)
    return result.astype(dtype) if dtype is not None else result


TOTAL_BUY_SIGNAL_ADJUSTED_HOLD_DAYS = 4


def _extend_binary_signal_hold(raw: pd.DataFrame, hold_days: int = TOTAL_BUY_SIGNAL_ADJUSTED_HOLD_DAYS) -> pd.DataFrame:
    """原始出信号日之后 hold_days 个交易日保持为 1；延长期内再次出信号不续期。"""
    if hold_days <= 0:
        return (raw > 0).astype(float)
    raw_bool = (raw > 0).fillna(False)
    out = pd.DataFrame(0.0, index=raw.index, columns=raw.columns, dtype=float)
    for col in raw.columns:
        remaining = 0
        values: list[float] = []
        for is_raw in raw_bool[col].to_numpy():
            if remaining > 0:
                values.append(1.0)
                remaining -= 1
            elif is_raw:
                values.append(1.0)
                remaining = hold_days
            else:
                values.append(0.0)
        out[col] = values
    return out


def _to_window_array(n: Any, index: pd.Index, columns: pd.Index) -> np.ndarray:
    if np.isscalar(n):
        value = max(int(n), 0)
        return np.full((len(index), len(columns)), value, dtype=np.int64)
    frame = _to_frame(n, index=index, columns=columns)
    values = np.nan_to_num(frame.to_numpy(), nan=0.0).astype(np.int64)
    values[values < 0] = 0
    return values


def REF(X: Any, N: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(X, index=index, columns=columns)
    is_bool = bool(frame.dtypes.map(pd.api.types.is_bool_dtype).all())
    values = frame.astype(float).to_numpy()
    windows = _to_window_array(N, frame.index, frame.columns)
    out = np.full(values.shape, np.nan, dtype=float)
    rows, cols = values.shape
    for c in range(cols):
        for r in range(rows):
            step = int(windows[r, c])
            src = r - step
            if src >= 0:
                out[r, c] = values[src, c]
    result = pd.DataFrame(out, index=frame.index, columns=frame.columns)
    if is_bool:
        return result.fillna(0.0).astype(bool)
    return result


def REFX(X: Any, N: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    windows = _to_window_array(N, frame.index, frame.columns)
    values = frame.to_numpy()
    out = np.full(values.shape, np.nan, dtype=float)
    rows, cols = values.shape
    for c in range(cols):
        for r in range(rows):
            step = int(windows[r, c])
            src = r + step
            if src < rows:
                out[r, c] = values[src, c]
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)


def LLV(X: Any, N: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    windows = _to_window_array(N, frame.index, frame.columns)
    values = frame.to_numpy()
    out = np.full(values.shape, np.nan, dtype=float)
    rows, cols = values.shape
    for c in range(cols):
        for r in range(rows):
            w = max(int(windows[r, c]), 1)
            start = max(0, r - w + 1)
            seg = values[start : r + 1, c]
            if not np.isnan(seg).all():
                out[r, c] = np.nanmin(seg)
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)


def HHV(X: Any, N: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    windows = _to_window_array(N, frame.index, frame.columns)
    values = frame.to_numpy()
    out = np.full(values.shape, np.nan, dtype=float)
    rows, cols = values.shape
    for c in range(cols):
        for r in range(rows):
            w = max(int(windows[r, c]), 1)
            start = max(0, r - w + 1)
            seg = values[start : r + 1, c]
            if not np.isnan(seg).all():
                out[r, c] = np.nanmax(seg)
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)


def MAX(A: Any, B: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    a = _to_frame(A, index=index, columns=columns).astype(float)
    b = _to_frame(B, index=index, columns=columns).astype(float)
    return pd.DataFrame(np.maximum(a.to_numpy(), b.to_numpy()), index=index, columns=columns)


def MIN(A: Any, B: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    a = _to_frame(A, index=index, columns=columns).astype(float)
    b = _to_frame(B, index=index, columns=columns).astype(float)
    return pd.DataFrame(np.minimum(a.to_numpy(), b.to_numpy()), index=index, columns=columns)


def HHVBARS(X: Any, N: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    windows = _to_window_array(N, frame.index, frame.columns)
    values = frame.to_numpy()
    out = np.full(values.shape, np.nan, dtype=float)
    rows, cols = values.shape
    for c in range(cols):
        for r in range(rows):
            w = max(int(windows[r, c]), 1)
            start = max(0, r - w + 1)
            seg = values[start : r + 1, c]
            if not np.isnan(seg).all():
                idx = int(np.nanargmax(seg))
                out[r, c] = len(seg) - 1 - idx
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)


def LOWRANGE_STACK(X: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    """与6条归1 一致：通达信 LOWRANGE 单调栈口径（区别于本文件 LOWRANGE 的逐段计数）。"""
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    values = frame.to_numpy()
    out = np.zeros(values.shape, dtype=np.int64)
    rows, cols = values.shape
    for c in range(cols):
        stack: list[int] = []
        for r in range(rows):
            cur = values[r, c]
            while stack and values[stack[-1], c] >= cur:
                stack.pop()
            if stack:
                out[r, c] = r - stack[-1] - 1
            else:
                out[r, c] = r
            stack.append(r)
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)


def TOPRANGE(X: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    values = frame.to_numpy()
    out = np.zeros(values.shape, dtype=np.int64)
    rows, cols = values.shape
    for c in range(cols):
        stack: list[int] = []
        for r in range(rows):
            cur = values[r, c]
            while stack and values[stack[-1], c] <= cur:
                stack.pop()
            if stack:
                out[r, c] = r - stack[-1] - 1
            else:
                out[r, c] = r
            stack.append(r)
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)


def LLVBARS(X: Any, N: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    windows = _to_window_array(N, frame.index, frame.columns)
    values = frame.to_numpy()
    out = np.full(values.shape, np.nan, dtype=float)
    rows, cols = values.shape
    for c in range(cols):
        for r in range(rows):
            w = max(int(windows[r, c]), 1)
            start = max(0, r - w + 1)
            seg = values[start : r + 1, c]
            if not np.isnan(seg).all():
                idx = int(np.nanargmin(seg))
                out[r, c] = len(seg) - 1 - idx
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)


def LOWRANGE(L: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(L, index=index, columns=columns).astype(float)
    values = frame.to_numpy()
    out = np.zeros(values.shape, dtype=np.int64)
    rows, cols = values.shape
    for c in range(cols):
        for r in range(rows):
            cur = values[r, c]
            if np.isnan(cur):
                continue
            step = 0
            k = r - 1
            while k >= 0 and not np.isnan(values[k, c]) and values[k, c] > cur:
                step += 1
                k -= 1
            out[r, c] = step + 1
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)


def MA(X: Any, N: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    values = frame.to_numpy()
    windows = _to_window_array(N, frame.index, frame.columns)
    out = np.full(values.shape, np.nan, dtype=float)
    rows, cols = values.shape
    for c in range(cols):
        for r in range(rows):
            window = max(int(windows[r, c]), 1)
            start = max(0, r - window + 1)
            out[r, c] = np.nanmean(values[start : r + 1, c])
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)


def EMA(X: Any, N: int, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    span = max(int(N), 1)
    return frame.ewm(span=span, adjust=False, min_periods=1).mean()


def COUNT(condition: Any, N: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(condition, index=index, columns=columns).astype(bool)
    values = frame.to_numpy()
    windows = _to_window_array(N, frame.index, frame.columns)
    out = np.zeros(values.shape, dtype=np.int64)
    rows, cols = values.shape
    for c in range(cols):
        for r in range(rows):
            window = max(int(windows[r, c]), 1)
            start = max(0, r - window + 1)
            out[r, c] = int(values[start : r + 1, c].sum())
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)


def CROSS(A: Any, B: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    a = _to_frame(A, index=index, columns=columns).astype(float)
    b = _to_frame(B, index=index, columns=columns).astype(float)
    return (a > b) & (REF(a, 1, index, columns) <= REF(b, 1, index, columns))


def BARSLAST(condition: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(condition, index=index, columns=columns).astype(bool)
    values = frame.to_numpy()
    out = np.zeros(values.shape, dtype=np.int64)
    rows, cols = values.shape
    for c in range(cols):
        last_true_idx = -1
        for r in range(rows):
            if values[r, c]:
                last_true_idx = r
                out[r, c] = 0
            else:
                out[r, c] = r + 1 if last_true_idx == -1 else r - last_true_idx
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)


def NOT(X: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    return ~_to_frame(X, index=index, columns=columns).astype(bool)


def EVERY(condition: Any, N: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(condition, index=index, columns=columns).astype(bool)
    windows = _to_window_array(N, frame.index, frame.columns)
    values = frame.to_numpy()
    out = np.zeros(values.shape, dtype=bool)
    rows, cols = values.shape
    for c in range(cols):
        for r in range(rows):
            w = max(int(windows[r, c]), 1)
            start = max(0, r - w + 1)
            out[r, c] = bool(values[start : r + 1, c].all())
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)


def IF(condition: Any, A: Any, B: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    cond = _to_frame(condition, index=index, columns=columns).astype(bool)
    a = _to_frame(A, index=index, columns=columns)
    b = _to_frame(B, index=index, columns=columns)
    return pd.DataFrame(np.where(cond.to_numpy(), a.to_numpy(), b.to_numpy()), index=index, columns=columns)


def build_p_base_factors(
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    index: pd.Index,
    columns: pd.Index,
) -> dict[str, pd.DataFrame]:
    low_range_l = LOWRANGE_STACK(L, index, columns)
    top_range_h = TOPRANGE(H, index, columns)

    ref_h_low_range_plus_1 = REF(H, low_range_l + 1, index, columns)
    ref_l_low_range_plus_1 = REF(L, low_range_l + 1, index, columns)
    hhv_h_low_range_plus_2 = HHV(H, low_range_l + 2, index, columns)
    llv_l_low_range_plus_2 = LLV(L, low_range_l + 2, index, columns)

    lhl = IF(
        (ref_h_low_range_plus_1 == hhv_h_low_range_plus_2)
        & (ref_l_low_range_plus_1 == llv_l_low_range_plus_2),
        low_range_l + 2,
        low_range_l + 1,
        index,
        columns,
    )

    ref_l_top_range_plus_1 = REF(L, top_range_h + 1, index, columns)
    ref_h_top_range_plus_1 = REF(H, top_range_h + 1, index, columns)
    llv_l_top_range_plus_2 = LLV(L, top_range_h + 2, index, columns)
    hhv_h_top_range_plus_2 = HHV(H, top_range_h + 2, index, columns)

    tll = IF(
        (ref_l_top_range_plus_1 == llv_l_top_range_plus_2)
        & (ref_h_top_range_plus_1 == hhv_h_top_range_plus_2),
        top_range_h + 2,
        top_range_h + 1,
        index,
        columns,
    )

    ref_max_co_1 = REF(MAX(C, O, index, columns), 1, index, columns)
    ref_ref_max_co_1_low_range = REF(ref_max_co_1, low_range_l, index, columns)

    shl = IF(
        L >= ref_ref_max_co_1_low_range,
        low_range_l + 1,
        low_range_l + 2,
        index,
        columns,
    )

    highest_p_since = HHVBARS(H, lhl, index, columns) + 1

    refx_shl_minus_1_1 = REFX(shl - 1, 1, index, columns)
    hhv_h_refx_shl_minus_1_1 = HHV(H, refx_shl_minus_1_1, index, columns)
    ref_hhv_h_refx_shl_minus_1_1_1 = REF(hhv_h_refx_shl_minus_1_1, 1, index, columns)

    hhvbars_h_refx_shl_minus_1_1 = HHVBARS(H, refx_shl_minus_1_1, index, columns)
    ref_hhvbars_h_refx_shl_minus_1_1_plus_1_1 = REF(hhvbars_h_refx_shl_minus_1_1 + 1, 1, index, columns)

    back_cross_d_count = IF(
        shl == 1,
        0,
        IF(
            O >= ref_hhv_h_refx_shl_minus_1_1_1,
            0,
            ref_hhvbars_h_refx_shl_minus_1_1_plus_1_1 + 1,
            index,
            columns,
        ),
        index,
        columns,
    )

    ftr = top_range_h + 2
    phl = LLVBARS(L, ftr, index, columns) + 1

    ref_min_co_1 = REF(MIN(C, O, index, columns), 1, index, columns)
    ref_ref_min_co_1_top_range = REF(ref_min_co_1, top_range_h, index, columns)

    u_zone = IF(
        H < ref_ref_min_co_1_top_range,
        top_range_h,
        top_range_h + 1,
        index,
        columns,
    )

    return {
        "low_range_l": low_range_l,
        "top_range_h": top_range_h,
        "lhl": lhl,
        "tll": tll,
        "shl": shl,
        "highest_p_since": highest_p_since,
        "back_cross_d_count": back_cross_d_count,
        "ftr": ftr,
        "phl": phl,
        "u_zone": u_zone,
    }


def build_negative_volume_shapes(
    O: pd.DataFrame, C: pd.DataFrame, index: pd.Index, columns: pd.Index
) -> dict[str, pd.DataFrame]:
    """阴形量、纯阴量（S笔反K / 阴J贯穿 依赖）。"""
    negative_shape_volume = C < O
    pure_negative_volume = (C < REF(C, 1, index, columns)) & (C < O)
    return {
        "negative_shape_volume": negative_shape_volume,
        "pure_negative_volume": pure_negative_volume,
    }


def build_upper_stroke_reverse_k_bundle(
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    index: pd.Index,
    columns: pd.Index,
) -> dict[str, pd.DataFrame]:
    """S笔反K 及其中间矩阵（不含 MAX上笔反K）。与 6条归1.ipynb 逻辑对齐。"""
    p = build_p_base_factors(O, H, L, C, index, columns)
    vol = build_negative_volume_shapes(O, C, index, columns)
    pure_negative_volume = vol["pure_negative_volume"]
    negative_shape_volume = vol["negative_shape_volume"]

    lhl = p["lhl"]
    shl = p["shl"]
    highest_p_since = p["highest_p_since"]
    back_cross_d_count = p["back_cross_d_count"]
    ftr = p["ftr"]
    phl = p["phl"]
    u_zone = p["u_zone"]

    ref_l_phl_minus_1 = REF(L, phl - 1, index, columns)
    llv_l_phl_minus_1 = LLV(L, phl - 1, index, columns)
    ref_h_phl_minus_1 = REF(H, phl - 1, index, columns)
    ref_positive_shape_phl_minus_1 = REF(C > O, phl - 1, index, columns)

    prior_d_positive_top = (
        (ref_l_phl_minus_1 <= llv_l_phl_minus_1)
        & (ref_h_phl_minus_1 > H)
        & ref_positive_shape_phl_minus_1
    )

    ref_positive_shape_u_zone = REF(C > O, u_zone, index, columns)
    ref_l_u_zone = REF(L, u_zone, index, columns)

    refx_u_zone_minus_1_1 = REFX(u_zone - 1, 1, index, columns)
    refx_u_zone_1 = REFX(u_zone, 1, index, columns)

    llv_l_refx_u_zone_minus_1_1 = LLV(L, refx_u_zone_minus_1_1, index, columns)
    ref_llv_l_refx_u_zone_minus_1_1_1 = REF(llv_l_refx_u_zone_minus_1_1, 1, index, columns)

    llvbars_l_refx_u_zone_minus_1_1 = LLVBARS(L, refx_u_zone_minus_1_1, index, columns)
    ref_llvbars_l_refx_u_zone_minus_1_1_1 = REF(llvbars_l_refx_u_zone_minus_1_1, 1, index, columns)

    llvbars_l_refx_u_zone_1 = LLVBARS(L, refx_u_zone_1, index, columns)
    ref_llvbars_l_refx_u_zone_1_1 = REF(llvbars_l_refx_u_zone_1, 1, index, columns)

    back_cross_f_count = IF(
        ref_positive_shape_u_zone & (ref_l_u_zone < ref_llv_l_refx_u_zone_minus_1_1_1),
        ref_llvbars_l_refx_u_zone_minus_1_1_1 + 2,
        ref_llvbars_l_refx_u_zone_1_1 + 2,
        index,
        columns,
    )

    ref_h_1 = REF(H, 1, index, columns)
    ref_l_back_cross_f_count_minus_1 = REF(L, back_cross_f_count - 1, index, columns)

    negative_top_break = (
        (H > ref_h_1)
        & (L <= ref_l_back_cross_f_count_minus_1)
        & (C < O)
        & (O > ref_l_back_cross_f_count_minus_1)
    )

    base_lower_stroke_reverse_k_duration = IF(
        (L >= REF(L, 1, index, columns))
        & (H <= REF(H, 1, index, columns))
        & (
            REF(C > O, 1, index, columns)
            | (O == REF(L, 1, index, columns))
            | (H <= REF(C, 1, index, columns))
            | ((C < O) & (C < REF(C, 1, index, columns)))
        ),
        1,
        IF(
            (highest_p_since == 2) & REF(highest_p_since == 0, 1, index, columns),
            1,
            IF(
                prior_d_positive_top & NOT(negative_top_break, index, columns),
                LLVBARS(L, phl - 1, index, columns) + 1,
                IF(
                    negative_top_break,
                    IF(
                        (REF(H, back_cross_f_count - 1, index, columns) > H)
                        & REF(
                            (C > O) & (REF(H, highest_p_since - 1, index, columns) <= H),
                            back_cross_f_count - 1,
                            index,
                            columns,
                        ),
                        back_cross_f_count - 1,
                        back_cross_f_count,
                        index,
                        columns,
                    ),
                    LLVBARS(L, ftr, index, columns) + 1,
                    index,
                    columns,
                ),
                index,
                columns,
            ),
            index,
            columns,
        ),
        index,
        columns,
    )

    lower_stroke_reverse_k = IF(
        (base_lower_stroke_reverse_k_duration == 2)
        & (EVERY(C <= REF(C, 1, index, columns), 2, index, columns) & (L < REF(L, 1, index, columns))),
        1,
        base_lower_stroke_reverse_k_duration,
        index,
        columns,
    )

    negative_j_break = pure_negative_volume & (shl > 1) & (H >= HHV(H, shl, index, columns))

    upper_stroke_reverse_k = IF(
        (
            (L >= REF(L, 1, index, columns))
            & (H <= REF(H, 1, index, columns))
            & (
                REF(C < O, 1, index, columns)
                | (O == REF(H, 1, index, columns))
                | (L >= REF(C, 1, index, columns))
                | ((C > O) & (C > REF(C, 1, index, columns)))
            )
        )
        | negative_j_break,
        1,
        IF(
            (highest_p_since == 1) & (back_cross_d_count > 2),
            back_cross_d_count,
            IF(
                (highest_p_since == 1)
                & (back_cross_d_count == 2)
                & ((L < REF(L, 1, index, columns)) & REF((H - C) >= 2 * (C - L), 1, index, columns)),
                2,
                IF(
                    shl == 1,
                    1,
                    HHVBARS(
                        H,
                        IF(
                            REF(negative_shape_volume, shl - 1, index, columns)
                            & (REF(L, shl - 1, index, columns) <= L),
                            shl - 1,
                            shl,
                            index,
                            columns,
                        ),
                        index,
                        columns,
                    )
                    + 1,
                    index,
                    columns,
                ),
                index,
                columns,
            ),
            index,
            columns,
        ),
        index,
        columns,
    )

    out: dict[str, pd.DataFrame] = {**p, **vol}
    out.update(
        {
            "prior_d_positive_top": prior_d_positive_top,
            "back_cross_f_count": back_cross_f_count,
            "negative_top_break": negative_top_break,
            "base_lower_stroke_reverse_k_duration": base_lower_stroke_reverse_k_duration,
            "lower_stroke_reverse_k": lower_stroke_reverse_k,
            "negative_j_break": negative_j_break,
            "upper_stroke_reverse_k": upper_stroke_reverse_k,
        }
    )
    return out


def build_macd_factors(C: pd.DataFrame) -> dict[str, pd.DataFrame]:
    index, columns = C.index, C.columns
    dif = (EMA(C, 12, index, columns) - EMA(C, 26, index, columns)) * 100
    dea = EMA(dif, 9, index, columns)
    mac = (dif - dea) * 2
    return {"dif": dif, "dea": dea, "mac": mac}


def build_bottom_divergence_factors(
    L: pd.DataFrame,
    C: pd.DataFrame,
    O: pd.DataFrame,
    H: pd.DataFrame,
    dif: pd.DataFrame,
    dea: pd.DataFrame,
    mac: pd.DataFrame,
    s_reverse_k: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    index, columns = C.index, C.columns
    low_range_l = LOWRANGE(L, index, columns)
    red_bar = (mac > 0) & (mac > MA(mac, 60, index, columns))
    golden_cross = CROSS(dif, dea, index, columns)
    p_mark_arc_bottom = low_range_l >= 35

    refx_s_reverse_k_minus_2 = REFX(s_reverse_k - 2, 1, index, columns)
    llvbars_l_refx_s_reverse_k_minus_2 = LLVBARS(L, refx_s_reverse_k_minus_2, index, columns)
    ref_llvbars_l_refx_s_reverse_k_minus_2_ge_30_1 = REF(
        llvbars_l_refx_s_reverse_k_minus_2 >= 30, 1, index, columns
    )

    p_new_low_start = (
        (
            EVERY(p_mark_arc_bottom, 2, index, columns)
            & (low_range_l > REF(low_range_l + 10, 1, index, columns))
            & ref_llvbars_l_refx_s_reverse_k_minus_2_ge_30_1
        )
        |
        (
            p_mark_arc_bottom
            & (low_range_l > REF(low_range_l + 20, 1, index, columns))
            & ref_llvbars_l_refx_s_reverse_k_minus_2_ge_30_1
        )
    )

    p_initial_bottom_divergence = p_new_low_start & (dif > LLV(dif, s_reverse_k, index, columns))
    bars_last_initial_bottom_divergence = BARSLAST(p_initial_bottom_divergence, index, columns)
    p_continued_bottom_divergence = (
        (bars_last_initial_bottom_divergence <= 34)
        &
        (
            LLV(dif, bars_last_initial_bottom_divergence, index, columns)
            >
            REF(LLV(dif, s_reverse_k, index, columns), bars_last_initial_bottom_divergence, index, columns)
        )
    )

    bottom_divergence = p_initial_bottom_divergence | p_continued_bottom_divergence
    bottom_divergence_and_red_bar = bottom_divergence & red_bar
    bottom_divergence_and_golden_cross = bottom_divergence & golden_cross
    golden_cross_and_red_bar = golden_cross & red_bar

    # 仅用于 mac_total 分级
    a_plus = bottom_divergence_and_red_bar | bottom_divergence_and_golden_cross
    a_only = red_bar & (COUNT(golden_cross, 7, index, columns) >= 1) & NOT(a_plus, index, columns)

    mac_total = IF(
        a_plus,
        4,
        IF(
            a_only,
            3,
            IF(golden_cross | red_bar, 2, IF(bottom_divergence, 1, 0, index, columns), index, columns),
            index,
            columns,
        ),
        index,
        columns,
    )

    return {
        "red_bar": red_bar,
        "golden_cross": golden_cross,
        "p_mark_arc_bottom": p_mark_arc_bottom,
        "p_new_low_start": p_new_low_start,
        "p_initial_bottom_divergence": p_initial_bottom_divergence,
        "bars_last_initial_bottom_divergence": bars_last_initial_bottom_divergence,
        "p_continued_bottom_divergence": p_continued_bottom_divergence,
        "bottom_divergence": bottom_divergence,
        "bottom_divergence_and_red_bar": bottom_divergence_and_red_bar,
        "bottom_divergence_and_golden_cross": bottom_divergence_and_golden_cross,
        "golden_cross_and_red_bar": golden_cross_and_red_bar,
        "mac_total": mac_total,
    }


def build_d_class_factor_bundle(
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    s_reverse_k: pd.DataFrame | None = None,
) -> dict[str, Any]:
    index, columns = C.index, C.columns

    stroke_bundle = build_upper_stroke_reverse_k_bundle(O, H, L, C, index, columns)
    computed_s_reverse_k = stroke_bundle["upper_stroke_reverse_k"].astype(float)
    if s_reverse_k is None:
        s_reverse_k = computed_s_reverse_k
    else:
        s_reverse_k = _to_frame(s_reverse_k, index=index, columns=columns).astype(float)

    macd_factors = build_macd_factors(C)
    dif = macd_factors["dif"]
    dea = macd_factors["dea"]
    mac = macd_factors["mac"]

    bottom = build_bottom_divergence_factors(
        L=L, C=C, O=O, H=H, dif=dif, dea=dea, mac=mac, s_reverse_k=s_reverse_k
    )

    factor_dfs: dict[str, pd.DataFrame] = {
        "dif": dif,
        "dea": dea,
        "mac": mac,
        "red_bar": bottom["red_bar"],
        "golden_cross": bottom["golden_cross"],
        "p_mark_arc_bottom": bottom["p_mark_arc_bottom"],
        "p_new_low_start": bottom["p_new_low_start"],
        "p_initial_bottom_divergence": bottom["p_initial_bottom_divergence"],
        "p_continued_bottom_divergence": bottom["p_continued_bottom_divergence"],
        "bottom_divergence": bottom["bottom_divergence"],
        "bottom_divergence_and_red_bar": bottom["bottom_divergence_and_red_bar"],
        "bottom_divergence_and_golden_cross": bottom["bottom_divergence_and_golden_cross"],
        "golden_cross_and_red_bar": bottom["golden_cross_and_red_bar"],
        "mac_total": bottom["mac_total"],
        **stroke_bundle,
    }

    factor_name_map: dict[str, str] = {
        "DIF": "dif",
        "DEA": "dea",
        "MAC": "mac",
        "红柱": "red_bar",
        "金叉": "golden_cross",
        "P标弧底": "p_mark_arc_bottom",
        "P弧新低初": "p_new_low_start",
        "P新低初背离": "p_initial_bottom_divergence",
        "P新低延续背离": "p_continued_bottom_divergence",
        "底背离": "bottom_divergence",
        "底背离&红柱": "bottom_divergence_and_red_bar",
        "底背离&金叉": "bottom_divergence_and_golden_cross",
        "金叉&红柱": "golden_cross_and_red_bar",
        "MAC总": "mac_total",
        "FTR": "ftr",
        "后穿D数": "back_cross_d_count",
        "最高P至今": "highest_p_since",
        "PHL": "phl",
        "U域": "u_zone",
        "SHL": "shl",
        "LHL": "lhl",
        "阴形量": "negative_shape_volume",
        "纯阴量": "pure_negative_volume",
        "前D阳顶": "prior_d_positive_top",
        "后穿F数": "back_cross_f_count",
        "后阴顶穿": "negative_top_break",
        "基础下笔反K时长": "base_lower_stroke_reverse_k_duration",
        "下笔反K": "lower_stroke_reverse_k",
        "阴J贯穿": "negative_j_break",
        "S笔反K": "upper_stroke_reverse_k",
    }

    return {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
        "bottom_divergence_factors": bottom,
        "stroke_reverse_k_bundle": stroke_bundle,
    }


# === KDJ因子 ===

def _kdj_LLV(X: Any, N: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    windows = _to_window_array(N, frame.index, frame.columns)
    values = frame.to_numpy()
    out = np.full(values.shape, np.nan, dtype=float)
    rows, cols = values.shape
    for c in range(cols):
        for r in range(rows):
            w = max(int(windows[r, c]), 1)
            start = max(0, r - w + 1)
            out[r, c] = np.nanmin(values[start : r + 1, c])
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)


def _kdj_HHV(X: Any, N: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    windows = _to_window_array(N, frame.index, frame.columns)
    values = frame.to_numpy()
    out = np.full(values.shape, np.nan, dtype=float)
    rows, cols = values.shape
    for c in range(cols):
        for r in range(rows):
            w = max(int(windows[r, c]), 1)
            start = max(0, r - w + 1)
            out[r, c] = np.nanmax(values[start : r + 1, c])
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)

def SMA_TDX(X: Any, N: int, M: int, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    """通达信 SMA(X,N,M): Y=(M*X+(N-M)*Y')/N。"""
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    n = max(int(N), 1)
    m = int(M)
    values = frame.to_numpy()
    out = np.full(values.shape, np.nan, dtype=float)
    rows, cols = values.shape
    for c in range(cols):
        prev = np.nan
        for r in range(rows):
            x = values[r, c]
            if np.isnan(x):
                out[r, c] = prev
                continue
            if np.isnan(prev):
                prev = x
            else:
                prev = (m * x + (n - m) * prev) / n
            out[r, c] = prev
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)


def build_kdj_factor_bundle(
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
) -> dict[str, dict[str, pd.DataFrame]]:
    index, columns = C.index, C.columns

    llv_l_9 = _kdj_LLV(L, 9, index, columns)
    hhv_h_9 = _kdj_HHV(H, 9, index, columns)
    denominator = hhv_h_9 - llv_l_9
    denominator = denominator.replace(0, np.nan)
    rsv = (C - llv_l_9) / denominator * 100
    rsv = rsv.fillna(0.0)

    k_value = SMA_TDX(rsv, 3, 1, index, columns)
    d_value = SMA_TDX(k_value, 3, 1, index, columns)
    j_raw = 3 * k_value - 2 * d_value

    r_condition = j_raw < 30

    factor_dfs: dict[str, pd.DataFrame] = {
        "rsv": rsv,
        "k_value": k_value,
        "d_value": d_value,
        "j_raw": j_raw,
        "r_condition": r_condition,
    }

    factor_name_map: dict[str, str] = {
        "RSV": "rsv",
        "K值": "k_value",
        "D值": "d_value",
        "J值": "j_raw",
        "KDJ信号": "r_condition",
    }

    return {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }


# === 抄底因子 ===

def _barscount(C: pd.DataFrame) -> pd.DataFrame:
    values = C.astype(float).to_numpy()
    rows, cols = values.shape
    out = np.zeros((rows, cols), dtype=np.int64)
    for c in range(cols):
        valid_idx = np.flatnonzero(np.isfinite(values[:, c]))
        if valid_idx.size == 0:
            continue
        start = int(valid_idx[0])
        out[start:, c] = np.arange(1, rows - start + 1, dtype=np.int64)
    return pd.DataFrame(out, index=C.index, columns=C.columns)


def _between(x: Any, lower: float, upper: float, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(x, index=index, columns=columns).astype(float)
    return (frame >= lower) & (frame <= upper)


def _make_rank_frame(
    pairs: list[tuple[pd.DataFrame, float]],
    index: pd.Index,
    columns: pd.Index,
    *,
    default: float = np.nan,
) -> pd.DataFrame:
    out = np.full((len(index), len(columns)), default, dtype=float)
    for cond, value in pairs:
        cond_values = _to_frame(cond, index=index, columns=columns).astype(bool).to_numpy()
        out = np.where(cond_values, float(value), out)
    return pd.DataFrame(out, index=index, columns=columns)


def build_bottom_fishing_factor_bundle(
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
) -> dict[str, dict[str, pd.DataFrame]]:
    index, columns = C.index, C.columns
    O = _to_frame(O, index=index, columns=columns).astype(float)
    H = _to_frame(H, index=index, columns=columns).astype(float)
    L = _to_frame(L, index=index, columns=columns).astype(float)
    C = _to_frame(C, index=index, columns=columns).astype(float)

    barscount_c = _barscount(C)

    ref_c_1 = REF(C, 1, index, columns)
    ref_h_1 = REF(H, 1, index, columns)
    ref_l_1 = REF(L, 1, index, columns)

    # 量性
    positive_volume = (C > ref_c_1) | (C > O)
    positive_shape_volume = C > O
    pure_positive_volume = (C > ref_c_1) & (C > O)
    negative_shape_volume = C < O
    flat_positive_volume = (C > ref_c_1) & (C >= O)
    diff_price_positive_volume = (C < ref_c_1) & (C > O)
    diff_shape_positive_volume = (C > ref_c_1) & (C < O)
    negative_volume = C < ref_c_1
    pure_negative_volume = (C < ref_c_1) & (C < O)

    # P类基础数据定义
    low_range_l = LOWRANGE(L, index, columns)
    top_range_h = TOPRANGE(H, index, columns)

    lhl = IF(
        (REF(H, low_range_l + 1, index, columns) == HHV(H, low_range_l + 2, index, columns))
        & (REF(L, low_range_l + 1, index, columns) == LLV(L, low_range_l + 2, index, columns)),
        low_range_l + 2,
        low_range_l + 1,
        index,
        columns,
    )
    tll = IF(
        (REF(L, top_range_h + 1, index, columns) == LLV(L, top_range_h + 2, index, columns))
        & (REF(H, top_range_h + 1, index, columns) == HHV(H, top_range_h + 2, index, columns)),
        top_range_h + 2,
        top_range_h + 1,
        index,
        columns,
    )
    shl = IF(
        L >= REF(REF(MAX(C, O, index, columns), 1, index, columns), low_range_l, index, columns),
        low_range_l + 1,
        low_range_l + 2,
        index,
        columns,
    )

    current_duration = HHVBARS(H, lhl, index, columns) + 1
    back_cross_d_count = IF(
        shl == 1,
        0,
        IF(
            O >= REF(HHV(H, REFX(shl - 1, 1, index, columns), index, columns), 1, index, columns),
            0,
            REF(HHVBARS(H, REFX(shl - 1, 1, index, columns), index, columns) + 1, 1, index, columns) + 1,
            index,
            columns,
        ),
        index,
        columns,
    )
    adjacent_top_k = REF(H == HHV(H, 4, index, columns), 1, index, columns) & (
        (((REF(H - C, 1, index, columns) + O - L) > 2 * (L - ref_l_1)) & (O < ref_h_1))
        | (((ref_h_1 - L) > REF(H - L, 1, index, columns) / 2) & (L < O) & (L < REF(MIN(O, C, index, columns), 1, index, columns)))
    )
    time_yq = IF(
        current_duration == 1,
        (REF(C < O, 1, index, columns) & (L < ref_l_1)) | (back_cross_d_count > 2),
        IF(
            current_duration == 2,
            adjacent_top_k | (C < O),
            (current_duration > 2) & (L < ref_l_1),
            index,
            columns,
        ),
        index,
        columns,
    )
    back_cross_situation = (back_cross_d_count > 2) | (
        (back_cross_d_count == 2)
        & (adjacent_top_k | REF((C < O) | (C < ref_c_1), 1, index, columns))
    )
    highest_p_since = HHVBARS(H, lhl, index, columns) + 1
    highest_price_since = highest_p_since.copy()
    ftr = TOPRANGE(H, index, columns) + 2
    phl = LLVBARS(L, ftr, index, columns) + 1
    u_zone = IF(
        H < REF(REF(MIN(C, O, index, columns), 1, index, columns), top_range_h, index, columns),
        top_range_h,
        top_range_h + 1,
        index,
        columns,
    )

    # 最大下线段反向K
    prior_d_positive_top = (
        (REF(L, phl - 1, index, columns) <= LLV(L, phl - 1, index, columns))
        & (REF(H, phl - 1, index, columns) > H)
        & REF(C > O, phl - 1, index, columns)
    )
    back_cross_f_count = IF(
        REF(C > O, u_zone, index, columns)
        & (
            REF(L, u_zone, index, columns)
            < REF(LLV(L, REFX(u_zone - 1, 1, index, columns), index, columns), 1, index, columns)
        ),
        REF(LLVBARS(L, REFX(u_zone - 1, 1, index, columns), index, columns), 1, index, columns) + 2,
        REF(LLVBARS(L, REFX(u_zone, 1, index, columns), index, columns), 1, index, columns) + 2,
        index,
        columns,
    )
    negative_top_break = (
        (H > ref_h_1)
        & (L <= REF(L, back_cross_f_count - 1, index, columns))
        & (C < O)
        & (O > REF(L, back_cross_f_count - 1, index, columns))
    )
    base_lower_stroke_reverse_k_duration = IF(
        (L >= ref_l_1)
        & (H <= ref_h_1)
        & (
            REF(C > O, 1, index, columns)
            | (O == ref_l_1)
            | (H <= ref_c_1)
            | ((C < O) & (C < ref_c_1))
        ),
        1,
        IF(
            (current_duration == 2) & REF(highest_p_since == 0, 1, index, columns),
            1,
            IF(
                prior_d_positive_top & NOT(negative_top_break, index, columns),
                LLVBARS(L, phl - 1, index, columns) + 1,
                IF(
                    negative_top_break,
                    IF(
                        (REF(H, back_cross_f_count - 1, index, columns) > H)
                        & REF(
                            (C > O) & (REF(H, highest_p_since - 1, index, columns) <= H),
                            back_cross_f_count - 1,
                            index,
                            columns,
                        ),
                        back_cross_f_count - 1,
                        back_cross_f_count,
                        index,
                        columns,
                    ),
                    LLVBARS(L, ftr, index, columns) + 1,
                    index,
                    columns,
                ),
                index,
                columns,
            ),
            index,
            columns,
        ),
        index,
        columns,
    )
    lower_stroke_reverse_k = IF(
        (base_lower_stroke_reverse_k_duration == 2)
        & EVERY(C <= ref_c_1, 2, index, columns)
        & (L < ref_l_1),
        1,
        base_lower_stroke_reverse_k_duration,
        index,
        columns,
    )
    negative_j_break = pure_negative_volume & (shl > 1) & (H >= HHV(H, shl, index, columns))
    upper_stroke_reverse_k = IF(
        (
            (L >= ref_l_1)
            & (H <= ref_h_1)
            & (
                REF(C < O, 1, index, columns)
                | (O == ref_h_1)
                | (L >= ref_c_1)
                | ((C > O) & (C > ref_c_1))
            )
        )
        | negative_j_break,
        1,
        IF(
            (current_duration == 1) & (back_cross_d_count > 2),
            back_cross_d_count,
            IF(
                (current_duration == 1)
                & (back_cross_d_count == 2)
                & ((L < ref_l_1) & REF((H - C) >= 2 * (C - L), 1, index, columns)),
                2,
                IF(
                    shl == 1,
                    1,
                    HHVBARS(
                        H,
                        IF(
                            REF(negative_shape_volume, shl - 1, index, columns)
                            & (REF(L, shl - 1, index, columns) <= L),
                            shl - 1,
                            shl,
                            index,
                            columns,
                        ),
                        index,
                        columns,
                    )
                    + 1,
                    index,
                    columns,
                ),
                index,
                columns,
            ),
            index,
            columns,
        ),
        index,
        columns,
    )
    max_upper_stroke_reverse_k = IF(
        phl > 1,
        HHV(upper_stroke_reverse_k, phl - 1, index, columns),
        0,
        index,
        columns,
    )

    # K线底因子
    historical_bottom = (L == LLV(L, barscount_c, index, columns)) & (barscount_c >= 750)
    five_year_bottom = L == LLV(L, MIN(1250, barscount_c, index, columns), index, columns)
    near_historical_bottom = LLV(L, 15, index, columns) == LLV(L, barscount_c, index, columns)
    two_year_bottom = L == LLV(L, MIN(500, barscount_c, index, columns), index, columns)
    major_bottom_lift = five_year_bottom & REF(
        REF(BARSLAST(historical_bottom, index, columns) < 1000, upper_stroke_reverse_k - 1, index, columns),
        LLVBARS(L, 5, index, columns),
        index,
        columns,
    )
    two_five_year_bottom_lift = two_year_bottom & REF(
        REF(BARSLAST(five_year_bottom, index, columns) < 1000, upper_stroke_reverse_k - 1, index, columns),
        LLVBARS(L, 5, index, columns),
        index,
        columns,
    )
    price_yoy_ratio = _between(
        (
            REF(REF(H, upper_stroke_reverse_k - 1, index, columns), LLVBARS(L, 250, index, columns), index, columns)
            - LLV(L, 250, index, columns)
        )
        / (
            REF(REF(H, upper_stroke_reverse_k - 1, index, columns), LLVBARS(L, 5, index, columns), index, columns)
            - LLV(L, 5, index, columns)
        ),
        0.5,
        2.0,
        index,
        columns,
    )
    k_yoy_ratio = _between(
        REF(upper_stroke_reverse_k - 1, LLVBARS(L, 250, index, columns), index, columns)
        / REF(upper_stroke_reverse_k - 1, LLVBARS(L, 5, index, columns), index, columns),
        0.5,
        2.0,
        index,
        columns,
    )
    yearly_double_bottom = (
        (upper_stroke_reverse_k >= 85)
        & (upper_stroke_reverse_k < 250)
        & _between(LLVBARS(L, 250, index, columns), 86, 250, index, columns)
        & (L < REF(REF(H, upper_stroke_reverse_k - 1, index, columns), LLVBARS(L, 250, index, columns), index, columns))
        & (price_yoy_ratio | k_yoy_ratio)
    )
    recent_yearly_double_bottom = BARSLAST(yearly_double_bottom, index, columns) <= 15
    yearly_bottom = L == LLV(L, 250, index, columns)
    recent_yearly_bottom = BARSLAST(yearly_bottom, index, columns) <= 35
    yearly_double_bottom_lift = (
        (LLV(L, 5, index, columns) == LLV(L, 100, index, columns))
        & ((LLV(L, 5, index, columns) / LLV(L, 250, index, columns)) < 1.2)
        & (LLVBARS(L, 250, index, columns) >= 80)
        & (LLV(L, 5, index, columns) < REF(REF(H, upper_stroke_reverse_k - 1, index, columns), LLVBARS(L, 250, index, columns), index, columns))
        & (price_yoy_ratio | k_yoy_ratio)
    )

    # 等级改为：1最弱，4最强 / DRAWNULL 改为 NaN
    kline_bottom_rank_raw = _make_rank_frame(
        [
            (recent_yearly_bottom, 1),
            (two_five_year_bottom_lift | recent_yearly_double_bottom | yearly_bottom, 2),
            (yearly_double_bottom, 3),
            (two_year_bottom | major_bottom_lift, 4),
            (five_year_bottom | near_historical_bottom, 5),
            (historical_bottom, 6),
        ],
        index,
        columns,
        default=np.nan,
    )
    kline_bottom_base = kline_bottom_rank_raw.fillna(0.0)
    k_bottom = historical_bottom | five_year_bottom | two_year_bottom | yearly_bottom | yearly_double_bottom
    relative_low_top = IF(
        historical_bottom,
        L + (HHV(H, barscount_c, index, columns) - L) * 0.1,
        IF(
            five_year_bottom,
            REF(L + (HHV(H, upper_stroke_reverse_k, index, columns) - L) * 0.1, BARSLAST(k_bottom, index, columns), index, columns),
            IF(
                two_year_bottom,
                REF(L + (HHV(H, upper_stroke_reverse_k, index, columns) - L) * 0.1, BARSLAST(k_bottom, index, columns), index, columns),
                IF(
                    yearly_bottom | yearly_double_bottom,
                    REF(
                        LLV(L, 250, index, columns)
                        + (HHV(H, MAX(upper_stroke_reverse_k, 250, index, columns), index, columns) - LLV(L, 250, index, columns)) * 0.1,
                        BARSLAST(k_bottom, index, columns),
                        index,
                        columns,
                    ),
                    L * 1.1,
                    index,
                    columns,
                ),
                index,
                columns,
            ),
            index,
            columns,
        ),
        index,
        columns,
    )
    k_bottom_requirement = L <= REF(relative_low_top, BARSLAST(k_bottom, index, columns), index, columns)
    kline_bottom_1 = _make_rank_frame(
        [
            (k_bottom_requirement & REF(yearly_bottom | yearly_double_bottom, BARSLAST(k_bottom, index, columns), index, columns), 1),
            (k_bottom_requirement & REF(two_year_bottom, BARSLAST(k_bottom, index, columns), index, columns), 2),
            (k_bottom_requirement & REF(five_year_bottom, BARSLAST(k_bottom, index, columns), index, columns), 3),
            (k_bottom_requirement & REF(historical_bottom, BARSLAST(k_bottom, index, columns), index, columns), 4),
        ],
        index,
        columns,
        default=0.0,
    )

    k_bottom_arrival_requirement = IF(
        yearly_double_bottom,
        L <= LLV(C, 250, index, columns) * 1.1,
        L <= REF(C, BARSLAST(k_bottom, index, columns), index, columns) * 1.1,
        index,
        columns,
    ).astype(bool)
    k_bottom_arrival_base = k_bottom_arrival_requirement.where(k_bottom_arrival_requirement, np.nan)
    kline_bottom_2 = _make_rank_frame(
        [
            (k_bottom_arrival_requirement & REF(yearly_bottom | yearly_double_bottom, BARSLAST(k_bottom, index, columns), index, columns), 1),
            (k_bottom_arrival_requirement & REF(two_year_bottom, BARSLAST(k_bottom, index, columns), index, columns), 2),
            (k_bottom_arrival_requirement & REF(five_year_bottom, BARSLAST(k_bottom, index, columns), index, columns), 3),
            (k_bottom_arrival_requirement & REF(historical_bottom, BARSLAST(k_bottom, index, columns), index, columns), 4),
        ],
        index,
        columns,
        default=0.0,
    )

    kline_bottom = pd.DataFrame(
        np.maximum(kline_bottom_1.to_numpy(), kline_bottom_2.to_numpy()),
        index=index,
        columns=columns,
    )
    bottom_fishing_score = kline_bottom.copy()

    factor_dfs: dict[str, pd.DataFrame] = {
        "positive_volume": positive_volume,
        "positive_shape_volume": positive_shape_volume,
        "pure_positive_volume": pure_positive_volume,
        "negative_shape_volume": negative_shape_volume,
        "flat_positive_volume": flat_positive_volume,
        "diff_price_positive_volume": diff_price_positive_volume,
        "diff_shape_positive_volume": diff_shape_positive_volume,
        "negative_volume": negative_volume,
        "pure_negative_volume": pure_negative_volume,
        "lhl": lhl,
        "tll": tll,
        "shl": shl,
        "current_duration": current_duration,
        "back_cross_d_count": back_cross_d_count,
        "adjacent_top_k": adjacent_top_k,
        "time_yq": time_yq,
        "back_cross_situation": back_cross_situation,
        "highest_p_since": highest_p_since,
        "highest_price_since": highest_price_since,
        "ftr": ftr,
        "phl": phl,
        "u_zone": u_zone,
        "prior_d_positive_top": prior_d_positive_top,
        "back_cross_f_count": back_cross_f_count,
        "negative_top_break": negative_top_break,
        "base_lower_stroke_reverse_k_duration": base_lower_stroke_reverse_k_duration,
        "lower_stroke_reverse_k": lower_stroke_reverse_k,
        "negative_j_break": negative_j_break,
        "upper_stroke_reverse_k": upper_stroke_reverse_k,
        "max_upper_stroke_reverse_k": max_upper_stroke_reverse_k,
        "historical_bottom": historical_bottom,
        "five_year_bottom": five_year_bottom,
        "near_historical_bottom": near_historical_bottom,
        "two_year_bottom": two_year_bottom,
        "major_bottom_lift": major_bottom_lift,
        "two_five_year_bottom_lift": two_five_year_bottom_lift,
        "price_yoy_ratio": price_yoy_ratio,
        "k_yoy_ratio": k_yoy_ratio,
        "yearly_double_bottom": yearly_double_bottom,
        "recent_yearly_double_bottom": recent_yearly_double_bottom,
        "yearly_bottom": yearly_bottom,
        "recent_yearly_bottom": recent_yearly_bottom,
        "yearly_double_bottom_lift": yearly_double_bottom_lift,
        "kline_bottom_rank_raw": kline_bottom_rank_raw,
        "kline_bottom_base": kline_bottom_base,
        "k_bottom": k_bottom,
        "relative_low_top": relative_low_top,
        "k_bottom_requirement": k_bottom_requirement,
        "kline_bottom_1": kline_bottom_1,
        "k_bottom_arrival_requirement": k_bottom_arrival_requirement,
        "k_bottom_arrival_base": k_bottom_arrival_base,
        "kline_bottom_2": kline_bottom_2,
        "kline_bottom": kline_bottom,
        "bottom_fishing_score": bottom_fishing_score,
    }

    factor_name_map: dict[str, str] = {
        "阳量": "positive_volume",
        "阳形量": "positive_shape_volume",
        "纯阳量": "pure_positive_volume",
        "阴形量": "negative_shape_volume",
        "平阳量": "flat_positive_volume",
        "异价阳量": "diff_price_positive_volume",
        "异形阳量": "diff_shape_positive_volume",
        "阴量": "negative_volume",
        "纯阴量": "pure_negative_volume",
        "LHL": "lhl",
        "TLL": "tll",
        "SHL": "shl",
        "现在时长": "current_duration",
        "后穿D数": "back_cross_d_count",
        "邻顶K间": "adjacent_top_k",
        "时长YQ": "time_yq",
        "后穿情形": "back_cross_situation",
        "最高P至今": "highest_p_since",
        "最高价到今时长": "highest_price_since",
        "FTR": "ftr",
        "PHL": "phl",
        "U域": "u_zone",
        "前D阳顶": "prior_d_positive_top",
        "后穿F数": "back_cross_f_count",
        "后阴顶穿": "negative_top_break",
        "基础下笔反K时长": "base_lower_stroke_reverse_k_duration",
        "下笔反K": "lower_stroke_reverse_k",
        "阴J贯穿": "negative_j_break",
        "S笔反K": "upper_stroke_reverse_k",
        "MAX上笔反K": "max_upper_stroke_reverse_k",
        "历史大底": "historical_bottom",
        "五年底": "five_year_bottom",
        "近历史大底": "near_historical_bottom",
        "两年底": "two_year_bottom",
        "大底抬升": "major_bottom_lift",
        "两五大底抬升": "two_five_year_bottom_lift",
        "价同比数": "price_yoy_ratio",
        "K同比数": "k_yoy_ratio",
        "年内双底": "yearly_double_bottom",
        "近年内双底": "recent_yearly_double_bottom",
        "年内底": "yearly_bottom",
        "近年内底": "recent_yearly_bottom",
        "年内双底抬升": "yearly_double_bottom_lift",
        "K线底数": "kline_bottom_rank_raw",
        "K线底基": "kline_bottom_base",
        "K底": "k_bottom",
        "相对低顶": "relative_low_top",
        "K底要求": "k_bottom_requirement",
        "K线底1": "kline_bottom_1",
        "K底来要求": "k_bottom_arrival_requirement",
        "K底来幅": "k_bottom_arrival_base",
        "K线底2": "kline_bottom_2",
        "K线底": "kline_bottom",
        "抄底总分": "bottom_fishing_score",
    }

    # 统一关键列类型，避免后续 Arrow 转换错误。
    # factor_dfs 的值是 DataFrame，不是 Series；这里按各列 dtype 判断。
    for factor_name, df in factor_dfs.items():
        try:
            dtype_kinds = {dtype.kind for dtype in df.dtypes}
            if dtype_kinds & {"b", "i", "u", "O"}:
                factor_dfs[factor_name] = df.astype(float)
        except Exception:
            pass  # 转换失败保持原样

    return {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }


# === 总买入信号 ===

def _align(
    df: pd.DataFrame,
    index: pd.Index,
    columns: pd.Index,
) -> pd.DataFrame:
    return df.reindex(index=index, columns=columns)


def _has_recent_consecutive_runup(
    C: pd.DataFrame,
    lookback_days: int = 20,
    runup_threshold: float = 0.22,
) -> pd.DataFrame:
    """过去 lookback_days 内，是否存在连续上涨区间累计涨幅 >= runup_threshold。"""
    close_df = C.astype(float)
    prev = close_df.shift(1)
    up = close_df.gt(prev)

    # 连涨段首日：当天上涨且前一日不是上涨
    first_up = up & (~up.shift(1, fill_value=False))

    # 连涨段起始价：在段首写入前一日收盘，随后前向填充到整段，并在非上涨日清空
    run_start_price = prev.where(first_up).ffill().where(up)

    run_gain = (close_df / run_start_price) - 1.0
    run_hit = (run_gain >= float(runup_threshold)).fillna(False)

    # 过去 lookback_days 日内只要出现过一次满足阈值的连续上涨段，则记为 True
    out = run_hit.rolling(window=int(lookback_days), min_periods=1).max().astype(bool)
    return out


def build_total_buy_signal_bundle(
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    V: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """当 MAC总、KDJ信号、抄底总分 同时为「有信号」时，生成总买入信号。

    - MAC总 ``mac_total``：分档 0～4，>0 视为有信号
    - KDJ信号 ``r_condition``：J<30 为 True
    - 抄底总分 ``bottom_fishing_score``：>0 视为有信号
    - 当基础条件满足时，若 ``集中总`` > 0 再加 1，若 ``筹码峰赋值`` > 0 再加 1
      得到中间强度分 ``raw_total_buy_signal``（范围 0~3）。
    - 最终输出阈值化：``raw_total_buy_signal >= 2`` 记为 1，否则为 0。
    """
    index, columns = C.index, C.columns
    debug_timing = os.getenv("ZXW_FACTOR_DEBUG_TIMING", "0") == "1"
    use_local_impl = os.getenv("ZXW_TOTAL_USE_LOCAL_IMPL", "0") == "1"
    t0 = time.perf_counter() if debug_timing else 0.0

    if _EXT_BUNDLES_AVAILABLE and not use_local_impl:
        bottom_bundle = _ext_build_bottom_fishing_factor_bundle(O, H, L, C)
        kdj_bundle = _ext_build_kdj_factor_bundle(O, H, L, C)
        d_bundle = _ext_build_d_class_factor_bundle(O, H, L, C)
    else:
        bottom_bundle = build_bottom_fishing_factor_bundle(O, H, L, C)
        kdj_bundle = build_kdj_factor_bundle(O, H, L, C)
        d_bundle = build_d_class_factor_bundle(O, H, L, C)
    t1 = time.perf_counter() if debug_timing else 0.0

    bottom_fishing_score = _align(
        bottom_bundle["factor_dfs"]["bottom_fishing_score"], index, columns
    ).astype(float)
    r_condition = _align(kdj_bundle["factor_dfs"]["r_condition"], index, columns)
    mac_total = _align(d_bundle["factor_dfs"]["mac_total"], index, columns).astype(float)

    mac_signal = mac_total > 0
    kdj_signal = r_condition.fillna(False).astype(bool)
    bottom_signal = bottom_fishing_score > 0

    base_signal = mac_signal & kdj_signal & bottom_signal
    raw_total_buy_signal = base_signal.astype(float)

    single_peak_best_signal = pd.DataFrame(False, index=index, columns=columns)
    concentration_total = pd.DataFrame(0.0, index=index, columns=columns)
    chip_peak_score = pd.DataFrame(0.0, index=index, columns=columns)
    if V is not None and _CHIP_BUNDLE_AVAILABLE:
        chip_bundle = _ext_build_chip_structure_factor_bundle(
            H=H,
            L=L,
            C=C,
            V=V,
            window_days=100,
            grid_size=600,
            history_decay=0.95,
        )
        concentration_total = _align(
            chip_bundle["factor_dfs"]["concentration_total_score"], index, columns
        ).astype(float)
        chip_peak_score = _align(
            chip_bundle["factor_dfs"]["chip_peak_score"], index, columns
        ).astype(float)
        single_peak_best = _align(
            chip_bundle["factor_dfs"].get(
                "single_peak_best",
                pd.DataFrame(0.0, index=index, columns=columns),
            ),
            index,
            columns,
        ).astype(float)
        single_peak_best_signal = single_peak_best > 0.0

        raw_total_buy_signal += (base_signal & (concentration_total > 0)).astype(float)
        raw_total_buy_signal += (base_signal & (chip_peak_score > 0)).astype(float)

    total_buy_signal = (raw_total_buy_signal >= 2.0).astype(float)
    super_strong_bottom = (
        (total_buy_signal > 0.0) & single_peak_best_signal.fillna(False)
    ).astype(float)

    # 总买入信号改 = 总买入信号 AND 筹码单峰优；出信号后再延长 4 个交易日（延长期内不续期）
    total_buy_signal_adjusted_raw = (
        (total_buy_signal > 0.0) & single_peak_best_signal.fillna(False)
    ).astype(float)
    total_buy_signal_adjusted = _extend_binary_signal_hold(total_buy_signal_adjusted_raw)
    total_buy_signal_adjusted_no_concentration_raw = (
        base_signal & single_peak_best_signal.fillna(False)
    ).astype(float)
    total_buy_signal_adjusted_no_concentration = _extend_binary_signal_hold(
        total_buy_signal_adjusted_no_concentration_raw
    )

    factor_dfs: dict[str, pd.DataFrame] = {
        "total_buy_signal": total_buy_signal.astype(float),
        "total_buy_signal_adjusted": total_buy_signal_adjusted.astype(float),
        "total_buy_signal_adjusted_no_concentration": total_buy_signal_adjusted_no_concentration.astype(float),
        "super_strong_bottom": super_strong_bottom.astype(float),
    }
    factor_name_map: dict[str, str] = {
        "总买入信号": "total_buy_signal",
        "总买入信号改": "total_buy_signal_adjusted",
        "总买入信号改(不包集中总)": "total_buy_signal_adjusted_no_concentration",
        "总买入超强底": "super_strong_bottom",
    }

    result = {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }
    if debug_timing:
        t2 = time.perf_counter()
        print(
            f"[总买入信号] factors={((t1 - t0) * 1000):.2f}ms combine={((t2 - t1) * 1000):.2f}ms "
            f"total={((t2 - t0) * 1000):.2f}ms backend={'external' if (_EXT_BUNDLES_AVAILABLE and not use_local_impl) else 'local'}"
        )
    return result


if __name__ == '__main__':
    idx = pd.date_range('2020-01-01', periods=5, freq='B')
    cols = ['000001.SZ', '000002.SZ']
    rng = np.random.default_rng(0)
    C = pd.DataFrame(rng.uniform(8, 12, size=(len(idx), len(cols))), index=idx, columns=cols)
    O = C * rng.uniform(0.99, 1.01, size=C.shape)
    H = np.maximum(O, C) * rng.uniform(1.0, 1.02, size=C.shape)
    L = np.minimum(O, C) * rng.uniform(0.98, 1.0, size=C.shape)
    H = pd.DataFrame(H, index=idx, columns=cols)
    L = pd.DataFrame(L, index=idx, columns=cols)
    V = pd.DataFrame(rng.uniform(1e6, 1e7, size=C.shape), index=idx, columns=cols)
    out = build_total_buy_signal_bundle(O, H, L, C, V=V)
    print('factor_name_map:', out['factor_name_map'])
    print('total_buy_signal sample:\n', out['factor_dfs']['total_buy_signal'].iloc[:2])


BUNDLE_ID = "total_buy_signal"
FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    "total_buy_signal": 1300,
    "total_buy_signal_adjusted": 1300,
    "total_buy_signal_adjusted_no_concentration": 1300,
    "super_strong_bottom": 1300,
}


def get_factor_lookback_config() -> dict[str, object]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": 1300,
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
