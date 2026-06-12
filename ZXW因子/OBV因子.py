from __future__ import annotations

import os
import time
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


def _timing_enabled() -> bool:
    return os.getenv("ZXW_FACTOR_DEBUG_TIMING", "0") == "1"


def _fast_round_decimals() -> int:
    return int(os.getenv("ZXW_OBV_FAST_DECIMALS", "3"))


if _NUMBA_AVAILABLE:
    @njit(cache=True, fastmath=False, parallel=True)
    def _obv_numba(close_values: np.ndarray, volume_values: np.ndarray) -> np.ndarray:
        rows, cols = close_values.shape
        out = np.zeros((rows, cols), dtype=np.float64)
        for c in prange(cols):
            for r in range(1, rows):
                close_cur = close_values[r, c]
                vol_cur = volume_values[r, c]
                if np.isnan(close_cur) or np.isnan(vol_cur):
                    out[r, c] = out[r - 1, c]
                    continue
                prev_close = close_values[r - 1, c]
                if close_cur > prev_close:
                    out[r, c] = out[r - 1, c] + vol_cur
                elif close_cur < prev_close:
                    out[r, c] = out[r - 1, c] - vol_cur
                else:
                    out[r, c] = out[r - 1, c]
        return out

    @njit(cache=True, fastmath=False, parallel=True)
    def _obv_slope_numba(values: np.ndarray, window: int) -> np.ndarray:
        rows, cols = values.shape
        out = np.empty((rows, cols), dtype=np.float64)
        out[:, :] = np.nan
        n_win = int(window)
        for c in prange(cols):
            for r in range(n_win, rows):
                sum_x = 0.0
                sum_y = 0.0
                sum_xy = 0.0
                sum_x2 = 0.0
                valid = 0
                for k in range(n_win):
                    y = values[r - n_win + k, c]
                    if not np.isnan(y):
                        x = float(k)
                        sum_x += x
                        sum_y += y
                        sum_xy += x * y
                        sum_x2 += x * x
                        valid += 1
                if valid >= 2:
                    denom = valid * sum_x2 - sum_x * sum_x
                    if denom != 0.0:
                        out[r, c] = (valid * sum_xy - sum_x * sum_y) / denom
        return out

    @njit(cache=True, fastmath=False, parallel=True)
    def _detect_divergence_numba(
        close_values: np.ndarray,
        obv_values: np.ndarray,
        window: int,
        bearish: bool,
    ) -> np.ndarray:
        rows, cols = close_values.shape
        out = np.zeros((rows, cols), dtype=np.bool_)
        for c in prange(cols):
            for r in range(window, rows):
                start = r - window
                # window all-NaN checks
                close_all_nan = True
                obv_all_nan = True
                for k in range(start, r + 1):
                    if not np.isnan(close_values[k, c]):
                        close_all_nan = False
                    if not np.isnan(obv_values[k, c]):
                        obv_all_nan = False
                if close_all_nan or obv_all_nan:
                    continue

                if bearish:
                    price_max_idx = -1
                    obv_max_idx = -1
                    price_max = 0.0
                    obv_max = 0.0
                    for k in range(start, r + 1):
                        pv = close_values[k, c]
                        ov = obv_values[k, c]
                        if not np.isnan(pv):
                            if price_max_idx == -1 or pv > price_max:
                                price_max = pv
                                price_max_idx = k
                        if not np.isnan(ov):
                            if obv_max_idx == -1 or ov > obv_max:
                                obv_max = ov
                                obv_max_idx = k
                    if price_max_idx == r and obv_max_idx < r:
                        current_obv = obv_values[r, c]
                        if np.isnan(current_obv):
                            continue
                        prev_high = np.nan
                        for k in range(start, r):
                            ov = obv_values[k, c]
                            if np.isnan(ov):
                                continue
                            if np.isnan(prev_high) or ov > prev_high:
                                prev_high = ov
                        if not np.isnan(prev_high) and current_obv < prev_high * 0.98:
                            out[r, c] = True
                else:
                    price_min_idx = -1
                    obv_min_idx = -1
                    price_min = 0.0
                    obv_min = 0.0
                    for k in range(start, r + 1):
                        pv = close_values[k, c]
                        ov = obv_values[k, c]
                        if not np.isnan(pv):
                            if price_min_idx == -1 or pv < price_min:
                                price_min = pv
                                price_min_idx = k
                        if not np.isnan(ov):
                            if obv_min_idx == -1 or ov < obv_min:
                                obv_min = ov
                                obv_min_idx = k
                    if price_min_idx == r and obv_min_idx < r:
                        current_obv = obv_values[r, c]
                        if np.isnan(current_obv):
                            continue
                        prev_low = np.nan
                        for k in range(start, r):
                            ov = obv_values[k, c]
                            if np.isnan(ov):
                                continue
                            if np.isnan(prev_low) or ov < prev_low:
                                prev_low = ov
                        if not np.isnan(prev_low) and current_obv > prev_low * 1.02:
                            out[r, c] = True
        return out

    @njit(cache=True, fastmath=False, parallel=True)
    def _rolling_mean_numba(values: np.ndarray, window: int) -> np.ndarray:
        rows, cols = values.shape
        out = np.empty((rows, cols), dtype=np.float64)
        out[:, :] = np.nan
        w = max(int(window), 1)
        for c in prange(cols):
            for r in range(rows):
                start = r - w + 1
                if start < 0:
                    start = 0
                total = 0.0
                count = 0
                for k in range(start, r + 1):
                    v = values[k, c]
                    if not np.isnan(v):
                        total += v
                        count += 1
                if count > 0:
                    out[r, c] = total / count
        return out

    @njit(cache=True, fastmath=False, parallel=True)
    def _rolling_max_numba(values: np.ndarray, window: int) -> np.ndarray:
        rows, cols = values.shape
        out = np.empty((rows, cols), dtype=np.float64)
        out[:, :] = np.nan
        w = max(int(window), 1)
        for c in prange(cols):
            for r in range(rows):
                start = r - w + 1
                if start < 0:
                    start = 0
                found = False
                cur_max = 0.0
                for k in range(start, r + 1):
                    v = values[k, c]
                    if not np.isnan(v):
                        if (not found) or (v > cur_max):
                            cur_max = v
                            found = True
                if found:
                    out[r, c] = cur_max
        return out

    @njit(cache=True, fastmath=False, parallel=True)
    def _rolling_std_numba(values: np.ndarray, window: int) -> np.ndarray:
        rows, cols = values.shape
        out = np.empty((rows, cols), dtype=np.float64)
        out[:, :] = np.nan
        w = max(int(window), 1)
        for c in prange(cols):
            for r in range(rows):
                start = r - w + 1
                if start < 0:
                    start = 0
                total = 0.0
                count = 0
                for k in range(start, r + 1):
                    v = values[k, c]
                    if not np.isnan(v):
                        total += v
                        count += 1
                if count <= 1:
                    continue
                mean = total / count
                var_sum = 0.0
                for k in range(start, r + 1):
                    v = values[k, c]
                    if not np.isnan(v):
                        d = v - mean
                        var_sum += d * d
                out[r, c] = np.sqrt(var_sum / (count - 1))
        return out

    @njit(cache=True, fastmath=False, parallel=True)
    def _rolling_sum_bool_numba(values: np.ndarray, window: int) -> np.ndarray:
        rows, cols = values.shape
        out = np.zeros((rows, cols), dtype=np.int64)
        w = max(int(window), 1)
        for c in prange(cols):
            prefix = np.zeros(rows + 1, dtype=np.int64)
            for r in range(rows):
                prefix[r + 1] = prefix[r] + (1 if values[r, c] else 0)
            for r in range(rows):
                start = r - w + 1
                if start < 0:
                    start = 0
                out[r, c] = prefix[r + 1] - prefix[start]
        return out

