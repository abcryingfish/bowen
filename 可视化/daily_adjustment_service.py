from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ADJ_WIDE_BASE_PATH = Path(r"D:\database\stock_adj_daily\wide_xdy")
OHLC_FIELDS = ("open", "high", "low", "close")
ADJUST_ALIASES = {
    "": "forward",
    "qfq": "forward",
    "forward": "forward",
    "前复权": "forward",
    "hfq": "backward",
    "backward": "backward",
    "后复权": "backward",
    "none": "none",
    "raw": "none",
    "不复权": "none",
}

_MONTH_WIDE_CACHE: dict[str, dict[str, Any]] = {}
_CODE_XDY_CACHE: dict[str, dict[str, Any]] = {}


def normalize_adjust_mode(mode: Any) -> str:
    raw = "" if mode is None else str(mode).strip().lower()
    normalized = ADJUST_ALIASES.get(raw)
    if normalized is None:
        raise ValueError("adjust 仅支持: none / forward / backward")
    return normalized


def _bar_time_to_day(time_value: Any) -> pd.Timestamp:
    ts = pd.to_datetime(time_value, unit="s", errors="coerce")
    if pd.isna(ts):
        ts = pd.to_datetime(time_value, errors="coerce")
    if pd.isna(ts):
        return pd.NaT
    return pd.Timestamp(ts).normalize()


def _month_partition_path(base_path: Path, day_value: pd.Timestamp) -> Path:
    return base_path / f"year={day_value.year:04d}" / f"month={day_value.month:02d}" / "merged.parquet"


def _load_month_wide_frame(path: Path) -> pd.DataFrame:
    cache_key = str(path)
    if not path.is_file():
        return pd.DataFrame()
    mtime = path.stat().st_mtime
    cached = _MONTH_WIDE_CACHE.get(cache_key)
    if cached and cached.get("mtime") == mtime and isinstance(cached.get("frame"), pd.DataFrame):
        return cached["frame"]
    frame = pd.read_parquet(path)
    _MONTH_WIDE_CACHE[cache_key] = {
        "mtime": mtime,
        "loaded_at": time.time(),
        "frame": frame,
    }
    return frame


def _iter_month_partition_paths(base_path: Path) -> list[Path]:
    root = Path(base_path)
    if not root.exists():
        return []
    paths: list[Path] = []
    for year_dir in sorted(root.glob("year=*")):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.glob("month=*")):
            merged_path = month_dir / "merged.parquet"
            if merged_path.is_file():
                paths.append(merged_path)
    return paths


def _load_full_xdy_series_for_code(
    code: str,
    wide_base_path: Path = ADJ_WIDE_BASE_PATH,
) -> pd.Series:
    normalized_code = str(code).strip().upper()
    base_path = Path(wide_base_path)
    partition_paths = _iter_month_partition_paths(base_path)
    cache_key = f"{normalized_code}|{base_path}"
    mtimes = tuple(
        (str(path), path.stat().st_mtime)
        for path in partition_paths
    )
    cached = _CODE_XDY_CACHE.get(cache_key)
    if cached and cached.get("mtimes") == mtimes and isinstance(cached.get("series"), pd.Series):
        return cached["series"]

    parts: list[pd.Series] = []
    for path in partition_paths:
        frame = _load_month_wide_frame(path)
        if frame.empty or "htsc_code" not in frame.columns:
            continue
        row = frame.loc[frame["htsc_code"].astype(str).str.strip().str.upper() == normalized_code]
        if row.empty:
            continue
        row = row.iloc[0]
        mapping: dict[pd.Timestamp, float] = {}
        for column in frame.columns:
            if column == "htsc_code":
                continue
            try:
                day = pd.Timestamp(pd.to_datetime(str(column), format="%Y/%m/%d", errors="raise")).normalize()
            except Exception:
                continue
            value = pd.to_numeric(row[column], errors="coerce")
            if pd.isna(value):
                continue
            mapping[day] = float(value)
        if mapping:
            parts.append(pd.Series(mapping, dtype=np.float64))
    if not parts:
        return pd.Series(dtype=np.float64)
    series = pd.concat(parts)
    series = series[~series.index.duplicated(keep="last")]
    series = series.sort_index()
    _CODE_XDY_CACHE[cache_key] = {
        "mtimes": mtimes,
        "series": series,
        "loaded_at": time.time(),
    }
    return series


