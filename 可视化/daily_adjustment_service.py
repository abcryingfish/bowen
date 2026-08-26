from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ADJ_WIDE_BASE_PATH = Path(r"D:\database\stock_adj_daily\wide_xdy")
ADJ_RAW_BASE_PATH = Path(r"D:\database\stock_adj_daily_raw")
OHLC_FIELDS = ("open", "high", "low", "close")
RAW_EVENT_COLUMNS = (
    "htsc_code",
    "event_date",
    "interest",
    "stockBonus",
    "stockGift",
    "allotNum",
    "allotPrice",
)
ADJUST_ALIASES = {
    "": "forward_ratio",
    "qfq": "forward_ratio",
    "forward": "forward_ratio",
    "forward_ratio": "forward_ratio",
    "qfq_ratio": "forward_ratio",
    "equal_forward": "forward_ratio",
    "?????": "forward_ratio",
    "???": "forward_ratio",
    "hfq": "backward_ratio",
    "backward": "backward_ratio",
    "backward_ratio": "backward_ratio",
    "hfq_ratio": "backward_ratio",
    "equal_backward": "backward_ratio",
    "?????": "backward_ratio",
    "???": "backward_ratio",
    "forward_ordinary": "forward_ordinary",
    "ordinary_forward": "forward_ordinary",
    "qfq_ordinary": "forward_ordinary",
    "?????": "forward_ordinary",
    "backward_ordinary": "backward_ordinary",
    "ordinary_backward": "backward_ordinary",
    "hfq_ordinary": "backward_ordinary",
    "?????": "backward_ordinary",
    "none": "none",
    "raw": "none",
    "???": "none",
}

_MONTH_WIDE_CACHE: dict[str, dict[str, Any]] = {}
_CODE_XDY_CACHE: dict[str, dict[str, Any]] = {}
_RAW_EVENT_CACHE: dict[str, dict[str, Any]] = {}


def normalize_adjust_mode(mode: Any) -> str:
    raw = "" if mode is None else str(mode).strip().lower()
    normalized = ADJUST_ALIASES.get(raw)
    if normalized is None:
        raise ValueError("adjust ???: none / forward_ratio / backward_ratio / forward_ordinary / backward_ordinary")
    return normalized


def _adjust_direction(mode: str) -> str:
    if mode.startswith("forward"):
        return "forward"
    if mode.startswith("backward"):
        return "backward"
    return mode


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


def _load_raw_events_for_code(
    code: str,
    raw_base_path: Path = ADJ_RAW_BASE_PATH,
) -> pd.DataFrame:
    normalized_code = str(code).strip().upper()
    base_path = Path(raw_base_path)
    partition_paths = _iter_month_partition_paths(base_path)
    cache_key = f"{normalized_code}|{base_path}"
    mtimes = tuple((str(path), path.stat().st_mtime) for path in partition_paths)
    cached = _RAW_EVENT_CACHE.get(cache_key)
    if cached and cached.get("mtimes") == mtimes and isinstance(cached.get("frame"), pd.DataFrame):
        return cached["frame"]

    parts: list[pd.DataFrame] = []
    for path in partition_paths:
        try:
            frame = pd.read_parquet(path)
        except Exception:
            continue
        if frame.empty or "htsc_code" not in frame.columns:
            continue
        row_frame = frame.loc[frame["htsc_code"].astype(str).str.strip().str.upper() == normalized_code]
        if row_frame.empty:
            continue
        parts.append(row_frame)

    if not parts:
        return pd.DataFrame(columns=RAW_EVENT_COLUMNS)

    events = pd.concat(parts, ignore_index=True)
    for column in RAW_EVENT_COLUMNS:
        if column not in events.columns:
            events[column] = np.nan
    events = events.loc[:, list(RAW_EVENT_COLUMNS)].copy()
    events["htsc_code"] = events["htsc_code"].astype(str).str.strip().str.upper()
    events["event_date"] = pd.to_datetime(events["event_date"], errors="coerce").dt.normalize()
    numeric_cols = ["interest", "stockBonus", "stockGift", "allotNum", "allotPrice"]
    for column in numeric_cols:
        events[column] = pd.to_numeric(events[column], errors="coerce").fillna(0.0)
    events = (
        events.dropna(subset=["htsc_code", "event_date"])
        .drop_duplicates(subset=["htsc_code", "event_date"], keep="last")
        .sort_values("event_date")
        .reset_index(drop=True)
    )
    _RAW_EVENT_CACHE[cache_key] = {
        "mtimes": mtimes,
        "frame": events,
        "loaded_at": time.time(),
    }
    return events


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


def _event_effective_date(event_row: pd.Series) -> pd.Timestamp:
    return pd.Timestamp(event_row["event_date"]).normalize()


def _infer_event_effective_dates(events: pd.DataFrame, xdy_series: pd.Series) -> pd.DataFrame:
    if events.empty:
        return events
    out = events.copy()
    out["effective_date"] = out["event_date"]
    if xdy_series.empty:
        return out

    xdy_values = pd.to_numeric(xdy_series, errors="coerce").dropna().sort_index()
    if xdy_values.empty:
        return out
    change_days = xdy_values.index[xdy_values.ne(xdy_values.shift(1))]
    for idx, row in out.iterrows():
        event_day = pd.Timestamp(row["event_date"]).normalize()
        ratio = _event_share_ratio(row)
        candidates = [day for day in change_days if day >= event_day and day <= event_day + pd.Timedelta(days=10)]
        if not candidates:
            continue
        best_day = min(candidates, key=lambda day: abs(float(xdy_values.loc[day]) - ratio))
        out.at[idx, "effective_date"] = pd.Timestamp(best_day).normalize()
    return out


