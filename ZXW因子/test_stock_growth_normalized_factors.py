from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from 股票成长标准化因子 import (
    DERIVED_FACTOR_NAME_MAP,
    RAW_FACTOR_NAME_MAP,
    build_growth_normalized_factor_bundle,
    cross_sectional_rank_normalize,
    load_raw_growth_factor_dfs,
)


def test_cross_sectional_rank_then_inverse_normal_keeps_missing_and_averages_ties() -> None:
    date = pd.Timestamp("2026-08-03")
    raw = pd.DataFrame(
        [[10.0, 20.0, 20.0, 40.0, np.nan]],
        index=[date],
        columns=["000001.SZ", "000002.SZ", "000003.SZ", "600000.SH", "600001.SH"],
    )

    percentiles, scores = cross_sectional_rank_normalize(raw, min_valid_count=4)

    expected_percentiles = [0.125, 0.5, 0.5, 0.875]
    assert percentiles.loc[date, raw.columns[:4]].tolist() == pytest.approx(expected_percentiles)
    assert scores.loc[date, raw.columns[:4]].tolist() == pytest.approx(
        [norm.ppf(value) for value in expected_percentiles]
    )
    assert pd.isna(percentiles.loc[date, "600001.SH"])
    assert pd.isna(scores.loc[date, "600001.SH"])


def test_cross_sectional_rank_requires_minimum_valid_stock_count() -> None:
    raw = pd.DataFrame(
        [[1.0, 2.0, np.nan]],
        index=[pd.Timestamp("2026-08-03")],
        columns=["000001.SZ", "000002.SZ", "000003.SZ"],
    )

    percentiles, scores = cross_sectional_rank_normalize(raw, min_valid_count=3)

    assert percentiles.isna().all().all()
    assert scores.isna().all().all()


def test_growth_pillars_use_available_inputs_and_adjust_composite_weights() -> None:
    date = pd.Timestamp("2026-08-03")
    codes = ["000001.SZ", "000002.SZ", "000003.SZ"]
    raw_factor_dfs: dict[str, pd.DataFrame] = {}
    for factor_key in RAW_FACTOR_NAME_MAP.values():
        raw_factor_dfs[factor_key] = pd.DataFrame(
            [[1.0, 2.0, 3.0]], index=[date], columns=codes
        )

    # 规模支柱保留 2/3 个输入；盈利支柱只保留 1/3，仍应计算但降低合成权重。
    raw_factor_dfs["operating_profit_growth_yoy_ttm"].loc[date, "000002.SZ"] = np.nan
    raw_factor_dfs["adjusted_net_profit_growth_yoy_ttm"].loc[date, "000002.SZ"] = np.nan
    raw_factor_dfs["basic_eps_growth_yoy_ttm"].loc[date, "000002.SZ"] = np.nan

    result = build_growth_normalized_factor_bundle(raw_factor_dfs, min_valid_count=2)

    factor_dfs = result["factor_dfs"]
    assert result["bundle_id"] == "stock_growth_normalized"
    assert set(result["factor_name_map"]) == set(DERIVED_FACTOR_NAME_MAP)
    assert np.isfinite(factor_dfs["growth_scale_score"].loc[date, "000002.SZ"])
    assert np.isfinite(factor_dfs["growth_profit_score"].loc[date, "000002.SZ"])
    assert np.isfinite(factor_dfs["growth_style_raw_score"].loc[date, "000002.SZ"])

    # 规模完整率=2/3、盈利完整率=1/3，支柱权重按完整率缩减后再归一。
    expected = (
        factor_dfs["growth_scale_score"].loc[date, "000002.SZ"] * (0.30 * 2 / 3)
        + factor_dfs["growth_profit_score"].loc[date, "000002.SZ"] * (0.35 / 3)
        + factor_dfs["growth_quality_score"].loc[date, "000002.SZ"] * 0.25
        + factor_dfs["growth_research_score"].loc[date, "000002.SZ"] * 0.10
    ) / (0.30 * 2 / 3 + 0.35 / 3 + 0.25 + 0.10)
    assert factor_dfs["growth_style_raw_score"].loc[date, "000002.SZ"] == pytest.approx(expected)


