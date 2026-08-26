# -*- coding: utf-8 -*-
"""从流动性原始因子生成股票流动性综合评分。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


BUNDLE_ID = "stock_liquidity_composite"
DEFAULT_SIGNAL_BASE_DIR = Path(r"D:\database\signal_daily")
DEFAULT_MIN_VALID_STOCKS = 100
TURNOVER_PERCENTILE_CAP = 95.0
FACTOR_NAME_MAP = {
    "流动性综合评分": "liquidity_composite_score",
}
RAW_FACTOR_KEYS = (
    "avg_trading_value_20d",
    "avg_trading_value_60d",
    "avg_turnover_20d",
    "avg_turnover_60d",
    "amihud_20d",
    "trading_value_volatility_20d",
    "zero_trading_value_ratio_20d",
)
RAW_FACTOR_NAME_MAP = {
    "20日平均成交额": "avg_trading_value_20d",
    "60日平均成交额": "avg_trading_value_60d",
    "20日平均换手率": "avg_turnover_20d",
    "60日平均换手率": "avg_turnover_60d",
    "20日Amihud非流动性": "amihud_20d",
    "20日成交额波动率": "trading_value_volatility_20d",
    "20日零成交额占比": "zero_trading_value_ratio_20d",
}
DIMENSION_WEIGHTS = {
    "trading_scale": 0.35,
    "price_impact": 0.30,
    "turnover_activity": 0.20,
    "trading_continuity": 0.15,
}


def get_factor_catalog() -> dict[str, dict[str, str]]:
    return {"factor_name_map": dict(FACTOR_NAME_MAP)}


def get_factor_lookback_config() -> dict[str, object]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": 0,
        "factor_lookback_days": {"liquidity_composite_score": 0},
        "source_history_start": "2010-01-01",
    }


def _is_sh_sz_stock_code(value: object) -> bool:
    code = str(value or "").strip().upper()
    return bool(
        re.fullmatch(r"(?:60[0135]\d{3}|68\d{4})\.SH", code)
        or re.fullmatch(r"(?:00[0123]\d{3}|30\d{4})\.SZ", code)
    )


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    numeric = frame.copy()
    numeric.index = pd.DatetimeIndex(pd.to_datetime(numeric.index)).floor("D")
    numeric.columns = numeric.columns.astype(str).str.strip().str.upper()
    numeric = numeric.loc[:, [_is_sh_sz_stock_code(code) for code in numeric.columns]]
    numeric = numeric.loc[:, ~numeric.columns.duplicated(keep="last")]
    numeric = numeric[~numeric.index.duplicated(keep="last")]
    numeric = numeric.apply(pd.to_numeric, errors="coerce")
    return numeric.replace([np.inf, -np.inf], np.nan).astype(float)


def _cross_sectional_percentile(
    frame: pd.DataFrame,
    *,
    min_valid_count: int,
) -> pd.DataFrame:
    valid_counts = frame.notna().sum(axis=1)
    ranks = frame.rank(axis=1, method="average", na_option="keep")
    score = ranks.sub(0.5).div(valid_counts.replace(0, np.nan), axis=0) * 100.0
    score.loc[valid_counts < min_valid_count, :] = np.nan
    return score.astype(float)


def _mean_available(frames: list[pd.DataFrame]) -> pd.DataFrame:
    total = pd.DataFrame(0.0, index=frames[0].index, columns=frames[0].columns)
    for frame in frames:
        total = total.add(frame.fillna(0.0))
    counts = sum((frame.notna().astype(int) for frame in frames))
    return total.div(counts.where(counts > 0)).astype(float)


def _month_starts(
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> Iterable[pd.Timestamp]:
    cursor = pd.Timestamp(start_date.year, start_date.month, 1)
    end_month = pd.Timestamp(end_date.year, end_date.month, 1)
    while cursor <= end_month:
        yield cursor
        cursor += pd.offsets.MonthBegin(1)


def load_liquidity_raw_factor_frames(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    """读取七个流动性原始因子的完整月份分区。"""
    start_dt = pd.Timestamp(start_date).floor("D")
    end_dt = pd.Timestamp(end_date).floor("D")
    if start_dt > end_dt:
        raise ValueError(
            f"start_date 不能晚于 end_date: {start_dt.date()} > {end_dt.date()}"
        )

    result: dict[str, pd.DataFrame] = {}
    for factor_name, factor_key in RAW_FACTOR_NAME_MAP.items():
        files: list[Path] = []
        missing_months: list[str] = []
        for month_start in _month_starts(start_dt, end_dt):
            month_dir = (
                Path(base_dir)
                / f"factor={factor_key}"
                / f"year={month_start.year}"
                / f"month={month_start.month:02d}"
            )
            month_files: list[Path] = []
            merged_path = month_dir / "merged.parquet"
            if merged_path.is_file():
                month_files.append(merged_path)
            month_files.extend(sorted(month_dir.glob("part_*.parquet")))
            if not month_files:
                missing_months.append(month_start.strftime("%Y-%m"))
            files.extend(month_files)
        if missing_months:
            raise FileNotFoundError(
                f"{factor_name} 缺少月份分区: " + "、".join(missing_months)
            )

        frames: list[pd.DataFrame] = []
        for file_order, path in enumerate(files):
            try:
                frame = pd.read_parquet(path, columns=["time", "htsc_code", "value"])
            except Exception as exc:
                raise ValueError(f"{factor_name} 分区读取失败: {path}: {exc}") from exc
            frame["_file_order"] = file_order
            frame["_row_order"] = np.arange(len(frame), dtype=np.int64)
            frames.append(frame)
        long_frame = pd.concat(frames, ignore_index=True)
        long_frame["time"] = pd.to_datetime(
            long_frame["time"], errors="coerce"
        ).dt.floor("D")
        long_frame["htsc_code"] = (
            long_frame["htsc_code"].astype(str).str.strip().str.upper()
        )
        long_frame["value"] = pd.to_numeric(long_frame["value"], errors="coerce")
        long_frame = long_frame[
            long_frame["time"].between(start_dt, end_dt)
            & long_frame["htsc_code"].map(_is_sh_sz_stock_code)
        ]
        long_frame = long_frame.sort_values(
            ["_file_order", "_row_order"], kind="stable"
        ).drop_duplicates(["time", "htsc_code"], keep="last")
        wide = long_frame.pivot(
            index="time",
            columns="htsc_code",
            values="value",
        ).sort_index()
        wide.columns.name = None
        result[factor_key] = wide.astype(float)
    return result


def build_stock_liquidity_composite_bundle(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
) -> dict[str, object]:
    factor_frames = load_liquidity_raw_factor_frames(
        base_dir=base_dir,
        start_date=start_date,
        end_date=end_date,
    )
    return build_liquidity_composite_score_bundle(
        factor_frames,
        min_valid_count=min_valid_count,
    )


def build_liquidity_composite_score_bundle(
    factor_frames: dict[str, pd.DataFrame],
    *,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
) -> dict[str, object]:
    """逐日合成方向统一的 0-100 股票流动性评分。"""
    if int(min_valid_count) < 1:
        raise ValueError("min_valid_count 必须大于等于 1")
    missing_keys = [key for key in RAW_FACTOR_KEYS if key not in factor_frames]
    if missing_keys:
        raise ValueError("缺少流动性原始因子: " + ", ".join(missing_keys))

    normalized = {key: _normalize_frame(factor_frames[key]) for key in RAW_FACTOR_KEYS}
    all_dates = sorted({date for frame in normalized.values() for date in frame.index})
    all_codes = sorted({code for frame in normalized.values() for code in frame.columns})
    aligned = {
        key: frame.reindex(index=all_dates, columns=all_codes)
        for key, frame in normalized.items()
    }
    percentiles = {
        key: _cross_sectional_percentile(frame, min_valid_count=int(min_valid_count))
        for key, frame in aligned.items()
    }

    trading_scale = _mean_available(
        [
            percentiles["avg_trading_value_20d"],
            percentiles["avg_trading_value_60d"],
        ]
    )
    price_impact = 100.0 - percentiles["amihud_20d"]
    turnover_activity = _mean_available(
        [
            percentiles["avg_turnover_20d"].clip(upper=TURNOVER_PERCENTILE_CAP)
            / TURNOVER_PERCENTILE_CAP
            * 100.0,
            percentiles["avg_turnover_60d"].clip(upper=TURNOVER_PERCENTILE_CAP)
            / TURNOVER_PERCENTILE_CAP
            * 100.0,
        ]
    )

    continuity_children: list[pd.DataFrame] = []
    for key in ("trading_value_volatility_20d", "zero_trading_value_ratio_20d"):
        child = 100.0 - percentiles[key]
        informative = aligned[key].nunique(axis=1, dropna=True).gt(1)
        continuity_children.append(child.where(informative, np.nan, axis=0))
    trading_continuity = _mean_available(continuity_children)

    dimensions = {
        "trading_scale": trading_scale,
        "price_impact": price_impact,
        "turnover_activity": turnover_activity,
        "trading_continuity": trading_continuity,
    }
    numerator = pd.DataFrame(0.0, index=all_dates, columns=all_codes)
    denominator = pd.DataFrame(0.0, index=all_dates, columns=all_codes)
    for name, dimension in dimensions.items():
        weight = DIMENSION_WEIGHTS[name]
        numerator = numerator.add(dimension.fillna(0.0) * weight)
        denominator = denominator.add(dimension.notna().astype(float) * weight)

    score = numerator.div(denominator.where(denominator > 0.0))
    mandatory = trading_scale.notna() & price_impact.notna()
    optional = turnover_activity.notna() | trading_continuity.notna()
    score = score.where(mandatory & optional)
    score.loc[score.notna().sum(axis=1) < int(min_valid_count), :] = np.nan

    return {
        "bundle_id": BUNDLE_ID,
        "factor_dfs": {"liquidity_composite_score": score.astype(float)},
        "factor_name_map": dict(FACTOR_NAME_MAP),
    }
