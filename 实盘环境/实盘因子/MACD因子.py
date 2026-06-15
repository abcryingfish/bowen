




# ============================================================
# 文件名称：MACD因子.py
# 创建时间：2026-04-07
# 创建者 ：LimxTeam
# 设计哲学：将 D 类因子独立模块化，避免 notebook 内重复定义和顺序依赖
# 功能描述：提供 MACD 与底背离相关因子的完整计算与映射输出
# 技术特性：DataFrame 矩阵运算、动态窗口、空值安全、可选 s_reverse_k 兜底
#
# ── 函数/方法表 ──────────────────────────────────────────────
# │ 函数名 │ 描述 │
# │──────────────────────────│───────────────────────────────│
# │ build_d_class_factor_bundle() │ 构建 D 类因子与名称映射 │
# │ build_macd_factors() │ 计算 DIF/DEA/MAC │
# │ build_bottom_divergence_factors() │ 计算底背离体系相关因子 │
#
# ── 状态/变量表 ───────────────────────────────────────────────
# │ 变量名 │ 类型 │ 描述 │
# │──────────────────────────│──────────────────│────────────│
# │ factor_dfs │ dict[str, pd.DataFrame] │ 英文因子名到矩阵映射 │
# │ factor_name_map │ dict[str, str] │ 中文名到英文因子名映射 │
#
# ── 更新历史 ──────────────────────────────────────────────────
# │ 日期 │ 作者 │ 描述 │
# │─────────────│──────────│───────────────────────────────│
# │ 2026-04-07 │ LimxTeam │ 初始创建，抽离 D 类因子可复用模块 │
# ============================================================

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
    def _ref_numba(values: np.ndarray, windows: np.ndarray) -> np.ndarray:
        rows, cols = values.shape
        out = np.empty((rows, cols), dtype=np.float64)
        out[:, :] = np.nan
        for c in prange(cols):
            for r in range(rows):
                step = int(windows[r, c])
                src = r - step
                if src >= 0:
                    out[r, c] = values[src, c]
        return out

    @njit(cache=True, fastmath=False, parallel=True)
    def _refx_numba(values: np.ndarray, windows: np.ndarray) -> np.ndarray:
        rows, cols = values.shape
        out = np.empty((rows, cols), dtype=np.float64)
        out[:, :] = np.nan
        for c in prange(cols):
            for r in range(rows):
                step = int(windows[r, c])
                src = r + step
                if src < rows:
                    out[r, c] = values[src, c]
        return out

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
    def _hhvbars_numba(values: np.ndarray, windows: np.ndarray) -> np.ndarray:
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
                best = 0.0
                best_idx = -1
                for k in range(start, r + 1):
                    v = values[k, c]
                    if not np.isnan(v):
                        if (not found) or (v > best):
                            best = v
                            best_idx = k
                            found = True
                if found:
                    out[r, c] = r - best_idx
        return out

    @njit(cache=True, fastmath=False, parallel=True)
    def _llvbars_numba(values: np.ndarray, windows: np.ndarray) -> np.ndarray:
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
                best = 0.0
                best_idx = -1
                for k in range(start, r + 1):
                    v = values[k, c]
                    if not np.isnan(v):
                        if (not found) or (v < best):
                            best = v
                            best_idx = k
                            found = True
                if found:
                    out[r, c] = r - best_idx
        return out

    @njit(cache=True, fastmath=False, parallel=True)
    def _ma_numba(values: np.ndarray, windows: np.ndarray) -> np.ndarray:
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
    def _count_numba(values: np.ndarray, windows: np.ndarray) -> np.ndarray:
        rows, cols = values.shape
        out = np.zeros((rows, cols), dtype=np.int64)
        for c in prange(cols):
            prefix = np.zeros(rows + 1, dtype=np.int64)
            for r in range(rows):
                prefix[r + 1] = prefix[r] + (1 if values[r, c] else 0)
            for r in range(rows):
                w = int(windows[r, c])
                if w < 1:
                    w = 1
                start = r - w + 1
                if start < 0:
                    start = 0
                out[r, c] = prefix[r + 1] - prefix[start]
        return out

    @njit(cache=True, fastmath=False, parallel=True)
    def _every_numba(values: np.ndarray, windows: np.ndarray) -> np.ndarray:
        rows, cols = values.shape
        out = np.zeros((rows, cols), dtype=np.bool_)
        for c in prange(cols):
            false_prefix = np.zeros(rows + 1, dtype=np.int64)
            for r in range(rows):
                false_prefix[r + 1] = false_prefix[r] + (0 if values[r, c] else 1)
            for r in range(rows):
                w = int(windows[r, c])
                if w < 1:
                    w = 1
                start = r - w + 1
                if start < 0:
                    start = 0
                out[r, c] = (false_prefix[r + 1] - false_prefix[start]) == 0
        return out

    @njit(cache=True, fastmath=False, parallel=True)
    def _lowrange_numba(values: np.ndarray) -> np.ndarray:
        rows, cols = values.shape
        out = np.zeros((rows, cols), dtype=np.int64)
        for c in prange(cols):
            stack_idx = np.empty(rows, dtype=np.int64)
            top = -1
            seg_start = 0
            for r in range(rows):
                cur = values[r, c]
                if np.isnan(cur):
                    top = -1
                    seg_start = r + 1
                    continue
                while top >= 0 and values[stack_idx[top], c] > cur:
                    top -= 1
                if top >= 0:
                    out[r, c] = r - stack_idx[top]
                else:
                    out[r, c] = r - seg_start + 1
                top += 1
                stack_idx[top] = r
        return out

    @njit(cache=True, fastmath=False, parallel=True)
    def _lowrange_stack_numba(values: np.ndarray) -> np.ndarray:
        rows, cols = values.shape
        out = np.zeros((rows, cols), dtype=np.int64)
        for c in prange(cols):
            stack_idx = np.empty(rows, dtype=np.int64)
            top = -1
            for r in range(rows):
                cur = values[r, c]
                while top >= 0 and values[stack_idx[top], c] >= cur:
                    top -= 1
                if top >= 0:
                    out[r, c] = r - stack_idx[top] - 1
                else:
                    out[r, c] = r
                top += 1
                stack_idx[top] = r
        return out

    @njit(cache=True, fastmath=False, parallel=True)
    def _toprange_numba(values: np.ndarray) -> np.ndarray:
        rows, cols = values.shape
        out = np.zeros((rows, cols), dtype=np.int64)
        for c in prange(cols):
            stack_idx = np.empty(rows, dtype=np.int64)
            top = -1
            for r in range(rows):
                cur = values[r, c]
                while top >= 0 and values[stack_idx[top], c] <= cur:
                    top -= 1
                if top >= 0:
                    out[r, c] = r - stack_idx[top] - 1
                else:
                    out[r, c] = r
                top += 1
                stack_idx[top] = r
        return out

    @njit(cache=True, fastmath=False, parallel=True)
    def _barslast_numba(values: np.ndarray) -> np.ndarray:
        rows, cols = values.shape
        out = np.zeros((rows, cols), dtype=np.int64)
        for c in prange(cols):
            last_true_idx = -1
            for r in range(rows):
                if values[r, c]:
                    last_true_idx = r
                    out[r, c] = 0
                else:
                    out[r, c] = (r + 1) if last_true_idx == -1 else (r - last_true_idx)
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
    values = np.ascontiguousarray(frame.astype(float).to_numpy(dtype=np.float64, copy=False))
    if np.isscalar(N):
        step = max(int(N), 0)
        out = np.full(values.shape, np.nan, dtype=np.float64)
        if step == 0:
            out[:, :] = values
        elif step < values.shape[0]:
            out[step:, :] = values[:-step, :]
        result = pd.DataFrame(out, index=frame.index, columns=frame.columns)
        if is_bool:
            return result.fillna(0.0).astype(bool)
        return result
    windows = np.ascontiguousarray(_to_window_array(N, frame.index, frame.columns), dtype=np.int64)
    if _use_numba(values.shape):
        out = _ref_numba(values, windows)
    else:
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
    values = np.ascontiguousarray(frame.to_numpy(dtype=np.float64, copy=False))
    if np.isscalar(N):
        step = max(int(N), 0)
        out = np.full(values.shape, np.nan, dtype=np.float64)
        if step == 0:
            out[:, :] = values
        elif step < values.shape[0]:
            out[:-step, :] = values[step:, :]
        return pd.DataFrame(out, index=frame.index, columns=frame.columns)
    windows = np.ascontiguousarray(_to_window_array(N, frame.index, frame.columns), dtype=np.int64)
    if _use_numba(values.shape):
        out = _refx_numba(values, windows)
    else:
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
    windows = np.ascontiguousarray(_to_window_array(N, frame.index, frame.columns), dtype=np.int64)
    values = np.ascontiguousarray(frame.to_numpy(dtype=np.float64, copy=False))
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
    windows = np.ascontiguousarray(_to_window_array(N, frame.index, frame.columns), dtype=np.int64)
    values = np.ascontiguousarray(frame.to_numpy(dtype=np.float64, copy=False))
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
    windows = np.ascontiguousarray(_to_window_array(N, frame.index, frame.columns), dtype=np.int64)
    values = np.ascontiguousarray(frame.to_numpy(dtype=np.float64, copy=False))
    if _use_numba(values.shape):
        out = _hhvbars_numba(values, windows)
    else:
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
    values = np.ascontiguousarray(frame.to_numpy(dtype=np.float64, copy=False))
    if _use_numba(values.shape):
        out = _lowrange_stack_numba(values)
    else:
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
    values = np.ascontiguousarray(frame.to_numpy(dtype=np.float64, copy=False))
    if _use_numba(values.shape):
        out = _toprange_numba(values)
    else:
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
    windows = np.ascontiguousarray(_to_window_array(N, frame.index, frame.columns), dtype=np.int64)
    values = np.ascontiguousarray(frame.to_numpy(dtype=np.float64, copy=False))
    if _use_numba(values.shape):
        out = _llvbars_numba(values, windows)
    else:
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
    values = np.ascontiguousarray(frame.to_numpy(dtype=np.float64, copy=False))
    if _use_numba(values.shape):
        out = _lowrange_numba(values)
    else:
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
    values = np.ascontiguousarray(frame.to_numpy(dtype=np.float64, copy=False))
    windows = np.ascontiguousarray(_to_window_array(N, frame.index, frame.columns), dtype=np.int64)
    if _use_numba(values.shape):
        out = _ma_numba(values, windows)
    else:
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
    values = np.ascontiguousarray(frame.to_numpy(dtype=np.bool_, copy=False))
    windows = np.ascontiguousarray(_to_window_array(N, frame.index, frame.columns), dtype=np.int64)
    if _use_numba(values.shape):
        out = _count_numba(values, windows)
    else:
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
    values = np.ascontiguousarray(frame.to_numpy(dtype=np.bool_, copy=False))
    if _use_numba(values.shape):
        out = _barslast_numba(values)
    else:
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
    windows = np.ascontiguousarray(_to_window_array(N, frame.index, frame.columns), dtype=np.int64)
    values = np.ascontiguousarray(frame.to_numpy(dtype=np.bool_, copy=False))
    if _use_numba(values.shape):
        out = _every_numba(values, windows)
    else:
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
    top_range_h = TOPRANGE(H, index, columns)
    red_bar = (mac > 0) & (mac > MA(mac, 60, index, columns))
    golden_cross = CROSS(dif, dea, index, columns)
    p_mark_arc_bottom = low_range_l >= 35
    p_mark_arc_top = top_range_h >= 35

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

    p_new_high_start = (
        (
            EVERY(p_mark_arc_top, 2, index, columns)
            & (top_range_h > REF(top_range_h + 10, 1, index, columns))
            & ref_llvbars_l_refx_s_reverse_k_minus_2_ge_30_1
        )
        |
        (
            p_mark_arc_top
            & (top_range_h > REF(top_range_h + 20, 1, index, columns))
            & ref_llvbars_l_refx_s_reverse_k_minus_2_ge_30_1
        )
    )
    p_initial_top_divergence = p_new_high_start & (dif < HHV(dif, s_reverse_k, index, columns))
    bars_last_initial_top_divergence = BARSLAST(p_initial_top_divergence, index, columns)
    p_continued_top_divergence = (
        (bars_last_initial_top_divergence <= 34)
        &
        (
            HHV(dif, bars_last_initial_top_divergence, index, columns)
            <
            REF(HHV(dif, s_reverse_k, index, columns), bars_last_initial_top_divergence, index, columns)
        )
    )
    top_divergence_in_mac_total = p_initial_top_divergence | p_continued_top_divergence

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
            IF(golden_cross | red_bar, 2, IF(bottom_divergence | top_divergence_in_mac_total, 1, 0, index, columns), index, columns),
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
        "p_mark_arc_top": p_mark_arc_top,
        "p_new_high_start": p_new_high_start,
        "p_initial_top_divergence": p_initial_top_divergence,
        "bars_last_initial_top_divergence": bars_last_initial_top_divergence,
        "p_continued_top_divergence": p_continued_top_divergence,
        "top_divergence_in_mac_total": top_divergence_in_mac_total,
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
    debug_timing = _timing_enabled()
    t0 = time.perf_counter() if debug_timing else 0.0

    stroke_bundle = build_upper_stroke_reverse_k_bundle(O, H, L, C, index, columns)
    t1 = time.perf_counter() if debug_timing else 0.0
    computed_s_reverse_k = stroke_bundle["upper_stroke_reverse_k"].astype(float)
    if s_reverse_k is None:
        s_reverse_k = computed_s_reverse_k
    else:
        s_reverse_k = _to_frame(s_reverse_k, index=index, columns=columns).astype(float)

    macd_factors = build_macd_factors(C)
    t2 = time.perf_counter() if debug_timing else 0.0
    dif = macd_factors["dif"]
    dea = macd_factors["dea"]
    mac = macd_factors["mac"]

    bottom = build_bottom_divergence_factors(
        L=L, C=C, O=O, H=H, dif=dif, dea=dea, mac=mac, s_reverse_k=s_reverse_k
    )
    t3 = time.perf_counter() if debug_timing else 0.0

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
        "p_mark_arc_top": bottom["p_mark_arc_top"],
        "p_new_high_start": bottom["p_new_high_start"],
        "p_initial_top_divergence": bottom["p_initial_top_divergence"],
        "p_continued_top_divergence": bottom["p_continued_top_divergence"],
        "top_divergence_in_mac_total": bottom["top_divergence_in_mac_total"],
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
        "P标弧顶(MAC总)": "p_mark_arc_top",
        "P弧新高初(MAC总)": "p_new_high_start",
        "P新高初背离(MAC总)": "p_initial_top_divergence",
        "P新高延续背离(MAC总)": "p_continued_top_divergence",
        "MAC总顶背离": "top_divergence_in_mac_total",
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

    result = {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
        "bottom_divergence_factors": bottom,
        "stroke_reverse_k_bundle": stroke_bundle,
    }
    if debug_timing:
        t4 = time.perf_counter()
        print(
            f"[MACD因子] preprocess={((t1 - t0) * 1000):.2f}ms "
            f"core={((t3 - t1) * 1000):.2f}ms post={((t4 - t3) * 1000):.2f}ms total={((t4 - t0) * 1000):.2f}ms"
        )
    return result


