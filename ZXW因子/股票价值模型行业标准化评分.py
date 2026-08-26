# -*- coding: utf-8 -*-
"""基于 THS 881 行业生成价值模型综合评分（行业标准化）。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


BUNDLE_ID = "stock_value_model_industry_normalized"
DEFAULT_SIGNAL_BASE_DIR = Path(r"D:\database\signal_daily")
DEFAULT_INDUSTRY_SNAPSHOT_DIR = Path(
    r"D:\database\sector_information\constituent_snapshots_eligible"
)
MODEL_START_DATE = pd.Timestamp("2010-01-01")
DEFAULT_MIN_INDUSTRY_COUNT = 3
MIN_VALID_FACTORS = 4
MISSING_PENALTY_RATE = 0.50

RAW_FACTOR_NAME_MAP = {
    "盈利收益率_EY_TTM": "earnings_yield_ttm",
    "账面市值比_BM": "book_to_market_ratio",
    "销售收益率_SY_TTM": "sales_yield_ttm",
    "经营现金流收益率_OCFY_TTM": "operating_cashflow_yield_ttm",
    "自由现金流收益率_FCFY_TTM": "free_cashflow_yield_ttm",
    "净现金市值比": "net_cash_to_market_value",
}

INPUT_FACTOR_WEIGHTS = {
    "earnings_yield_ttm": 1.0 / 6.0,
    "book_to_market_ratio": 1.0 / 6.0,
    "sales_yield_ttm": 1.0 / 6.0,
    "operating_cashflow_yield_ttm": 0.15,
    "free_cashflow_yield_ttm": 0.15,
    "net_cash_to_market_value": 0.20,
}

FACTOR_NAME_MAP = {
    "价值模型综合评分(行业标准化)": (
        "value_model_composite_score_industry_normalized"
    )
}


def get_factor_catalog() -> dict[str, dict[str, str]]:
    return {"factor_name_map": dict(FACTOR_NAME_MAP)}


def get_factor_lookback_config() -> dict[str, object]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": 0,
        "factor_lookback_days": {
            "value_model_composite_score_industry_normalized": 0
        },
        "source_history_start": str(MODEL_START_DATE.date()),
        "industry_snapshot_policy": "latest_available_fixed",
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


def load_ths881_industry_snapshots(
    *,
    snapshot_dir: str | Path = DEFAULT_INDUSTRY_SNAPSHOT_DIR,
    end_date: str | pd.Timestamp,
    latest_only: bool = False,
) -> pd.DataFrame:
    root = Path(snapshot_dir)
    end_dt = pd.Timestamp(end_date).floor("D")
    files: list[tuple[pd.Timestamp, Path]] = []
    for path in sorted(root.glob("analysis_date=*/*.parquet")):
        match = re.fullmatch(r"analysis_date=(\d{4}-\d{2}-\d{2})", path.parent.name)
        if match is None:
            continue
        partition_date = pd.Timestamp(match.group(1)).floor("D")
        if latest_only or partition_date <= end_dt:
            files.append((partition_date, path))
    if not files:
        raise FileNotFoundError(f"没有找到行业快照 parquet: {root}")
    if latest_only:
        latest_date = max(partition_date for partition_date, _ in files)
        files = [item for item in files if item[0] == latest_date]
    frames: list[pd.DataFrame] = []
    for partition_date, path in files:
        frame = pd.read_parquet(
            path,
            columns=["analysis_date", "sector_code", "stock_code", "eligible"],
        )
        parsed_dates = pd.to_datetime(frame["analysis_date"], errors="coerce").dt.floor("D")
        if parsed_dates.isna().any() or not parsed_dates.eq(partition_date).all():
            raise ValueError(
                f"行业快照分区日期与 analysis_date 不一致: {path}"
            )
        frame["analysis_date"] = parsed_dates
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True)
    result["stock_code"] = result["stock_code"].astype(str).str.strip().str.upper()
    result["industry_code"] = (
        result["sector_code"].astype(str).str.strip().str.upper().str.removesuffix(".THS")
    )
    result = result[
        result["eligible"].fillna(False).astype(bool)
        & (result["analysis_date"].le(end_dt) | latest_only)
        & result["stock_code"].map(_is_a_share_code)
        & result["industry_code"].str.fullmatch(r"881\d{3}", na=False)
    ][["analysis_date", "stock_code", "industry_code"]].drop_duplicates()
    conflicts = (
        result.groupby(["analysis_date", "stock_code"])["industry_code"]
        .nunique()
        .loc[lambda values: values > 1]
    )
    if not conflicts.empty:
        examples = "、".join(
            f"{date.date()} {code}" for date, code in conflicts.index[:10]
        )
        raise ValueError(f"同一股票同日对应多个 881 行业: {examples}")
    return result.sort_values(["analysis_date", "stock_code"]).reset_index(drop=True)


def build_industry_frame(
    *,
    dates: pd.DatetimeIndex,
    stock_codes: pd.Index,
    snapshots: pd.DataFrame,
    fixed_latest: bool = False,
) -> pd.DataFrame:
    normalized_dates = pd.DatetimeIndex(pd.to_datetime(dates)).floor("D")
    normalized_codes = pd.Index(stock_codes.astype(str))
    output = pd.DataFrame(
        np.nan, index=normalized_dates, columns=normalized_codes, dtype=object
    )
    if snapshots.empty:
        return output
    data = snapshots.copy()
    data["analysis_date"] = pd.to_datetime(data["analysis_date"]).dt.floor("D")
    snapshot_dates = pd.DatetimeIndex(data["analysis_date"].unique()).sort_values()
    mappings = {
        snapshot_date: group.set_index("stock_code")["industry_code"]
        for snapshot_date, group in data.groupby("analysis_date", sort=True)
    }
    if fixed_latest:
        mapping = mappings[pd.Timestamp(snapshot_dates[-1])]
        fixed_values = normalized_codes.map(mapping).to_numpy(dtype=object)
        for score_date in normalized_dates.unique():
            output.loc[score_date] = fixed_values
        return output
    for score_date in normalized_dates.unique():
        position = snapshot_dates.searchsorted(score_date, side="right") - 1
        if position < 0:
            continue
        mapping = mappings[pd.Timestamp(snapshot_dates[position])]
        output.loc[score_date] = normalized_codes.map(mapping).to_numpy(dtype=object)
    return output


def industry_percentile_rank(
    frame: pd.DataFrame,
    industry_frame: pd.DataFrame,
    *,
    min_industry_count: int = DEFAULT_MIN_INDUSTRY_COUNT,
) -> pd.DataFrame:
    if min_industry_count < 1:
        raise ValueError("min_industry_count 必须大于等于 1")
    numeric = frame.apply(pd.to_numeric, errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    industries = industry_frame.reindex(index=numeric.index, columns=numeric.columns)
    output = pd.DataFrame(np.nan, index=numeric.index, columns=numeric.columns)
    for date in numeric.index:
        labels = industries.loc[date].dropna()
        for _, codes in labels.groupby(labels).groups.items():
            values = numeric.loc[date, list(codes)].dropna()
            if len(values) < int(min_industry_count):
                continue
            output.loc[date, values.index] = (
                values.rank(method="average") - 0.5
            ) / float(len(values))
    return output.astype(float)


def _align_raw_factor_frames(
    raw_factor_dfs: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    missing = [key for key in RAW_FACTOR_NAME_MAP.values() if key not in raw_factor_dfs]
    if missing:
        raise ValueError("缺少价值原始因子: " + "、".join(missing))
    indexes = [pd.DatetimeIndex(pd.to_datetime(raw_factor_dfs[key].index)).floor("D") for key in RAW_FACTOR_NAME_MAP.values()]
    columns_list = [pd.Index(raw_factor_dfs[key].columns.astype(str)) for key in RAW_FACTOR_NAME_MAP.values()]
    index = indexes[0]
    columns = columns_list[0]
    for item in indexes[1:]:
        index = index.union(item)
    for item in columns_list[1:]:
        columns = columns.union(item)
    aligned: dict[str, pd.DataFrame] = {}
    for key in RAW_FACTOR_NAME_MAP.values():
        item = raw_factor_dfs[key].copy()
        item.index = pd.DatetimeIndex(pd.to_datetime(item.index)).floor("D")
        item.columns = item.columns.astype(str)
        if item.index.has_duplicates:
            raise ValueError(f"{key} 存在重复日期")
        if item.columns.has_duplicates:
            raise ValueError(f"{key} 存在重复股票列")
        aligned[key] = item.reindex(
            index=index.sort_values(), columns=columns.sort_values()
        )
    return aligned


def build_value_model_industry_normalized_score(
    raw_factor_dfs: dict[str, pd.DataFrame],
    industry_frame: pd.DataFrame,
    *,
    min_industry_count: int = DEFAULT_MIN_INDUSTRY_COUNT,
    min_valid_factors: int = MIN_VALID_FACTORS,
) -> dict[str, object]:
    if not 1 <= int(min_valid_factors) <= len(INPUT_FACTOR_WEIGHTS):
        raise ValueError("min_valid_factors 必须在 1 至 6 之间")
    aligned = _align_raw_factor_frames(raw_factor_dfs)
    percentiles = {
        key: industry_percentile_rank(
            frame,
            industry_frame,
            min_industry_count=min_industry_count,
        )
        for key, frame in aligned.items()
    }
    template = next(iter(percentiles.values()))
    valid_count = pd.DataFrame(0, index=template.index, columns=template.columns)
    valid_weight = pd.DataFrame(0.0, index=template.index, columns=template.columns)
    weighted_sum = pd.DataFrame(0.0, index=template.index, columns=template.columns)
    for key, weight in INPUT_FACTOR_WEIGHTS.items():
        valid = percentiles[key].notna()
        valid_count = valid_count.add(valid.astype(int))
        valid_weight = valid_weight.add(valid.astype(float) * float(weight))
        weighted_sum = weighted_sum.add(percentiles[key].fillna(0.0) * float(weight))
    raw_composite = weighted_sum.div(valid_weight.where(valid_weight > 0.0))
    eligible = valid_count >= int(min_valid_factors)
    raw_composite = raw_composite.where(eligible)
    final_percentile = industry_percentile_rank(
        raw_composite,
        industry_frame,
        min_industry_count=min_industry_count,
    )
    base_score = final_percentile * 100.0
    score = base_score * (1.0 - MISSING_PENALTY_RATE * (1.0 - valid_weight))
    model_date_mask = pd.Series(
        score.index >= MODEL_START_DATE,
        index=score.index,
        dtype=bool,
    )
    score = score.where(eligible).where(model_date_mask, axis=0)
    score = score.clip(0.0, 100.0)
    return {
        "bundle_id": BUNDLE_ID,
        "factor_dfs": {
            "value_model_composite_score_industry_normalized": score.astype(float)
        },
        "factor_name_map": dict(FACTOR_NAME_MAP),
    }


def load_raw_value_factor_dfs(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    start_dt = pd.Timestamp(start_date).floor("D")
    end_dt = pd.Timestamp(end_date).floor("D")
    root = Path(base_dir)
    output: dict[str, pd.DataFrame] = {}
    for factor_name, factor_key in RAW_FACTOR_NAME_MAP.items():
        files: list[Path] = []
        for month_dir in _month_directories(root / f"factor={factor_key}", start_dt, end_dt):
            merged = month_dir / "merged.parquet"
            if merged.is_file():
                files.append(merged)
            files.extend(sorted(month_dir.glob("part_*.parquet")))
        if not files:
            raise FileNotFoundError(f"{factor_name} 在目标区间没有 parquet")
        frames = []
        for order, path in enumerate(files):
            item = pd.read_parquet(path, columns=["time", "htsc_code", "value"])
            item["time"] = pd.to_datetime(item["time"], errors="coerce").dt.floor("D")
            item["htsc_code"] = item["htsc_code"].astype(str).str.strip().str.upper()
            item["value"] = pd.to_numeric(item["value"], errors="coerce")
            item = item[
                item["time"].between(start_dt, end_dt)
                & item["htsc_code"].map(_is_a_share_code)
            ]
            conflicts = (
                item.groupby(["time", "htsc_code"])["value"]
                .nunique(dropna=False)
                .loc[lambda values: values > 1]
            )
            if not conflicts.empty:
                raise ValueError(f"同一文件存在冲突重复键: {path}")
            item = item.drop_duplicates(["time", "htsc_code", "value"])
            item["_file_order"] = order
            frames.append(item)
        long = (
            pd.concat(frames, ignore_index=True)
            .sort_values("_file_order")
            .drop_duplicates(["time", "htsc_code"], keep="last")
        )
        output[factor_key] = long.pivot(
            index="time", columns="htsc_code", values="value"
        ).sort_index().astype(float)
    return output


def build_stock_value_model_industry_normalized_score_bundle(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    snapshot_dir: str | Path = DEFAULT_INDUSTRY_SNAPSHOT_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> dict[str, object]:
    start_dt = max(pd.Timestamp(start_date).floor("D"), MODEL_START_DATE)
    end_dt = pd.Timestamp(end_date).floor("D")
    if start_dt > end_dt:
        raise ValueError("目标区间早于首个 THS881 行业快照")
    raw = load_raw_value_factor_dfs(
        base_dir=base_dir, start_date=start_dt, end_date=end_dt
    )
    aligned = _align_raw_factor_frames(raw)
    template = next(iter(aligned.values()))
    snapshots = load_ths881_industry_snapshots(
        snapshot_dir=snapshot_dir, end_date=end_dt, latest_only=True
    )
    industries = build_industry_frame(
        dates=template.index,
        stock_codes=template.columns,
        snapshots=snapshots,
        fixed_latest=True,
    )
    return build_value_model_industry_normalized_score(raw, industries)
