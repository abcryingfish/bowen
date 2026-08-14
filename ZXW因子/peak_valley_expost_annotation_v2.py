"""V2 continuous ex-post peak/valley annotation.

The same deterministic calculation is used by the offline simulator and the
label-only production writer. It is never a predictive feature and contains
future information by design.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd


V2_FACTOR_NAME_MAP = {
    "波峰事后连续强度（label专用，有未来数据）": "peak_strength_ex_post",
    "波谷事后连续强度（label专用，有未来数据）": "valley_strength_ex_post",
    "波峰局部高位分（label专用，有未来数据）": "peak_local_position",
    "波谷局部低位分（label专用，有未来数据）": "valley_local_position",
    "波峰趋势转折分（label专用，有未来数据）": "peak_trend_turn",
    "波谷趋势转折分（label专用，有未来数据）": "valley_trend_turn",
    "波峰反转强度（label专用，有未来数据）": "peak_reversal_strength",
    "波谷反转强度（label专用，有未来数据）": "valley_reversal_strength",
    "波峰反转持续性（label专用，有未来数据）": "peak_persistence",
    "波谷反转持续性（label专用，有未来数据）": "valley_persistence",
    "波峰确认延迟（label专用，有未来数据）": "peak_confirm_delay",
    "波谷确认延迟（label专用，有未来数据）": "valley_confirm_delay",
}

V2_RECOMPUTE_BARS = 60
V2_CONTEXT_BARS = 60


_COMPONENT_COLUMNS = (
    "peak_local_position",
    "valley_local_position",
    "peak_trend_turn",
    "valley_trend_turn",
    "peak_reversal_strength",
    "valley_reversal_strength",
    "peak_persistence",
    "valley_persistence",
)


def plan_peak_valley_v2_refresh(
    available_dates: pd.DatetimeIndex | Iterable[object],
    *,
    existing_last_dates: Iterable[object],
    start_date: object,
    end_date: object,
    recompute_bars: int = V2_RECOMPUTE_BARS,
    context_bars: int = V2_CONTEXT_BARS,
    required_factor_count: int = len(V2_FACTOR_NAME_MAP),
) -> dict[str, object]:
    """Plan a stable tail refresh for labels that depend on future bars."""

    dates = pd.DatetimeIndex(pd.to_datetime(list(available_dates), errors="coerce"))
    dates = dates[~dates.isna()].floor("D").unique().sort_values()
    start_dt = pd.Timestamp(start_date).floor("D")
    end_dt = pd.Timestamp(end_date).floor("D")
    if start_dt > end_dt:
        raise ValueError("start_date 不能晚于 end_date")
    recompute_bars = max(0, int(recompute_bars))
    context_bars = max(0, int(context_bars))
    required_factor_count = max(1, int(required_factor_count))

    normalized_last_dates = [
        pd.Timestamp(value).floor("D")
        for value in existing_last_dates
        if value is not None and not pd.isna(value)
    ]
    complete_date = (
        min(normalized_last_dates)
        if len(normalized_last_dates) == required_factor_count
        else None
    )
    needs_refresh = complete_date is None or complete_date < end_dt
    if not needs_refresh:
        return {
            "needs_refresh": False,
            "complete_date": complete_date,
            "query_start": None,
            "write_start": None,
        }

    anchor = min(complete_date, end_dt) if complete_date is not None else start_dt
    eligible = dates[dates <= anchor]
    if complete_date is None:
        write_start = start_dt
    elif len(eligible):
        write_start = pd.Timestamp(eligible[max(0, len(eligible) - recompute_bars - 1)]).floor("D")
        write_start = max(start_dt, write_start)
    else:
        write_start = start_dt

    context_dates = dates[dates < write_start]
    if len(context_dates) and context_bars > 0:
        context_pos = max(0, len(context_dates) - context_bars)
        query_start = pd.Timestamp(context_dates[context_pos]).floor("D")
    else:
        query_start = write_start

    return {
        "needs_refresh": True,
        "complete_date": complete_date,
        "query_start": query_start,
        "write_start": write_start,
    }


def _normalise_inputs(
    high: pd.Series | Iterable[float],
    low: pd.Series | Iterable[float],
    close: pd.Series | Iterable[float],
) -> pd.DataFrame:
    series = []
    for name, values in (("high", high), ("low", low), ("close", close)):
        if isinstance(values, pd.Series):
            item = values.rename(name).copy()
        else:
            item = pd.Series(values, name=name)
        if not isinstance(item.index, pd.DatetimeIndex):
            item.index = pd.RangeIndex(len(item))
        series.append(item)
    frame = pd.concat(series, axis=1)
    frame = frame.apply(pd.to_numeric, errors="coerce")
    frame = frame[~frame.index.duplicated(keep="last")].sort_index().dropna()
    if frame.empty:
        raise ValueError("high、low、close 不能没有有效数据")
    if (frame["high"] < frame[["low", "close"]].min(axis=1)).any():
        raise ValueError("high 必须不小于 low 和 close")
    if (frame["low"] > frame[["high", "close"]].max(axis=1)).any():
        raise ValueError("low 必须不大于 high 和 close")
    return frame


def _atr(frame: pd.DataFrame, period: int) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.rolling(max(int(period), 1), min_periods=1).mean()
    fallback = float(true_range.replace(0.0, np.nan).median()) if len(true_range) else 1.0
    if not np.isfinite(fallback) or fallback <= 0:
        fallback = 1.0
    return atr.replace([np.inf, -np.inf], np.nan).fillna(fallback).clip(lower=1e-12)


def _bounded_sigmoid(values: pd.Series | np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    values = np.clip(values, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-values))


def _local_position(values: pd.Series, windows: tuple[int, ...], *, high_side: bool) -> pd.Series:
    scores = []
    for window in windows:
        rolling_min = values.rolling(window, center=True, min_periods=1).min()
        rolling_max = values.rolling(window, center=True, min_periods=1).max()
        span = (rolling_max - rolling_min).replace(0.0, np.nan)
        if high_side:
            score = (values - rolling_min) / span
        else:
            score = (rolling_max - values) / span
        scores.append(score.fillna(0.5).clip(0.0, 1.0))
    return pd.concat(scores, axis=1).mean(axis=1).clip(0.0, 1.0)


def _trend_turn(close: pd.Series, atr: pd.Series, *, peak: bool) -> pd.Series:
    fast = close.ewm(span=5, adjust=False, min_periods=1).mean()
    slow = close.ewm(span=20, adjust=False, min_periods=1).mean()
    momentum = fast - slow
    lookback = 5
    left_slope = momentum - momentum.shift(lookback)
    right_slope = momentum.shift(-lookback) - momentum
    if peak:
        raw = (left_slope - right_slope) / atr
    else:
        raw = (right_slope - left_slope) / atr
    return pd.Series(_bounded_sigmoid(raw.fillna(0.0)), index=close.index).clip(0.0, 1.0)


def _future_components(
    frame: pd.DataFrame,
    atr: pd.Series,
    horizons: tuple[int, ...],
    *,
    peak: bool,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    n = len(frame)
    close_values = frame["close"].to_numpy(dtype=float)
    high_values = frame["high"].to_numpy(dtype=float)
    low_values = frame["low"].to_numpy(dtype=float)
    atr_values = atr.to_numpy(dtype=float)
    reversal = np.zeros(n, dtype=float)
    persistence = np.zeros(n, dtype=float)
    delays = np.full(n, np.nan, dtype=float)
    max_horizon = max(horizons, default=0)

    for i in range(n):
        barrier = close_values[i] - atr_values[i] if peak else close_values[i] + atr_values[i]
        magnitudes: list[float] = []
        first_hit: int | None = None
        for horizon in horizons:
            end = min(n, i + horizon + 1)
            if i + 1 >= end:
                magnitudes.append(0.0)
                continue
            future_slice = slice(i + 1, end)
            if peak:
                excursion = max(0.0, (close_values[i] - float(np.min(low_values[future_slice]))) / atr_values[i])
                hit_positions = np.flatnonzero(low_values[future_slice] <= barrier)
            else:
                excursion = max(0.0, (float(np.max(high_values[future_slice])) - close_values[i]) / atr_values[i])
                hit_positions = np.flatnonzero(high_values[future_slice] >= barrier)
            magnitudes.append(1.0 - np.exp(-excursion))
            if hit_positions.size and first_hit is None:
                first_hit = int(hit_positions[0]) + 1

        if magnitudes:
            reversal[i] = float(np.mean(magnitudes))
        if first_hit is not None:
            delays[i] = first_hit
            persistence_end = min(n, i + max_horizon + 1)
            after_hit_start = i + first_hit + 1
            if after_hit_start >= persistence_end:
                persistence[i] = 1.0
            else:
                remaining = close_values[after_hit_start:persistence_end]
                if peak:
                    persistence[i] = float(np.mean(remaining <= barrier))
                else:
                    persistence[i] = float(np.mean(remaining >= barrier))
    index = frame.index
    return (
        pd.Series(reversal, index=index),
        pd.Series(persistence, index=index),
        pd.Series(delays, index=index),
    )


def _smooth_geometric_mean(components: pd.DataFrame, epsilon: float) -> pd.Series:
    values = components.clip(0.0, 1.0).to_numpy(dtype=float)
    epsilon = float(epsilon)
    if not 0.0 < epsilon < 1.0:
        raise ValueError("epsilon 必须位于 (0, 1) 区间")
    strength = np.prod(values + epsilon, axis=1) ** (1.0 / values.shape[1])
    strength = (strength - epsilon) / (1.0 - epsilon)
    return pd.Series(np.clip(strength, 0.0, 1.0), index=components.index)


def annotate_peak_valley_ex_post(
    high: pd.Series | Iterable[float],
    low: pd.Series | Iterable[float],
    close: pd.Series | Iterable[float],
    *,
    windows: tuple[int, ...] = (3, 5, 10, 20, 40, 60),
    horizons: tuple[int, ...] = (5, 10, 20, 40),
    atr_period: int = 20,
    epsilon: float = 0.02,
) -> pd.DataFrame:
    """Return independent continuous peak/valley ex-post annotations.

    The result uses a sorted, de-duplicated DatetimeIndex when the inputs have
    one.  Scores are continuous in ``[0, 1]``; zero is only a low algorithmic
    score and is not an explicit negative label.
    """

    windows = tuple(sorted({int(window) for window in windows if int(window) > 0}))
    horizons = tuple(sorted({int(horizon) for horizon in horizons if int(horizon) > 0}))
    if not windows or not horizons:
        raise ValueError("windows 和 horizons 至少各需要一个正整数")
    frame = _normalise_inputs(high, low, close)
    atr = _atr(frame, atr_period)
    peak_local = _local_position(frame["high"], windows, high_side=True)
    valley_local = _local_position(frame["low"], windows, high_side=False)
    peak_trend = _trend_turn(frame["close"], atr, peak=True)
    valley_trend = _trend_turn(frame["close"], atr, peak=False)
    peak_reversal, peak_persistence, peak_delay = _future_components(
        frame, atr, horizons, peak=True
    )
    valley_reversal, valley_persistence, valley_delay = _future_components(
        frame, atr, horizons, peak=False
    )
    peak_components = pd.DataFrame(
        {
            "local": peak_local,
            "trend": peak_trend,
            "reversal": peak_reversal,
            "persistence": peak_persistence,
        },
        index=frame.index,
    )
    valley_components = pd.DataFrame(
        {
            "local": valley_local,
            "trend": valley_trend,
            "reversal": valley_reversal,
            "persistence": valley_persistence,
        },
        index=frame.index,
    )
    return pd.DataFrame(
        {
            "peak_strength_ex_post": _smooth_geometric_mean(peak_components, epsilon),
            "valley_strength_ex_post": _smooth_geometric_mean(valley_components, epsilon),
            "peak_local_position": peak_local,
            "valley_local_position": valley_local,
            "peak_trend_turn": peak_trend,
            "valley_trend_turn": valley_trend,
            "peak_reversal_strength": peak_reversal.clip(0.0, 1.0),
            "valley_reversal_strength": valley_reversal.clip(0.0, 1.0),
            "peak_persistence": peak_persistence.clip(0.0, 1.0),
            "valley_persistence": valley_persistence.clip(0.0, 1.0),
            "peak_confirm_delay": peak_delay,
            "valley_confirm_delay": valley_delay,
        },
        index=frame.index,
    )


def build_peak_valley_expost_v2_label_bundle(
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    **kwargs,
) -> dict[str, object]:
    """Build the twelve V2 label-only factor frames for the main generator."""

    if not isinstance(H, pd.DataFrame) or not isinstance(L, pd.DataFrame) or not isinstance(C, pd.DataFrame):
        raise TypeError("H、L、C 必须都是 pandas.DataFrame")
    if list(H.columns) != list(L.columns) or list(H.columns) != list(C.columns):
        raise ValueError("H、L、C 的股票列必须完全一致")
    factor_values = {
        factor_key: {}
        for factor_key in V2_FACTOR_NAME_MAP.values()
    }
    for code in C.columns:
        result = annotate_peak_valley_ex_post(H[code], L[code], C[code], **kwargs)
        aligned = result.reindex(C.index)
        for factor_key in factor_values:
            factor_values[factor_key][code] = aligned[factor_key]
    factor_dfs = {
        factor_key: pd.DataFrame(values, index=C.index)
        for factor_key, values in factor_values.items()
    }
    return {
        "bundle_id": "peak_valley_expost_v2_label",
        "factor_dfs": factor_dfs,
        "factor_name_map": dict(V2_FACTOR_NAME_MAP),
    }


__all__ = [
    "V2_CONTEXT_BARS",
    "V2_FACTOR_NAME_MAP",
    "V2_RECOMPUTE_BARS",
    "annotate_peak_valley_ex_post",
    "build_peak_valley_expost_v2_label_bundle",
    "plan_peak_valley_v2_refresh",
]
