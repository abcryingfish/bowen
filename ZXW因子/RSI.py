from __future__ import annotations

import os
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

try:
    from numba import njit, prange

    _NUMBA_AVAILABLE = True
except Exception:  # noqa: BLE001
    _NUMBA_AVAILABLE = False

    def njit(*args, **kwargs):  # type: ignore[override]
        def _decorator(func):
            return func

        return _decorator

    def prange(*args):  # type: ignore[override]
        return range(*args)

_RSI_DEBUG_TIMING = os.environ.get("RSI_DEBUG_TIMING", "").strip().lower() in {"1", "true", "yes"}
_RSI_NUMBA_MIN_SIZE = 50_000


def _to_frame(x: Any, index: pd.Index, columns: pd.Index, dtype: Any = None) -> pd.DataFrame:
    if isinstance(x, pd.DataFrame):
        result = x.reindex(index=index, columns=columns)
        return result.astype(dtype) if dtype is not None else result
    if np.isscalar(x):
        return pd.DataFrame(x, index=index, columns=columns, dtype=dtype)
    result = pd.DataFrame(x, index=index, columns=columns)
    return result.astype(dtype) if dtype is not None else result


def _calc_rsi_value(avg_gain: float, avg_loss: float) -> float:
    if not np.isfinite(avg_gain) or not np.isfinite(avg_loss):
        return np.nan
    if avg_gain == 0 and avg_loss == 0:
        return 50.0
    if avg_loss == 0:
        return 100.0
    if avg_gain == 0:
        return 0.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


@njit(cache=True)
def _calc_rsi_value_numba(avg_gain: float, avg_loss: float) -> float:
    if not np.isfinite(avg_gain) or not np.isfinite(avg_loss):
        return np.nan
    if avg_gain == 0.0 and avg_loss == 0.0:
        return 50.0
    if avg_loss == 0.0:
        return 100.0
    if avg_gain == 0.0:
        return 0.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


@njit(cache=True, parallel=True)
def _wilder_rsi_multi_numba(values: np.ndarray, periods: np.ndarray) -> np.ndarray:
    rows, cols = values.shape
    period_count = periods.shape[0]
    out = np.empty((period_count, rows, cols), dtype=np.float64)
    out[:, :, :] = np.nan

    for c in prange(cols):
        for p in range(period_count):
            n = periods[p]
            start = -1
            for r in range(rows + 1):
                is_valid = r < rows and np.isfinite(values[r, c])
                if is_valid and start < 0:
                    start = r
                elif start >= 0 and not is_valid:
                    seg_len = r - start
                    if seg_len > n:
                        sum_gain = 0.0
                        sum_loss = 0.0
                        for k in range(1, n + 1):
                            delta = values[start + k, c] - values[start + k - 1, c]
                            if delta > 0.0:
                                sum_gain += delta
                            elif delta < 0.0:
                                sum_loss += -delta

                        avg_gain = sum_gain / n
                        avg_loss = sum_loss / n
                        out[p, start + n, c] = _calc_rsi_value_numba(avg_gain, avg_loss)

                        for pos in range(n + 1, seg_len):
                            delta = values[start + pos, c] - values[start + pos - 1, c]
                            gain = delta if delta > 0.0 else 0.0
                            loss = -delta if delta < 0.0 else 0.0
                            avg_gain = ((n - 1) * avg_gain + gain) / n
                            avg_loss = ((n - 1) * avg_loss + loss) / n
                            out[p, start + pos, c] = _calc_rsi_value_numba(avg_gain, avg_loss)
                    start = -1
    return out


def _wilder_rsi_multi_python(values: np.ndarray, periods: list[int]) -> dict[int, np.ndarray]:
    rows, cols = values.shape
    out_map: dict[int, np.ndarray] = {
        n: np.full((rows, cols), np.nan, dtype=float)
        for n in periods
    }

    for c in range(cols):
        series = values[:, c]
        valid_mask = np.isfinite(series)
        start = -1
        for r in range(rows + 1):
            is_valid = r < rows and valid_mask[r]
            if is_valid and start < 0:
                start = r
            elif start >= 0 and not is_valid:
                end = r
                seg = series[start:end]
                seg_len = len(seg)
                if seg_len >= 2:
                    delta = np.diff(seg)
                    gains = np.where(delta > 0.0, delta, 0.0)
                    losses = np.where(delta < 0.0, -delta, 0.0)
                    delta_len = len(delta)

                    for n in periods:
                        if seg_len <= n:
                            continue
                        avg_gain = float(gains[:n].mean())
                        avg_loss = float(losses[:n].mean())
                        out = out_map[n]
                        out[start + n, c] = _calc_rsi_value(avg_gain, avg_loss)

                        for i in range(n, delta_len):
                            avg_gain = ((n - 1) * avg_gain + gains[i]) / n
                            avg_loss = ((n - 1) * avg_loss + losses[i]) / n
                            out[start + i + 1, c] = _calc_rsi_value(avg_gain, avg_loss)
                start = -1
    return out_map


