from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
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

# 对齐通达信/fengwo CYQ：峰 (H+L)/2、minD=0.01、换手%/100、AC=1
# fengwo.COST 实测与 VOL 无关（旧筹码衰减和新增筹码均按换手率；新增为三角分布）
DEFAULT_TURNOVER_BASE_DIR = r"D:\database\stock_financial_statements\market_equity_data"
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


def _timing_enabled() -> bool:
    return os.getenv("ZXW_FACTOR_DEBUG_TIMING", "0") == "1"


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


def _costs_array_to_matrix(col_costs: np.ndarray, n_rows: int, ci: int, costs_np: np.ndarray) -> None:
    costs_np[:, :, ci] = col_costs


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
    del window_days, grid_size, history_decay, turnover_ma_window

    debug_timing = _timing_enabled()
    t0 = time.perf_counter() if debug_timing else 0.0

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
    p_count = len(_COST_PERCENTILES)
    costs_np = np.zeros((p_count, n_rows, n_cols), dtype=np.float64)

    use_numba = _use_numba(n_rows, n_cols)
    use_parallel = False if use_numba else (parallel if parallel is not None else n_cols >= 4)
    t1 = time.perf_counter() if debug_timing else 0.0

    if use_numba:
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
        for ci in range(n_cols):
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

    t2 = time.perf_counter() if debug_timing else 0.0

    cost = {
        int(p): pd.DataFrame(costs_np[pi], index=index, columns=columns)
        for pi, p in enumerate(_COST_PERCENTILES)
    }

    c1, c5, c10, c15, c20, c30 = cost[1], cost[5], cost[10], cost[15], cost[20], cost[30]
    c33, c34, c35, c40 = cost[33], cost[34], cost[35], cost[40]
    c50, c60, c66, c67 = cost[50], cost[60], cost[66], cost[67]
    c70, c80, c85, c90, c95, c99 = cost[70], cost[80], cost[85], cost[90], cost[95], cost[99]

    cum_high = H.expanding(min_periods=1).max().to_numpy(dtype=np.float64)
    cum_low = L.expanding(min_periods=1).min().to_numpy(dtype=np.float64)
    abs_conc = _safe_divide((c95 - c5).to_numpy(dtype=np.float64) * 100.0, cum_high - cum_low)

    rel_conc = _tdx_relative_concentration(abs_conc)

    rel_score = _score_by_threshold(rel_conc)
    abs_score = _score_by_threshold(abs_conc)
    # 通达信：集中总:=IF(相对>0 AND 绝对>0, MIN(相对,绝对), MAX(相对,绝对))
    conc_total = np.zeros_like(rel_score, dtype=np.float64)
    both = (rel_score > 0) & (abs_score > 0)
    either = (rel_score > 0) | (abs_score > 0)
    conc_total[both] = np.minimum(rel_score[both], abs_score[both])
    conc_total[either & ~both] = np.maximum(rel_score[either & ~both], abs_score[either & ~both])

    c85_np = c85.to_numpy(dtype=np.float64)
    c15_np = c15.to_numpy(dtype=np.float64)
    c99_np = c99.to_numpy(dtype=np.float64)
    c1_np = c1.to_numpy(dtype=np.float64)
    c33_np = c33.to_numpy(dtype=np.float64)
    c34_np = c34.to_numpy(dtype=np.float64)
    c35_np = c35.to_numpy(dtype=np.float64)
    c66_np = c66.to_numpy(dtype=np.float64)
    c67_np = c67.to_numpy(dtype=np.float64)

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
        (c1, c10), (c10, c20), (c20, c30), (c30, c40), (c40, c50),
        (c50, c60), (c60, c70), (c70, c80), (c80, c90), (c90, c99),
    ]
    k_list = []
    for lo_df, hi_df in bounds:
        k_list.append(_safe_divide(np.full_like(close_np, 10.0), (hi_df - lo_df).to_numpy(dtype=np.float64)))
    k_avg = _safe_divide(np.full_like(close_np, 100.0), (c99 - c1).to_numpy(dtype=np.float64))
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
    t3 = time.perf_counter() if debug_timing else 0.0

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
        "cost_1pct": c1,
        "cost_5pct": c5,
        "cost_15pct": c15,
        "cost_33pct": c33,
        "cost_34pct": c34,
        "cost_35pct": c35,
        "cost_66pct": c66,
        "cost_67pct": c67,
        "cost_85pct": c85,
        "cost_95pct": c95,
        "cost_99pct": c99,
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

    return {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }


BUNDLE_ID = "chip_structure"
_DEFAULT_LOOKBACK_DAYS = 1220

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


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
