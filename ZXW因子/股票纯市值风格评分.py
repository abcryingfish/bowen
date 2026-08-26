# -*- coding: utf-8 -*-
"""从自由流通市值对数生成互补的纯市值风格评分。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


BUNDLE_ID = "stock_size_style_pure"
DEFAULT_SIGNAL_BASE_DIR = Path(r"D:\database\signal_daily")
DEFAULT_MIN_VALID_STOCKS = 100
INPUT_FACTOR_NAME = "ln_自由流通市值"
INPUT_FACTOR_KEY = "ln_free_float_market_value"
FACTOR_NAME_MAP = {
    "大市值风格评分（纯市值）": "large_cap_style_score_pure",
    "小市值风格评分（纯市值）": "small_cap_style_score_pure",
}


def get_factor_catalog() -> dict[str, dict[str, str]]:
    return {"factor_name_map": dict(FACTOR_NAME_MAP)}


def get_factor_lookback_config() -> dict[str, object]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": 0,
        "factor_lookback_days": {key: 0 for key in FACTOR_NAME_MAP.values()},
        "source_history_start": "2010-01-01",
    }


def _is_sh_sz_stock_code(value: object) -> bool:
    return bool(re.fullmatch(r"\d{6}\.(?:SH|SZ)", str(value or "").strip().upper()))


def _month_starts(
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> Iterable[pd.Timestamp]:
    cursor = pd.Timestamp(start_date.year, start_date.month, 1)
    end_month = pd.Timestamp(end_date.year, end_date.month, 1)
    while cursor <= end_month:
        yield cursor
        cursor += pd.offsets.MonthBegin(1)


def build_size_style_score_bundle(
    ln_free_float_market_value: pd.DataFrame,
    *,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
) -> dict[str, object]:
    """逐日按自由流通市值排名，生成严格互补的 0-100 风格评分。"""
    if int(min_valid_count) < 1:
        raise ValueError("min_valid_count 必须大于等于 1")

    numeric = ln_free_float_market_value.copy()
    numeric.index = pd.DatetimeIndex(pd.to_datetime(numeric.index)).floor("D")
    numeric.columns = numeric.columns.astype(str)
    numeric = numeric[~numeric.index.duplicated(keep="last")]
    numeric = numeric.apply(pd.to_numeric, errors="coerce")
    numeric = numeric.replace([np.inf, -np.inf], np.nan).astype(float)

    valid_counts = numeric.notna().sum(axis=1)
    ranks = numeric.rank(axis=1, method="average", na_option="keep")
    large_score = ranks.sub(0.5).div(valid_counts.replace(0, np.nan), axis=0) * 100.0
    large_score.loc[valid_counts < int(min_valid_count), :] = np.nan
    small_score = 100.0 - large_score

    return {
        "bundle_id": BUNDLE_ID,
        "factor_dfs": {
            "large_cap_style_score_pure": large_score.astype(float),
            "small_cap_style_score_pure": small_score.astype(float),
        },
        "factor_name_map": dict(FACTOR_NAME_MAP),
    }


def load_ln_free_float_market_value(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> pd.DataFrame:
    """读取完整月份的自由流通市值对数，最新 part 覆盖同键旧值。"""
    start_dt = pd.Timestamp(start_date).floor("D")
    end_dt = pd.Timestamp(end_date).floor("D")
    if start_dt > end_dt:
        raise ValueError(
            f"start_date 不能晚于 end_date: {start_dt.date()} > {end_dt.date()}"
        )

    factor_dir = Path(base_dir) / f"factor={INPUT_FACTOR_KEY}"
    files: list[Path] = []
    missing_months: list[str] = []
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
            f"{INPUT_FACTOR_NAME} 缺少月份分区: " + "、".join(missing_months)
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
        & long_frame["htsc_code"].map(_is_sh_sz_stock_code)
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
    return wide.astype(float)


def build_stock_size_style_pure_bundle(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
) -> dict[str, object]:
    frame = load_ln_free_float_market_value(
        base_dir=base_dir,
        start_date=start_date,
        end_date=end_date,
    )
    return build_size_style_score_bundle(
        frame,
        min_valid_count=min_valid_count,
    )