def _resolve_xdy_values_for_bars(
    bars: list[dict[str, Any]],
    xdy_series: pd.Series,
) -> tuple[np.ndarray, np.ndarray]:
    if not bars:
        return np.array([], dtype=np.float64), np.array([], dtype=bool)
    if xdy_series.empty:
        return np.ones(len(bars), dtype=np.float64), np.zeros(len(bars), dtype=bool)

    last_known_day = xdy_series.index.max()
    last_known_value = float(xdy_series.iloc[-1])
    values: list[float] = []
    inferred: list[bool] = []
    for bar in bars:
        day = _bar_time_to_day(bar.get("time"))
        value = xdy_series.get(day)
        if pd.isna(value):
            if pd.notna(day) and day > last_known_day:
                value = last_known_value
                inferred.append(True)
            else:
                value = 1.0
                inferred.append(False)
        else:
            inferred.append(False)
        values.append(float(value))
    return np.asarray(values, dtype=np.float64), np.asarray(inferred, dtype=bool)


def _compute_backward_factor_series(xdy_series: pd.Series) -> pd.Series:
    if xdy_series.empty:
        return pd.Series(dtype=np.float64)
    values = pd.to_numeric(xdy_series, errors="coerce").astype(np.float64)
    if values.empty:
        return pd.Series(dtype=np.float64)
    raw_values = values.to_numpy(dtype=np.float64)
    segment_start_mask = np.ones(len(raw_values), dtype=bool)
    if len(raw_values) > 1:
        segment_start_mask[1:] = raw_values[1:] != raw_values[:-1]
    segment_factors = np.where(segment_start_mask, raw_values, 1.0)
    backward_factor = np.cumprod(segment_factors)
    return pd.Series(backward_factor, index=xdy_series.index, dtype=np.float64)


def _resolve_backward_factors_for_bars(
    bars: list[dict[str, Any]],
    backward_series: pd.Series,
) -> np.ndarray:
    if not bars:
        return np.array([], dtype=np.float64)
    if backward_series.empty:
        return np.ones(len(bars), dtype=np.float64)

    first_known_day = backward_series.index.min()
    last_known_day = backward_series.index.max()
    last_known_factor = float(backward_series.iloc[-1])
    values: list[float] = []
    for bar in bars:
        day = _bar_time_to_day(bar.get("time"))
        factor = backward_series.get(day)
        if pd.isna(factor):
            if pd.notna(day) and day > last_known_day:
                factor = last_known_factor
            elif pd.notna(day) and day < first_known_day:
                factor = 1.0
            else:
                factor = 1.0
        values.append(float(factor))
    return np.asarray(values, dtype=np.float64)


def apply_daily_adjustment(
    bars: list[dict[str, Any]],
    code: str,
    mode: Any = "forward",
    *,
    wide_base_path: Path = ADJ_WIDE_BASE_PATH,
) -> list[dict[str, Any]]:
    adjust_mode = normalize_adjust_mode(mode)
    if adjust_mode == "none" or not bars:
        return [dict(bar) for bar in bars]

    xdy_series = _load_full_xdy_series_for_code(code, wide_base_path=Path(wide_base_path))
    if xdy_series.empty:
        return [dict(bar) for bar in bars]

    full_backward_series = _compute_backward_factor_series(xdy_series)
    backward_factor = _resolve_backward_factors_for_bars(bars, full_backward_series)
    if backward_factor.size == 0:
        return [dict(bar) for bar in bars]
    if adjust_mode == "forward":
        last_factor = float(full_backward_series.iloc[-1]) if not full_backward_series.empty else 1.0
        factors = backward_factor / (last_factor if last_factor != 0.0 else 1.0)
    else:
        factors = backward_factor

    adjusted = [dict(bar) for bar in bars]
    for idx, bar in enumerate(adjusted):
        factor = float(factors[idx])
        for field in OHLC_FIELDS:
            if field in bar:
                bar[field] = float(pd.to_numeric(bar[field], errors="coerce")) * factor
    return adjusted


def adjust_daily_bars(
    code: str,
    bars: list[dict[str, Any]],
    mode: Any = "forward",
    *,
    wide_base_path: Path = ADJ_WIDE_BASE_PATH,
) -> tuple[list[dict[str, Any]], str]:
    adjust_mode = normalize_adjust_mode(mode)
    if adjust_mode == "none" or not bars:
        return [dict(bar) for bar in bars], adjust_mode
    adjusted = apply_daily_adjustment(bars, code, adjust_mode, wide_base_path=wide_base_path)
    return adjusted, adjust_mode
