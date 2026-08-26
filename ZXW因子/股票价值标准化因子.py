# -*- coding: utf-8 -*-
"""从已落盘的价值原始因子派生去极值与标准化因子。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import norm


BUNDLE_ID = "stock_value_normalized"
DEFAULT_SIGNAL_BASE_DIR = Path(r"D:\database\signal_daily")
DEFAULT_MIN_VALID_STOCKS = 100
DEFAULT_MIN_COVERAGE_RATIO = 0.30
MAD_NORMAL_SCALE = 1.4826
MAD_LIMIT = 3.0
STANDARD_SCORE_CLIP = 3.0

# 独立保留映射，避免派生模块依赖基本面原始因子的计算实现。
RAW_FACTOR_NAME_MAP = {
    "盈利收益率_EY_TTM": "earnings_yield_ttm",
    "账面市值比_BM": "book_to_market_ratio",
    "销售收益率_SY_TTM": "sales_yield_ttm",
    "经营现金流收益率_OCFY_TTM": "operating_cashflow_yield_ttm",
    "自由现金流收益率_FCFY_TTM": "free_cashflow_yield_ttm",
    "净现金市值比": "net_cash_to_market_value",
}

DERIVED_FACTOR_NAME_MAP: dict[str, str] = {}
for _raw_name, _raw_key in RAW_FACTOR_NAME_MAP.items():
    DERIVED_FACTOR_NAME_MAP[f"{_raw_name}_去极值"] = f"{_raw_key}_winsorized"
    DERIVED_FACTOR_NAME_MAP[f"{_raw_name}_百分位"] = f"{_raw_key}_percentile"
    DERIVED_FACTOR_NAME_MAP[f"{_raw_name}_标准分"] = f"{_raw_key}_standard_score"


def get_factor_catalog() -> dict[str, dict[str, str]]:
    return {"factor_name_map": dict(DERIVED_FACTOR_NAME_MAP)}


def get_factor_lookback_config() -> dict[str, object]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": 0,
        "factor_lookback_days": {key: 0 for key in DERIVED_FACTOR_NAME_MAP.values()},
    }


def _validate_thresholds(
    *,
    min_valid_count: int,
    min_coverage_ratio: float,
    mad_scale: float,
    score_clip: float,
) -> None:
    if min_valid_count < 1:
        raise ValueError("min_valid_count 必须大于等于 1")
    if not 0.0 < min_coverage_ratio <= 1.0:
        raise ValueError("min_coverage_ratio 必须在 (0, 1] 范围内")
    if mad_scale <= 0.0:
        raise ValueError("mad_scale 必须大于 0")
    if score_clip <= 0.0:
        raise ValueError("score_clip 必须大于 0")


def cross_sectional_value_normalize(
    frame: pd.DataFrame,
    *,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
    min_coverage_ratio: float = DEFAULT_MIN_COVERAGE_RATIO,
    mad_scale: float = MAD_LIMIT,
    score_clip: float = STANDARD_SCORE_CLIP,
    universe_mask: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """逐日做 MAD 去极值、平均排名百分位和逆正态标准化。"""
    _validate_thresholds(
        min_valid_count=min_valid_count,
        min_coverage_ratio=min_coverage_ratio,
        mad_scale=mad_scale,
        score_clip=score_clip,
    )
    numeric = frame.apply(pd.to_numeric, errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    if universe_mask is None:
        universe_counts = pd.Series(
            numeric.shape[1],
            index=numeric.index,
            dtype=float,
        )
    else:
        aligned_mask = universe_mask.reindex(
            index=numeric.index,
            columns=numeric.columns,
            fill_value=False,
        ).fillna(False)
        universe_counts = aligned_mask.astype(bool).sum(axis=1).astype(float)

    valid_counts = numeric.notna().sum(axis=1)
    coverage = valid_counts.div(universe_counts.replace(0.0, np.nan))
    eligible_rows = (
        valid_counts.ge(int(min_valid_count))
        & coverage.ge(float(min_coverage_ratio))
    )

    medians = numeric.median(axis=1, skipna=True)
    deviations = numeric.sub(medians, axis=0).abs()
    mad = deviations.median(axis=1, skipna=True)
    robust_distance = mad * MAD_NORMAL_SCALE * float(mad_scale)
    lower = medians - robust_distance
    upper = medians + robust_distance

    row_min = numeric.min(axis=1, skipna=True)
    row_max = numeric.max(axis=1, skipna=True)
    fallback_rows = mad.eq(0.0) & row_min.ne(row_max)
    if fallback_rows.any():
        lower_quantile = numeric.quantile(0.01, axis=1, interpolation="linear")
        upper_quantile = numeric.quantile(0.99, axis=1, interpolation="linear")
        lower = lower.where(~fallback_rows, lower_quantile)
        upper = upper.where(~fallback_rows, upper_quantile)

    winsorized = numeric.clip(lower=lower, upper=upper, axis=0)
    winsorized = winsorized.where(eligible_rows, axis=0)

    ranks = winsorized.rank(axis=1, method="average", na_option="keep")
    percentiles = ranks.sub(0.5).div(valid_counts.replace(0, np.nan), axis=0)
    percentiles = percentiles.where(eligible_rows, axis=0)

    percentile_values = percentiles.to_numpy(dtype=float)
    score_values = np.full(percentile_values.shape, np.nan, dtype=float)
    valid = np.isfinite(percentile_values)
    score_values[valid] = norm.ppf(percentile_values[valid])
    score_values = np.clip(score_values, -float(score_clip), float(score_clip))
    scores = pd.DataFrame(
        score_values,
        index=percentiles.index,
        columns=percentiles.columns,
    )
    return winsorized.astype(float), percentiles.astype(float), scores.astype(float)


def _align_raw_factor_frames(
    raw_factor_dfs: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    missing = [key for key in RAW_FACTOR_NAME_MAP.values() if key not in raw_factor_dfs]
    if missing:
        raise ValueError(f"缺少价值原始因子: {', '.join(missing)}")

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


def build_value_normalized_factor_bundle(
    raw_factor_dfs: dict[str, pd.DataFrame],
    *,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
    min_coverage_ratio: float = DEFAULT_MIN_COVERAGE_RATIO,
) -> dict[str, object]:
    aligned = _align_raw_factor_frames(raw_factor_dfs)
    universe_mask: pd.DataFrame | None = None
    for frame in aligned.values():
        valid = frame.apply(pd.to_numeric, errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        ).notna()
        universe_mask = valid if universe_mask is None else universe_mask | valid
    if universe_mask is None:
        raise ValueError("价值原始因子不能为空")

    factor_dfs: dict[str, pd.DataFrame] = {}
    for raw_key, frame in aligned.items():
        winsorized, percentiles, standard_scores = cross_sectional_value_normalize(
            frame,
            min_valid_count=min_valid_count,
            min_coverage_ratio=min_coverage_ratio,
            universe_mask=universe_mask,
        )
        factor_dfs[f"{raw_key}_winsorized"] = winsorized
        factor_dfs[f"{raw_key}_percentile"] = percentiles
        factor_dfs[f"{raw_key}_standard_score"] = standard_scores

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


def load_raw_value_factor_dfs(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    """读取完整 A 股价值原始因子横截面；同键按文件顺序保留最新 part。"""
    start_dt = pd.Timestamp(start_date).floor("D")
    end_dt = pd.Timestamp(end_date).floor("D")
    if start_dt > end_dt:
        raise ValueError(
            f"start_date 不能晚于 end_date: {start_dt.date()} > {end_dt.date()}"
        )

    root = Path(base_dir)
    output: dict[str, pd.DataFrame] = {}
    missing_factors: list[str] = []
    for factor_name, factor_key in RAW_FACTOR_NAME_MAP.items():
        factor_dir = root / f"factor={factor_key}"
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
        long_frame = long_frame.sort_values("_file_order").drop_duplicates(
            ["time", "htsc_code"], keep="last"
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
            "以下价值原始因子在目标月份没有 parquet: " + "、".join(missing_factors)
        )
    return output


def build_stock_value_normalized_factor_bundle(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
    min_coverage_ratio: float = DEFAULT_MIN_COVERAGE_RATIO,
) -> dict[str, object]:
    raw_factor_dfs = load_raw_value_factor_dfs(
        base_dir=base_dir,
        start_date=start_date,
        end_date=end_date,
    )
    return build_value_normalized_factor_bundle(
        raw_factor_dfs,
        min_valid_count=min_valid_count,
        min_coverage_ratio=min_coverage_ratio,
    )