def _wilder_rsi_multi(C: pd.DataFrame, lengths: list[int]) -> dict[int, pd.DataFrame]:
    frame = C.astype(float)
    values = np.ascontiguousarray(frame.to_numpy(dtype=np.float64, copy=False))
    rows, cols = values.shape
    periods = sorted({max(int(x), 1) for x in lengths})
    period_arr = np.asarray(periods, dtype=np.int64)

    start_time = perf_counter()
    use_numba = _NUMBA_AVAILABLE and values.size >= _RSI_NUMBA_MIN_SIZE
    if use_numba:
        out_3d = _wilder_rsi_multi_numba(values, period_arr)
        out_map = {
            periods[i]: out_3d[i]
            for i in range(len(periods))
        }
    else:
        out_map = _wilder_rsi_multi_python(values, periods)

    if _RSI_DEBUG_TIMING:
        elapsed = perf_counter() - start_time
        backend = "numba-parallel" if use_numba else "python-fallback"
        print(f"[RSI] backend={backend} rows={rows} cols={cols} elapsed={elapsed:.3f}s")

    return {
        n: pd.DataFrame(out_map[n], index=frame.index, columns=frame.columns)
        for n in periods
    }


def _cross_up(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    prev_a = a.shift(1)
    prev_b = b.shift(1)
    return (a > b) & (prev_a <= prev_b)


def _cross_down(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    prev_a = a.shift(1)
    prev_b = b.shift(1)
    return (a < b) & (prev_a >= prev_b)


def build_rsi_factor_bundle(C: pd.DataFrame) -> dict[str, dict[str, pd.DataFrame]]:
    index, columns = C.index, C.columns
    C = _to_frame(C, index=index, columns=columns).astype(float)

    rsi_map = _wilder_rsi_multi(C, [6, 12, 24, 48, 96, 120])
    rsi_6 = rsi_map[6]
    rsi_12 = rsi_map[12]
    rsi_24 = rsi_map[24]
    rsi_48 = rsi_map[48]
    rsi_96 = rsi_map[96]
    rsi_120 = rsi_map[120]

    rsi_6_oversold = rsi_6 < 30
    rsi_6_overbought = rsi_6 > 70
    rsi_6_cross_up_rsi_12 = _cross_up(rsi_6, rsi_12)
    rsi_6_cross_down_rsi_12 = _cross_down(rsi_6, rsi_12)
    rsi_multi_bullish = (rsi_6 > rsi_12) & (rsi_12 > rsi_24)
    rsi_multi_bearish = (rsi_6 < rsi_12) & (rsi_12 < rsi_24)
    rsi_6_extreme_oversold = rsi_6 < 6

    rsi_total_score = pd.DataFrame(0, index=index, columns=columns, dtype=int)
    rsi_total_score = rsi_total_score + rsi_6_oversold.astype(int)
    rsi_total_score = rsi_total_score + rsi_6_cross_up_rsi_12.astype(int)
    rsi_total_score = rsi_total_score + rsi_multi_bullish.astype(int)

    factor_dfs: dict[str, pd.DataFrame] = {
        "rsi_6": rsi_6,
        "rsi_12": rsi_12,
        "rsi_24": rsi_24,
        "rsi_48": rsi_48,
        "rsi_96": rsi_96,
        "rsi_120": rsi_120,
        "rsi_6_oversold": rsi_6_oversold,
        "rsi_6_overbought": rsi_6_overbought,
        "rsi_6_cross_up_rsi_12": rsi_6_cross_up_rsi_12,
        "rsi_6_cross_down_rsi_12": rsi_6_cross_down_rsi_12,
        "rsi_multi_bullish": rsi_multi_bullish,
        "rsi_multi_bearish": rsi_multi_bearish,
        "rsi_6_extreme_oversold": rsi_6_extreme_oversold,
        "rsi_total_score": rsi_total_score,
    }

    factor_name_map: dict[str, str] = {
        "RSI6": "rsi_6",
        "RSI12": "rsi_12",
        "RSI24": "rsi_24",
        "RSI48": "rsi_48",
        "RSI96": "rsi_96",
        "RSI120": "rsi_120",
        "RSI超卖": "rsi_6_oversold",
        "RSI超买": "rsi_6_overbought",
        "RSI金叉": "rsi_6_cross_up_rsi_12",
        "RSI死叉": "rsi_6_cross_down_rsi_12",
        "RSI多头排列": "rsi_multi_bullish",
        "RSI空头排列": "rsi_multi_bearish",
        "RSI极端超卖": "rsi_6_extreme_oversold",
        "RSI买入信号": "rsi_6_extreme_oversold",
        "RSI总分": "rsi_total_score",
    }

    return {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }


BUNDLE_ID = "rsi"
_DEFAULT_LOOKBACK_DAYS = 180

FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    "rsi_6": 30,
    "rsi_12": 45,
    "rsi_24": 75,
    "rsi_48": 120,
    "rsi_96": 160,
    "rsi_120": 180,
    "rsi_6_oversold": 30,
    "rsi_6_overbought": 30,
    "rsi_6_cross_up_rsi_12": 60,
    "rsi_6_cross_down_rsi_12": 60,
    "rsi_multi_bullish": 90,
    "rsi_multi_bearish": 90,
    "rsi_6_extreme_oversold": 30,
    "rsi_total_score": 180,
}


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