BUNDLE_ID = "macd"
_DEFAULT_LOOKBACK_DAYS = 260

FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    "dif": 120,
    "dea": 140,
    "mac": 140,
    "red_bar": 180,
    "golden_cross": 180,
    "p_mark_arc_bottom": 180,
    "p_new_low_start": 220,
    "p_initial_bottom_divergence": 240,
    "p_continued_bottom_divergence": 240,
    "p_mark_arc_top": 180,
    "p_new_high_start": 220,
    "p_initial_top_divergence": 240,
    "p_continued_top_divergence": 240,
    "top_divergence_in_mac_total": 240,
    "bottom_divergence": 240,
    "bottom_divergence_and_red_bar": 240,
    "bottom_divergence_and_golden_cross": 240,
    "golden_cross_and_red_bar": 240,
    "mac_total": 260,
    "ftr": 200,
    "back_cross_d_count": 220,
    "highest_p_since": 220,
    "phl": 220,
    "u_zone": 220,
    "shl": 220,
    "lhl": 220,
    "negative_shape_volume": 90,
    "pure_negative_volume": 90,
    "prior_d_positive_top": 220,
    "back_cross_f_count": 220,
    "negative_top_break": 220,
    "base_lower_stroke_reverse_k_duration": 220,
    "lower_stroke_reverse_k": 220,
    "negative_j_break": 220,
    "upper_stroke_reverse_k": 220,
}


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }

