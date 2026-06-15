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


if _NUMBA_AVAILABLE:
    @njit(cache=True, fastmath=False, parallel=True)
    def _llv_numba(values: np.ndarray, windows: np.ndarray) -> np.ndarray:
        rows, cols = values.shape
        out = np.empty((rows, cols), dtype=np.float64)
        out[:, :] = np.nan
        for c in prange(cols):
            for r in range(rows):
                w = int(windows[r, c])
                if w < 1:
                    w = 1
                start = r - w + 1
                if start < 0:
                    start = 0
                found = False
                cur_min = 0.0
                for k in range(start, r + 1):
                    v = values[k, c]
                    if not np.isnan(v):
                        if (not found) or (v < cur_min):
                            cur_min = v
                            found = True
                if found:
                    out[r, c] = cur_min
        return out

    @njit(cache=True, fastmath=False, parallel=True)
    def _hhv_numba(values: np.ndarray, windows: np.ndarray) -> np.ndarray:
        rows, cols = values.shape
        out = np.empty((rows, cols), dtype=np.float64)
        out[:, :] = np.nan
        for c in prange(cols):
            for r in range(rows):
                w = int(windows[r, c])
                if w < 1:
                    w = 1
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
    def _sma_tdx_numba(values: np.ndarray, n: int, m: int) -> np.ndarray:
        rows, cols = values.shape
        out = np.empty((rows, cols), dtype=np.float64)
        out[:, :] = np.nan
        n = max(n, 1)
        for c in prange(cols):
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
        return out

def _to_frame(x: Any, index: pd.Index, columns: pd.Index, dtype: Any = None) -> pd.DataFrame:
    if isinstance(x, pd.DataFrame):
        result = x.reindex(index=index, columns=columns)
        return result.astype(dtype) if dtype is not None else result
    if np.isscalar(x):
        return pd.DataFrame(x, index=index, columns=columns, dtype=dtype)
    result = pd.DataFrame(x, index=index, columns=columns)
    return result.astype(dtype) if dtype is not None else result


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


def LLV(X: Any, N: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    legacy = os.getenv("ZXW_FORCE_LEGACY_PYTHON", "0") == "1"
    if np.isscalar(N) and (not legacy):
        window = max(int(N), 1)
        return frame.rolling(window=window, min_periods=1).min()
    windows = _to_window_array(N, frame.index, frame.columns)
    values = np.ascontiguousarray(frame.to_numpy(dtype=np.float64, copy=False))
    windows = np.ascontiguousarray(windows, dtype=np.int64)
    if _use_numba(values.shape):
        out = _llv_numba(values, windows)
    else:
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
    legacy = os.getenv("ZXW_FORCE_LEGACY_PYTHON", "0") == "1"
    if np.isscalar(N) and (not legacy):
        window = max(int(N), 1)
        return frame.rolling(window=window, min_periods=1).max()
    windows = _to_window_array(N, frame.index, frame.columns)
    values = np.ascontiguousarray(frame.to_numpy(dtype=np.float64, copy=False))
    windows = np.ascontiguousarray(windows, dtype=np.int64)
    if _use_numba(values.shape):
        out = _hhv_numba(values, windows)
    else:
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


def SMA_TDX(X: Any, N: int, M: int, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    """通达信 SMA(X,N,M): Y=(M*X+(N-M)*Y')/N。"""
    frame = _to_frame(X, index=index, columns=columns).astype(float)
    n = max(int(N), 1)
    m = int(M)
    values = np.ascontiguousarray(frame.to_numpy(dtype=np.float64, copy=False))
    if _use_numba(values.shape):
        out = _sma_tdx_numba(values, n, m)
    else:
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
    debug_timing = _timing_enabled()
    t0 = time.perf_counter() if debug_timing else 0.0

    llv_l_9 = LLV(L, 9, index, columns)
    hhv_h_9 = HHV(H, 9, index, columns)
    denominator = hhv_h_9 - llv_l_9
    denominator = denominator.replace(0, np.nan)
    rsv = (C - llv_l_9) / denominator * 100
    rsv = rsv.fillna(0.0)

    k_value = SMA_TDX(rsv, 3, 1, index, columns)
    d_value = SMA_TDX(k_value, 3, 1, index, columns)
    j_raw = 3 * k_value - 2 * d_value
    t1 = time.perf_counter() if debug_timing else 0.0

    r_condition = j_raw < 30
    j_oversold_factor = j_raw < 30
    j_overbought_factor = j_raw > 70

    factor_dfs: dict[str, pd.DataFrame] = {
        "rsv": rsv,
        "k_value": k_value,
        "d_value": d_value,
        "j_raw": j_raw,
        "r_condition": r_condition,
        "j_oversold_factor": j_oversold_factor,
        "j_overbought_factor": j_overbought_factor,
    }

    factor_name_map: dict[str, str] = {
        "RSV": "rsv",
        "K值": "k_value",
        "D值": "d_value",
        "J值": "j_raw",
        "KDJ信号": "r_condition",
        "J值超卖因子": "j_oversold_factor",
        "J值超买因子": "j_overbought_factor",
    }

    result = {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }
    if debug_timing:
        t2 = time.perf_counter()
        print(
            f"[KDJ因子] core={((t1 - t0) * 1000):.2f}ms post={((t2 - t1) * 1000):.2f}ms total={((t2 - t0) * 1000):.2f}ms"
        )
    return result


BUNDLE_ID = "kdj"
_DEFAULT_LOOKBACK_DAYS = 90

FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    "rsv": 30,
    "k_value": 45,
    "d_value": 60,
    "j_raw": 60,
    "r_condition": 60,
    "j_oversold_factor": 60,
    "j_overbought_factor": 60,
}


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