def _event_share_ratio(event_row: pd.Series) -> float:
    return 1.0 + float(event_row.get("stockBonus", 0.0)) + float(event_row.get("stockGift", 0.0)) + float(event_row.get("allotNum", 0.0))


def _apply_backward_event_value(value: float, event_row: pd.Series) -> float:
    ratio = _event_share_ratio(event_row)
    interest = float(event_row.get("interest", 0.0))
    allot_num = float(event_row.get("allotNum", 0.0))
    allot_price = float(event_row.get("allotPrice", 0.0))
    if ratio <= 0.0:
        ratio = 1.0
    return value * ratio + interest + allot_num * allot_price


def _apply_forward_event_value(value: float, event_row: pd.Series) -> float:
    ratio = _event_share_ratio(event_row)
    interest = float(event_row.get("interest", 0.0))
    allot_num = float(event_row.get("allotNum", 0.0))
    allot_price = float(event_row.get("allotPrice", 0.0))
    if ratio <= 0.0:
        ratio = 1.0
    return (value - interest - allot_num * allot_price) / ratio


def _apply_ordinary_adjustment(
    bars: list[dict[str, Any]],
    code: str,
    mode: str,
    *,
    raw_base_path: Path = ADJ_RAW_BASE_PATH,
    wide_base_path: Path = ADJ_WIDE_BASE_PATH,
) -> list[dict[str, Any]] | None:
    events = _load_raw_events_for_code(code, raw_base_path=Path(raw_base_path))
    if events.empty:
        return None
    xdy_series = _load_full_xdy_series_for_code(code, wide_base_path=Path(wide_base_path))
    events = _infer_event_effective_dates(events, xdy_series)
    direction = _adjust_direction(mode)

    adjusted = [dict(bar) for bar in bars]
    for bar in adjusted:
        day = _bar_time_to_day(bar.get("time"))
        if pd.isna(day):
            continue
        if direction == "backward":
            active_events = events.loc[events["effective_date"] <= day]
            iterator = reversed(list(active_events.itertuples(index=False)))
        else:
            active_events = events.loc[events["effective_date"] > day]
            iterator = active_events.itertuples(index=False)

        event_rows = [pd.Series(row._asdict()) for row in iterator]
        if not event_rows:
            continue
        for field in OHLC_FIELDS:
            if field not in bar:
                continue
            value = pd.to_numeric(bar[field], errors="coerce")
            if pd.isna(value):
                continue
            adjusted_value = float(value)
            for event_row in event_rows:
                if direction == "backward":
                    adjusted_value = _apply_backward_event_value(adjusted_value, event_row)
                else:
                    adjusted_value = _apply_forward_event_value(adjusted_value, event_row)
            bar[field] = adjusted_value
    return adjusted


def _apply_ratio_adjustment(
    bars: list[dict[str, Any]],
    code: str,
    mode: str,
    *,
    wide_base_path: Path = ADJ_WIDE_BASE_PATH,
) -> list[dict[str, Any]] | None:
    xdy_series = _load_full_xdy_series_for_code(code, wide_base_path=Path(wide_base_path))
    if xdy_series.empty:
        return None

    full_backward_series = _compute_backward_factor_series(xdy_series)
    backward_factor = _resolve_backward_factors_for_bars(bars, full_backward_series)
    if backward_factor.size == 0:
        return None
    direction = _adjust_direction(mode)
    if direction == "forward":
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


def apply_daily_adjustment(
    bars: list[dict[str, Any]],
    code: str,
    mode: Any = "forward",
    *,
    wide_base_path: Path = ADJ_WIDE_BASE_PATH,
    raw_base_path: Path = ADJ_RAW_BASE_PATH,
) -> list[dict[str, Any]]:
    adjust_mode = normalize_adjust_mode(mode)
    if adjust_mode == "none" or not bars:
        return [dict(bar) for bar in bars]

    if adjust_mode.endswith("_ratio"):
        ratio_adjusted = _apply_ratio_adjustment(
            bars,
            code,
            adjust_mode,
            wide_base_path=Path(wide_base_path),
        )
        if ratio_adjusted is not None:
            return ratio_adjusted

    ordinary_adjusted = _apply_ordinary_adjustment(
        bars,
        code,
        adjust_mode,
        raw_base_path=Path(raw_base_path),
        wide_base_path=Path(wide_base_path),
    )
    if ordinary_adjusted is not None:
        return ordinary_adjusted

    if adjust_mode.endswith("_ordinary"):
        return [dict(bar) for bar in bars]

    ratio_adjusted = _apply_ratio_adjustment(
        bars,
        code,
        adjust_mode,
        wide_base_path=Path(wide_base_path),
    )
    if ratio_adjusted is not None:
        return ratio_adjusted

    return [dict(bar) for bar in bars]


def adjust_daily_bars(
    code: str,
    bars: list[dict[str, Any]],
    mode: Any = "forward",
    *,
    wide_base_path: Path = ADJ_WIDE_BASE_PATH,
    raw_base_path: Path = ADJ_RAW_BASE_PATH,
) -> tuple[list[dict[str, Any]], str]:
    adjust_mode = normalize_adjust_mode(mode)
    if adjust_mode == "none" or not bars:
        return [dict(bar) for bar in bars], adjust_mode
    adjusted = apply_daily_adjustment(
        bars,
        code,
        adjust_mode,
        wide_base_path=wide_base_path,
        raw_base_path=raw_base_path,
    )
    return adjusted, adjust_mode