def _to_frame(x: Any, index: pd.Index, columns: pd.Index, dtype: Any = None) -> pd.DataFrame:
    if isinstance(x, pd.DataFrame):
        result = x.reindex(index=index, columns=columns)
        return result.astype(dtype) if dtype is not None else result
    if np.isscalar(x):
        return pd.DataFrame(x, index=index, columns=columns, dtype=dtype)
    result = pd.DataFrame(x, index=index, columns=columns)
    return result.astype(dtype) if dtype is not None else result


def _calculate_obv(C: pd.DataFrame, V: pd.DataFrame) -> pd.DataFrame:
    """计算基础OBV值。"""
    close_values = np.ascontiguousarray(C.astype(float).to_numpy(dtype=np.float64, copy=False))
    volume_values = np.ascontiguousarray(V.astype(float).to_numpy(dtype=np.float64, copy=False))
    rows, cols = close_values.shape
    if _use_numba((rows, cols)):
        obv = _obv_numba(close_values, volume_values)
    else:
        obv = np.zeros((rows, cols), dtype=float)
        for c in range(cols):
            for r in range(1, rows):
                if np.isnan(close_values[r, c]) or np.isnan(volume_values[r, c]):
                    obv[r, c] = obv[r - 1, c]
                    continue
                if close_values[r, c] > close_values[r - 1, c]:
                    obv[r, c] = obv[r - 1, c] + volume_values[r, c]
                elif close_values[r, c] < close_values[r - 1, c]:
                    obv[r, c] = obv[r - 1, c] - volume_values[r, c]
                else:
                    obv[r, c] = obv[r - 1, c]

    return pd.DataFrame(obv, index=C.index, columns=C.columns)


