# -*- coding: utf-8 -*-
"""从已落盘的红利原始因子派生标准化因子与红利基础分。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import norm


BUNDLE_ID = "stock_dividend_normalized"
DEFAULT_SIGNAL_BASE_DIR = Path(r"D:\database\signal_daily")
DEFAULT_MIN_VALID_STOCKS = 100
STANDARD_SCORE_CLIP = 3.0

# 独立保留映射，避免派生模块依赖红利原始因子的计算实现。
RAW_FACTOR_NAME_MAP = {
    "调整后每股现金分红_TTM": "cash_dividend_per_share_ttm_adjusted",
    "已实施股息率_TTM": "realized_dividend_yield_ttm",
    "现金分红次数_近3年": "cash_dividend_event_count_3y",
    "有分红年度占比_近5年": "cash_dividend_active_year_ratio_5y",
    "连续分红年数_近5年": "cash_dividend_consecutive_years",
    "每股分红三年复合增长率": "cash_dividend_cagr_3y",
    "分红削减次数_近5年": "cash_dividend_cut_count_5y",
}

# 正权重表示数值越高越好；负权重表示数值越高越差。
BASE_SCORE_WEIGHTS = {
    "realized_dividend_yield_ttm": 0.35,
    "cash_dividend_active_year_ratio_5y": 0.25,
    "cash_dividend_consecutive_years": 0.20,
    "cash_dividend_cagr_3y": 0.15,
    "cash_dividend_cut_count_5y": -0.05,
}

DERIVED_FACTOR_NAME_MAP: dict[str, str] = {}
for _raw_name, _raw_key in RAW_FACTOR_NAME_MAP.items():
    DERIVED_FACTOR_NAME_MAP[f"{_raw_name}_百分位"] = f"{_raw_key}_percentile"
    DERIVED_FACTOR_NAME_MAP[f"{_raw_name}_标准分"] = f"{_raw_key}_standard_score"
DERIVED_FACTOR_NAME_MAP.update(
    {
        "红利基础分": "dividend_base_score",
        "红利基础原始得分": "dividend_base_raw_score",
        "红利基础标准分": "dividend_base_standard_score",
        "红利基础百分位": "dividend_base_percentile",
    }
)


def get_factor_catalog() -> dict[str, dict[str, str]]:
    return {"factor_name_map": dict(DERIVED_FACTOR_NAME_MAP)}


def get_factor_lookback_config() -> dict[str, object]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": 0,
        "factor_lookback_days": {key: 0 for key in DERIVED_FACTOR_NAME_MAP.values()},
    }


def cross_sectional_rank_normalize(
    frame: pd.DataFrame,
    *,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
    score_clip: float = STANDARD_SCORE_CLIP,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """逐日做平均排名百分位和逆正态变换，缺失值保持缺失。"""
    if min_valid_count < 1:
        raise ValueError("min_valid_count 必须大于等于 1")
    numeric = frame.apply(pd.to_numeric, errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    valid_counts = numeric.notna().sum(axis=1)
    ranks = numeric.rank(axis=1, method="average", na_option="keep")
    percentiles = ranks.sub(0.5).div(valid_counts.replace(0, np.nan), axis=0)
    percentiles.loc[valid_counts < int(min_valid_count), :] = np.nan

    values = percentiles.to_numpy(dtype=float)
    scores = np.full(values.shape, np.nan, dtype=float)
    valid = np.isfinite(values)
    scores[valid] = norm.ppf(values[valid])
    scores = np.clip(scores, -float(score_clip), float(score_clip))
    score_frame = pd.DataFrame(
        scores,
        index=percentiles.index,
        columns=percentiles.columns,
    )
    return percentiles.astype(float), score_frame.astype(float)


def _weighted_available_score(
    frames: dict[str, pd.DataFrame],
    weights: dict[str, float],
    *,
    minimum_inputs: int,
) -> pd.DataFrame:
    keys = list(weights)
    if not keys:
        raise ValueError("合成因子至少需要一个输入")
    template = frames[keys[0]]
    numerator = pd.DataFrame(0.0, index=template.index, columns=template.columns)
    denominator = pd.DataFrame(0.0, index=template.index, columns=template.columns)
    valid_count = pd.DataFrame(
        0,
        index=template.index,
        columns=template.columns,
        dtype=np.int16,
    )
    for key, raw_weight in weights.items():
        frame = frames[key]
        valid = frame.notna()
        weight = float(raw_weight)
        numerator = numerator.add(frame.fillna(0.0) * weight)
        denominator = denominator.add(valid.astype(float) * abs(weight))
        valid_count = valid_count.add(valid.astype(np.int16))
    result = numerator.div(denominator.where(denominator > 0))
    return result.where(valid_count >= int(minimum_inputs))


def _align_raw_factor_frames(
    raw_factor_dfs: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    missing = [key for key in RAW_FACTOR_NAME_MAP.values() if key not in raw_factor_dfs]
    if missing:
        raise ValueError(f"缺少红利原始因子: {', '.join(missing)}")
    indexes = [
        pd.DatetimeIndex(pd.to_datetime(raw_factor_dfs[key].index)).floor("D")
        for key in RAW_FACTOR_NAME_MAP.values()
    ]
    columns_list = [
        pd.Index(raw_factor_dfs[key].columns.astype(str))
        for key in RAW_FACTOR_NAME_MAP.values()
    ]
    index = indexes[0]
    columns = columns_list[0]
    for item in indexes[1:]:
        index = index.union(item)
    for item in columns_list[1:]:
        columns = columns.union(item)
    index = index.sort_values()
    columns = columns.sort_values()

    aligned: dict[str, pd.DataFrame] = {}
    for key in RAW_FACTOR_NAME_MAP.values():
        frame = raw_factor_dfs[key].copy()
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index)).floor("D")
        frame.columns = frame.columns.astype(str)
        frame = frame[~frame.index.duplicated(keep="last")]
        aligned[key] = frame.reindex(index=index, columns=columns)
    return aligned


def build_dividend_normalized_factor_bundle(
    raw_factor_dfs: dict[str, pd.DataFrame],
    *,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
) -> dict[str, object]:
    aligned = _align_raw_factor_frames(raw_factor_dfs)
    factor_dfs: dict[str, pd.DataFrame] = {}
    standard_frames: dict[str, pd.DataFrame] = {}

    for raw_key in RAW_FACTOR_NAME_MAP.values():
        percentiles, standard_scores = cross_sectional_rank_normalize(
            aligned[raw_key],
            min_valid_count=min_valid_count,
        )
        factor_dfs[f"{raw_key}_percentile"] = percentiles
        factor_dfs[f"{raw_key}_standard_score"] = standard_scores
        standard_frames[raw_key] = standard_scores

    raw_composite = _weighted_available_score(
        standard_frames,
        BASE_SCORE_WEIGHTS,
        minimum_inputs=3,
    )
    raw_composite = raw_composite.where(
        standard_frames["realized_dividend_yield_ttm"].notna()
    )
    composite_percentile, composite_standard = cross_sectional_rank_normalize(
        raw_composite,
        min_valid_count=min_valid_count,
    )
    factor_dfs["dividend_base_raw_score"] = raw_composite
    factor_dfs["dividend_base_standard_score"] = composite_standard
    factor_dfs["dividend_base_percentile"] = composite_percentile
    factor_dfs["dividend_base_score"] = composite_percentile * 100.0
    return {
        "bundle_id": BUNDLE_ID,
        "factor_dfs": factor_dfs,
        "factor_name_map": dict(DERIVED_FACTOR_NAME_MAP),
    }


def _is_a_share_code(value: object) -> bool:
    return bool(re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", str(value or "").strip().upper()))


def _month_directories(
    factor_dir: Path,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> Iterable[Path]:
    cursor = pd.Timestamp(start_date.year, start_date.month, 1)
    end_month = pd.Timestamp(end_date.year, end_date.month, 1)
    while cursor <= end_month:
        month_dir = factor_dir / f"year={cursor.year}" / f"month={cursor.month:02d}"
        if month_dir.is_dir():
            yield month_dir
        cursor += pd.offsets.MonthBegin(1)


def load_raw_dividend_factor_dfs(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    stock_codes: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, pd.DataFrame]:
    """读取红利原始因子的 merged 与 part；同键按文件顺序保留最新 part。"""
    start_dt = pd.Timestamp(start_date).floor("D")
    end_dt = pd.Timestamp(end_date).floor("D")
    if start_dt > end_dt:
        raise ValueError(
            f"start_date 不能晚于 end_date: {start_dt.date()} > {end_dt.date()}"
        )
    allowed_codes = (
        {str(code).strip().upper() for code in stock_codes if _is_a_share_code(code)}
        if stock_codes is not None
        else None
    )
    root = Path(base_dir)
    output: dict[str, pd.DataFrame] = {}
    missing_factors: list[str] = []

    for factor_name, factor_key in RAW_FACTOR_NAME_MAP.items():
        factor_dir = root / f"factor={factor_name}"
        files: list[Path] = []
        for month_dir in _month_directories(factor_dir, start_dt, end_dt):
            merged_path = month_dir / "merged.parquet"
            if merged_path.is_file():
                files.append(merged_path)
            files.extend(sorted(month_dir.glob("part_*.parquet")))
        if not files:
            missing_factors.append(factor_name)
            continue

        frames: list[pd.DataFrame] = []
        for file_order, path in enumerate(files):
            frame = pd.read_parquet(path, columns=["time", "htsc_code", "value"])
            frame["_file_order"] = file_order
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
            & long_frame["htsc_code"].map(_is_a_share_code)
        ]
        if allowed_codes is not None:
            long_frame = long_frame[long_frame["htsc_code"].isin(allowed_codes)]
        long_frame = long_frame.sort_values("_file_order").drop_duplicates(
            ["time", "htsc_code"],
            keep="last",
        )
        wide = long_frame.pivot(
            index="time",
            columns="htsc_code",
            values="value",
        ).sort_index()
        wide.columns.name = None
        output[factor_key] = wide.astype(float)

    if missing_factors:
        raise FileNotFoundError(
            "以下红利原始因子在目标月份没有 parquet: " + "、".join(missing_factors)
        )
    return output


def build_stock_dividend_normalized_factor_bundle(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    stock_codes: set[str] | list[str] | tuple[str, ...] | None = None,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
) -> dict[str, object]:
    raw_factor_dfs = load_raw_dividend_factor_dfs(
        base_dir=base_dir,
        start_date=start_date,
        end_date=end_date,
        stock_codes=stock_codes,
    )
    return build_dividend_normalized_factor_bundle(
        raw_factor_dfs,
        min_valid_count=min_valid_count,
    )