def test_growth_score_applies_weighted_completeness_gate_and_missing_penalty() -> None:
    date = pd.Timestamp("2026-08-03")
    codes = ["000001.SZ", "000002.SZ", "000003.SZ", "600000.SH"]
    raw_factor_dfs = {
        factor_key: pd.DataFrame([[1.0, 2.0, 3.0, 4.0]], index=[date], columns=codes)
        for factor_key in RAW_FACTOR_NAME_MAP.values()
    }

    # 第一只仅规模支柱的 1/3 有效，Q=10%，低于综合评分门槛。
    for factor_key in RAW_FACTOR_NAME_MAP.values():
        if factor_key != "revenue_growth_yoy_ttm":
            raw_factor_dfs[factor_key].loc[date, "000001.SZ"] = np.nan

    # 第二只：规模1/3、盈利3/3、质量2/4、研发0/2，Q=57.5%。
    keep_for_second = {
        "revenue_growth_yoy_ttm",
        "adjusted_net_profit_growth_yoy_ttm",
        "basic_eps_growth_yoy_ttm",
        "operating_cashflow_growth_yoy_ttm",
        "revenue_growth_acceleration_ttm",
        "return_on_equity_change_yoy_ttm",
    }
    for factor_key in RAW_FACTOR_NAME_MAP.values():
        if factor_key not in keep_for_second:
            raw_factor_dfs[factor_key].loc[date, "000002.SZ"] = np.nan

    result = build_growth_normalized_factor_bundle(raw_factor_dfs, min_valid_count=2)
    factor_dfs = result["factor_dfs"]

    assert factor_dfs["growth_data_completeness"].loc[date, "000001.SZ"] == pytest.approx(10.0)
    assert pd.isna(factor_dfs["growth_style_raw_score"].loc[date, "000001.SZ"])
    assert pd.isna(factor_dfs["growth_style_score"].loc[date, "000001.SZ"])

    completeness = 0.30 / 3 + 0.35 + 0.25 * 2 / 4
    assert completeness == pytest.approx(0.575)
    assert factor_dfs["growth_data_completeness"].loc[date, "000002.SZ"] == pytest.approx(
        completeness * 100
    )
    base_score = factor_dfs["growth_style_percentile"].loc[date, "000002.SZ"] * 100
    penalty = base_score * 0.5 * (1 - completeness)
    assert factor_dfs["growth_style_base_score"].loc[date, "000002.SZ"] == pytest.approx(base_score)
    assert factor_dfs["growth_data_missing_penalty"].loc[date, "000002.SZ"] == pytest.approx(penalty)
    assert factor_dfs["growth_style_score"].loc[date, "000002.SZ"] == pytest.approx(
        max(0.0, base_score - penalty)
    )
    assert factor_dfs["growth_data_completeness"].loc[date, "000003.SZ"] == 100.0
    assert factor_dfs["growth_data_missing_penalty"].loc[date, "000003.SZ"] == 0.0


def _write_factor_partition(
    base_dir: Path,
    factor_name: str,
    merged: pd.DataFrame,
    part: pd.DataFrame | None = None,
) -> None:
    month_dir = base_dir / f"factor={factor_name}" / "year=2026" / "month=08"
    month_dir.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(month_dir / "merged.parquet", index=False)
    if part is not None:
        part.to_parquet(month_dir / "part_new.parquet", index=False)


def test_loader_reads_raw_factor_library_and_latest_part_wins(tmp_path: Path) -> None:
    date = pd.Timestamp("2026-08-03")
    for factor_name in RAW_FACTOR_NAME_MAP:
        merged = pd.DataFrame(
            {
                "time": [date, date, date],
                "htsc_code": ["000001.SZ", "000002.SZ", "000001.THS"],
                "value": [1.0, 2.0, 999.0],
            }
        )
        part = None
        if factor_name == "营业收入同比_TTM":
            part = pd.DataFrame(
                {"time": [date], "htsc_code": ["000001.SZ"], "value": [9.0]}
            )
        _write_factor_partition(tmp_path, factor_name, merged, part)

    result = load_raw_growth_factor_dfs(
        base_dir=tmp_path,
        start_date=date,
        end_date=date,
    )

    revenue = result["revenue_growth_yoy_ttm"]
    assert revenue.loc[date, "000001.SZ"] == pytest.approx(9.0)
    assert revenue.loc[date, "000002.SZ"] == pytest.approx(2.0)
    assert "000001.THS" not in revenue.columns
    assert set(result) == set(RAW_FACTOR_NAME_MAP.values())


def test_normalized_growth_bundle_is_wired_to_generator_and_frontend_catalog() -> None:
    project_root = Path(__file__).resolve().parents[1]
    generator_source = (project_root / "ZXW因子" / "ZXW策略技术因子生成.py").read_text(
        encoding="utf-8"
    )
    catalog = json.loads(
        (project_root / "因子分类" / "factor_catalog.json").read_text(encoding="utf-8")
    )

    assert '"stock_growth_normalized"' in generator_source
    assert "build_stock_growth_normalized_factor_bundle" in generator_source
    groups = {group["group_id"]: group for group in catalog["groups"]}
    group = groups["stock_growth_normalized"]
    assert group["group_name"] == "股票成长标准化与风格因子"
    assert set(group["children"]) == set(DERIVED_FACTOR_NAME_MAP)
