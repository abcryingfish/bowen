from __future__ import annotations

import hashlib
import os
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

import numpy as np
import pandas as pd

try:
    from factor_debug_log import factor_log
except Exception:  # pragma: no cover
    def factor_log(event: str, **fields: Any) -> None:
        return

try:
    from numba import njit, prange

    _NUMBA_AVAILABLE = True
except Exception:  # pragma: no cover
    _NUMBA_AVAILABLE = False
    njit = None  # type: ignore
    prange = range  # type: ignore

# 对齐通达信/fengwo CYQ：峰 (H+L)/2、minD=0.01、换手%/100、AC=1
# fengwo.COST 实测与 VOL 无关（旧筹码衰减和新增筹码均按换手率；新增为三角分布）
DEFAULT_TURNOVER_BASE_DIR = r"D:\database\stock_financial_statements\market_equity_data"
CHIP_STATE_CACHE_PATH = (
    r"C:\Users\Administrator\Desktop\python_venv\temp_calculated_data\Chip Distribution\latest_state.parquet"
)
CHIP_STATE_ALGORITHM_VERSION = "tdx_fengwo_v1"
CHOUMA_MIN_D = 0.01
CHOUMA_AC = 1.0
CHOUMA_FLAG = 1
CHOUMA_PEAK_MODE = "hlavg"
CHOUMA_USE_VOLUME = False
# fengwo/通达信：新增筹码为三角分布，并按换手率加入
CHOUMA_ADD_SCALES_WITH_TURNOVER = True
CONCENTRATION_NORM_WINDOW = 1200
# 全分位 1~99，与通达信 COST(N) 一致；下游因子仍只导出常用分位
_COST_PERCENTILES = np.arange(1, 100, dtype=np.int64)
# 兼容旧调用参数
ROLLING_WINDOW_DAYS = 100
TURNOVER_MA_WINDOW = 20
CYQ_COEFF = CHOUMA_AC
PRICE_GRID_SIZE = 600
GRID_PADDING_RATIO = 0.05
_CHIP_BUNDLE_CACHE_MAX_SIZE = 2
_CHIP_BUNDLE_CACHE: OrderedDict[tuple[Any, ...], dict[str, dict[str, pd.DataFrame]]] = OrderedDict()
_CHIP_STATE_CACHE_WRITE_LOCK = threading.RLock()


def _chip_state_cache_enabled() -> bool:
    return os.getenv("ZXW_CHIP_STATE_CACHE", "1") != "0"


def _chip_state_cache_explicitly_enabled() -> bool:
    return os.getenv("ZXW_CHIP_STATE_CACHE") == "1"


def _chip_state_cache_min_cols() -> int:
    raw = os.getenv("ZXW_CHIP_STATE_MIN_COLS", "64").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 64


def _chip_state_cache_bootstrap_enabled(n_rows: int, n_cols: int) -> bool:
    raw = os.getenv("ZXW_CHIP_STATE_BOOTSTRAP_MAX_CELLS", "50000").strip()
    try:
        max_cells = int(raw)
    except ValueError:
        max_cells = 0
    return max_cells > 0 and (int(n_rows) * int(n_cols)) <= max_cells


def _chip_state_max_bins() -> int:
    raw = os.getenv("ZXW_CHIP_STATE_MAX_BINS", "500000").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 500000


def _timing_enabled() -> bool:
    return os.getenv("ZXW_FACTOR_DEBUG_TIMING", "0") == "1"


def _chip_bundle_cache_enabled() -> bool:
    return os.getenv("ZXW_CHIP_BUNDLE_CACHE", "1") != "0"


def clear_chip_structure_bundle_cache() -> None:
    _CHIP_BUNDLE_CACHE.clear()


def _update_hash_with_index(h: "hashlib._Hash", index: pd.Index) -> None:
    h.update(str(len(index)).encode("utf-8"))
    if isinstance(index, pd.DatetimeIndex):
        values = index.view("int64")
        h.update(np.ascontiguousarray(values).view(np.uint8))
        return
    for value in index:
        h.update(str(value).encode("utf-8", errors="surrogatepass"))
        h.update(b"\x00")


def _array_digest(arr: np.ndarray) -> bytes:
    data = np.ascontiguousarray(arr)
    h = hashlib.blake2b(digest_size=16)
    h.update(str(data.shape).encode("ascii"))
    h.update(str(data.dtype).encode("ascii"))
    h.update(data.view(np.uint8))
    return h.digest()


def _chip_bundle_cache_key(
    *,
    index: pd.Index,
    columns: pd.Index,
    h_np: np.ndarray,
    l_np: np.ndarray,
    c_np: np.ndarray,
    v_np: np.ndarray,
    t_np: np.ndarray,
    min_d: float,
    ac: float,
) -> tuple[Any, ...]:
    index_hash = hashlib.blake2b(digest_size=16)
    _update_hash_with_index(index_hash, index)
    column_hash = hashlib.blake2b(digest_size=16)
    _update_hash_with_index(column_hash, columns)
    return (
        index_hash.digest(),
        column_hash.digest(),
        tuple(c_np.shape),
        float(min_d),
        float(ac),
        bool(CHOUMA_USE_VOLUME),
        bool(CHOUMA_ADD_SCALES_WITH_TURNOVER),
        _array_digest(h_np),
        _array_digest(l_np),
        _array_digest(c_np),
        _array_digest(v_np),
        _array_digest(t_np),
    )


def _get_cached_chip_bundle(
    key: tuple[Any, ...],
) -> dict[str, dict[str, pd.DataFrame]] | None:
    cached = _CHIP_BUNDLE_CACHE.get(key)
    if cached is None:
        return None
    _CHIP_BUNDLE_CACHE.move_to_end(key)
    return cached


def _store_cached_chip_bundle(
    key: tuple[Any, ...],
    bundle: dict[str, dict[str, pd.DataFrame]],
) -> None:
    _CHIP_BUNDLE_CACHE[key] = bundle
    _CHIP_BUNDLE_CACHE.move_to_end(key)
    max_size = max(1, int(os.getenv("ZXW_CHIP_BUNDLE_CACHE_SIZE", _CHIP_BUNDLE_CACHE_MAX_SIZE)))
    while len(_CHIP_BUNDLE_CACHE) > max_size:
        _CHIP_BUNDLE_CACHE.popitem(last=False)


def _use_numba(n_rows: int, n_cols: int) -> bool:
    return _NUMBA_AVAILABLE


def _parallel_workers() -> int:
    raw = os.getenv("ZXW_CHIP_PARALLEL_WORKERS", "").strip()
    if raw:
        return max(1, int(raw))
    return max(1, min(os.cpu_count() or 4, 8))


