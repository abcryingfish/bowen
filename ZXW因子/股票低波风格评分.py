# -*- coding: utf-8 -*-
"""从七项股票风险指标生成每日低波风格评分。"""
from __future__ import annotations

import re
from numbers import Integral
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


BUNDLE_ID = "stock_low_volatility_style_score"
DEFAULT_SIGNAL_BASE_DIR = Path(r"D:\database\signal_daily")
DEFAULT_MIN_VALID_STOCKS = 100
FACTOR_NAME_MAP = {"低波风格评分": "low_volatility_style_score"}
SOURCE_FACTOR_NAME_MAP = {
    "20日年化波动率": "annual_vol_20d",
    "60日年化波动率_股票": "annual_vol_60d",
    "252日年化波动率": "annual_vol_252d",
    "20日下行波动率": "downside_vol_20d",
    "60日下行波动率": "downside_vol_60d",
    "60日最大回撤": "max_drawdown_60d",
    "14日ATR波动率": "atr_volatility_14d",
}
EFFECTIVE_FACTOR_WEIGHTS = {
    "annual_vol_20d": 0.05,
    "annual_vol_60d": 0.125,
    "annual_vol_252d": 0.075,
    "downside_vol_20d": 0.075,
    "downside_vol_60d": 0.175,
    "max_drawdown_60d": 0.25,
    "atr_volatility_14d": 0.25,
}
_STOCK_CODE_PATTERN = re.compile(
    r"(?:(?:60[0135]\d{3}|68\d{4})\.SH|(?:00[0123]\d{3}|30\d{4})\.SZ)"
)


def get_factor_catalog() -> dict[str, dict[str, str]]:
    return {"factor_name_map": dict(FACTOR_NAME_MAP)}


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": 0,
        "factor_lookback_days": {
            factor_key: 0 for factor_key in FACTOR_NAME_MAP.values()
        },
        "source_history_start": "2010-01-01",
    }


def _month_starts(
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> Iterable[pd.Timestamp]:
    cursor = pd.Timestamp(start_date.year, start_date.month, 1)
    end_month = pd.Timestamp(end_date.year, end_date.month, 1)
    while cursor <= end_month:
        yield cursor
        cursor += pd.offsets.MonthBegin(1)


def _is_sh_sz_stock_code(value: object) -> bool:
    return bool(_STOCK_CODE_PATTERN.fullmatch(str(value or "").strip().upper()))


def _ordered_union(indexes: list[pd.Index]) -> pd.Index:
    values: list[object] = []
    seen: set[object] = set()
    for index in indexes:
        for value in index:
            if value not in seen:
                values.append(value)
                seen.add(value)
    return pd.Index(values)


def _normalize_source_frames(
    factor_frames: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    required_keys = tuple(SOURCE_FACTOR_NAME_MAP.values())
    missing_keys = [key for key in required_keys if key not in factor_frames]
    if missing_keys:
        raise ValueError(f"缺少低波来源因子: {', '.join(missing_keys)}")

    normalized: dict[str, pd.DataFrame] = {}
    for key in required_keys:
        frame = factor_frames[key].copy()
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index)).floor("D")
        frame.columns = frame.columns.astype(str).str.strip().str.upper()
        frame = frame.loc[~frame.index.duplicated(keep="last")]
        frame = frame.loc[:, ~frame.columns.duplicated(keep="last")]
        frame = frame.loc[
            :, [code for code in frame.columns if _is_sh_sz_stock_code(code)]
        ]
        normalized[key] = (
            frame.apply(pd.to_numeric, errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .astype(float)
        )

    all_dates = _ordered_union([frame.index for frame in normalized.values()])
    all_dates = pd.DatetimeIndex(all_dates).sort_values()
    all_codes = _ordered_union([frame.columns for frame in normalized.values()])
    return {
        key: frame.reindex(index=all_dates, columns=all_codes)
        for key, frame in normalized.items()
    }


def load_low_volatility_source_frames(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    """读取七项低波来源因子的完整月份，最新 part 覆盖同键旧值。"""
    start_dt = pd.Timestamp(start_date).floor("D")
    end_dt = pd.Timestamp(end_date).floor("D")
    if start_dt > end_dt:
        raise ValueError(
            f"start_date 不能晚于 end_date: {start_dt.date()} > {end_dt.date()}"
        )

    result: dict[str, pd.DataFrame] = {}
    for factor_name, factor_key in SOURCE_FACTOR_NAME_MAP.items():
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
                frame = pd.read_parquet(
                    path,
                    columns=["time", "htsc_code", "value"],
                )
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


def build_stock_low_volatility_style_bundle(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
) -> dict[str, object]:
    source_frames = load_low_volatility_source_frames(
        base_dir=base_dir,
        start_date=start_date,
        end_date=end_date,
    )
    return build_low_volatility_style_score_bundle(
        source_frames,
        min_valid_count=min_valid_count,
    )


def _inverse_percentile_score(
    risk: pd.DataFrame,
    eligible: pd.DataFrame,
) -> pd.DataFrame:
    masked = risk.where(eligible)
    counts = eligible.sum(axis=1).replace(0, np.nan).astype(float)
    ranks = masked.rank(axis=1, method="average", na_option="keep")
    return ranks.rsub(counts.add(0.5), axis=0).div(counts, axis=0) * 100.0


def build_low_volatility_style_score_bundle(
    factor_frames: dict[str, pd.DataFrame],
    *,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
) -> dict[str, object]:
    """在每日统一完整沪深股票截面中合成低波风格评分。"""
    if (
        isinstance(min_valid_count, bool)
        or not isinstance(min_valid_count, Integral)
        or min_valid_count < 1
    ):
        raise ValueError("min_valid_count 必须是大于等于 1 的整数")
    minimum_count = int(min_valid_count)

    sources = _normalize_source_frames(factor_frames)
    first = next(iter(sources.values()))
    eligible = pd.DataFrame(True, index=first.index, columns=first.columns)
    for frame in sources.values():
        eligible &= frame.notna()
    eligible.loc[eligible.sum(axis=1) < minimum_count, :] = False

    component_scores: dict[str, pd.DataFrame] = {}
    for key, frame in sources.items():
        risk = frame.abs() if key == "max_drawdown_60d" else frame
        component_scores[key] = _inverse_percentile_score(risk, eligible)

    score = pd.DataFrame(0.0, index=first.index, columns=first.columns)
    for key, weight in EFFECTIVE_FACTOR_WEIGHTS.items():
        score = score + component_scores[key] * weight
    score = score.where(eligible).astype(float)

    return {
        "bundle_id": BUNDLE_ID,
        "factor_dfs": {"low_volatility_style_score": score},
        "factor_name_map": dict(FACTOR_NAME_MAP),
        "factor_merge_policies": {
            "low_volatility_style_score": {
                "preserve_columns": True,
                "preserve_nan": True,
            }
        },
    }
