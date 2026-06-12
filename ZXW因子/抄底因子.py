from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from MACD因子 import (
    BARSLAST,
    COUNT,
    EVERY,
    HHV,
    HHVBARS,
    IF,
    LLV,
    LLVBARS,
    LOWRANGE,
    MAX,
    MIN,
    NOT,
    REF,
    REFX,
    TOPRANGE,
)


def _to_frame(x: Any, index: pd.Index, columns: pd.Index, dtype: Any = None) -> pd.DataFrame:
    if isinstance(x, pd.DataFrame):
        result = x.reindex(index=index, columns=columns)
        return result.astype(dtype) if dtype is not None else result
    if np.isscalar(x):
        return pd.DataFrame(x, index=index, columns=columns, dtype=dtype)
    result = pd.DataFrame(x, index=index, columns=columns)
    return result.astype(dtype) if dtype is not None else result


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


def _tdx_kline_12_score(
    requirement: Any,
    barslast: Any,
    *,
    historical_flag: Any,
    five_flag: Any,
    two_flag: Any,
    yearly_combo_flag: Any,
    index: pd.Index,
    columns: pd.Index,
) -> pd.DataFrame:
    """通达信侧 K线底1/2、K线顶1/2：嵌套 IF，1=历史(最强)…4=年内(最弱)；输出给 `_kline_12_tdx_to_user_scale` 再映为 1最弱4最强。"""
    req = _to_frame(requirement, index=index, columns=columns).astype(bool)
    bl = _to_frame(barslast, index=index, columns=columns)
    return IF(
        req & REF(historical_flag, bl, index, columns),
        1,
        IF(
            req & REF(five_flag, bl, index, columns),
            2,
            IF(
                req & REF(two_flag, bl, index, columns),
                3,
                IF(req & REF(yearly_combo_flag, bl, index, columns), 4, 0, index, columns),
                index,
                columns,
            ),
            index,
            columns,
        ),
        index,
        columns,
    ).astype(float)