def _to_frame(x: Any, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    if isinstance(x, pd.DataFrame):
        return x.reindex(index=index, columns=columns)
    if np.isscalar(x):
        return pd.DataFrame(x, index=index, columns=columns)
    return pd.DataFrame(x, index=index, columns=columns)


def _safe_divide(numer: np.ndarray, denom: np.ndarray) -> np.ndarray:
    out = np.zeros_like(numer, dtype=np.float64)
    mask = np.isfinite(numer) & np.isfinite(denom) & (denom > 0)
    out[mask] = numer[mask] / denom[mask]
    return out


def _score_by_threshold(value: np.ndarray) -> np.ndarray:
    """通达信：集中度越低赋值越小（<=10→1，(10,20]→2，(20,30]→3）。"""
    out = np.zeros_like(value, dtype=np.float64)
    valid = np.isfinite(value)
    out[valid & (value <= 10)] = 1.0
    out[valid & (value > 10) & (value <= 20)] = 2.0
    out[valid & (value > 20) & (value <= 30)] = 3.0
    return out


def _chouma_peak(high: float, low: float, close: float, mode: str = CHOUMA_PEAK_MODE) -> float:
    if mode == "hlc3":
        return (high + low + close) / 3.0
    if mode == "ohlc4":
        return (high + low + close) / 3.0  # open 未传入时等同 hlc3
    return (high + low) / 2.0


def _round_price_py(x: float) -> float:
    return float(np.round(x, 2))


def _expand_chip_grid_py(
    chip: np.ndarray,
    base_low: float,
    n_bins: int,
    day_low: float,
    day_high: float,
    min_d: float,
) -> tuple[np.ndarray, float, int]:
    """逐日扩展价格网格，不使用未来最高/最低价。"""
    if n_bins == 0:
        bl = _round_price_py(day_low)
        bh = _round_price_py(day_high)
        if bh < bl:
            bh, bl = bl, bh
        span = int((bh - bl) / min_d)
        nb = span + 5
        if nb < 1:
            nb = 1
        return np.zeros(nb, dtype=np.float64), bl, nb

    cur_high = base_low + (n_bins - 1) * min_d
    need_low = base_low
    need_high = cur_high
    dl = _round_price_py(day_low)
    dh = _round_price_py(day_high)
    if dl > dh:
        dl, dh = dh, dl
    if dl < need_low:
        need_low = dl
    if dh > need_high:
        need_high = dh

    left_pad = int(np.round((base_low - need_low) / min_d))
    if left_pad < 0:
        left_pad = 0
    new_base = _round_price_py(base_low - left_pad * min_d)
    left_pad = int(np.round((base_low - new_base) / min_d))
    if left_pad < 0:
        left_pad = 0
        new_base = base_low

    span_bins = int(np.round((need_high - new_base) / min_d)) + 5
    new_n = left_pad + n_bins
    if span_bins > new_n:
        new_n = span_bins
    if new_n < 1:
        new_n = 1

    new_chip = np.zeros(new_n, dtype=np.float64)
    new_chip[left_pad : left_pad + n_bins] = chip
    return new_chip, new_base, new_n


def _fill_costs_from_chip_py(
    chip: np.ndarray,
    base_low: float,
    min_d: float,
    n_bins: int,
    targets: np.ndarray,
    out: np.ndarray,
    day_i: int,
) -> None:
    p_count = len(targets)
    sum_of = float(np.sum(chip))
    if sum_of <= 0.0:
        out[:, day_i] = 0.0
        return

    cum = 0.0
    pi = 0
    last_price = 0.0
    for b in range(n_bins):
        mass = chip[b]
        if mass <= 0.0:
            continue
        price = _round_price_py(base_low + b * min_d)
        last_price = price
        cum += mass / sum_of
        while pi < p_count and cum > targets[pi]:
            out[pi, day_i] = price
            pi += 1
    while pi < p_count:
        out[pi, day_i] = last_price
        pi += 1


def _update_chip_one_day_py(
    chip: np.ndarray,
    base_low: float,
    n_bins: int,
    high: float,
    low: float,
    volume: float,
    turnover_dec: float,
    min_d: float,
    ac: float,
    use_volume: bool,
) -> tuple[np.ndarray, float, int]:
    """单日 CYQ 更新：衰减 + 对称三角新增（fengwo hlavg）。"""
    h = float(high)
    l = float(low)
    if h < l:
        h, l = l, h

    chip, base_low, n_bins = _expand_chip_grid_py(chip, base_low, n_bins, l, h, min_d)

    tr = float(turnover_dec)
    if tr < 0.0:
        tr = 0.0
    if tr > 1.0:
        tr = 1.0

    decay = 1.0 - tr * ac
    chip = chip * decay

    length = int((h - l) / min_d)
    if length <= 0:
        return chip, base_low, n_bins

    avg = (h + l) / 2.0
    denom = h - l
    h_coef = 2.0 / denom
    add_scale = (tr * ac) if CHOUMA_ADD_SCALES_WITH_TURNOVER else 1.0
    if use_volume and not np.isfinite(volume):
        return chip, base_low, n_bins
    vol_t = float(volume) if use_volume else 1.0

    for ii in range(length):
        price = _round_price_py(l + ii * min_d)
        bidx = int(np.round((price - base_low) / min_d))
        if bidx < 0 or bidx >= n_bins:
            continue
        x1 = price
        x2 = price + min_d
        if price < avg:
            y1 = h_coef / (avg - l) * (x1 - l)
            y2 = h_coef / (avg - l) * (x2 - l)
            s = min_d * (y1 + y2) / 2.0 * vol_t
        else:
            y1 = h_coef / (h - avg) * (h - x1)
            y2 = h_coef / (h - avg) * (h - x2)
            s = min_d * (y1 + y2) / 2.0 * vol_t
        chip[bidx] += s * add_scale
    return chip, base_low, n_bins


def _compute_chouma_cost_series_python(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    turnover_pct: np.ndarray,
    percentiles: np.ndarray,
    min_d: float = CHOUMA_MIN_D,
    ac: float = CHOUMA_AC,
    use_volume: bool = CHOUMA_USE_VOLUME,
) -> np.ndarray:
    """
    全历史逐日递推（fengwo/通达信对齐）；有效 OHLC 日从第 0 根 K 线开始。
    turnover_pct: 百分数刻度（如 5.2 表示 5.2%），内部 /100。
    NaN 换手日：chip 不衰减、不新增，COST 沿用前一日。
    """
    del close
    n = len(high)
    p_count = len(percentiles)
    out = np.zeros((p_count, n), dtype=np.float64)
    targets = percentiles / 100.0
    if n == 0:
        return out

    chip = np.zeros(0, dtype=np.float64)
    base_low = 0.0
    n_bins = 0

    for i in range(n):
        tr_raw = turnover_pct[i]
        if not np.isfinite(tr_raw):
            if i > 0:
                out[:, i] = out[:, i - 1]
            continue

        h = high[i]
        l = low[i]
        if not (np.isfinite(h) and np.isfinite(l)):
            if i > 0:
                out[:, i] = out[:, i - 1]
            continue

        tr_dec = float(tr_raw) / 100.0
        v = volume[i]
        chip, base_low, n_bins = _update_chip_one_day_py(
            chip, base_low, n_bins, h, l, v, tr_dec, min_d, ac, use_volume
        )
        _fill_costs_from_chip_py(chip, base_low, min_d, n_bins, targets, out, i)
    return out


if _NUMBA_AVAILABLE:

    @njit(cache=True, fastmath=False)
    def _round_price(x: float) -> float:
        return float(np.round(x, 2))

    @njit(cache=True, fastmath=False)
    def _expand_chip_grid(
        chip: np.ndarray,
        base_low: float,
        n_bins: int,
        day_low: float,
        day_high: float,
        min_d: float,
    ) -> tuple:
        if n_bins == 0:
            bl = _round_price(day_low)
            bh = _round_price(day_high)
            if bh < bl:
                bh, bl = bl, bh
            span = int((bh - bl) / min_d)
            nb = span + 5
            if nb < 1:
                nb = 1
            return np.zeros(nb, dtype=np.float64), bl, nb

        cur_high = base_low + (n_bins - 1) * min_d
        need_low = base_low
        need_high = cur_high
        dl = _round_price(day_low)
        dh = _round_price(day_high)
        if dl > dh:
            dl, dh = dh, dl
        if dl < need_low:
            need_low = dl
        if dh > need_high:
            need_high = dh

        left_pad = int(np.round((base_low - need_low) / min_d))
        if left_pad < 0:
            left_pad = 0
        new_base = _round_price(base_low - left_pad * min_d)
        left_pad = int(np.round((base_low - new_base) / min_d))
        if left_pad < 0:
            left_pad = 0
            new_base = base_low

        span_bins = int(np.round((need_high - new_base) / min_d)) + 5
        new_n = left_pad + n_bins
        if span_bins > new_n:
            new_n = span_bins
        if new_n < 1:
            new_n = 1

        new_chip = np.zeros(new_n, dtype=np.float64)
        for b in range(n_bins):
            new_chip[left_pad + b] = chip[b]
        return new_chip, new_base, new_n

    @njit(cache=True, fastmath=False)
    def _fill_costs_from_chip(
        chip: np.ndarray,
        base_low: float,
        min_d: float,
        n_bins: int,
        targets: np.ndarray,
        out: np.ndarray,
        day_i: int,
    ) -> None:
        p_count = len(targets)
        sum_of = 0.0
        for b in range(n_bins):
            sum_of += chip[b]
        if sum_of <= 0.0:
            for p in range(p_count):
                out[p, day_i] = 0.0
            return

        cum = 0.0
        pi = 0
        last_price = 0.0
        for b in range(n_bins):
            mass = chip[b]
            if mass <= 0.0:
                continue
            price = _round_price(base_low + b * min_d)
            last_price = price
            cum += mass / sum_of
            while pi < p_count and cum > targets[pi]:
                out[pi, day_i] = price
                pi += 1
        while pi < p_count:
            out[pi, day_i] = last_price
            pi += 1

    @njit(cache=True, fastmath=False)
    def _update_chip_one_day(
        chip: np.ndarray,
        base_low: float,
        n_bins: int,
        high: float,
        low: float,
        volume: float,
        turnover_dec: float,
        min_d: float,
        ac: float,
        use_volume: bool,
        add_scales_with_turnover: bool,
    ) -> tuple:
        h = high
        l = low
        if h < l:
            h, l = l, h

        chip, base_low, n_bins = _expand_chip_grid(chip, base_low, n_bins, l, h, min_d)

        tr = turnover_dec
        if tr < 0.0:
            tr = 0.0
        if tr > 1.0:
            tr = 1.0

        decay = 1.0 - tr * ac
        for b in range(n_bins):
            if chip[b] != 0.0:
                chip[b] *= decay

        length = int((h - l) / min_d)
        if length <= 0:
            return chip, base_low, n_bins

        avg = (h + l) / 2.0
        denom = h - l
        h_coef = 2.0 / denom
        add_scale = (tr * ac) if add_scales_with_turnover else 1.0
        if use_volume and not np.isfinite(volume):
            return chip, base_low, n_bins
        vol_t = volume if use_volume else 1.0

        for ii in range(length):
            price = _round_price(l + ii * min_d)
            bidx = int(np.round((price - base_low) / min_d))
            if bidx < 0 or bidx >= n_bins:
                continue
            x1 = price
            x2 = price + min_d
            if price < avg:
                y1 = h_coef / (avg - l) * (x1 - l)
                y2 = h_coef / (avg - l) * (x2 - l)
                s = min_d * (y1 + y2) / 2.0 * vol_t
            else:
                y1 = h_coef / (h - avg) * (h - x1)
                y2 = h_coef / (h - avg) * (h - x2)
                s = min_d * (y1 + y2) / 2.0 * vol_t
            chip[bidx] += s * add_scale
        return chip, base_low, n_bins

    @njit(cache=True, fastmath=False)
    def _compute_chouma_cost_series_numba_single(
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        turnover_pct: np.ndarray,
        percentiles: np.ndarray,
        min_d: float,
        ac: float,
        use_volume: bool,
        add_scales_with_turnover: bool,
    ) -> np.ndarray:
        n = len(high)
        p_count = len(percentiles)
        out = np.zeros((p_count, n), dtype=np.float64)
        targets = percentiles / 100.0

        chip = np.zeros(0, dtype=np.float64)
        base_low = 0.0
        n_bins = 0

        for i in range(n):
            tr_raw = turnover_pct[i]
            if not np.isfinite(tr_raw):
                if i > 0:
                    for p in range(p_count):
                        out[p, i] = out[p, i - 1]
                continue

            h = high[i]
            l = low[i]
            if not (np.isfinite(h) and np.isfinite(l)):
                if i > 0:
                    for p in range(p_count):
                        out[p, i] = out[p, i - 1]
                continue

            tr_dec = tr_raw / 100.0
            chip, base_low, n_bins = _update_chip_one_day(
                chip,
                base_low,
                n_bins,
                h,
                l,
                volume[i],
                tr_dec,
                min_d,
                ac,
                use_volume,
                add_scales_with_turnover,
            )
            _fill_costs_from_chip(chip, base_low, min_d, n_bins, targets, out, i)
        return out

    @njit(cache=True, fastmath=False, parallel=True)
    def _compute_chouma_cost_matrix_numba(
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        turnover: np.ndarray,
        percentiles: np.ndarray,
        min_d: float,
        ac: float,
        use_volume: bool,
        add_scales_with_turnover: bool,
    ) -> np.ndarray:
        n_rows, n_cols = high.shape
        p_count = len(percentiles)
        out = np.zeros((p_count, n_rows, n_cols), dtype=np.float64)
        for ci in prange(n_cols):
            col_out = _compute_chouma_cost_series_numba_single(
                high[:, ci],
                low[:, ci],
                close[:, ci],
                volume[:, ci],
                turnover[:, ci],
                percentiles,
                min_d,
                ac,
                use_volume,
                add_scales_with_turnover,
            )
            for p in range(p_count):
                out[p, :, ci] = col_out[p, :]
        return out

    @njit(cache=True, fastmath=False)
    def _compute_chouma_cost_series_numba_with_state(
        high: np.ndarray,
        low: np.ndarray,
        volume: np.ndarray,
        turnover_pct: np.ndarray,
        percentiles: np.ndarray,
        min_d: float,
        ac: float,
        use_volume: bool,
        add_scales_with_turnover: bool,
        init_chip: np.ndarray,
        init_base_low: float,
        init_n_bins: int,
        init_cum_high: float,
        init_cum_low: float,
    ) -> tuple:
        n = len(high)
        p_count = len(percentiles)
        out = np.zeros((p_count, n), dtype=np.float64)
        abs_conc = np.zeros(n, dtype=np.float64)
        targets = percentiles / 100.0

        chip = init_chip.copy()
        base_low = init_base_low
        n_bins = init_n_bins
        if n_bins != len(chip):
            n_bins = len(chip)
        cum_high = init_cum_high
        cum_low = init_cum_low
        prev_cost = np.zeros(p_count, dtype=np.float64)

        for i in range(n):
            tr_raw = turnover_pct[i]
            h = high[i]
            l = low[i]
            valid_bar = np.isfinite(tr_raw) and np.isfinite(h) and np.isfinite(l)
            if valid_bar:
                if not np.isfinite(cum_high):
                    cum_high = h
                elif h > cum_high:
                    cum_high = h
                if not np.isfinite(cum_low):
                    cum_low = l
                elif l < cum_low:
                    cum_low = l

                chip, base_low, n_bins = _update_chip_one_day(
                    chip,
                    base_low,
                    n_bins,
                    h,
                    l,
                    volume[i],
                    tr_raw / 100.0,
                    min_d,
                    ac,
                    use_volume,
                    add_scales_with_turnover,
                )
                _fill_costs_from_chip(chip, base_low, min_d, n_bins, targets, out, i)
                for p in range(p_count):
                    prev_cost[p] = out[p, i]
            else:
                if i > 0:
                    for p in range(p_count):
                        out[p, i] = out[p, i - 1]
                        prev_cost[p] = out[p, i]
                else:
                    for p in range(p_count):
                        out[p, i] = prev_cost[p]

            denom = cum_high - cum_low
            if denom > 0.0 and np.isfinite(denom):
                abs_conc[i] = ((out[94, i] - out[4, i]) * 100.0) / denom
            else:
                abs_conc[i] = 0.0

        return out, chip, base_low, n_bins, cum_high, cum_low, abs_conc

    @njit(cache=True, fastmath=False)
    def _rolling_minmax_norm_numba(abs_conc: np.ndarray, window: int) -> np.ndarray:
        rows, cols = abs_conc.shape
        out = np.zeros((rows, cols), dtype=np.float64)
        for ci in range(cols):
            for r in range(rows):
                start = r - window + 1
                if start < 0:
                    start = 0
                cur_min = abs_conc[start, ci]
                cur_max = abs_conc[start, ci]
                for k in range(start + 1, r + 1):
                    v = abs_conc[k, ci]
                    if v < cur_min:
                        cur_min = v
                    if v > cur_max:
                        cur_max = v
                denom = cur_max - cur_min
                if denom > 0.0 and np.isfinite(denom):
                    out[r, ci] = (abs_conc[r, ci] - cur_min) / denom * 100.0
        return out


def _compute_chouma_cost_series(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    turnover_pct: np.ndarray,
    percentiles: np.ndarray,
    min_d: float = CHOUMA_MIN_D,
    ac: float = CHOUMA_AC,
    use_volume: bool = CHOUMA_USE_VOLUME,
    add_scales_with_turnover: bool = CHOUMA_ADD_SCALES_WITH_TURNOVER,
) -> np.ndarray:
    if _NUMBA_AVAILABLE:
        return _compute_chouma_cost_series_numba_single(
            high,
            low,
            close,
            volume,
            turnover_pct,
            percentiles,
            min_d,
            ac,
            use_volume,
            add_scales_with_turnover,
        )
    return _compute_chouma_cost_series_python(
        high,
        low,
        close,
        volume,
        turnover_pct,
        percentiles,
        min_d=min_d,
        ac=ac,
        use_volume=use_volume,
    )


def _compute_chouma_cost_series_worker(args: tuple) -> tuple[int, np.ndarray]:
    ci, high, low, close, volume, turnover_pct, percentiles, min_d, ac, use_volume = args
    costs = _compute_chouma_cost_series_python(
        high, low, close, volume, turnover_pct, percentiles, min_d=min_d, ac=ac, use_volume=use_volume
    )
    return ci, costs


def _compute_chouma_cost_series_with_state(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    turnover_pct: np.ndarray,
    percentiles: np.ndarray,
    dates: pd.Index,
    *,
    state: dict[str, Any] | None,
    min_d: float,
    ac: float,
    use_volume: bool,
) -> tuple[np.ndarray, dict[str, Any], np.ndarray]:
    del close
    n = len(high)
    p_count = len(percentiles)
    if state is None:
        init_chip = np.zeros(0, dtype=np.float64)
        init_base_low = 0.0
        init_n_bins = 0
        init_cum_high = np.nan
        init_cum_low = np.nan
        abs_tail = np.zeros(0, dtype=np.float64)
    else:
        init_chip = np.asarray(state.get("chip", np.zeros(0)), dtype=np.float64).copy()
        init_base_low = float(state.get("base_low", 0.0))
        init_n_bins = int(state.get("n_bins", len(init_chip)))
        init_cum_high = float(state.get("cum_high", np.nan))
        init_cum_low = float(state.get("cum_low", np.nan))
        abs_tail = np.asarray(state.get("abs_conc_tail", np.zeros(0)), dtype=np.float64).copy()

    if _NUMBA_AVAILABLE:
        out, chip, base_low, n_bins, cum_high, cum_low, abs_conc = _compute_chouma_cost_series_numba_with_state(
            np.ascontiguousarray(high, dtype=np.float64),
            np.ascontiguousarray(low, dtype=np.float64),
            np.ascontiguousarray(volume, dtype=np.float64),
            np.ascontiguousarray(turnover_pct, dtype=np.float64),
            np.ascontiguousarray(percentiles, dtype=np.int64),
            min_d,
            ac,
            use_volume,
            CHOUMA_ADD_SCALES_WITH_TURNOVER,
            init_chip,
            init_base_low,
            init_n_bins,
            init_cum_high,
            init_cum_low,
        )
        if n > 0:
            tail_joined = np.concatenate([abs_tail, abs_conc])
            abs_tail = tail_joined[-(CONCENTRATION_NORM_WINDOW - 1) :]
            last_dt = pd.Timestamp(dates[-1]).floor("D")
        else:
            last_dt = pd.Timestamp(state["last_dt"]).floor("D") if state else pd.NaT
        new_state = {
            "last_dt": last_dt,
            "base_low": float(base_low),
            "n_bins": int(n_bins),
            "chip": np.asarray(chip, dtype=np.float64),
            "cum_high": float(cum_high),
            "cum_low": float(cum_low),
            "abs_conc_tail": abs_tail,
            "min_d": float(min_d),
            "ac": float(ac),
            "algorithm_version": CHIP_STATE_ALGORITHM_VERSION,
        }
        return out, new_state, abs_conc

    out = np.zeros((p_count, n), dtype=np.float64)
    targets = percentiles / 100.0
    chip = init_chip.copy()
    base_low = init_base_low
    n_bins = init_n_bins
    if n_bins != len(chip):
        n_bins = len(chip)
    cum_high = init_cum_high
    cum_low = init_cum_low
    prev_cost = np.zeros(p_count, dtype=np.float64)

    abs_conc = np.zeros(n, dtype=np.float64)
    for i in range(n):
        tr_raw = turnover_pct[i]
        h = high[i]
        l = low[i]
        valid_bar = np.isfinite(tr_raw) and np.isfinite(h) and np.isfinite(l)
        if valid_bar:
            if not np.isfinite(cum_high):
                cum_high = float(h)
            else:
                cum_high = max(cum_high, float(h))
            if not np.isfinite(cum_low):
                cum_low = float(l)
            else:
                cum_low = min(cum_low, float(l))
            chip, base_low, n_bins = _update_chip_one_day_py(
                chip,
                base_low,
                n_bins,
                h,
                l,
                volume[i],
                float(tr_raw) / 100.0,
                min_d,
                ac,
                use_volume,
            )
            _fill_costs_from_chip_py(chip, base_low, min_d, n_bins, targets, out, i)
            prev_cost = out[:, i].copy()
        else:
            if i > 0:
                out[:, i] = out[:, i - 1]
                prev_cost = out[:, i].copy()
            else:
                out[:, i] = prev_cost

        denom = cum_high - cum_low if np.isfinite(cum_high) and np.isfinite(cum_low) else np.nan
        if denom > 0 and np.isfinite(denom):
            c5 = out[4, i]
            c95 = out[94, i]
            abs_conc[i] = ((c95 - c5) * 100.0) / denom
        else:
            abs_conc[i] = 0.0

    if n > 0:
        tail_joined = np.concatenate([abs_tail, abs_conc])
        abs_tail = tail_joined[-(CONCENTRATION_NORM_WINDOW - 1) :]
        last_dt = pd.Timestamp(dates[-1]).floor("D")
    else:
        last_dt = pd.Timestamp(state["last_dt"]).floor("D") if state else pd.NaT
    new_state = {
        "last_dt": last_dt,
        "base_low": float(base_low),
        "n_bins": int(n_bins),
        "chip": chip,
        "cum_high": float(cum_high),
        "cum_low": float(cum_low),
        "abs_conc_tail": abs_tail,
        "min_d": float(min_d),
        "ac": float(ac),
        "algorithm_version": CHIP_STATE_ALGORITHM_VERSION,
    }
    return out, new_state, abs_conc


def _costs_array_to_matrix(col_costs: np.ndarray, n_rows: int, ci: int, costs_np: np.ndarray) -> None:
    costs_np[:, :, ci] = col_costs


def _cost_slice(costs_np: np.ndarray, percentile: int) -> np.ndarray:
    """COST(N) 对应 _COST_PERCENTILES 中的 N 分位，保留 numpy 热路径。"""
    idx = int(percentile) - 1
    if idx < 0 or idx >= costs_np.shape[0]:
        raise KeyError(f"COST percentile out of range: {percentile}")
    return costs_np[idx]


def _encode_float_array(arr: np.ndarray) -> bytes:
    return np.ascontiguousarray(arr, dtype=np.float64).tobytes()


def _decode_float_array(raw: Any) -> np.ndarray:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return np.zeros(0, dtype=np.float64)
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    return np.frombuffer(raw, dtype=np.float64).copy()


def _load_chip_state_cache(path: str | None = None) -> dict[str, dict[str, Any]]:
    if path is None:
        path = CHIP_STATE_CACHE_PATH
    if not path or not os.path.exists(path):
        return {}
    try:
        with _CHIP_STATE_CACHE_WRITE_LOCK:
            df = pd.read_parquet(path)
    except Exception:
        return {}
    required = {
        "htsc_code",
        "last_dt",
        "base_low",
        "n_bins",
        "chip_bytes",
        "cum_high",
        "cum_low",
        "abs_conc_tail_bytes",
        "min_d",
        "ac",
        "algorithm_version",
    }
    if not required.issubset(set(df.columns)):
        return {}
    states: dict[str, dict[str, Any]] = {}
    for _, row in df.iterrows():
        code = str(row["htsc_code"])
        try:
            states[code] = {
                "htsc_code": code,
                "last_dt": pd.Timestamp(row["last_dt"]).floor("D"),
                "base_low": float(row["base_low"]),
                "n_bins": int(row["n_bins"]),
                "chip": _decode_float_array(row["chip_bytes"]),
                "cum_high": float(row["cum_high"]),
                "cum_low": float(row["cum_low"]),
                "abs_conc_tail": _decode_float_array(row["abs_conc_tail_bytes"]),
                "min_d": float(row["min_d"]),
                "ac": float(row["ac"]),
                "algorithm_version": str(row["algorithm_version"]),
            }
        except Exception:
            continue
    return states


def _state_params_match(state: dict[str, Any], min_d: float, ac: float) -> bool:
    return (
        state.get("algorithm_version") == CHIP_STATE_ALGORITHM_VERSION
        and np.isclose(float(state.get("min_d", np.nan)), float(min_d))
        and np.isclose(float(state.get("ac", np.nan)), float(ac))
    )


def _state_usable_for_incremental(state: dict[str, Any], min_d: float, ac: float) -> bool:
    if not _state_params_match(state, min_d, ac):
        return False
    try:
        n_bins = int(state.get("n_bins", 0))
    except Exception:
        return False
    return 0 < n_bins <= _chip_state_max_bins()


def _save_chip_state_cache(states: dict[str, dict[str, Any]], path: str | None = None) -> None:
    if path is None:
        path = CHIP_STATE_CACHE_PATH
    if not states:
        return
    cache_dir = os.path.dirname(path)
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
    tmp_name = f"latest_state.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp.parquet"
    tmp_path = os.path.join(cache_dir, tmp_name) if cache_dir else f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        with _CHIP_STATE_CACHE_WRITE_LOCK:
            merged_states = _load_chip_state_cache(path)
            merged_states.update(states)

            rows: list[dict[str, Any]] = []
            updated_at = pd.Timestamp.now()
            for code, state in merged_states.items():
                chip = np.asarray(state.get("chip", np.zeros(0)), dtype=np.float64)
                abs_tail = np.asarray(state.get("abs_conc_tail", np.zeros(0)), dtype=np.float64)
                rows.append(
                    {
                        "htsc_code": str(code),
                        "last_dt": pd.Timestamp(state["last_dt"]).floor("D"),
                        "base_low": float(state.get("base_low", 0.0)),
                        "n_bins": int(state.get("n_bins", len(chip))),
                        "chip_bytes": _encode_float_array(chip),
                        "cum_high": float(state.get("cum_high", np.nan)),
                        "cum_low": float(state.get("cum_low", np.nan)),
                        "abs_conc_tail_bytes": _encode_float_array(abs_tail[-(CONCENTRATION_NORM_WINDOW - 1) :]),
                        "min_d": float(state.get("min_d", CHOUMA_MIN_D)),
                        "ac": float(state.get("ac", CHOUMA_AC)),
                        "algorithm_version": CHIP_STATE_ALGORITHM_VERSION,
                        "updated_at": updated_at,
                    }
                )
            df = pd.DataFrame(rows)
            df.to_parquet(tmp_path, index=False)
            last_exc: OSError | None = None
            for attempt in range(20):
                try:
                    os.replace(tmp_path, path)
                    last_exc = None
                    break
                except OSError as exc:
                    last_exc = exc
                    time.sleep(0.1 * (attempt + 1))
            if last_exc is not None:
                raise last_exc
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def load_turnover_wide(
    index: pd.Index,
    columns: pd.Index,
    base_dir: str = DEFAULT_TURNOVER_BASE_DIR,
) -> pd.DataFrame:
    """从 market_equity_data 分区 parquet 读取换手率宽表（百分数刻度）。"""
    import duckdb

    if len(index) == 0 or len(columns) == 0:
        return pd.DataFrame(index=index, columns=columns, dtype=np.float64)

    con = duckdb.connect()
    try:
        codes = [str(c).strip().upper() for c in columns]
        start_dt = pd.Timestamp(index.min()).floor("D")
        end_dt = pd.Timestamp(index.max()).floor("D")
        pattern = os.path.join(base_dir, "year=*/month=*/merged.parquet").replace("\\", "/")
        codes_sql = ", ".join(f"'{c}'" for c in codes)
        query = f"""
        SELECT
            CAST(time AS TIMESTAMP) AS time,
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            CAST(turnover_rate AS DOUBLE) AS turnover_rate
        FROM read_parquet('{pattern}', hive_partitioning=1)
        WHERE htsc_code IN ({codes_sql})
          AND CAST(time AS DATE) >= DATE '{start_dt.date()}'
          AND CAST(time AS DATE) <= DATE '{end_dt.date()}'
        """
        df = con.execute(query).df()
    finally:
        con.close()

    if df.empty:
        return pd.DataFrame(0.0, index=index, columns=columns, dtype=np.float64)

    df["time"] = pd.to_datetime(df["time"], errors="coerce").dt.floor("D")
    df["htsc_code"] = df["htsc_code"].astype(str).str.strip().str.upper()
    wide = (
        df.pivot_table(index="time", columns="htsc_code", values="turnover_rate", aggfunc="last")
        .reindex(index=index)
        .reindex(columns=codes)
    )
    wide.columns = columns
    return wide.astype(float).fillna(0.0)


def _tdx_relative_concentration(abs_conc: np.ndarray) -> np.ndarray:
    if _NUMBA_AVAILABLE:
        return _rolling_minmax_norm_numba(
            np.ascontiguousarray(abs_conc, dtype=np.float64),
            CONCENTRATION_NORM_WINDOW,
        )
    out = np.zeros_like(abs_conc, dtype=np.float64)
    for ci in range(abs_conc.shape[1]):
        s = pd.Series(abs_conc[:, ci])
        mn = s.rolling(CONCENTRATION_NORM_WINDOW, min_periods=1).min().to_numpy(dtype=np.float64)
        mx = s.rolling(CONCENTRATION_NORM_WINDOW, min_periods=1).max().to_numpy(dtype=np.float64)
        out[:, ci] = _safe_divide(abs_conc[:, ci] - mn, mx - mn) * 100.0
    return out


def _tdx_relative_concentration_with_tail(abs_conc: np.ndarray, tails: list[np.ndarray]) -> np.ndarray:
    out = np.zeros_like(abs_conc, dtype=np.float64)
    for ci in range(abs_conc.shape[1]):
        tail = np.asarray(tails[ci], dtype=np.float64) if ci < len(tails) else np.zeros(0, dtype=np.float64)
        joined = np.concatenate([tail, abs_conc[:, ci]])
        if joined.size == 0:
            continue
        s = pd.Series(joined)
        mn = s.rolling(CONCENTRATION_NORM_WINDOW, min_periods=1).min().to_numpy(dtype=np.float64)
        mx = s.rolling(CONCENTRATION_NORM_WINDOW, min_periods=1).max().to_numpy(dtype=np.float64)
        rel = _safe_divide(joined - mn, mx - mn) * 100.0
        out[:, ci] = rel[-abs_conc.shape[0] :]
    return out


def _align_tail_matrix(tail_values: np.ndarray, n_rows: int, start_row: int, n_cols: int) -> np.ndarray:
    out = np.full((n_rows, n_cols), np.nan, dtype=np.float64)
    if tail_values.size:
        out[start_row:, :] = tail_values
    return out


def build_chip_structure_factor_bundle(
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    V: pd.DataFrame,
    T: pd.DataFrame | None = None,
    *,
    turnover_base_dir: str = DEFAULT_TURNOVER_BASE_DIR,
    window_days: int = ROLLING_WINDOW_DAYS,
    grid_size: int = PRICE_GRID_SIZE,
    history_decay: float = 0.995,
    turnover_ma_window: int = TURNOVER_MA_WINDOW,
    min_d: float = CHOUMA_MIN_D,
    ac: float = CHOUMA_AC,
    parallel: bool | None = None,
) -> dict[str, dict[str, pd.DataFrame]]:
    """
    CYQ（fengwo/通达信对齐：对称三角峰 (H+L)/2，新增乘换手，旧筹码衰减乘换手）+ 集中总/筹码峰。
    T: 换手率宽表，百分数刻度；缺失值在加载层 fillna(0)，NaN 日 chip 不衰减不新增。
    """
    debug_timing = _timing_enabled()
    t0 = time.perf_counter()

    index, columns = C.index, C.columns
    H = _to_frame(H, index=index, columns=columns).astype(float)
    L = _to_frame(L, index=index, columns=columns).astype(float)
    C = _to_frame(C, index=index, columns=columns).astype(float)
    V = _to_frame(V, index=index, columns=columns).astype(float)

    if T is None:
        turnover_wide = load_turnover_wide(index, columns, base_dir=turnover_base_dir)
    else:
        turnover_wide = _to_frame(T, index=index, columns=columns).astype(float).fillna(0.0)

    h_np = np.ascontiguousarray(H.to_numpy(dtype=np.float64))
    l_np = np.ascontiguousarray(L.to_numpy(dtype=np.float64))
    c_np = np.ascontiguousarray(C.to_numpy(dtype=np.float64))
    v_np = np.ascontiguousarray(V.to_numpy(dtype=np.float64))
    t_np = np.ascontiguousarray(turnover_wide.to_numpy(dtype=np.float64))
    n_rows, n_cols = c_np.shape
    factor_log(
        "chip.start",
        rows=int(n_rows),
        cols=int(n_cols),
        start=str(pd.Timestamp(index.min()).date()) if len(index) else None,
        end=str(pd.Timestamp(index.max()).date()) if len(index) else None,
        state_cache_enabled=_chip_state_cache_enabled(),
        bundle_cache_enabled=_chip_bundle_cache_enabled(),
        numba_available=_NUMBA_AVAILABLE,
        min_d=float(min_d),
        ac=float(ac),
    )

    cache_key = None
    if _chip_bundle_cache_enabled():
        cache_key = _chip_bundle_cache_key(
            index=index,
            columns=columns,
            h_np=h_np,
            l_np=l_np,
            c_np=c_np,
            v_np=v_np,
            t_np=t_np,
            min_d=min_d,
            ac=ac,
        )
        cached = _get_cached_chip_bundle(cache_key)
        if cached is not None:
            factor_log("chip.bundle_cache_hit", rows=int(n_rows), cols=int(n_cols))
            if debug_timing:
                print("[筹码结构因子] bundle_cache=hit")
            return cached

    p_count = len(_COST_PERCENTILES)
    costs_np = np.full((p_count, n_rows, n_cols), np.nan, dtype=np.float64)
    abs_conc_override: np.ndarray | None = None
    rel_conc_tail_inputs: list[np.ndarray] | None = None
    rel_conc_override: np.ndarray | None = None
    state_cache_enabled = _chip_state_cache_enabled() and (
        n_cols >= _chip_state_cache_min_cols() or _chip_state_cache_explicitly_enabled()
    )
    state_cache = _load_chip_state_cache() if state_cache_enabled else {}
    new_states: dict[str, dict[str, Any]] = {}
    input_dates = pd.DatetimeIndex(index).floor("D") if n_rows > 0 else pd.DatetimeIndex([])
    state_cache_skip_reason = ""
    state_cache_checked_cols = 0

    state_start_rows: list[int] | None = None
    if state_cache_enabled and n_rows > 0 and n_cols > 0:
        state_start_rows = []
        for col in columns:
            state_cache_checked_cols += 1
            st = state_cache.get(str(col))
            if st is None or not _state_usable_for_incremental(st, min_d, ac):
                state_cache_skip_reason = "missing_or_unusable_state"
                state_start_rows = None
                break
            last_dt = pd.Timestamp(st["last_dt"]).floor("D")
            valid_after_cache = np.flatnonzero(input_dates > last_dt)
            if valid_after_cache.size == 0:
                state_cache_skip_reason = "no_input_after_cached_date"
                state_start_rows = None
                break
            state_start_rows.append(int(valid_after_cache[0]))
    factor_log(
        "chip.state_cache_checked",
        enabled=state_cache_enabled,
        loaded_states=len(state_cache),
        checked_cols=state_cache_checked_cols,
        usable=state_start_rows is not None,
        skip_reason=state_cache_skip_reason,
        max_bins=_chip_state_max_bins(),
        min_cols=_chip_state_cache_min_cols(),
        explicit_enabled=_chip_state_cache_explicitly_enabled(),
        bootstrap_max_cells=os.getenv("ZXW_CHIP_STATE_BOOTSTRAP_MAX_CELLS", "50000"),
    )

    if state_start_rows is not None:
        abs_conc_override = np.zeros((n_rows, n_cols), dtype=np.float64)
        rel_conc_override = np.full((n_rows, n_cols), np.nan, dtype=np.float64)
        for ci, col in enumerate(columns):
            prev_state = state_cache[str(col)]
            start_row = int(state_start_rows[ci])
            col_costs, col_state, col_abs = _compute_chouma_cost_series_with_state(
                h_np[start_row:, ci],
                l_np[start_row:, ci],
                c_np[start_row:, ci],
                v_np[start_row:, ci],
                t_np[start_row:, ci],
                _COST_PERCENTILES,
                index[start_row:],
                state=prev_state,
                min_d=min_d,
                ac=ac,
                use_volume=CHOUMA_USE_VOLUME,
            )
            _costs_array_to_matrix(col_costs, n_rows - start_row, ci, costs_np[:, start_row:, :])
            abs_conc_override[:start_row, ci] = np.nan
            abs_conc_override[start_row:, ci] = col_abs
            tail = np.asarray(prev_state.get("abs_conc_tail", np.zeros(0)), dtype=np.float64)
            rel_conc_override[:, ci : ci + 1] = _align_tail_matrix(
                _tdx_relative_concentration_with_tail(col_abs.reshape(-1, 1), [tail]),
                n_rows,
                start_row,
                1,
            )
            col_state["htsc_code"] = str(col)
            new_states[str(col)] = col_state

    use_numba = _use_numba(n_rows, n_cols)
    use_parallel = False if use_numba else (parallel if parallel is not None else n_cols >= 4)
    t1 = time.perf_counter()

    if state_start_rows is not None:
        factor_log(
            "chip.path",
            path="state_incremental",
            rows=int(n_rows),
            cols=int(n_cols),
            min_start_row=int(min(state_start_rows)) if state_start_rows else None,
            max_start_row=int(max(state_start_rows)) if state_start_rows else None,
        )
        pass
    elif state_cache_enabled and _chip_state_cache_bootstrap_enabled(n_rows, n_cols):
        factor_log("chip.path", path="state_bootstrap", rows=int(n_rows), cols=int(n_cols))
        abs_conc_override = np.zeros((n_rows, n_cols), dtype=np.float64)
        rel_conc_tail_inputs = [np.zeros(0, dtype=np.float64) for _ in range(n_cols)]
        for ci, col in enumerate(columns):
            if ci == 0 or (ci + 1) % 200 == 0 or ci + 1 == n_cols:
                factor_log("chip.state_bootstrap_progress", done=int(ci + 1), total=int(n_cols), code=str(col))
            col_costs, col_state, col_abs = _compute_chouma_cost_series_with_state(
                h_np[:, ci],
                l_np[:, ci],
                c_np[:, ci],
                v_np[:, ci],
                t_np[:, ci],
                _COST_PERCENTILES,
                index,
                state=None,
                min_d=min_d,
                ac=ac,
                use_volume=CHOUMA_USE_VOLUME,
            )
            _costs_array_to_matrix(col_costs, n_rows, ci, costs_np)
            abs_conc_override[:, ci] = col_abs
            col_state["htsc_code"] = str(col)
            new_states[str(col)] = col_state
    elif use_numba:
        factor_log("chip.path", path="numba_matrix", rows=int(n_rows), cols=int(n_cols))
        costs_np = _compute_chouma_cost_matrix_numba(
            h_np,
            l_np,
            c_np,
            v_np,
            t_np,
            _COST_PERCENTILES,
            min_d,
            ac,
            CHOUMA_USE_VOLUME,
            CHOUMA_ADD_SCALES_WITH_TURNOVER,
        )
    elif use_parallel and n_cols > 1:
        factor_log("chip.path", path="process_pool", rows=int(n_rows), cols=int(n_cols), workers=min(_parallel_workers(), n_cols))
        tasks = [
            (
                ci,
                h_np[:, ci].copy(),
                l_np[:, ci].copy(),
                c_np[:, ci].copy(),
                v_np[:, ci].copy(),
                t_np[:, ci].copy(),
                _COST_PERCENTILES,
                min_d,
                ac,
                CHOUMA_USE_VOLUME,
            )
            for ci in range(n_cols)
        ]
        workers = min(_parallel_workers(), len(tasks))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_compute_chouma_cost_series_worker, task) for task in tasks]
            for fut in as_completed(futures):
                ci, col_costs = fut.result()
                _costs_array_to_matrix(col_costs, n_rows, ci, costs_np)
    else:
        factor_log("chip.path", path="python_loop", rows=int(n_rows), cols=int(n_cols))
        for ci in range(n_cols):
            if ci == 0 or (ci + 1) % 200 == 0 or ci + 1 == n_cols:
                factor_log("chip.python_loop_progress", done=int(ci + 1), total=int(n_cols), code=str(columns[ci]))
            col_costs = _compute_chouma_cost_series(
                h_np[:, ci],
                l_np[:, ci],
                c_np[:, ci],
                v_np[:, ci],
                t_np[:, ci],
                _COST_PERCENTILES,
                min_d=min_d,
                ac=ac,
                use_volume=CHOUMA_USE_VOLUME,
            )
            _costs_array_to_matrix(col_costs, n_rows, ci, costs_np)

    t2 = time.perf_counter()

    c1_np, c5_np, c10_np, c15_np = (
        _cost_slice(costs_np, 1),
        _cost_slice(costs_np, 5),
        _cost_slice(costs_np, 10),
        _cost_slice(costs_np, 15),
    )
    c20_np, c30_np, c33_np, c34_np, c35_np, c40_np = (
        _cost_slice(costs_np, 20),
        _cost_slice(costs_np, 30),
        _cost_slice(costs_np, 33),
        _cost_slice(costs_np, 34),
        _cost_slice(costs_np, 35),
        _cost_slice(costs_np, 40),
    )
    c50_np, c60_np, c66_np, c67_np, c70_np, c80_np = (
        _cost_slice(costs_np, 50),
        _cost_slice(costs_np, 60),
        _cost_slice(costs_np, 66),
        _cost_slice(costs_np, 67),
        _cost_slice(costs_np, 70),
        _cost_slice(costs_np, 80),
    )
    c85_np, c90_np, c95_np, c99_np = (
        _cost_slice(costs_np, 85),
        _cost_slice(costs_np, 90),
        _cost_slice(costs_np, 95),
        _cost_slice(costs_np, 99),
    )

    if abs_conc_override is None:
        cum_high = H.expanding(min_periods=1).max().to_numpy(dtype=np.float64)
        cum_low = L.expanding(min_periods=1).min().to_numpy(dtype=np.float64)
        abs_conc = _safe_divide((c95_np - c5_np) * 100.0, cum_high - cum_low)
        rel_conc = _tdx_relative_concentration(abs_conc)
    else:
        abs_conc = abs_conc_override
        if rel_conc_override is not None:
            rel_conc = rel_conc_override
        else:
            rel_conc = _tdx_relative_concentration_with_tail(abs_conc, rel_conc_tail_inputs or [])

    rel_score = _score_by_threshold(rel_conc)
    abs_score = _score_by_threshold(abs_conc)
    # 通达信：集中总:=IF(相对>0 AND 绝对>0, MIN(相对,绝对), MAX(相对,绝对))
    conc_total = np.zeros_like(rel_score, dtype=np.float64)
    both = (rel_score > 0) & (abs_score > 0)
    either = (rel_score > 0) | (abs_score > 0)
    conc_total[both] = np.minimum(rel_score[both], abs_score[both])
    conc_total[either & ~both] = np.maximum(rel_score[either & ~both], abs_score[either & ~both])

    # 通达信：筹码单峰密度 / 筹码单峰态 / 筹码单峰1~3 / 筹码单峰优
    single_peak_density_value = _safe_divide((c85_np - c15_np) * 200.0, (c85_np + c15_np))
    single_peak_density_state = single_peak_density_value < 20.0
    core_ratio_value = _safe_divide((c85_np - c15_np) * 100.0, (c99_np - c1_np))
    core_ratio_state = core_ratio_value < 50.0
    single_peak_state = single_peak_density_state & core_ratio_state

    center = (c85_np + c15_np) / 2.0
    single_peak_low = (
        single_peak_density_state
        & core_ratio_state
        & (center >= c1_np)
        & (center <= c34_np)
    )
    single_peak_mid = (
        single_peak_density_state
        & core_ratio_state
        & (center >= c35_np)
        & (center <= c67_np)
    )
    single_peak_high = (
        single_peak_density_state
        & core_ratio_state
        & (center >= c66_np)
        & (center <= c99_np)
    )

    close_np = c_np
    above_c33 = close_np >= (c33_np * 0.98)
    single_peak_best = single_peak_state & above_c33

    bounds = [
        (c1_np, c10_np), (c10_np, c20_np), (c20_np, c30_np), (c30_np, c40_np), (c40_np, c50_np),
        (c50_np, c60_np), (c60_np, c70_np), (c70_np, c80_np), (c80_np, c90_np), (c90_np, c99_np),
    ]
    k_list = []
    for lo_np, hi_np in bounds:
        k_list.append(_safe_divide(np.full_like(close_np, 10.0), hi_np - lo_np))
    k_avg = _safe_divide(np.full_like(close_np, 100.0), c99_np - c1_np)
    k_avg_safe = np.where(k_avg > 0, k_avg, np.nan)

    # 通达信：峰1~峰10，峰数量1；筹码两峰态=非单峰态且峰数量1=2；筹码多峰=非单峰且非两峰
    peaks = []
    for i in range(9):
        ratio_i = _safe_divide(k_list[i], k_avg_safe)
        ratio_next = _safe_divide(k_list[i + 1], k_avg_safe)
        peaks.append((ratio_i > 1.5) & (ratio_next < 0.67))
    ratio_9 = _safe_divide(k_list[9], k_avg_safe)
    ratio_8 = _safe_divide(k_list[8], k_avg_safe)
    peaks.append((ratio_9 > 1.5) & (ratio_8 < 0.67))

    peak_count = np.zeros_like(close_np, dtype=np.float64)
    for p in peaks:
        peak_count += p.astype(np.float64)

    double_peak = (~single_peak_state) & (peak_count == 2.0)
    multi_peak = (~single_peak_state) & (~double_peak)

    # 通达信：筹码峰:=IF(筹码单峰优,1,IF(筹码两峰态&&C>=COST(33)*0.98,2,IF(筹码多峰&&...,3,0)))
    chip_peak_score = np.zeros_like(close_np, dtype=np.float64)
    chip_peak_score[single_peak_best] = 1.0
    chip_peak_score[(chip_peak_score == 0) & double_peak & above_c33] = 2.0
    chip_peak_score[(chip_peak_score == 0) & multi_peak & above_c33] = 3.0
    t3 = time.perf_counter()

    factor_dfs: dict[str, pd.DataFrame] = {
        "absolute_concentration": pd.DataFrame(abs_conc, index=index, columns=columns),
        "relative_concentration": pd.DataFrame(rel_conc, index=index, columns=columns),
        "relative_concentration_score": pd.DataFrame(rel_score, index=index, columns=columns),
        "absolute_concentration_score": pd.DataFrame(abs_score, index=index, columns=columns),
        "concentration_total_score": pd.DataFrame(conc_total, index=index, columns=columns),
        "single_peak_density_value": pd.DataFrame(single_peak_density_value, index=index, columns=columns),
        "single_peak_density_state": pd.DataFrame(single_peak_density_state.astype(float), index=index, columns=columns),
        "single_peak_core_ratio_value": pd.DataFrame(core_ratio_value, index=index, columns=columns),
        "single_peak_core_ratio_state": pd.DataFrame(core_ratio_state.astype(float), index=index, columns=columns),
        "single_peak_state": pd.DataFrame(single_peak_state.astype(float), index=index, columns=columns),
        "single_peak_center_price": pd.DataFrame(center, index=index, columns=columns),
        "cost_1pct": pd.DataFrame(c1_np, index=index, columns=columns),
        "cost_5pct": pd.DataFrame(c5_np, index=index, columns=columns),
        "cost_15pct": pd.DataFrame(c15_np, index=index, columns=columns),
        "cost_33pct": pd.DataFrame(c33_np, index=index, columns=columns),
        "cost_34pct": pd.DataFrame(c34_np, index=index, columns=columns),
        "cost_35pct": pd.DataFrame(c35_np, index=index, columns=columns),
        "cost_66pct": pd.DataFrame(c66_np, index=index, columns=columns),
        "cost_67pct": pd.DataFrame(c67_np, index=index, columns=columns),
        "cost_85pct": pd.DataFrame(c85_np, index=index, columns=columns),
        "cost_95pct": pd.DataFrame(c95_np, index=index, columns=columns),
        "cost_99pct": pd.DataFrame(c99_np, index=index, columns=columns),
        "single_peak_low": pd.DataFrame(single_peak_low.astype(float), index=index, columns=columns),
        "single_peak_mid": pd.DataFrame(single_peak_mid.astype(float), index=index, columns=columns),
        "single_peak_high": pd.DataFrame(single_peak_high.astype(float), index=index, columns=columns),
        "single_peak_best": pd.DataFrame(single_peak_best.astype(float), index=index, columns=columns),
        "double_peak_state": pd.DataFrame(double_peak.astype(float), index=index, columns=columns),
        "multi_peak_state": pd.DataFrame(multi_peak.astype(float), index=index, columns=columns),
        "chip_peak_score": pd.DataFrame(chip_peak_score, index=index, columns=columns),
    }

    factor_name_map: dict[str, str] = {
        "绝对集中度": "absolute_concentration",
        "相对集中度": "relative_concentration",
        "相对集中度赋值": "relative_concentration_score",
        "集中度绝级": "absolute_concentration_score",
        "集中总": "concentration_total_score",
        "单峰密度指标": "single_peak_density_value",
        "筹码单峰密度": "single_peak_density_state",
        "核心宽度占比指标": "single_peak_core_ratio_value",
        "核心宽度占比条件": "single_peak_core_ratio_state",
        "筹码单峰态": "single_peak_state",
        "峰中心价格": "single_peak_center_price",
        "成本1": "cost_1pct",
        "成本5": "cost_5pct",
        "成本15": "cost_15pct",
        "成本33": "cost_33pct",
        "成本34": "cost_34pct",
        "成本35": "cost_35pct",
        "成本66": "cost_66pct",
        "成本67": "cost_67pct",
        "成本85": "cost_85pct",
        "成本95": "cost_95pct",
        "成本99": "cost_99pct",
        "低位单峰": "single_peak_low",
        "中位单峰": "single_peak_mid",
        "高位单峰": "single_peak_high",
        "筹码单峰优": "single_peak_best",
        "筹码两峰": "double_peak_state",
        "筹码多峰": "multi_peak_state",
        "筹码峰赋值": "chip_peak_score",
    }

    if debug_timing:
        t4 = time.perf_counter()
        engine = "numba" if use_numba else ("mp" if use_parallel else "python")
        print(
            f"[筹码结构因子] engine={engine} minD={min_d} AC={ac} "
            f"prep={((t1 - t0) * 1000):.2f}ms cost={((t2 - t1) * 1000):.2f}ms "
            f"post={((t3 - t2) * 1000):.2f}ms total={((t4 - t0) * 1000):.2f}ms"
        )

    result = {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }
    if cache_key is not None:
        _store_cached_chip_bundle(cache_key, result)
    if state_cache_enabled and new_states:
        try:
            factor_log("chip.state_cache_save_start", states=len(new_states))
            _save_chip_state_cache(new_states)
            factor_log("chip.state_cache_save_done", states=len(new_states))
        except OSError as exc:
            factor_log("chip.state_cache_save_failed", states=len(new_states), error=str(exc))
            print(f"[WARN] 筹码 latest_state 缓存保存失败，已跳过本次缓存写入: {exc}")
    factor_log(
        "chip.finish",
        rows=int(n_rows),
        cols=int(n_cols),
        factors=len(factor_dfs),
        prep_sec=round(float(t1 - t0), 3),
        cost_sec=round(float(t2 - t1), 3),
        post_sec=round(float(t3 - t2), 3),
        total_sec=round(float(time.perf_counter() - t0), 3),
    )
    return result


