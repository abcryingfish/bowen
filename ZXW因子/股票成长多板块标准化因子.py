# -*- coding: utf-8 -*-
"""基于 THS 885/886 板块生成成长风格综合评分（多板块标准化）。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import norm


BUNDLE_ID = "stock_growth_multi_board_normalized"
DEFAULT_SIGNAL_BASE_DIR = Path(r"D:\database\signal_daily")
DEFAULT_BOARD_SNAPSHOT_DIR = Path(
    r"D:\database\sector_information\constituent_snapshots_eligible"
)
MODEL_START_DATE = pd.Timestamp("2026-07-15")
DEFAULT_MIN_BOARD_COUNT = 20
STANDARD_SCORE_CLIP = 3.0
MIN_GROWTH_DATA_COMPLETENESS = 0.40
MISSING_DATA_PENALTY_RATE = 0.50

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
        "weight": 0.30,
        "factors": {
            "revenue_growth_yoy_ttm": 1.0,
            "revenue_cagr_3y_ttm": 1.0,
            "operating_profit_growth_yoy_ttm": 1.0,
        },
    },
    "growth_profit_score": {
        "weight": 0.35,
        "factors": {
            "adjusted_net_profit_growth_yoy_ttm": 1.0,
            "basic_eps_growth_yoy_ttm": 1.0,
            "operating_cashflow_growth_yoy_ttm": 1.0,
        },
    },
    "growth_quality_score": {
        "weight": 0.25,
        "factors": {
            "adjusted_net_profit_growth_acceleration_ttm": 1.0,
            "revenue_growth_acceleration_ttm": 1.0,
            "return_on_equity_change_yoy_ttm": 1.0,
            "sales_gross_margin_change_yoy_ttm": 1.0,
        },
    },
    "growth_research_score": {
        "weight": 0.10,
        "factors": {
            "research_expense_growth_yoy_ttm": 1.0,
            "research_expense_to_revenue_ttm": 1.0,
        },
    },
}

FACTOR_NAME_MAP = {
    "成长风格综合评分(多板块标准化)": (
        "growth_style_composite_score_multi_board_normalized"
    )
}

_MEMBERSHIP_KEYS = ["time", "stock_code", "board_code"]


def get_factor_catalog() -> dict[str, dict[str, str]]:
    return {"factor_name_map": dict(FACTOR_NAME_MAP)}


def get_factor_lookback_config() -> dict[str, object]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": 0,
        "factor_lookback_days": {
            "growth_style_composite_score_multi_board_normalized": 0
        },
        "source_history_start": str(MODEL_START_DATE.date()),
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


def load_ths_multi_board_snapshots(
    *,
    snapshot_dir: str | Path = DEFAULT_BOARD_SNAPSHOT_DIR,
    end_date: str | pd.Timestamp,
) -> pd.DataFrame:
    """读取不晚于 end_date 的 885/886 多板块成分快照。"""
    root = Path(snapshot_dir)
    end_dt = pd.Timestamp(end_date).floor("D")
    files: list[tuple[pd.Timestamp, Path]] = []
    for path in sorted(root.glob("analysis_date=*/*.parquet")):
        match = re.fullmatch(r"analysis_date=(\d{4}-\d{2}-\d{2})", path.parent.name)
        if match is None:
            continue
        partition_date = pd.Timestamp(match.group(1)).floor("D")
        if partition_date <= end_dt:
            files.append((partition_date, path))
    if not files:
        raise FileNotFoundError(f"没有找到板块快照 parquet: {root}")

    frames: list[pd.DataFrame] = []
    for partition_date, path in files:
        frame = pd.read_parquet(
            path,
            columns=["analysis_date", "sector_code", "stock_code", "eligible"],
        )
        parsed_dates = pd.to_datetime(frame["analysis_date"], errors="coerce").dt.floor("D")
        if parsed_dates.isna().any() or not parsed_dates.eq(partition_date).all():
            raise ValueError(f"板块快照分区日期与 analysis_date 不一致: {path}")
        frame["analysis_date"] = parsed_dates
        frames.append(frame)

    result = pd.concat(frames, ignore_index=True)
    result["stock_code"] = result["stock_code"].astype(str).str.strip().str.upper()
    result["board_code"] = (
        result["sector_code"].astype(str).str.strip().str.upper().str.removesuffix(".THS")
    )
    result = result[
        result["eligible"].fillna(False).astype(bool)
        & result["analysis_date"].le(end_dt)
        & result["stock_code"].map(_is_a_share_code)
        & result["board_code"].str.fullmatch(r"(?:885|886)\d{3}", na=False)
    ][["analysis_date", "stock_code", "board_code"]]
    return (
        result.drop_duplicates()
        .sort_values(["analysis_date", "stock_code", "board_code"])
        .reset_index(drop=True)
    )


def build_board_memberships(
    *,
    dates: pd.DatetimeIndex,
    stock_codes: pd.Index,
    snapshots: pd.DataFrame,
) -> pd.DataFrame:
    """按评分日选择最近非未来快照，并展开多对多股票板块关系。"""
    score_dates = pd.DatetimeIndex(pd.to_datetime(dates)).floor("D").unique().sort_values()
    normalized_codes = pd.Index(stock_codes.astype(str).str.strip().str.upper()).unique()
    empty = pd.DataFrame(columns=_MEMBERSHIP_KEYS)
    if len(score_dates) == 0 or snapshots.empty:
        return empty

    data = snapshots.copy()
    data["analysis_date"] = pd.to_datetime(data["analysis_date"], errors="coerce").dt.floor("D")
    data["stock_code"] = data["stock_code"].astype(str).str.strip().str.upper()
    data["board_code"] = data["board_code"].astype(str).str.strip().str.upper()
    data = data[
        data["analysis_date"].notna()
        & data["stock_code"].isin(normalized_codes)
        & data["board_code"].str.fullmatch(r"(?:885|886)\d{3}", na=False)
    ].drop_duplicates(["analysis_date", "stock_code", "board_code"])
    if data.empty:
        return empty

    snapshot_dates = pd.DatetimeIndex(data["analysis_date"].unique()).sort_values()
    selected: dict[pd.Timestamp, list[pd.Timestamp]] = {}
    for score_date in score_dates:
        position = snapshot_dates.searchsorted(score_date, side="right") - 1
        if position >= 0:
            selected.setdefault(pd.Timestamp(snapshot_dates[position]), []).append(
                pd.Timestamp(score_date)
            )

    frames: list[pd.DataFrame] = []
    for snapshot_date, selected_dates in selected.items():
        members = data.loc[
            data["analysis_date"].eq(snapshot_date), ["stock_code", "board_code"]
        ]
        if members.empty:
            continue
        expanded = pd.DataFrame({"time": selected_dates}).merge(members, how="cross")
        frames.append(expanded[_MEMBERSHIP_KEYS])
    if not frames:
        return empty
    return (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(_MEMBERSHIP_KEYS)
        .sort_values(_MEMBERSHIP_KEYS)
        .reset_index(drop=True)
    )


def _normalize_memberships(memberships: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in _MEMBERSHIP_KEYS if column not in memberships.columns]
    if missing:
        raise ValueError("板块成员关系缺少列: " + "、".join(missing))
    result = memberships[_MEMBERSHIP_KEYS].copy()
    result["time"] = pd.to_datetime(result["time"], errors="coerce").dt.floor("D")
    result["stock_code"] = result["stock_code"].astype(str).str.strip().str.upper()
    result["board_code"] = result["board_code"].astype(str).str.strip().str.upper()
    result = result[
        result["time"].notna()
        & result["stock_code"].map(_is_a_share_code)
        & result["board_code"].str.fullmatch(r"(?:885|886)\d{3}", na=False)
    ]
    return result.drop_duplicates(_MEMBERSHIP_KEYS).sort_values(_MEMBERSHIP_KEYS)


def _empty_board_series(name: str) -> pd.Series:
    index = pd.MultiIndex.from_arrays([[], [], []], names=_MEMBERSHIP_KEYS)
    return pd.Series(dtype=float, index=index, name=name)


def board_rank_normalize(
    frame: pd.DataFrame,
    memberships: pd.DataFrame,
    *,
    min_board_count: int = DEFAULT_MIN_BOARD_COUNT,
    score_clip: float = STANDARD_SCORE_CLIP,
) -> tuple[pd.Series, pd.Series]:
    """按日期和板块计算平均名次百分位与逆正态分。"""
    if min_board_count < 1:
        raise ValueError("min_board_count 必须大于等于 1")
    numeric = frame.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    numeric.index = pd.DatetimeIndex(pd.to_datetime(numeric.index)).floor("D")
    numeric.columns = numeric.columns.astype(str).str.strip().str.upper()
    long = (
        numeric.rename_axis("time")
        .reset_index()
        .melt(id_vars="time", var_name="stock_code", value_name="value")
        .dropna(subset=["value"])
    )
    expanded = _normalize_memberships(memberships).merge(
        long,
        on=["time", "stock_code"],
        how="inner",
        validate="many_to_one",
    )
    if expanded.empty:
        return _empty_board_series("percentile"), _empty_board_series("score")

    groups = expanded.groupby(["time", "board_code"], sort=False)["value"]
    expanded["valid_count"] = groups.transform("count")
    expanded = expanded[expanded["valid_count"] >= int(min_board_count)].copy()
    if expanded.empty:
        return _empty_board_series("percentile"), _empty_board_series("score")
    expanded["rank"] = expanded.groupby(
        ["time", "board_code"], sort=False
    )["value"].rank(method="average")
    expanded["percentile"] = (
        expanded["rank"] - 0.5
    ) / expanded["valid_count"].astype(float)
    expanded["score"] = np.clip(
        norm.ppf(expanded["percentile"].to_numpy(dtype=float)),
        -score_clip,
        score_clip,
    )
    indexed = expanded.set_index(_MEMBERSHIP_KEYS).sort_index()
    return indexed["percentile"].astype(float), indexed["score"].astype(float)


def _rank_board_series(
    values: pd.Series,
    *,
    min_board_count: int,
) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if numeric.empty:
        return _empty_board_series("percentile")
    counts = numeric.groupby(level=["time", "board_code"]).transform("count")
    numeric = numeric[counts >= int(min_board_count)]
    counts = counts.loc[numeric.index]
    if numeric.empty:
        return _empty_board_series("percentile")
    ranks = numeric.groupby(level=["time", "board_code"]).rank(method="average")
    return ((ranks - 0.5) / counts.astype(float)).rename("percentile")


def _align_raw_factor_frames(
    raw_factor_dfs: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    missing = [key for key in RAW_FACTOR_NAME_MAP.values() if key not in raw_factor_dfs]
    if missing:
        raise ValueError("缺少成长原始因子: " + "、".join(missing))
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

    aligned: dict[str, pd.DataFrame] = {}
    for key in RAW_FACTOR_NAME_MAP.values():
        item = raw_factor_dfs[key].copy()
        item.index = pd.DatetimeIndex(pd.to_datetime(item.index)).floor("D")
        item.columns = item.columns.astype(str)
        if item.index.has_duplicates:
            raise ValueError(f"{key} 存在重复日期")
        if item.columns.has_duplicates:
            raise ValueError(f"{key} 存在重复股票列")
        aligned[key] = item.reindex(index=index.sort_values(), columns=columns.sort_values())
    return aligned


def _weighted_available_score(
    frames: pd.DataFrame,
    weights: dict[str, float],
) -> tuple[pd.Series, pd.Series]:
    selected = frames.reindex(columns=list(weights))
    valid = selected.notna()
    weight_series = pd.Series(weights, dtype=float)
    denominator = valid.mul(weight_series, axis=1).sum(axis=1)
    numerator = selected.fillna(0.0).mul(weight_series, axis=1).sum(axis=1)
    score = numerator.div(denominator.where(denominator > 0.0))
    completeness = valid.sum(axis=1) / float(len(weights))
    return score, completeness


def average_board_scores(
    board_scores: pd.Series,
    *,
    dates: pd.DatetimeIndex,
    stock_codes: pd.Index,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    normalized_dates = pd.DatetimeIndex(pd.to_datetime(dates)).floor("D").sort_values()
    normalized_codes = pd.Index(stock_codes.astype(str)).sort_values()
    score_template = pd.DataFrame(np.nan, index=normalized_dates, columns=normalized_codes)
    count_template = pd.DataFrame(0, index=normalized_dates, columns=normalized_codes, dtype=int)
    numeric = pd.to_numeric(board_scores, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if numeric.empty:
        return score_template, count_template
    grouped = numeric.groupby(level=["time", "stock_code"])
    average = grouped.mean().unstack("stock_code")
    count = grouped.count().unstack("stock_code")
    average = average.reindex(index=normalized_dates, columns=normalized_codes)
    count = count.reindex(index=normalized_dates, columns=normalized_codes).fillna(0).astype(int)
    return average.astype(float), count


def build_growth_multi_board_normalized_factor_bundle(
    raw_factor_dfs: dict[str, pd.DataFrame],
    memberships: pd.DataFrame,
    *,
    min_board_count: int = DEFAULT_MIN_BOARD_COUNT,
) -> dict[str, object]:
    aligned = _align_raw_factor_frames(raw_factor_dfs)
    normalized_memberships = _normalize_memberships(memberships)
    board_index = pd.MultiIndex.from_frame(normalized_memberships[_MEMBERSHIP_KEYS])
    standard_frames = pd.concat(
        {
            key: board_rank_normalize(
                frame,
                normalized_memberships,
                min_board_count=min_board_count,
            )[1]
            for key, frame in aligned.items()
        },
        axis=1,
    ).reindex(board_index)

    pillar_frames: dict[str, pd.Series] = {}
    pillar_completeness: dict[str, pd.Series] = {}
    for pillar_key, config in PILLAR_CONFIG.items():
        pillar_frames[pillar_key], pillar_completeness[pillar_key] = (
            _weighted_available_score(standard_frames, dict(config["factors"]))
        )

    numerator = pd.Series(0.0, index=board_index)
    completeness = pd.Series(0.0, index=board_index)
    for pillar_key, config in PILLAR_CONFIG.items():
        effective_weight = pillar_completeness[pillar_key] * float(config["weight"])
        numerator = numerator.add(pillar_frames[pillar_key].fillna(0.0) * effective_weight)
        completeness = completeness.add(effective_weight)
    completeness = completeness.clip(0.0, 1.0)
    eligible = completeness >= MIN_GROWTH_DATA_COMPLETENESS
    raw_composite = numerator.div(completeness.where(completeness > 0.0)).where(eligible)
    composite_percentile = _rank_board_series(
        raw_composite,
        min_board_count=min_board_count,
    )
    base_score = composite_percentile * 100.0
    board_score = (
        base_score - base_score * MISSING_DATA_PENALTY_RATE * (1.0 - completeness)
    ).where(eligible).clip(0.0, 100.0)
    date_mask = board_score.index.get_level_values("time") >= MODEL_START_DATE
    board_score = board_score.where(date_mask)

    template = next(iter(aligned.values()))
    final_score, valid_board_count = average_board_scores(
        board_score,
        dates=template.index,
        stock_codes=template.columns,
    )
    return {
        "bundle_id": BUNDLE_ID,
        "factor_dfs": {
            "growth_style_composite_score_multi_board_normalized": final_score
        },
        "factor_name_map": dict(FACTOR_NAME_MAP),
        "diagnostics": {"valid_board_count": valid_board_count},
    }


def load_raw_growth_factor_dfs(
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
        frames: list[pd.DataFrame] = []
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


def build_stock_growth_multi_board_normalized_factor_bundle(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    snapshot_dir: str | Path = DEFAULT_BOARD_SNAPSHOT_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> dict[str, object]:
    start_dt = max(pd.Timestamp(start_date).floor("D"), MODEL_START_DATE)
    end_dt = pd.Timestamp(end_date).floor("D")
    if start_dt > end_dt:
        raise ValueError("目标区间早于首个 THS 多板块快照")
    raw = load_raw_growth_factor_dfs(
        base_dir=base_dir,
        start_date=start_dt,
        end_date=end_dt,
    )
    aligned = _align_raw_factor_frames(raw)
    template = next(iter(aligned.values()))
    snapshots = load_ths_multi_board_snapshots(
        snapshot_dir=snapshot_dir,
        end_date=end_dt,
    )
    memberships = build_board_memberships(
        dates=template.index,
        stock_codes=template.columns,
        snapshots=snapshots,
    )
    return build_growth_multi_board_normalized_factor_bundle(raw, memberships)