def _linear_slope(series: pd.Series, window: int) -> float:
    """计算线性回归斜率。"""
    valid_data = series.dropna()
    if len(valid_data) < window:
        return np.nan

    y = valid_data.iloc[-window:].to_numpy()
    x = np.arange(len(y))

    mask = ~np.isnan(y)
    if mask.sum() < 2:
        return np.nan

    x_valid = x[mask]
    y_valid = y[mask]

    n = len(x_valid)
    sum_x = np.sum(x_valid)
    sum_y = np.sum(y_valid)
    sum_xy = np.sum(x_valid * y_valid)
    sum_x2 = np.sum(x_valid * x_valid)

    denominator = n * sum_x2 - sum_x * sum_x
    if denominator == 0:
        return np.nan

    slope = (n * sum_xy - sum_x * sum_y) / denominator
    return slope


def _calculate_obv_slope(obv: pd.DataFrame, window: int) -> pd.DataFrame:
    """计算OBV斜率。"""
    values = np.ascontiguousarray(obv.astype(float).to_numpy(dtype=np.float64, copy=False))
    if _use_numba(values.shape):
        out = _obv_slope_numba(values, int(window))
        return pd.DataFrame(out, index=obv.index, columns=obv.columns)
    result = pd.DataFrame(np.nan, index=obv.index, columns=obv.columns)
    for col_idx, col in enumerate(obv.columns):
        for i in range(window, len(obv)):
            window_data = obv[col].iloc[i - window : i]
            slope = _linear_slope(window_data, window)
            result.iat[i, col_idx] = slope
    return result


def _calculate_ma(O: pd.DataFrame, window: int) -> pd.DataFrame:
    """计算移动平均。"""
    values = np.ascontiguousarray(O.astype(float).to_numpy(dtype=np.float64, copy=False))
    if _use_numba(values.shape):
        out = _rolling_mean_numba(values, int(window))
        return pd.DataFrame(out, index=O.index, columns=O.columns)
    return O.rolling(window=window, min_periods=1).mean()


def _detect_divergence(
    C: pd.DataFrame,
    obv: pd.DataFrame,
    window: int,
    divergence_type: str
) -> pd.DataFrame:
    """检测OBV背离。"""
    close_values = np.ascontiguousarray(C.astype(float).to_numpy(dtype=np.float64, copy=False))
    obv_values = np.ascontiguousarray(obv.astype(float).to_numpy(dtype=np.float64, copy=False))
    if _use_numba(close_values.shape):
        out = _detect_divergence_numba(close_values, obv_values, int(window), divergence_type == "bearish")
        return pd.DataFrame(out, index=C.index, columns=C.columns)

    rows, cols = close_values.shape

    result = np.zeros((rows, cols), dtype=bool)

    for c in range(cols):
        for r in range(window, rows):
            # 获取窗口内数据
            close_window = close_values[r-window:r+1, c]
            obv_window = obv_values[r-window:r+1, c]

            # 某些股票在该窗口内可能全为空，直接跳过避免 nanargmax/nanargmin 抛错
            if np.isnan(close_window).all() or np.isnan(obv_window).all():
                continue

            # 找到窗口内的极值位置
            if divergence_type == "bearish":  # 顶背离：价格新高，OBV未新高
                price_max_idx = np.nanargmax(close_window)
                obv_max_idx = np.nanargmax(obv_window)

                # 如果价格在当前点创新高，但OBV没有
                if price_max_idx == window and obv_max_idx < window:
                    # 检查OBV是否确实低于前期高点
                    current_obv = obv_window[-1]
                    prev_obv_window = obv_window[:-1]
                    if np.isnan(prev_obv_window).all():
                        continue
                    prev_obv_high = np.nanmax(prev_obv_window)
                    if not np.isnan(current_obv) and current_obv < prev_obv_high * 0.98:  # 允许2%误差
                        result[r, c] = True

            elif divergence_type == "bullish":  # 底背离：价格新低，OBV未新低
                price_min_idx = np.nanargmin(close_window)
                obv_min_idx = np.nanargmin(obv_window)

                # 如果价格在当前点创新低，但OBV没有
                if price_min_idx == window and obv_min_idx < window:
                    # 检查OBV是否确实高于前期低点
                    current_obv = obv_window[-1]
                    prev_obv_window = obv_window[:-1]
                    if np.isnan(prev_obv_window).all():
                        continue
                    prev_obv_low = np.nanmin(prev_obv_window)
                    if not np.isnan(current_obv) and current_obv > prev_obv_low * 1.02:  # 允许2%误差
                        result[r, c] = True

    return pd.DataFrame(result, index=C.index, columns=C.columns)