def _kline_12_tdx_to_user_scale(
    tdx_score: Any,
    index: pd.Index,
    columns: pd.Index,
) -> pd.DataFrame:
    """通达信 1=最强…4=最弱 → 本地 1=最弱…4=最强；0 不变。MIN/MAX 须在映射前用通达信刻度。"""
    v = _to_frame(tdx_score, index=index, columns=columns).astype(float).to_numpy()
    return pd.DataFrame(np.where(v == 0, 0.0, 5.0 - v), index=index, columns=columns)


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
    refx_shl_minus_1 = REFX(shl - 1, 1, index, columns)
    hhv_h_refx_shl_minus_1 = HHV(H, refx_shl_minus_1, index, columns)
    hhvbars_h_refx_shl_minus_1 = HHVBARS(H, refx_shl_minus_1, index, columns)
    back_cross_d_count = IF(
        shl == 1,
        0,
        IF(
            O >= REF(hhv_h_refx_shl_minus_1, 1, index, columns),
            0,
            REF(hhvbars_h_refx_shl_minus_1 + 1, 1, index, columns) + 1,
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
    highest_p_since = current_duration.copy()
    highest_price_since = highest_p_since.copy()
    ftr = top_range_h + 2
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
    llvbars_l_5 = LLVBARS(L, 5, index, columns)
    llvbars_l_250 = LLVBARS(L, 250, index, columns)
    hhvbars_h_5 = HHVBARS(H, 5, index, columns)
    hhvbars_h_250 = HHVBARS(H, 250, index, columns)
    llv_l_5 = LLV(L, 5, index, columns)
    llv_l_100 = LLV(L, 100, index, columns)
    llv_l_250 = LLV(L, 250, index, columns)
    hhv_h_5 = HHV(H, 5, index, columns)
    hhv_h_100 = HHV(H, 100, index, columns)
    hhv_h_250 = HHV(H, 250, index, columns)

    historical_bottom = (L == LLV(L, barscount_c, index, columns)) & (barscount_c >= 750)
    five_year_bottom = L == LLV(L, MIN(1250, barscount_c, index, columns), index, columns)
    near_historical_bottom = LLV(L, 15, index, columns) == LLV(L, barscount_c, index, columns)
    two_year_bottom = L == LLV(L, MIN(500, barscount_c, index, columns), index, columns)
    barslast_historical_bottom = BARSLAST(historical_bottom, index, columns)
    barslast_five_year_bottom = BARSLAST(five_year_bottom, index, columns)
    major_bottom_lift = five_year_bottom & REF(
        REF(barslast_historical_bottom < 1000, upper_stroke_reverse_k - 1, index, columns),
        llvbars_l_5,
        index,
        columns,
    )
    two_five_year_bottom_lift = two_year_bottom & REF(
        REF(barslast_five_year_bottom < 1000, upper_stroke_reverse_k - 1, index, columns),
        llvbars_l_5,
        index,
        columns,
    )
    ref_h_upper_minus_1 = REF(H, upper_stroke_reverse_k - 1, index, columns)
    ref_h_upper_minus_1_at_l250 = REF(ref_h_upper_minus_1, llvbars_l_250, index, columns)
    ref_h_upper_minus_1_at_l5 = REF(ref_h_upper_minus_1, llvbars_l_5, index, columns)
    ref_upper_minus_1_at_l250 = REF(upper_stroke_reverse_k - 1, llvbars_l_250, index, columns)
    ref_upper_minus_1_at_l5 = REF(upper_stroke_reverse_k - 1, llvbars_l_5, index, columns)

    price_yoy_ratio = _between(
        (
            ref_h_upper_minus_1_at_l250
            - llv_l_250
        )
        / (
            ref_h_upper_minus_1_at_l5
            - llv_l_5
        ),
        0.5,
        2.0,
        index,
        columns,
    )
    k_yoy_ratio = _between(
        ref_upper_minus_1_at_l250 / ref_upper_minus_1_at_l5,
        0.5,
        2.0,
        index,
        columns,
    )
    yearly_double_bottom = (
        (upper_stroke_reverse_k >= 85)
        & (upper_stroke_reverse_k < 250)
        & _between(llvbars_l_250, 86, 250, index, columns)
        & (L < ref_h_upper_minus_1_at_l250)
        & (price_yoy_ratio | k_yoy_ratio)
    )
    recent_yearly_double_bottom = BARSLAST(yearly_double_bottom, index, columns) <= 15
    yearly_bottom = L == llv_l_250
    recent_yearly_bottom = BARSLAST(yearly_bottom, index, columns) <= 35
    yearly_double_bottom_lift = (
        (llv_l_5 == llv_l_100)
        & ((llv_l_5 / llv_l_250) < 1.2)
        & (llvbars_l_250 >= 80)
        & (llv_l_5 < ref_h_upper_minus_1_at_l250)
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
    barslast_k_bottom = BARSLAST(k_bottom, index, columns)
    # 通达信：REF(内层, BARSLAST(K底)) — 内层逐根已含该根上的 S笔反K 变窗 HHV；REF 取回「上一 K 底」那根上的值
    relative_low_top_inner_five_two = L + (HHV(H, upper_stroke_reverse_k, index, columns) - L) * 0.1
    relative_low_top_inner_yearly = llv_l_250 + (
        HHV(H, MAX(upper_stroke_reverse_k, 250, index, columns), index, columns) - llv_l_250
    ) * 0.1
    relative_low_top = IF(
        historical_bottom,
        L + (HHV(H, barscount_c, index, columns) - L) * 0.1,
        IF(
            five_year_bottom,
            REF(relative_low_top_inner_five_two, barslast_k_bottom, index, columns),
            IF(
                two_year_bottom,
                REF(relative_low_top_inner_five_two, barslast_k_bottom, index, columns),
                IF(
                    yearly_bottom | yearly_double_bottom,
                    REF(relative_low_top_inner_yearly, barslast_k_bottom, index, columns),
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
    k_bottom_requirement = L <= REF(relative_low_top, barslast_k_bottom, index, columns)
    kline_bottom_1_tdx = _tdx_kline_12_score(
        k_bottom_requirement,
        barslast_k_bottom,
        historical_flag=historical_bottom,
        five_flag=five_year_bottom,
        two_flag=two_year_bottom,
        yearly_combo_flag=yearly_bottom | yearly_double_bottom,
        index=index,
        columns=columns,
    )

    k_bottom_arrival_requirement = IF(
        yearly_double_bottom,
        L <= LLV(C, 250, index, columns) * 1.1,
        L <= REF(C, barslast_k_bottom, index, columns) * 1.1,
        index,
        columns,
    ).astype(bool)
    k_bottom_arrival_base = k_bottom_arrival_requirement.where(k_bottom_arrival_requirement, np.nan)
    kline_bottom_2_tdx = _tdx_kline_12_score(
        k_bottom_arrival_requirement,
        barslast_k_bottom,
        historical_flag=historical_bottom,
        five_flag=five_year_bottom,
        two_flag=two_year_bottom,
        yearly_combo_flag=yearly_bottom | yearly_double_bottom,
        index=index,
        columns=columns,
    )

    # 通达信：K线底:=IF(K线底1*K线底2=0,MAX,MIN)；在通达信刻度上合成后再映为 1最弱4最强
    _kb1 = kline_bottom_1_tdx.astype(float)
    _kb2 = kline_bottom_2_tdx.astype(float)
    _kb_prod = _kb1 * _kb2
    kline_bottom_tdx = IF(
        _kb_prod == 0,
        pd.DataFrame(np.maximum(_kb1.to_numpy(), _kb2.to_numpy()), index=index, columns=columns),
        pd.DataFrame(np.minimum(_kb1.to_numpy(), _kb2.to_numpy()), index=index, columns=columns),
        index,
        columns,
    )
    kline_bottom_1 = _kline_12_tdx_to_user_scale(kline_bottom_1_tdx, index, columns)
    kline_bottom_2 = _kline_12_tdx_to_user_scale(kline_bottom_2_tdx, index, columns)
    kline_bottom = _kline_12_tdx_to_user_scale(kline_bottom_tdx, index, columns)
    bottom_fishing_score = kline_bottom.copy()

    # K线顶因子（镜像 K线底）
    historical_top = (H == HHV(H, barscount_c, index, columns)) & (barscount_c >= 750)
    five_year_top = H == HHV(H, MIN(1250, barscount_c, index, columns), index, columns)
    near_historical_top = HHV(H, 15, index, columns) == HHV(H, barscount_c, index, columns)
    two_year_top = H == HHV(H, MIN(500, barscount_c, index, columns), index, columns)
    barslast_historical_top = BARSLAST(historical_top, index, columns)
    barslast_five_year_top = BARSLAST(five_year_top, index, columns)
    major_top_drop = five_year_top & REF(
        REF(barslast_historical_top < 1000, upper_stroke_reverse_k - 1, index, columns),
        hhvbars_h_5,
        index,
        columns,
    )
    two_five_year_top_drop = two_year_top & REF(
        REF(barslast_five_year_top < 1000, upper_stroke_reverse_k - 1, index, columns),
        hhvbars_h_5,
        index,
        columns,
    )

    ref_l_upper_minus_1 = REF(L, upper_stroke_reverse_k - 1, index, columns)
    ref_l_upper_minus_1_at_h250 = REF(ref_l_upper_minus_1, hhvbars_h_250, index, columns)
    ref_l_upper_minus_1_at_h5 = REF(ref_l_upper_minus_1, hhvbars_h_5, index, columns)
    ref_upper_minus_1_at_h250 = REF(upper_stroke_reverse_k - 1, hhvbars_h_250, index, columns)
    ref_upper_minus_1_at_h5 = REF(upper_stroke_reverse_k - 1, hhvbars_h_5, index, columns)

    price_yoy_ratio_top = _between(
        (hhv_h_250 - ref_l_upper_minus_1_at_h250) / (hhv_h_5 - ref_l_upper_minus_1_at_h5),
        0.5,
        2.0,
        index,
        columns,
    )
    k_yoy_ratio_top = _between(
        ref_upper_minus_1_at_h250 / ref_upper_minus_1_at_h5,
        0.5,
        2.0,
        index,
        columns,
    )

    yearly_double_top = (
        (upper_stroke_reverse_k >= 85)
        & (upper_stroke_reverse_k < 250)
        & _between(hhvbars_h_250, 86, 250, index, columns)
        & (H > ref_l_upper_minus_1_at_h250)
        & (price_yoy_ratio_top | k_yoy_ratio_top)
    )
    recent_yearly_double_top = BARSLAST(yearly_double_top, index, columns) <= 15
    yearly_top = H == hhv_h_250
    recent_yearly_top = BARSLAST(yearly_top, index, columns) <= 35
    yearly_double_top_drop = (
        (hhv_h_5 == hhv_h_100)
        & ((hhv_h_250 / hhv_h_5) < 1.2)
        & (hhvbars_h_250 >= 80)
        & (H > ref_l_upper_minus_1_at_h250)
        & (price_yoy_ratio_top | k_yoy_ratio_top)
    )

    kline_top_rank_raw = _make_rank_frame(
        [
            (recent_yearly_top, 1),
            (two_five_year_top_drop | recent_yearly_double_top | yearly_top, 2),
            (yearly_double_top, 3),
            (two_year_top | major_top_drop, 4),
            (five_year_top | near_historical_top, 5),
            (historical_top, 6),
        ],
        index,
        columns,
        default=np.nan,
    )
    kline_top_base = kline_top_rank_raw.fillna(0.0)
    k_top = historical_top | five_year_top | two_year_top | yearly_top | yearly_double_top
    barslast_k_top = BARSLAST(k_top, index, columns)
    relative_high_bottom_inner_five_two = H - (H - LLV(L, upper_stroke_reverse_k, index, columns)) * 0.1
    relative_high_bottom_inner_yearly = hhv_h_250 - (
        hhv_h_250 - LLV(L, MAX(upper_stroke_reverse_k, 250, index, columns), index, columns)
    ) * 0.1
    relative_high_bottom = IF(
        historical_top,
        H - (H - LLV(L, barscount_c, index, columns)) * 0.1,
        IF(
            five_year_top,
            REF(relative_high_bottom_inner_five_two, barslast_k_top, index, columns),
            IF(
                two_year_top,
                REF(relative_high_bottom_inner_five_two, barslast_k_top, index, columns),
                IF(
                    yearly_top | yearly_double_top,
                    REF(relative_high_bottom_inner_yearly, barslast_k_top, index, columns),
                    H * 0.9,
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
    k_top_requirement = H >= REF(relative_high_bottom, barslast_k_top, index, columns)
    kline_top_1_tdx = _tdx_kline_12_score(
        k_top_requirement,
        barslast_k_top,
        historical_flag=historical_top,
        five_flag=five_year_top,
        two_flag=two_year_top,
        yearly_combo_flag=yearly_top | yearly_double_top,
        index=index,
        columns=columns,
    )
    k_top_arrival_requirement = IF(
        yearly_double_top,
        H >= HHV(C, 250, index, columns) * 0.9,
        H >= REF(C, barslast_k_top, index, columns) * 0.9,
        index,
        columns,
    ).astype(bool)
    k_top_arrival_base = k_top_arrival_requirement.where(k_top_arrival_requirement, np.nan)
    kline_top_2_tdx = _tdx_kline_12_score(
        k_top_arrival_requirement,
        barslast_k_top,
        historical_flag=historical_top,
        five_flag=five_year_top,
        two_flag=two_year_top,
        yearly_combo_flag=yearly_top | yearly_double_top,
        index=index,
        columns=columns,
    )
    _kt1 = kline_top_1_tdx.astype(float)
    _kt2 = kline_top_2_tdx.astype(float)
    _kt_prod = _kt1 * _kt2
    kline_top_tdx = IF(
        _kt_prod == 0,
        pd.DataFrame(np.maximum(_kt1.to_numpy(), _kt2.to_numpy()), index=index, columns=columns),
        pd.DataFrame(np.minimum(_kt1.to_numpy(), _kt2.to_numpy()), index=index, columns=columns),
        index,
        columns,
    )
    kline_top_1 = _kline_12_tdx_to_user_scale(kline_top_1_tdx, index, columns)
    kline_top_2 = _kline_12_tdx_to_user_scale(kline_top_2_tdx, index, columns)
    kline_top = _kline_12_tdx_to_user_scale(kline_top_tdx, index, columns)
    top_escape_score = kline_top.copy()

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
        "historical_top": historical_top,
        "five_year_top": five_year_top,
        "near_historical_top": near_historical_top,
        "two_year_top": two_year_top,
        "major_top_drop": major_top_drop,
        "two_five_year_top_drop": two_five_year_top_drop,
        "yearly_double_top": yearly_double_top,
        "recent_yearly_double_top": recent_yearly_double_top,
        "yearly_top": yearly_top,
        "recent_yearly_top": recent_yearly_top,
        "yearly_double_top_drop": yearly_double_top_drop,
        "kline_top_rank_raw": kline_top_rank_raw,
        "kline_top_base": kline_top_base,
        "k_top": k_top,
        "relative_high_bottom": relative_high_bottom,
        "k_top_requirement": k_top_requirement,
        "kline_top_1": kline_top_1,
        "k_top_arrival_requirement": k_top_arrival_requirement,
        "k_top_arrival_base": k_top_arrival_base,
        "kline_top_2": kline_top_2,
        "kline_top": kline_top,
        "top_escape_score": top_escape_score,
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
        "历史大顶": "historical_top",
        "五年顶": "five_year_top",
        "近历史大顶": "near_historical_top",
        "两年顶": "two_year_top",
        "大顶回落": "major_top_drop",
        "两五大顶回落": "two_five_year_top_drop",
        "年内双顶": "yearly_double_top",
        "近年内双顶": "recent_yearly_double_top",
        "年内顶": "yearly_top",
        "近年内顶": "recent_yearly_top",
        "年内双顶回落": "yearly_double_top_drop",
        "K线顶数": "kline_top_rank_raw",
        "K线顶基": "kline_top_base",
        "K顶": "k_top",
        "相对高底": "relative_high_bottom",
        "K顶要求": "k_top_requirement",
        "K线顶1": "kline_top_1",
        "K顶来要求": "k_top_arrival_requirement",
        "K顶来幅": "k_top_arrival_base",
        "K线顶2": "kline_top_2",
        "K线顶": "kline_top",
        "逃顶总分": "top_escape_score",
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


BUNDLE_ID = "bottom_fishing"
_DEFAULT_LOOKBACK_DAYS = 1300
# Force the K-line bottom chain to query before the earliest A-share history.
FULL_HISTORY_LOOKBACK_DAYS = 50000

FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    "positive_volume": 10,
    "positive_shape_volume": 10,
    "pure_positive_volume": 10,
    "negative_shape_volume": 10,
    "flat_positive_volume": 10,
    "diff_price_positive_volume": 10,
    "diff_shape_positive_volume": 10,
    "negative_volume": 10,
    "pure_negative_volume": 10,
    "lhl": 220,
    "tll": 220,
    "shl": 220,
    "current_duration": 220,
    "back_cross_d_count": 220,
    "adjacent_top_k": 220,
    "time_yq": 220,
    "back_cross_situation": 220,
    "highest_p_since": 220,
    "highest_price_since": 220,
    "ftr": 220,
    "phl": 220,
    "u_zone": 220,
    "prior_d_positive_top": 220,
    "back_cross_f_count": 220,
    "negative_top_break": 220,
    "base_lower_stroke_reverse_k_duration": 220,
    "lower_stroke_reverse_k": 220,
    "negative_j_break": 220,
    "upper_stroke_reverse_k": 220,
    "max_upper_stroke_reverse_k": 260,
    "historical_bottom": FULL_HISTORY_LOOKBACK_DAYS,
    "five_year_bottom": FULL_HISTORY_LOOKBACK_DAYS,
    "near_historical_bottom": FULL_HISTORY_LOOKBACK_DAYS,
    "two_year_bottom": FULL_HISTORY_LOOKBACK_DAYS,
    "major_bottom_lift": FULL_HISTORY_LOOKBACK_DAYS,
    "two_five_year_bottom_lift": FULL_HISTORY_LOOKBACK_DAYS,
    "price_yoy_ratio": FULL_HISTORY_LOOKBACK_DAYS,
    "k_yoy_ratio": FULL_HISTORY_LOOKBACK_DAYS,
    "yearly_double_bottom": FULL_HISTORY_LOOKBACK_DAYS,
    "recent_yearly_double_bottom": FULL_HISTORY_LOOKBACK_DAYS,
    "yearly_bottom": FULL_HISTORY_LOOKBACK_DAYS,
    "recent_yearly_bottom": FULL_HISTORY_LOOKBACK_DAYS,
    "yearly_double_bottom_lift": FULL_HISTORY_LOOKBACK_DAYS,
    "kline_bottom_rank_raw": FULL_HISTORY_LOOKBACK_DAYS,
    "kline_bottom_base": FULL_HISTORY_LOOKBACK_DAYS,
    "k_bottom": FULL_HISTORY_LOOKBACK_DAYS,
    "relative_low_top": FULL_HISTORY_LOOKBACK_DAYS,
    "k_bottom_requirement": FULL_HISTORY_LOOKBACK_DAYS,
    "kline_bottom_1": FULL_HISTORY_LOOKBACK_DAYS,
    "k_bottom_arrival_requirement": FULL_HISTORY_LOOKBACK_DAYS,
    "k_bottom_arrival_base": FULL_HISTORY_LOOKBACK_DAYS,
    "kline_bottom_2": FULL_HISTORY_LOOKBACK_DAYS,
    "kline_bottom": FULL_HISTORY_LOOKBACK_DAYS,
    "bottom_fishing_score": FULL_HISTORY_LOOKBACK_DAYS,
    "historical_top": 1300,
    "five_year_top": 1300,
    "near_historical_top": 1300,
    "two_year_top": 800,
    "major_top_drop": 1300,
    "two_five_year_top_drop": 1300,
    "yearly_double_top": 1300,
    "recent_yearly_double_top": 1300,
    "yearly_top": 1300,
    "recent_yearly_top": 1300,
    "yearly_double_top_drop": 1300,
    "kline_top_rank_raw": 1300,
    "kline_top_base": 1300,
    "k_top": 1300,
    "relative_high_bottom": 1300,
    "k_top_requirement": 1300,
    "kline_top_1": 1300,
    "k_top_arrival_requirement": 1300,
    "k_top_arrival_base": 1300,
    "kline_top_2": 1300,
    "kline_top": 1300,
    "top_escape_score": 1300,
}


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
