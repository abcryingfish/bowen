# -*- coding: utf-8 -*-
"""从六个价值百分位因子生成单票价值模型综合评分。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


BUNDLE_ID = "stock_value_model"
DEFAULT_SIGNAL_BASE_DIR = Path(r"D:\database\signal_daily")
MODEL_START_DATE = pd.Timestamp("2015-01-01")
MIN_VALID_FACTORS = 4
MISSING_PENALTY_RATE = 0.50

INPUT_FACTOR_NAME_MAP = {
    "盈利收益率_EY_TTM_百分位": "earnings_yield_ttm_percentile",
    "账面市值比_BM_百分位": "book_to_market_ratio_percentile",
    "销售收益率_SY_TTM_百分位": "sales_yield_ttm_percentile",
    "经营现金流收益率_OCFY_TTM_百分位": "operating_cashflow_yield_ttm_percentile",
    "自由现金流收益率_FCFY_TTM_百分位": "free_cashflow_yield_ttm_percentile",
    "净现金市值比_百分位": "net_cash_to_market_value_percentile",
}

INPUT_FACTOR_WEIGHTS = {
    "earnings_yield_ttm_percentile": 1.0 / 6.0,
    "book_to_market_ratio_percentile": 1.0 / 6.0,
    "sales_yield_ttm_percentile": 1.0 / 6.0,
    "operating_cashflow_yield_ttm_percentile": 0.15,
    "free_cashflow_yield_ttm_percentile": 0.15,
    "net_cash_to_market_value_percentile": 0.20,
}

FACTOR_NAME_MAP = {"价值模型综合评分": "value_model_composite_score"}


def get_factor_catalog() -> dict[str, dict[str, str]]:
    return {"factor_name_map": dict(FACTOR_NAME_MAP)}


def get_factor_lookback_config() -> dict[str, object]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": 0,
        "factor_lookback_days": {"value_model_composite_score": 0},
        "source_history_start": str(MODEL_START_DATE.date()),
    }


def _is_a_share_code(value: object) -> bool:
    return bool(re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", str(value or "").strip().upper()))


def _month_starts(
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> Iterable[pd.Timestamp]:
    cursor = pd.Timestamp(start_date.year, start_date.month, 1)
    end_month = pd.Timestamp(end_date.year, end_date.month, 1)
    while cursor <= end_month:
        yield cursor
        cursor += pd.offsets.MonthBegin(1)


def _align_input_frames(
    percentile_factor_dfs: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    missing = [
        key for key in INPUT_FACTOR_NAME_MAP.values() if key not in percentile_factor_dfs
    ]
    if missing:
        raise ValueError("缺少价值百分位因子: " + "、".join(missing))

    indexes = [
        pd.DatetimeIndex(pd.to_datetime(percentile_factor_dfs[key].index)).floor("D")
        for key in INPUT_FACTOR_NAME_MAP.values()
    ]
    columns_list = [
        pd.Index(percentile_factor_dfs[key].columns.astype(str))
        for key in INPUT_FACTOR_NAME_MAP.values()
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
    for key in INPUT_FACTOR_NAME_MAP.values():
        frame = percentile_factor_dfs[key].copy()
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index)).floor("D")
        frame.columns = frame.columns.astype(str)
        frame = frame[~frame.index.duplicated(keep="last")]
        numeric = frame.reindex(index=index, columns=columns).apply(
            pd.to_numeric,
            errors="coerce",
        )
        finite_values = numeric.to_numpy(dtype=float)
        out_of_range = np.isfinite(finite_values) & (
            (finite_values < 0.0) | (finite_values > 1.0)
        )
        if out_of_range.any():
            raise ValueError(f"{key} 百分位必须在 [0, 1] 范围内")
        aligned[key] = numeric.replace([np.inf, -np.inf], np.nan).astype(float)
    return aligned


def build_value_model_composite_score(
    percentile_factor_dfs: dict[str, pd.DataFrame],
    *,
    min_valid_factors: int = MIN_VALID_FACTORS,
) -> dict[str, object]:
    if not 1 <= int(min_valid_factors) <= len(INPUT_FACTOR_WEIGHTS):
        raise ValueError("min_valid_factors 必须在 1 至 6 之间")

    aligned = _align_input_frames(percentile_factor_dfs)
    first = next(iter(aligned.values()))
    valid_count = pd.DataFrame(0, index=first.index, columns=first.columns, dtype=int)
    valid_weight = pd.DataFrame(0.0, index=first.index, columns=first.columns)
    weighted_sum = pd.DataFrame(0.0, index=first.index, columns=first.columns)

    for key, weight in INPUT_FACTOR_WEIGHTS.items():
        frame = aligned[key]
        valid = frame.notna()
        valid_count = valid_count + valid.astype(int)
        valid_weight = valid_weight + valid.astype(float) * float(weight)
        weighted_sum = weighted_sum + frame.fillna(0.0) * float(weight)

    base_score = weighted_sum.div(valid_weight.where(valid_weight > 0.0)) * 100.0
    score = base_score * (
        1.0 - float(MISSING_PENALTY_RATE) * (1.0 - valid_weight)
    )
    eligible = valid_count.ge(int(min_valid_factors))
    score = score.where(eligible, np.nan)
    model_date_mask = pd.Series(
        score.index >= MODEL_START_DATE,
        index=score.index,
        dtype=bool,
    )
    score = score.where(model_date_mask, np.nan, axis=0)
    score = score.clip(lower=0.0, upper=100.0)

    return {
        "bundle_id": BUNDLE_ID,
        "factor_dfs": {"value_model_composite_score": score.astype(float)},
        "factor_name_map": dict(FACTOR_NAME_MAP),
    }


def load_value_percentile_factor_dfs(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    start_dt = max(pd.Timestamp(start_date).floor("D"), MODEL_START_DATE)
    end_dt = pd.Timestamp(end_date).floor("D")
    if start_dt > end_dt:
        raise ValueError(
            f"start_date 不能晚于 end_date: {start_dt.date()} > {end_dt.date()}"
        )

    root = Path(base_dir)
    output: dict[str, pd.DataFrame] = {}
    for factor_name, factor_key in INPUT_FACTOR_NAME_MAP.items():
        files: list[Path] = []
        missing_months: list[str] = []
        factor_dir = root / f"factor={factor_key}"
        for month_start in _month_starts(start_dt, end_dt):
            month_dir = (
                factor_dir
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
    return output


def build_stock_value_model_composite_score_bundle(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> dict[str, object]:
    frames = load_value_percentile_factor_dfs(
        base_dir=base_dir,
        start_date=start_date,
        end_date=end_date,
    )
    return build_value_model_composite_score(frames)