def build_obv_factor_bundle(
    C: pd.DataFrame,
    V: pd.DataFrame,
) -> dict[str, Any]:
    """构建OBV因子包（非归一化版本）。"""
    index, columns = C.index, C.columns
    debug_timing = _timing_enabled()
    t0 = time.perf_counter() if debug_timing else 0.0
    
    # 一、基础OBV
    obv = _calculate_obv(C, V)
    t1 = time.perf_counter() if debug_timing else 0.0
    
    # 二、OBV趋势类因子
    obv_slope_20 = _calculate_obv_slope(obv, 20)
    obv_slope_60 = _calculate_obv_slope(obv, 60)
    obv_slope_120 = _calculate_obv_slope(obv, 120)
    t2 = time.perf_counter() if debug_timing else 0.0
    
    obv_ma5 = _calculate_ma(obv, 5)
    obv_ma20 = _calculate_ma(obv, 20)
    obv_ma60 = _calculate_ma(obv, 60)
    
    # OBV多头排列：OBV > MA5 > MA20 > MA60
    obv_bullish_arrange = (obv > obv_ma5) & (obv_ma5 > obv_ma20) & (obv_ma20 > obv_ma60)
    
    # OBV相对位置
    obv_position_ratio = obv / obv_ma60
    
    # 三、OBV背离类因子
    obv_bearish_divergence = _detect_divergence(C, obv, 20, "bearish")
    obv_bullish_divergence = _detect_divergence(C, obv, 20, "bullish")
    
    # 四、OBV动量类因子
    obv_mom_20 = obv - obv.shift(20)
    obv_mom_60 = obv - obv.shift(60)
    obv_accel = obv_mom_20 - obv_mom_60.shift(40)
    
    # 五、OBV波动类因子
    obv_values = np.ascontiguousarray(obv.to_numpy(dtype=np.float64, copy=False))
    if _use_numba(obv_values.shape):
        obv_std_20 = pd.DataFrame(_rolling_std_numba(obv_values, 20), index=index, columns=columns)
        obv_mean_20 = pd.DataFrame(_rolling_mean_numba(obv_values, 20), index=index, columns=columns)
        obv_volatility = obv_std_20 / obv_mean_20
    else:
        obv_volatility = obv.rolling(window=20, min_periods=1).std() / obv.rolling(window=20, min_periods=1).mean()
    
    # OBV集中度：OBV在MA20上方的天数占比（20日窗口）
    obv_above_ma20 = (obv > obv_ma20).astype(int)
    if _use_numba(obv_values.shape):
        above_values = np.ascontiguousarray((obv_values > np.ascontiguousarray(obv_ma20.to_numpy(dtype=np.float64, copy=False))))
        obv_concentration = pd.DataFrame(_rolling_sum_bool_numba(above_values, 20), index=index, columns=columns) / 20.0
    else:
        obv_concentration = obv_above_ma20.rolling(window=20, min_periods=1).sum() / 20
    
    # 六、复合因子
    # 价格趋势判断
    price_ma20 = _calculate_ma(C, 20)
    price_trend_up = C > price_ma20
    
    obv_trend_up = obv_slope_20 > 0
    
    # OBV-Price共振
    obv_up = np.ascontiguousarray(obv_trend_up.to_numpy(dtype=bool, copy=False))
    price_up = np.ascontiguousarray(price_trend_up.to_numpy(dtype=bool, copy=False))
    combo_values = np.where(obv_up & price_up, 2, np.where(obv_up ^ price_up, 1, 0))
    obv_price_combo = pd.DataFrame(combo_values, index=index, columns=columns, dtype=int)
    
    # OBV突破：OBV突破60日高点
    if _use_numba(obv_values.shape):
        obv_high_60 = pd.DataFrame(_rolling_max_numba(obv_values, 60), index=index, columns=columns)
    else:
        obv_high_60 = obv.rolling(window=60, min_periods=1).max()
    obv_breakout = obv > obv_high_60.shift(1)
    
    # OBV总分（简单版本）
    obv_total_score = pd.DataFrame(0, index=index, columns=columns, dtype=int)
    obv_total_score = obv_total_score + obv_bullish_divergence.astype(int) * 2
    obv_total_score = obv_total_score + obv_bullish_arrange.astype(int)
    obv_total_score = obv_total_score + (obv_position_ratio > 1.05).astype(int)
    t3 = time.perf_counter() if debug_timing else 0.0
    
    factor_dfs: dict[str, pd.DataFrame] = {
        "obv": obv,
        "obv_slope_20": obv_slope_20,
        "obv_slope_60": obv_slope_60,
        "obv_slope_120": obv_slope_120,
        "obv_bullish_arrange": obv_bullish_arrange,
        "obv_position_ratio": obv_position_ratio,
        "obv_bearish_divergence": obv_bearish_divergence,
        "obv_bullish_divergence": obv_bullish_divergence,
        "obv_mom_20": obv_mom_20,
        "obv_mom_60": obv_mom_60,
        "obv_accel": obv_accel,
        "obv_volatility": obv_volatility,
        "obv_concentration": obv_concentration,
        "obv_price_combo": obv_price_combo,
        "obv_breakout": obv_breakout,
        "obv_total_score": obv_total_score,
    }

    decimals = _fast_round_decimals()
    for name, df in list(factor_dfs.items()):
        try:
            # 保持布尔信号与离散打分语义；仅对浮点结果做快跑精度裁剪。
            if all(pd.api.types.is_bool_dtype(dtype) for dtype in df.dtypes):
                continue
            if all(pd.api.types.is_integer_dtype(dtype) for dtype in df.dtypes):
                continue
            factor_dfs[name] = df.round(decimals)
        except Exception:
            pass
    
    factor_name_map: dict[str, str] = {
        "OBV": "obv",
        "OBV斜率20": "obv_slope_20",
        "OBV斜率60": "obv_slope_60",
        "OBV斜率120": "obv_slope_120",
        "OBV多头排列": "obv_bullish_arrange",
        "OBV相对位置": "obv_position_ratio",
        "OBV顶背离": "obv_bearish_divergence",
        "OBV底背离": "obv_bullish_divergence",
        "OBV动量20": "obv_mom_20",
        "OBV动量60": "obv_mom_60",
        "OBV加速度": "obv_accel",
        "OBV波动率": "obv_volatility",
        "OBV集中度": "obv_concentration",
        "OBV价共振": "obv_price_combo",
        "OBV突破": "obv_breakout",
        "OBV总分": "obv_total_score",
    }
    
    result = {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }
    if debug_timing:
        t4 = time.perf_counter()
        print(
            f"[OBV因子] obv={((t1 - t0) * 1000):.2f}ms trend/div={((t2 - t1) * 1000):.2f}ms "
            f"assemble={((t3 - t2) * 1000):.2f}ms post={((t4 - t3) * 1000):.2f}ms total={((t4 - t0) * 1000):.2f}ms"
        )
    return result


BUNDLE_ID = "obv"
_DEFAULT_LOOKBACK_DAYS = 220

FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    "obv": 20,
    "obv_slope_20": 60,
    "obv_slope_60": 120,
    "obv_slope_120": 200,
    "obv_bullish_arrange": 80,
    "obv_position_ratio": 80,
    "obv_bearish_divergence": 80,
    "obv_bullish_divergence": 80,
    "obv_mom_20": 60,
    "obv_mom_60": 120,
    "obv_accel": 180,
    "obv_volatility": 80,
    "obv_concentration": 80,
    "obv_price_combo": 80,
    "obv_breakout": 120,
    "obv_total_score": 220,
}


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