BUNDLE_ID = "chip_structure"
_DEFAULT_LOOKBACK_DAYS = 1220
FACTOR_NAME_MAP: dict[str, str] = {
    "绝对集中度": "absolute_concentration",
    "相对集中度": "relative_concentration",
    "相对集中度赋值": "relative_concentration_score",
    "集中度绝级": "absolute_concentration_score",
    "集中总": "concentration_total_score",
    "单峰密度指标": "single_peak_density_value",
    "筹码单峰密度": "single_peak_density_state",
    "核心宽度占比指标": "single_peak_core_ratio_value",
    "核心宽度占比条件": "single_peak_core_ratio_state",
    "筹码单峰态": "single_peak_state",
    "峰中心价格": "single_peak_center_price",
    "成本1": "cost_1pct",
    "成本5": "cost_5pct",
    "成本15": "cost_15pct",
    "成本33": "cost_33pct",
    "成本34": "cost_34pct",
    "成本35": "cost_35pct",
    "成本66": "cost_66pct",
    "成本67": "cost_67pct",
    "成本85": "cost_85pct",
    "成本95": "cost_95pct",
    "成本99": "cost_99pct",
    "低位单峰": "single_peak_low",
    "中位单峰": "single_peak_mid",
    "高位单峰": "single_peak_high",
    "筹码单峰优": "single_peak_best",
    "筹码两峰": "double_peak_state",
    "筹码多峰": "multi_peak_state",
    "筹码峰赋值": "chip_peak_score",
}

FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    "absolute_concentration": 1200,
    "relative_concentration": 1200,
    "relative_concentration_score": 1200,
    "absolute_concentration_score": 1200,
    "concentration_total_score": 1200,
    "single_peak_density_value": 1200,
    "single_peak_density_state": 1200,
    "single_peak_core_ratio_value": 1200,
    "single_peak_core_ratio_state": 1200,
    "single_peak_state": 1200,
    "single_peak_center_price": 1200,
    "cost_1pct": 1200,
    "cost_5pct": 1200,
    "cost_15pct": 1200,
    "cost_33pct": 1200,
    "cost_34pct": 1200,
    "cost_35pct": 1200,
    "cost_66pct": 1200,
    "cost_67pct": 1200,
    "cost_85pct": 1200,
    "cost_95pct": 1200,
    "cost_99pct": 1200,
    "single_peak_low": 1200,
    "single_peak_mid": 1200,
    "single_peak_high": 1200,
    "single_peak_best": 1200,
    "double_peak_state": 1200,
    "multi_peak_state": 1200,
    "chip_peak_score": 1200,
}


def get_factor_catalog() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "factor_name_map": dict(FACTOR_NAME_MAP),
    }


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
