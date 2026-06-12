from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from MACD因子 import (
    BARSLAST,
    COUNT,
    CROSS,
    EMA,
    IF,
    MA,
    NOT,
    _to_frame,
    build_upper_stroke_reverse_k_bundle,
)


def build_macd_sell_factors(C: pd.DataFrame) -> dict[str, pd.DataFrame]:
    index, columns = C.index, C.columns
    dif = (EMA(C, 12, index, columns) - EMA(C, 26, index, columns)) * 100
    dea = EMA(dif, 9, index, columns)
    mac = (dif - dea) * 2
    return {"dif": dif, "dea": dea, "mac": mac}


def build_top_divergence_factors(
    H: pd.DataFrame,
    C: pd.DataFrame,
    dif: pd.DataFrame,
    dea: pd.DataFrame,
    mac: pd.DataFrame,
    s_reverse_k: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    index, columns = C.index, C.columns

    green_bar = (mac < 0) & (mac < MA(mac, 60, index, columns))
    death_cross = CROSS(dea, dif, index, columns)
    n_rows = len(index)

    p_mark_arc_top_arr = np.zeros((n_rows, len(columns)), dtype=bool)
    p_new_high_start_arr = np.zeros((n_rows, len(columns)), dtype=bool)
    p_initial_top_divergence_arr = np.zeros((n_rows, len(columns)), dtype=bool)
    top_divergence_held_arr = np.zeros((n_rows, len(columns)), dtype=bool)

    close_values = C.to_numpy(dtype=float)
    mac_values = mac.to_numpy(dtype=float)

    for col_idx in range(len(columns)):
        close_col = close_values[:, col_idx]
        mac_col = mac_values[:, col_idx]

        raw_peaks: list[int] = []
        for center in range(5, n_rows - 5):
            window = close_col[center - 5 : center + 6]
            if np.isnan(window).any():
                continue
            center_value = close_col[center]
            if center_value == np.max(window) and np.sum(window == center_value) == 1:
                raw_peaks.append(center)
                p_mark_arc_top_arr[center + 5, col_idx] = True

        latest_peak_idx = -1
        for t2 in range(0, n_rows - 2):
            while (latest_peak_idx + 1) < len(raw_peaks) and raw_peaks[latest_peak_idx + 1] < t2:
                latest_peak_idx += 1
            if latest_peak_idx < 0:
                continue
            if not np.isfinite(close_col[t2]) or not np.isfinite(close_col[t2 + 1]) or not np.isfinite(close_col[t2 + 2]):
                continue
            if not (close_col[t2] > close_col[t2 + 1] and close_col[t2] > close_col[t2 + 2]):
                continue

            t1 = raw_peaks[latest_peak_idx]
            if t2 - t1 <= 6:
                continue
            signal_idx = t2 + 2
            if signal_idx >= n_rows:
                continue

            valley_segment = close_col[t1 + 1 : t2]
            if valley_segment.size == 0 or np.isnan(valley_segment).all():
                continue
            valley_value = np.nanmin(valley_segment)
            if np.isnan(valley_value) or close_col[t1] == 0:
                continue

            drawdown_ok = (close_col[t1] - valley_value) / close_col[t1] >= 0.06
            price_new_high = close_col[t2] > close_col[t1]
            p_new_high_start_arr[signal_idx, col_idx] = drawdown_ok and price_new_high

            if not np.isfinite(mac_col[t1]) or not np.isfinite(mac_col[t2]):
                continue
            mac_not_new_high = mac_col[t2] < mac_col[t1]
            if drawdown_ok and price_new_high and mac_not_new_high:
                p_initial_top_divergence_arr[signal_idx, col_idx] = True
                hold_end = min(signal_idx + 3, n_rows)
                top_divergence_held_arr[signal_idx:hold_end, col_idx] = True

    p_mark_arc_top = pd.DataFrame(p_mark_arc_top_arr, index=index, columns=columns)
    p_new_high_start = pd.DataFrame(p_new_high_start_arr, index=index, columns=columns)
    p_initial_top_divergence = pd.DataFrame(p_initial_top_divergence_arr, index=index, columns=columns)
    bars_last_initial_top_divergence = BARSLAST(p_initial_top_divergence, index, columns)
    top_divergence = pd.DataFrame(top_divergence_held_arr, index=index, columns=columns)
    p_continued_top_divergence = top_divergence & (~p_initial_top_divergence)
    top_divergence_and_green_bar = top_divergence & green_bar
    top_divergence_and_death_cross = top_divergence & death_cross
    death_cross_and_green_bar = death_cross & green_bar

    a_plus = top_divergence_and_green_bar | top_divergence_and_death_cross
    a_only = green_bar & (COUNT(death_cross, 7, index, columns) >= 1) & NOT(a_plus, index, columns)

    mac_sell_total = IF(
        a_plus,
        4,
        IF(
            a_only,
            3,
            IF(death_cross | green_bar, 2, IF(top_divergence, 1, 0, index, columns), index, columns),
            index,
            columns,
        ),
        index,
        columns,
    )

    return {
        "green_bar": green_bar,
        "death_cross": death_cross,
        "p_mark_arc_top": p_mark_arc_top,
        "p_new_high_start": p_new_high_start,
        "p_initial_top_divergence": p_initial_top_divergence,
        "bars_last_initial_top_divergence": bars_last_initial_top_divergence,
        "p_continued_top_divergence": p_continued_top_divergence,
        "top_divergence": top_divergence,
        "top_divergence_and_green_bar": top_divergence_and_green_bar,
        "top_divergence_and_death_cross": top_divergence_and_death_cross,
        "death_cross_and_green_bar": death_cross_and_green_bar,
        "mac_sell_total": mac_sell_total,
    }


def build_macd_sell_factor_bundle(
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    s_reverse_k: pd.DataFrame | None = None,
) -> dict[str, Any]:
    index, columns = C.index, C.columns
    O = _to_frame(O, index=index, columns=columns).astype(float)
    H = _to_frame(H, index=index, columns=columns).astype(float)
    L = _to_frame(L, index=index, columns=columns).astype(float)
    C = _to_frame(C, index=index, columns=columns).astype(float)

    stroke_bundle = build_upper_stroke_reverse_k_bundle(O, H, L, C, index, columns)
    computed_s_reverse_k = stroke_bundle["lower_stroke_reverse_k"].astype(float)
    if s_reverse_k is None:
        s_reverse_k = computed_s_reverse_k
    else:
        s_reverse_k = _to_frame(s_reverse_k, index=index, columns=columns).astype(float)

    macd_factors = build_macd_sell_factors(C)
    dif = macd_factors["dif"]
    dea = macd_factors["dea"]
    mac = macd_factors["mac"]

    top = build_top_divergence_factors(
        H=H,
        C=C,
        dif=dif,
        dea=dea,
        mac=mac,
        s_reverse_k=s_reverse_k,
    )

    factor_dfs: dict[str, pd.DataFrame] = {
        "green_bar": top["green_bar"],
        "death_cross": top["death_cross"],
        "p_mark_arc_top": top["p_mark_arc_top"],
        "p_new_high_start": top["p_new_high_start"],
        "p_initial_top_divergence": top["p_initial_top_divergence"],
        "p_continued_top_divergence": top["p_continued_top_divergence"],
        "top_divergence": top["top_divergence"],
        "top_divergence_and_green_bar": top["top_divergence_and_green_bar"],
        "top_divergence_and_death_cross": top["top_divergence_and_death_cross"],
        "death_cross_and_green_bar": top["death_cross_and_green_bar"],
        "mac_sell_total": top["mac_sell_total"],
    }

    factor_name_map: dict[str, str] = {
        "绿柱": "green_bar",
        "死叉": "death_cross",
        "P标弧顶": "p_mark_arc_top",
        "P弧新高初": "p_new_high_start",
        "P新高初背离": "p_initial_top_divergence",
        "P新高延续背离": "p_continued_top_divergence",
        "顶背离": "top_divergence",
        "顶背离&绿柱": "top_divergence_and_green_bar",
        "顶背离&死叉": "top_divergence_and_death_cross",
        "死叉&绿柱": "death_cross_and_green_bar",
        "MAC卖出总": "mac_sell_total",
    }

    return {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }


BUNDLE_ID = "macd_sell"
_DEFAULT_LOOKBACK_DAYS = 260

FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    "green_bar": 180,
    "death_cross": 180,
    "p_mark_arc_top": 180,
    "p_new_high_start": 220,
    "p_initial_top_divergence": 240,
    "p_continued_top_divergence": 240,
    "top_divergence": 240,
    "top_divergence_and_green_bar": 240,
    "top_divergence_and_death_cross": 240,
    "death_cross_and_green_bar": 240,
    "mac_sell_total": 260,
}


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
