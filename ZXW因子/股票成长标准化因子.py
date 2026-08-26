# -*- coding: utf-8 -*-
"""从已落盘的成长原始因子派生成长标准化与风格合成因子。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import norm


BUNDLE_ID = "stock_growth_normalized"
DEFAULT_SIGNAL_BASE_DIR = Path(r"D:\database\signal_daily")
DEFAULT_MIN_VALID_STOCKS = 100
STANDARD_SCORE_CLIP = 3.0
MIN_GROWTH_DATA_COMPLETENESS = 0.40
MISSING_DATA_PENALTY_RATE = 0.50

# 独立保留映射，避免派生模块依赖财务原始因子的计算实现。
RAW_FACTOR_NAME_MAP = {
    "营业收入同比_TTM": "revenue_growth_yoy_ttm",
    "营业收入三年复合增长率": "revenue_cagr_3y_ttm",
    "营业利润同比_TTM": "operating_profit_growth_yoy_ttm",
    "扣非净利润同比_TTM": "adjusted_net_profit_growth_yoy_ttm",
    "基本每股收益同比_TTM": "basic_eps_growth_yoy_ttm",
    "经营现金流同比_TTM": "operating_cashflow_growth_yoy_ttm",
    "营业收入增速变化": "revenue_growth_acceleration_ttm",
    "扣非净利润增速变化": "adjusted_net_profit_growth_acceleration_ttm",
    "净资产收益率同比变化": "return_on_equity_change_yoy_ttm",
    "销售毛利率同比变化": "sales_gross_margin_change_yoy_ttm",
    "研发费用同比增速_TTM": "research_expense_growth_yoy_ttm",
    "研发费用率_TTM": "research_expense_to_revenue_ttm",
}

PILLAR_CONFIG = {
    "growth_scale_score": {
        "name": "成长规模分",
        "weight": 0.30,
        "factors": {
            "revenue_growth_yoy_ttm": 1.0,
            "revenue_cagr_3y_ttm": 1.0,
            "operating_profit_growth_yoy_ttm": 1.0,
        },
    },
    "growth_profit_score": {
        "name": "成长盈利分",
        "weight": 0.35,
        "factors": {
            "adjusted_net_profit_growth_yoy_ttm": 1.0,
            "basic_eps_growth_yoy_ttm": 1.0,
            "operating_cashflow_growth_yoy_ttm": 1.0,
        },
    },
    "growth_quality_score": {
        "name": "成长质量分",
        "weight": 0.25,
        "factors": {
            "adjusted_net_profit_growth_acceleration_ttm": 1.0,
            "revenue_growth_acceleration_ttm": 1.0,
            "return_on_equity_change_yoy_ttm": 1.0,
            "sales_gross_margin_change_yoy_ttm": 1.0,
        },
    },
    "growth_research_score": {
        "name": "成长研发分",
        "weight": 0.10,
        "factors": {
            "research_expense_growth_yoy_ttm": 1.0,
            "research_expense_to_revenue_ttm": 1.0,
        },
    },
}

DERIVED_FACTOR_NAME_MAP: dict[str, str] = {}
for _raw_name, _raw_key in RAW_FACTOR_NAME_MAP.items():
    DERIVED_FACTOR_NAME_MAP[f"{_raw_name}_百分位"] = f"{_raw_key}_percentile"
    DERIVED_FACTOR_NAME_MAP[f"{_raw_name}_标准分"] = f"{_raw_key}_standard_score"
for _pillar_key, _pillar in PILLAR_CONFIG.items():
    DERIVED_FACTOR_NAME_MAP[str(_pillar["name"])] = _pillar_key
DERIVED_FACTOR_NAME_MAP.update(
    {
        "成长风格原始得分": "growth_style_raw_score",
        "成长风格标准分": "growth_style_standard_score",
        "成长风格百分位": "growth_style_percentile",
        "成长数据完整度": "growth_data_completeness",
        "成长风格基础分": "growth_style_base_score",
        "成长数据缺失扣分": "growth_data_missing_penalty",
        "成长风格评分": "growth_style_score",
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
    numeric = frame.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    valid_counts = numeric.notna().sum(axis=1)
    ranks = numeric.rank(axis=1, method="average", na_option="keep")
    percentiles = ranks.sub(0.5).div(valid_counts.replace(0, np.nan), axis=0)
    percentiles.loc[valid_counts < int(min_valid_count), :] = np.nan

    values = percentiles.to_numpy(dtype=float)
    scores = np.full(values.shape, np.nan, dtype=float)
    valid = np.isfinite(values)
    scores[valid] = norm.ppf(values[valid])
    scores = np.clip(scores, -float(score_clip), float(score_clip))
    score_frame = pd.DataFrame(scores, index=percentiles.index, columns=percentiles.columns)
    return percentiles.astype(float), score_frame.astype(float)


def _weighted_available_score(
    frames: dict[str, pd.DataFrame],
    weights: dict[str, float],
    *,
    minimum_inputs: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    keys = list(weights)
    if not keys:
        raise ValueError("合成因子至少需要一个输入")
    template = frames[keys[0]]
    numerator = pd.DataFrame(0.0, index=template.index, columns=template.columns)
    denominator = pd.DataFrame(0.0, index=template.index, columns=template.columns)
    valid_count = pd.DataFrame(0, index=template.index, columns=template.columns, dtype=np.int16)
    for key, raw_weight in weights.items():
        frame = frames[key]
        valid = frame.notna()
        weight = float(raw_weight)
        numerator = numerator.add(frame.fillna(0.0) * weight)
        denominator = denominator.add(valid.astype(float) * weight)
        valid_count = valid_count.add(valid.astype(np.int16))
    result = numerator.div(denominator.where(denominator > 0))
    completeness = valid_count.astype(float) / float(len(keys))
    return result.where(valid_count >= int(minimum_inputs)), completeness


def _align_raw_factor_frames(
    raw_factor_dfs: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    missing = [key for key in RAW_FACTOR_NAME_MAP.values() if key not in raw_factor_dfs]
    if missing:
        raise ValueError(f"缺少成长原始因子: {', '.join(missing)}")
    all_indexes = [pd.DatetimeIndex(pd.to_datetime(raw_factor_dfs[key].index)).floor("D") for key in RAW_FACTOR_NAME_MAP.values()]
    all_columns = [pd.Index(raw_factor_dfs[key].columns.astype(str)) for key in RAW_FACTOR_NAME_MAP.values()]
    index = all_indexes[0]
    columns = all_columns[0]
    for item in all_indexes[1:]:
        index = index.union(item)
    for item in all_columns[1:]:
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


def build_growth_normalized_factor_bundle(
    raw_factor_dfs: dict[str, pd.DataFrame],
    *,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
) -> dict[str, object]:
    aligned = _align_raw_factor_frames(raw_factor_dfs)
    factor_dfs: dict[str, pd.DataFrame] = {}
    standard_frames: dict[str, pd.DataFrame] = {}

    for raw_key in RAW_FACTOR_NAME_MAP.values():
        percentiles, standard_scores = cross_sectional_rank_normalize(
            aligned[raw_key], min_valid_count=min_valid_count
        )
        factor_dfs[f"{raw_key}_percentile"] = percentiles
        factor_dfs[f"{raw_key}_standard_score"] = standard_scores
        standard_frames[raw_key] = standard_scores

    pillar_frames: dict[str, pd.DataFrame] = {}
    pillar_completeness_frames: dict[str, pd.DataFrame] = {}
    for pillar_key, config in PILLAR_CONFIG.items():
        weights = dict(config["factors"])
        pillar, pillar_completeness = _weighted_available_score(
            standard_frames,
            weights,
            minimum_inputs=1,
        )
        pillar_frames[pillar_key] = pillar
        pillar_completeness_frames[pillar_key] = pillar_completeness
        factor_dfs[pillar_key] = pillar

    template = next(iter(pillar_frames.values()))
    composite_numerator = pd.DataFrame(0.0, index=template.index, columns=template.columns)
    weighted_completeness = pd.DataFrame(0.0, index=template.index, columns=template.columns)
    for pillar_key, config in PILLAR_CONFIG.items():
        effective_weight = pillar_completeness_frames[pillar_key] * float(config["weight"])
        composite_numerator = composite_numerator.add(
            pillar_frames[pillar_key].fillna(0.0) * effective_weight
        )
        weighted_completeness = weighted_completeness.add(effective_weight)

    weighted_completeness = weighted_completeness.clip(lower=0.0, upper=1.0)
    weighted_completeness = weighted_completeness.mask(
        weighted_completeness.abs() < 1e-12, 0.0
    ).mask(
        (weighted_completeness - 1.0).abs() < 1e-12, 1.0
    )
    eligible = weighted_completeness >= MIN_GROWTH_DATA_COMPLETENESS
    raw_composite = composite_numerator.div(weighted_completeness.where(weighted_completeness > 0))
    raw_composite = raw_composite.where(eligible)
    composite_percentile, composite_standard = cross_sectional_rank_normalize(
        raw_composite, min_valid_count=min_valid_count
    )
    completeness_output = weighted_completeness * 100.0
    base_score = composite_percentile * 100.0
    missing_penalty = (
        base_score * MISSING_DATA_PENALTY_RATE * (1.0 - weighted_completeness)
    ).clip(lower=0.0)
    missing_penalty = missing_penalty.where(base_score.notna())
    final_score = (base_score - missing_penalty).clip(lower=0.0, upper=100.0)

    factor_dfs["growth_style_raw_score"] = raw_composite
    factor_dfs["growth_style_standard_score"] = composite_standard
    factor_dfs["growth_style_percentile"] = composite_percentile
    factor_dfs["growth_data_completeness"] = completeness_output
    factor_dfs["growth_style_base_score"] = base_score
    factor_dfs["growth_data_missing_penalty"] = missing_penalty
    factor_dfs["growth_style_score"] = final_score
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


def load_raw_growth_factor_dfs(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    stock_codes: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, pd.DataFrame]:
    """读取成长原始因子的 merged 与 part；同键按文件顺序保留最新 part。"""
    start_dt = pd.Timestamp(start_date).floor("D")
    end_dt = pd.Timestamp(end_date).floor("D")
    if start_dt > end_dt:
        raise ValueError(f"start_date 不能晚于 end_date: {start_dt.date()} > {end_dt.date()}")
    allowed_codes = (
        {str(code).strip().upper() for code in stock_codes if _is_a_share_code(code)}
        if stock_codes is not None
        else None
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
        long_frame["time"] = pd.to_datetime(long_frame["time"], errors="coerce").dt.floor("D")
        long_frame["htsc_code"] = long_frame["htsc_code"].astype(str).str.strip().str.upper()
        long_frame["value"] = pd.to_numeric(long_frame["value"], errors="coerce")
        long_frame = long_frame[
            long_frame["time"].between(start_dt, end_dt)
            & long_frame["htsc_code"].map(_is_a_share_code)
        ]
        if allowed_codes is not None:
            long_frame = long_frame[long_frame["htsc_code"].isin(allowed_codes)]
        long_frame = long_frame.sort_values("_file_order").drop_duplicates(
            ["time", "htsc_code"], keep="last"
        )
        wide = long_frame.pivot(index="time", columns="htsc_code", values="value").sort_index()
        wide.columns.name = None
        output[factor_key] = wide.astype(float)

    if missing_factors:
        raise FileNotFoundError(
            "以下成长原始因子在目标月份没有 parquet: " + "、".join(missing_factors)
        )
    return output


def build_stock_growth_normalized_factor_bundle(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    stock_codes: set[str] | list[str] | tuple[str, ...] | None = None,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
) -> dict[str, object]:
    raw_factor_dfs = load_raw_growth_factor_dfs(
        base_dir=base_dir,
        start_date=start_date,
        end_date=end_date,
        stock_codes=stock_codes,
    )
    return build_growth_normalized_factor_bundle(
        raw_factor_dfs,
        min_valid_count=min_valid_count,
    )
