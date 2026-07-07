from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

try:
    from numba import njit, prange

    _NUMBA_AVAILABLE = True
except Exception:  # pragma: no cover
    _NUMBA_AVAILABLE = False
    njit = None  # type: ignore
    prange = range  # type: ignore


def _use_numba(shape: tuple[int, int]) -> bool:
    return _NUMBA_AVAILABLE


def _align(df: pd.DataFrame, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    return df.reindex(index=index, columns=columns)


def _to_binary(mask: pd.DataFrame) -> pd.DataFrame:
    return mask.fillna(False).astype(float)


if _NUMBA_AVAILABLE:
    @njit(cache=True, fastmath=False, parallel=True)
    def _rolling_mean_window_numba(values: np.ndarray, window: int) -> np.ndarray:
        """rolling(window).mean()，min_periods=1，NaN 视为缺失。"""
        rows, cols = values.shape
        out = np.empty((rows, cols), dtype=np.float64)
        out[:, :] = np.nan
        win = max(int(window), 1)
        for c in prange(cols):
            running = 0.0
            count = 0
            for r in range(rows):
                v = values[r, c]
                if not np.isnan(v):
                    running += v
                    count += 1
                if r >= win:
                    old = values[r - win, c]
                    if not np.isnan(old):
                        running -= old
                        count -= 1
                if count > 0:
                    out[r, c] = running / count
        return out

    @njit(cache=True, fastmath=False, parallel=True)
    def _volume_surge_multi_numba(
        values: np.ndarray,
        total_days: int,
        recent_days: int,
        multiplier_1_2x: float,
        multiplier_1_5x: float,
        multiplier_1_8x: float,
        multiplier_2x: float,
        multiplier_3x: float,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """近 recent_days 均量 > 前 (total_days-recent_days) 均量 * 倍数；一次算 1.2/1.5/1.8/2/3 倍。"""
        rows, cols = values.shape
        out_1_2 = np.zeros((rows, cols), dtype=np.float64)
        out_1_5 = np.zeros((rows, cols), dtype=np.float64)
        out_1_8 = np.zeros((rows, cols), dtype=np.float64)
        out_2 = np.zeros((rows, cols), dtype=np.float64)
        out_3 = np.zeros((rows, cols), dtype=np.float64)
        total_days = max(int(total_days), 1)
        recent_days = max(int(recent_days), 1)
        prior_days = total_days - recent_days
        if prior_days <= 0:
            return out_1_2, out_1_5, out_1_8, out_2, out_3

        for c in prange(cols):
            sum_total = 0.0
            sum_recent = 0.0
            for r in range(rows):
                v = values[r, c]
                if np.isnan(v):
                    v = 0.0
                sum_total += v
                sum_recent += v
                if r >= total_days:
                    old = values[r - total_days, c]
                    if np.isnan(old):
                        old = 0.0
                    sum_total -= old
                if r >= recent_days:
                    old = values[r - recent_days, c]
                    if np.isnan(old):
                        old = 0.0
                    sum_recent -= old

                if r + 1 < total_days:
                    continue

                prior_sum = sum_total - sum_recent
                recent_avg = sum_recent / float(recent_days)
                prior_avg = prior_sum / float(prior_days)
                if recent_avg > prior_avg * multiplier_1_2x:
                    out_1_2[r, c] = 1.0
                if recent_avg > prior_avg * multiplier_1_5x:
                    out_1_5[r, c] = 1.0
                if recent_avg > prior_avg * multiplier_1_8x:
                    out_1_8[r, c] = 1.0
                if recent_avg > prior_avg * multiplier_2x:
                    out_2[r, c] = 1.0
                if recent_avg > prior_avg * multiplier_3x:
                    out_3[r, c] = 1.0
        return out_1_2, out_1_5, out_1_8, out_2, out_3


def _rolling_mean_window(values: np.ndarray, window: int) -> np.ndarray:
    if _use_numba(values.shape):
        return _rolling_mean_window_numba(values, window)
    frame = pd.DataFrame(values)
    return frame.rolling(window=max(int(window), 1), min_periods=1).mean().to_numpy(dtype=np.float64)


def _recent_vs_prior_avg_volume_signals(
    volume: pd.DataFrame,
    *,
    recent_days: int = 5,
    total_days: int = 25,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """返回 (放量1.2倍, 放量1.5倍, 放量1.8倍, 放量2倍, 放量3倍) 二值矩阵。"""
    prior_days = int(total_days) - int(recent_days)
    if prior_days <= 0 or recent_days <= 0:
        raise ValueError("total_days 必须大于 recent_days")

    values = np.ascontiguousarray(volume.to_numpy(dtype=np.float64, copy=False))
    if _use_numba(values.shape):
        out_1_2, out_1_5, out_1_8, out_2, out_3 = _volume_surge_multi_numba(
            values,
            int(total_days),
            int(recent_days),
            1.2,
            1.5,
            1.8,
            2.0,
            3.0,
        )
        return (
            pd.DataFrame(out_1_2, index=volume.index, columns=volume.columns),
            pd.DataFrame(out_1_5, index=volume.index, columns=volume.columns),
            pd.DataFrame(out_1_8, index=volume.index, columns=volume.columns),
            pd.DataFrame(out_2, index=volume.index, columns=volume.columns),
            pd.DataFrame(out_3, index=volume.index, columns=volume.columns),
        )

    vol_sum_total = volume.rolling(window=int(total_days), min_periods=int(total_days)).sum()
    vol_sum_recent = volume.rolling(window=int(recent_days), min_periods=int(recent_days)).sum()
    vol_sum_prior = vol_sum_total - vol_sum_recent
    recent_avg = vol_sum_recent / float(recent_days)
    prior_avg = vol_sum_prior / float(prior_days)
    return (
        _to_binary(recent_avg > prior_avg * 1.2),
        _to_binary(recent_avg > prior_avg * 1.5),
        _to_binary(recent_avg > prior_avg * 1.8),
        _to_binary(recent_avg > prior_avg * 2.0),
        _to_binary(recent_avg > prior_avg * 3.0),
    )


def build_volume_drop_factor_bundle(
    C: pd.DataFrame,
    V: pd.DataFrame,
    volume_window: int = 20,
    small_ratio_min: float = 1.2,
    medium_ratio_min: float = 1.8,
    large_ratio_min: float = 2.5,
) -> dict[str, Any]:
    """
    放量下跌分层：
    - 小放量下跌：V/MA(V,20) >= 1.2 且 < 1.8，且收盘下跌
    - 中放量下跌：V/MA(V,20) >= 1.8 且 < 2.5，且收盘下跌
    - 大放量下跌：V/MA(V,20) >= 2.5，且收盘下跌
    - 放量1.2倍：最近5日平均成交量 > 前20日（25日内除去最近5日）平均成交量 * 1.2
    - 放量1.5倍：最近5日平均成交量 > 前20日（25日内除去最近5日）平均成交量 * 1.5
    - 放量1.8倍：最近5日平均成交量 > 前20日（25日内除去最近5日）平均成交量 * 1.8
    - 放量2倍：最近5日平均成交量 > 前20日（25日内除去最近5日）平均成交量 * 2
    - 放量3倍：最近5日平均成交量 > 前20日（25日内除去最近5日）平均成交量 * 3
    """
    index, columns = C.index, C.columns

    close = _align(C, index, columns).astype(float)
    volume = _align(V, index, columns).astype(float)
    prev_close = close.shift(1)

    vol_values = np.ascontiguousarray(volume.to_numpy(dtype=np.float64, copy=False))
    volume_ma_arr = _rolling_mean_window(vol_values, max(int(volume_window), 1))
    volume_ma = pd.DataFrame(volume_ma_arr, index=index, columns=columns)
    volume_ratio = volume / volume_ma.replace(0.0, pd.NA)

    down_day = close < prev_close

    small_drop = down_day & (volume_ratio >= float(small_ratio_min)) & (volume_ratio < float(medium_ratio_min))
    medium_drop = down_day & (volume_ratio >= float(medium_ratio_min)) & (volume_ratio < float(large_ratio_min))
    large_drop = down_day & (volume_ratio >= float(large_ratio_min))
    any_drop = small_drop | medium_drop | large_drop
    (
        volume_surge_1_2x,
        volume_surge_1_5x,
        volume_surge_1_8x,
        volume_surge_2x,
        volume_surge_3x,
    ) = _recent_vs_prior_avg_volume_signals(volume)

    factor_dfs: dict[str, pd.DataFrame] = {
        "volume_ratio_20": volume_ratio.fillna(0.0).astype(float),
        "small_volume_drop": _to_binary(small_drop),
        "medium_volume_drop": _to_binary(medium_drop),
        "large_volume_drop": _to_binary(large_drop),
        "volume_drop_signal": _to_binary(any_drop),
        "volume_surge_1_2x": volume_surge_1_2x,
        "volume_surge_1_5x": volume_surge_1_5x,
        "volume_surge_1_8x": volume_surge_1_8x,
        "volume_surge_2x": volume_surge_2x,
        "volume_surge_3x": volume_surge_3x,
    }
    factor_name_map: dict[str, str] = {
        "量比20": "volume_ratio_20",
        "小放量下跌": "small_volume_drop",
        "中放量下跌": "medium_volume_drop",
        "大放量下跌": "large_volume_drop",
        "放量下跌": "volume_drop_signal",
        "放量1.2倍": "volume_surge_1_2x",
        "放量1.5倍": "volume_surge_1_5x",
        "放量1.8倍": "volume_surge_1_8x",
        "放量2倍": "volume_surge_2x",
        "放量3倍": "volume_surge_3x",
    }

    return {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }


BUNDLE_ID = "volume_drop"
_DEFAULT_LOOKBACK_DAYS = 90

FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    "volume_ratio_20": 20,
    "small_volume_drop": 21,
    "medium_volume_drop": 21,
    "large_volume_drop": 21,
    "volume_drop_signal": 21,
    "volume_surge_1_2x": 25,
    "volume_surge_1_5x": 25,
    "volume_surge_1_8x": 25,
    "volume_surge_2x": 25,
    "volume_surge_3x": 25,
}


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
