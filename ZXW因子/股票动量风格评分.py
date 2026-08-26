# -*- coding: utf-8 -*-
"""从股票 12-1 月与 6-1 月动量生成 0-100 风格评分。"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
from typing import Iterable


BUNDLE_ID = "stock_momentum_style"
DEFAULT_SIGNAL_BASE_DIR = Path(r"D:\database\signal_daily")
DEFAULT_MARKET_BASE_DIR = Path(r"D:\database\stock_basic_data_daily")
DEFAULT_MIN_VALID_STOCKS = 100
LONG_WEIGHT = 0.70
MEDIUM_WEIGHT = 0.30
INPUT_FACTOR_NAMES = {
    "momentum_12_1": "252日纯动量",
    "momentum_6_1": "纯动量",
}
INPUT_FACTOR_KEYS = {
    "momentum_12_1": "pure_momentum_252d",
    "momentum_6_1": "pure_momentum",
}
FACTOR_NAME_MAP = {"动量风格评分": "momentum_style_score"}


def get_factor_catalog() -> dict[str, dict[str, str]]:
    return {"factor_name_map": dict(FACTOR_NAME_MAP)}


def get_factor_lookback_config() -> dict[str, object]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": 0,
        "factor_lookback_days": {"momentum_style_score": 0},
        "source_history_start": "2010-01-01",
    }


def _as_finite_frame(value: pd.DataFrame) -> pd.DataFrame:
    frame = value.copy()
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index)).floor("D")
    frame.columns = frame.columns.astype(str)
    frame = frame[~frame.index.duplicated(keep="last")]
    return (
        frame.apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .astype(float)
    )


def _normalize_range(
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    start_dt = pd.Timestamp(start_date).floor("D")
    end_dt = pd.Timestamp(end_date).floor("D")
    if start_dt > end_dt:
        raise ValueError(
            f"start_date 不能晚于 end_date: {start_dt.date()} > {end_dt.date()}"
        )
    return start_dt, end_dt


def _month_starts(
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> Iterable[pd.Timestamp]:
    cursor = pd.Timestamp(start_date.year, start_date.month, 1)
    end_month = pd.Timestamp(end_date.year, end_date.month, 1)
    while cursor <= end_month:
        yield cursor
        cursor += pd.offsets.MonthBegin(1)


def load_saved_factor_frame(
    *,
    base_dir: str | Path,
    factor_name: str,
    factor_key: str,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> pd.DataFrame:
    """读取因子月分区，按文件顺序让最新 part 覆盖同键旧值。"""
    start_dt, end_dt = _normalize_range(start_date, end_date)
    factor_dir = Path(base_dir) / f"factor={factor_key}"
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
    long_frame = long_frame[long_frame["time"].between(start_dt, end_dt)]
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


def load_stock_valid_bar(
    *,
    base_dir: str | Path,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> pd.DataFrame:
    """从股票日线库读取真实行情掩码，并以其代码列定义股票范围。"""
    start_dt, end_dt = _normalize_range(start_date, end_date)
    files: list[Path] = []
    missing_months: list[str] = []
    for month_start in _month_starts(start_dt, end_dt):
        path = (
            Path(base_dir)
            / f"year={month_start.year}"
            / f"month={month_start.month:02d}"
            / "merged.parquet"
        )
        if path.is_file():
            files.append(path)
        else:
            missing_months.append(month_start.strftime("%Y-%m"))
    if missing_months:
        raise FileNotFoundError(
            "股票日线缺少月份分区: " + "、".join(missing_months)
        )

    frames = [
        pd.read_parquet(path, columns=["time", "htsc_code", "close"])
        for path in files
    ]
    long_frame = pd.concat(frames, ignore_index=True)
    long_frame["time"] = pd.to_datetime(
        long_frame["time"], errors="coerce"
    ).dt.floor("D")
    long_frame["htsc_code"] = (
        long_frame["htsc_code"].astype(str).str.strip().str.upper()
    )
    long_frame["close"] = pd.to_numeric(long_frame["close"], errors="coerce")
    long_frame = long_frame[long_frame["time"].between(start_dt, end_dt)]
    long_frame = long_frame.drop_duplicates(["time", "htsc_code"], keep="last")
    wide = long_frame.pivot(
        index="time",
        columns="htsc_code",
        values="close",
    ).sort_index()
    wide.columns.name = None
    values = wide.to_numpy(dtype=float)
    return pd.DataFrame(
        np.isfinite(values),
        index=wide.index,
        columns=wide.columns,
    )


def build_momentum_style_score_bundle(
    momentum_12_1: pd.DataFrame,
    momentum_6_1: pd.DataFrame,
    *,
    valid_bar: pd.DataFrame,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
) -> dict[str, object]:
    """分别排名两个动量周期，再按 70%/30% 合成股票动量评分。"""
    if int(min_valid_count) < 1:
        raise ValueError("min_valid_count 必须大于等于 1")

    long_frame, medium_frame = _as_finite_frame(momentum_12_1).align(
        _as_finite_frame(momentum_6_1), join="outer"
    )
    valid = valid_bar.reindex(
        index=long_frame.index,
        columns=long_frame.columns,
    ).eq(True)
    joint_valid = valid & long_frame.notna() & medium_frame.notna()
    long_frame = long_frame.where(joint_valid)
    medium_frame = medium_frame.where(joint_valid)
    valid_counts = joint_valid.sum(axis=1)

    denominator = valid_counts.replace(0, np.nan)
    long_rank = long_frame.rank(axis=1, method="average", na_option="keep")
    medium_rank = medium_frame.rank(axis=1, method="average", na_option="keep")
    long_score = long_rank.sub(0.5).div(denominator, axis=0) * 100.0
    medium_score = medium_rank.sub(0.5).div(denominator, axis=0) * 100.0
    score = LONG_WEIGHT * long_score + MEDIUM_WEIGHT * medium_score
    score.loc[valid_counts < int(min_valid_count), :] = np.nan

    return {
        "bundle_id": BUNDLE_ID,
        "factor_dfs": {"momentum_style_score": score.astype(float)},
        "factor_name_map": dict(FACTOR_NAME_MAP),
    }


def build_stock_momentum_style_bundle(
    *,
    signal_base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    market_base_dir: str | Path = DEFAULT_MARKET_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
) -> dict[str, object]:
    """从落盘原始因子与真实股票日线构造动量风格评分。"""
    momentum_12_1 = load_saved_factor_frame(
        base_dir=signal_base_dir,
        factor_name=INPUT_FACTOR_NAMES["momentum_12_1"],
        factor_key=INPUT_FACTOR_KEYS["momentum_12_1"],
        start_date=start_date,
        end_date=end_date,
    )
    momentum_6_1 = load_saved_factor_frame(
        base_dir=signal_base_dir,
        factor_name=INPUT_FACTOR_NAMES["momentum_6_1"],
        factor_key=INPUT_FACTOR_KEYS["momentum_6_1"],
        start_date=start_date,
        end_date=end_date,
    )
    valid_bar = load_stock_valid_bar(
        base_dir=market_base_dir,
        start_date=start_date,
        end_date=end_date,
    )
    stock_columns = valid_bar.columns
    return build_momentum_style_score_bundle(
        momentum_12_1.reindex(columns=stock_columns),
        momentum_6_1.reindex(columns=stock_columns),
        valid_bar=valid_bar,
        min_valid_count=min_valid_count,
    )
