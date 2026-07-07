from __future__ import annotations

import numpy as np
import pandas as pd

from MACD因子 import BARSLAST, HHV, LLV, REF

EN_FACTOR_PREFIX = "hong_"
CN_FACTOR_PREFIX = "洪"


def _prefix_factor_name(name: str) -> str:
    normalized = str(name).strip()
    if not normalized:
        return normalized
    if normalized.isascii():
        return normalized if normalized.startswith(EN_FACTOR_PREFIX) else f"{EN_FACTOR_PREFIX}{normalized}"
    return normalized if normalized.startswith(CN_FACTOR_PREFIX) else f"{CN_FACTOR_PREFIX}{normalized}"


def _history_ready_mask(length: int, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    row_ids = np.arange(len(index), dtype=np.int64).reshape(-1, 1)
    values = row_ids >= (int(length) - 1)
    return pd.DataFrame(np.repeat(values, len(columns), axis=1), index=index, columns=columns)


def _get_last_signal_low_and_rise(
    signal: pd.DataFrame,
    signal_low: pd.DataFrame,
    H: pd.DataFrame,
    index: pd.Index,
    columns: pd.Index,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    bars_last = BARSLAST(signal, index, columns).astype(np.int64)
    seen_signal = signal.astype(bool).cummax()
    last_signal_low = REF(signal_low, bars_last, index, columns).where(seen_signal)
    highest_since_signal = HHV(H, bars_last + 1, index, columns).where(seen_signal)
    rise = ((highest_since_signal - last_signal_low) / last_signal_low).where(last_signal_low > 0)
    return seen_signal, last_signal_low, rise


def _build_confirmed_first_lows(low_values: np.ndarray, flank: int = 5) -> list[list[int]]:
    rows, cols = low_values.shape
    candidates: list[list[int]] = [[] for _ in range(cols)]
    for c in range(cols):
        for idx in range(flank, rows - flank):
            cur = low_values[idx, c]
            if np.isnan(cur) or cur <= 0:
                continue
            window = low_values[idx - flank : idx + flank + 1, c]
            if np.isnan(window).all():
                continue
            if cur != np.nanmin(window):
                continue
            if candidates[c] and idx - candidates[c][-1] <= flank:
                prev_idx = candidates[c][-1]
                prev_low = low_values[prev_idx, c]
                if cur <= prev_low:
                    candidates[c][-1] = idx
                continue
            candidates[c].append(idx)
    return candidates


def _build_double_bottom_signal(
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    index: pd.Index,
    columns: pd.Index,
    *,
    lookback: int,
    min_separation: int,
    max_separation: int,
    price_tolerance: float,
    rebound_threshold: float,
    first_low_break_threshold: float = 0.03,
) -> pd.DataFrame:
    high_values = H.astype(float).to_numpy()
    low_values = L.astype(float).to_numpy()
    close_values = C.astype(float).to_numpy()
    rows, cols = low_values.shape

    first_low_candidates = _build_confirmed_first_lows(low_values, flank=5)
    active = np.zeros(low_values.shape, dtype=bool)

    for c in range(cols):
        column_candidates = first_low_candidates[c]
        if not column_candidates:
            continue

        for second_idx in range(rows):
            second_low = low_values[second_idx, c]
            if np.isnan(second_low) or second_low <= 0:
                continue
            if close_values[second_idx, c] == second_low:
                continue

            min_first_idx = max(0, second_idx - min(lookback, max_separation))
            matched = False

            for first_idx in reversed(column_candidates):
                if first_idx < min_first_idx:
                    break

                separation = second_idx - first_idx
                if separation < min_separation:
                    continue
                if separation > max_separation:
                    break

                first_confirm_idx = first_idx + 5
                if first_confirm_idx >= second_idx:
                    continue

                first_low = low_values[first_idx, c]
                if np.isnan(first_low) or first_low <= 0:
                    continue

                interior_lows = low_values[first_idx + 1 : second_idx, c]
                if interior_lows.size and np.nanmin(interior_lows) < first_low * (1.0 - first_low_break_threshold):
                    continue

                lower_low = min(first_low, second_low)
                price_gap = abs(second_low - first_low) / lower_low
                if price_gap > price_tolerance:
                    continue

                middle_highs = high_values[first_idx + 1 : second_idx, c]
                if middle_highs.size == 0 or np.isnan(middle_highs).all():
                    continue
                rebound = (np.nanmax(middle_highs) - lower_low) / lower_low
                if rebound < rebound_threshold:
                    continue

                active[second_idx, c] = True
                matched = True
                break

            if matched:
                continue

    return pd.DataFrame(active, index=index, columns=columns)


def build_bottom_fishing_factor_bundle(
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
) -> dict[str, dict[str, pd.DataFrame]]:
    index, columns = C.index, C.columns

    llv_7 = LLV(L, 7, index, columns)
    llv_20 = LLV(L, 20, index, columns)
    llv_200 = LLV(L, 200, index, columns)
    llv_400 = LLV(L, 400, index, columns)
    llv_1000 = LLV(L, 1000, index, columns)
    prev_llv_7 = REF(llv_7, 1, index, columns)
    prev_llv_20 = REF(llv_20, 1, index, columns)
    prev_llv_200 = REF(llv_200, 1, index, columns)
    prev_llv_400 = REF(llv_400, 1, index, columns)
    prev_llv_1000 = REF(llv_1000, 1, index, columns)

    mini_bottom = (L <= prev_llv_7) & _history_ready_mask(8, index, columns)
    small_bottom = (L <= prev_llv_20) & _history_ready_mask(21, index, columns)
    major_bottom = (L <= prev_llv_200) & _history_ready_mask(201, index, columns)
    near_historical_bottom = (L <= prev_llv_400) & _history_ready_mask(401, index, columns)
    historical_bottom = (L <= prev_llv_1000) & _history_ready_mask(1001, index, columns)
    mini_signal_low = L.where(mini_bottom)
    small_signal_low = L.where(small_bottom)
    major_signal_low = L.where(major_bottom)
    near_historical_signal_low = L.where(near_historical_bottom)
    historical_signal_low = L.where(historical_bottom)

    mini_seen, _, mini_rise = _get_last_signal_low_and_rise(mini_bottom, mini_signal_low, H, index, columns)
    small_seen, _, small_rise = _get_last_signal_low_and_rise(small_bottom, small_signal_low, H, index, columns)
    major_seen, _, major_rise = _get_last_signal_low_and_rise(major_bottom, major_signal_low, H, index, columns)
    near_historical_seen, _, near_historical_rise = _get_last_signal_low_and_rise(
        near_historical_bottom, near_historical_signal_low, H, index, columns
    )
    historical_seen, _, historical_rise = _get_last_signal_low_and_rise(
        historical_bottom, historical_signal_low, H, index, columns
    )

    mini_active = mini_seen & (mini_rise < 0.20)
    small_active = small_seen & (small_rise < 0.20)
    historical_active = historical_seen & (historical_rise < 0.20)
    near_historical_active = near_historical_seen & (near_historical_rise < 0.20)
    major_active = major_seen & (major_rise < 0.20)

    base_score = pd.DataFrame(0.0, index=index, columns=columns)
    base_rise = pd.DataFrame(np.nan, index=index, columns=columns)

    historical_mask = historical_active.to_numpy()
    near_historical_mask = (~historical_mask) & near_historical_active.to_numpy()
    major_mask = (~historical_mask) & (~near_historical_mask) & major_active.to_numpy()
    small_mask = (~historical_mask) & (~near_historical_mask) & (~major_mask) & small_active.to_numpy()
    mini_mask = (~historical_mask) & (~near_historical_mask) & (~major_mask) & (~small_mask) & mini_active.to_numpy()

    base_score_values = base_score.to_numpy()
    base_rise_values = base_rise.to_numpy()

    base_score_values[historical_mask] = 3.0
    base_score_values[near_historical_mask] = 2.0
    base_score_values[major_mask] = 1.0
    base_score_values[small_mask] = 1.0
    base_score_values[mini_mask] = 0.5

    mini_rise_values = mini_rise.to_numpy()
    small_rise_values = small_rise.to_numpy()
    historical_rise_values = historical_rise.to_numpy()
    near_historical_rise_values = near_historical_rise.to_numpy()
    major_rise_values = major_rise.to_numpy()

    base_rise_values[mini_mask] = mini_rise_values[mini_mask]
    base_rise_values[small_mask] = small_rise_values[small_mask]
    base_rise_values[historical_mask] = historical_rise_values[historical_mask]
    base_rise_values[near_historical_mask] = near_historical_rise_values[near_historical_mask]
    base_rise_values[major_mask] = major_rise_values[major_mask]

    bottom_fishing_score = base_score
    bottom_fishing_score = bottom_fishing_score.where(base_score > 0, 0.0)

    raw_factor_dfs: dict[str, pd.DataFrame] = {
        "mini_bottom": mini_bottom,
        "small_bottom": small_bottom,
        "major_bottom": major_bottom,
        "near_historical_bottom": near_historical_bottom,
        "historical_bottom": historical_bottom,
        "bottom_fishing_score": bottom_fishing_score,
    }

    raw_factor_name_map: dict[str, str] = {
        "迷你底": "mini_bottom",
        "小底": "small_bottom",
        "大底": "major_bottom",
        "近历史大底": "near_historical_bottom",
        "历史大底": "historical_bottom",
        "抄底总分": "bottom_fishing_score",
    }

    factor_dfs = {_prefix_factor_name(name): df for name, df in raw_factor_dfs.items()}
    factor_name_map = {
        _prefix_factor_name(display_name): _prefix_factor_name(internal_name)
        for display_name, internal_name in raw_factor_name_map.items()
    }

    return {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }


BUNDLE_ID = "hong_bottom_fishing"
_DEFAULT_LOOKBACK_DAYS = 1100

FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    "hong_mini_bottom": 30,
    "hong_small_bottom": 60,
    "hong_major_bottom": 260,
    "hong_near_historical_bottom": 500,
    "hong_historical_bottom": 1100,
    "hong_bottom_fishing_score": 1100,
}


def get_factor_lookback_config() -> dict[str, object]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
