from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from 股票红利标准化因子 import (
    BASE_SCORE_WEIGHTS,
    DERIVED_FACTOR_NAME_MAP,
    RAW_FACTOR_NAME_MAP,
    build_dividend_normalized_factor_bundle,
    cross_sectional_rank_normalize,
    load_raw_dividend_factor_dfs,
)


def test_cross_sectional_rank_normalize_averages_ties_and_keeps_missing() -> None:
    date = pd.Timestamp("2026-08-04")
    raw = pd.DataFrame(
        [[10.0, 20.0, 20.0, 40.0, np.nan]],
        index=[date],
        columns=["000001.SZ", "000002.SZ", "000003.SZ", "600000.SH", "600001.SH"],
    )

    percentiles, scores = cross_sectional_rank_normalize(raw, min_valid_count=4)

    expected = [0.125, 0.5, 0.5, 0.875]
    assert percentiles.loc[date, raw.columns[:4]].tolist() == pytest.approx(expected)
    assert scores.loc[date, raw.columns[:4]].tolist() == pytest.approx(
        [norm.ppf(value) for value in expected]
    )
    assert pd.isna(percentiles.loc[date, "600001.SH"])
    assert pd.isna(scores.loc[date, "600001.SH"])


def test_dividend_base_score_uses_confirmed_weights_and_reverses_cut_count() -> None:
    date = pd.Timestamp("2026-08-04")
    codes = ["000001.SZ", "000002.SZ", "000003.SZ", "600000.SH"]
    raw_factor_dfs = {
        key: pd.DataFrame([[1.0, 2.0, 3.0, 4.0]], index=[date], columns=codes)
        for key in RAW_FACTOR_NAME_MAP.values()
    }

    result = build_dividend_normalized_factor_bundle(
        raw_factor_dfs,
        min_valid_count=4,
    )
    factors = result["factor_dfs"]
    code = "000002.SZ"
    expected = 0.0
    for factor_key, weight in BASE_SCORE_WEIGHTS.items():
        score = factors[f"{factor_key}_standard_score"].loc[date, code]
        expected += score * weight
    assert factors["dividend_base_raw_score"].loc[date, code] == pytest.approx(expected)
    assert factors["dividend_base_score"].loc[date, code] == pytest.approx(
        factors["dividend_base_percentile"].loc[date, code] * 100.0
    )


def test_dividend_base_score_requires_yield_and_renormalizes_available_weights() -> None:
    date = pd.Timestamp("2026-08-04")
    codes = ["000001.SZ", "000002.SZ", "000003.SZ"]
    raw_factor_dfs = {
        key: pd.DataFrame([[1.0, 2.0, 3.0]], index=[date], columns=codes)
        for key in RAW_FACTOR_NAME_MAP.values()
    }
    raw_factor_dfs["cash_dividend_cagr_3y"].loc[date, "000002.SZ"] = np.nan
    raw_factor_dfs["cash_dividend_cut_count_5y"].loc[date, "000002.SZ"] = np.nan
    raw_factor_dfs["realized_dividend_yield_ttm"].loc[date, "000003.SZ"] = np.nan

    result = build_dividend_normalized_factor_bundle(
        raw_factor_dfs,
        min_valid_count=2,
    )
    factors = result["factor_dfs"]
    code = "000002.SZ"
    expected = (
        factors["realized_dividend_yield_ttm_standard_score"].loc[date, code] * 0.35
        + factors["cash_dividend_active_year_ratio_5y_standard_score"].loc[date, code] * 0.25
        + factors["cash_dividend_consecutive_years_standard_score"].loc[date, code] * 0.20
    ) / 0.80
    assert factors["dividend_base_raw_score"].loc[date, code] == pytest.approx(expected)
    assert pd.isna(factors["dividend_base_raw_score"].loc[date, "000003.SZ"])


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


def test_loader_reads_latest_raw_dividend_parts_and_filters_non_stocks(tmp_path: Path) -> None:
    date = pd.Timestamp("2026-08-04")
    for factor_name in RAW_FACTOR_NAME_MAP:
        merged = pd.DataFrame(
            {
                "time": [date, date, date],
                "htsc_code": ["000001.SZ", "000002.SZ", "000001.THS"],
                "value": [1.0, 2.0, 999.0],
            }
        )
        part = None
        if factor_name == "已实施股息率_TTM":
            part = pd.DataFrame(
                {"time": [date], "htsc_code": ["000001.SZ"], "value": [9.0]}
            )
        _write_factor_partition(tmp_path, factor_name, merged, part)

    result = load_raw_dividend_factor_dfs(
        base_dir=tmp_path,
        start_date=date,
        end_date=date,
    )

    dividend_yield = result["realized_dividend_yield_ttm"]
    assert dividend_yield.loc[date, "000001.SZ"] == pytest.approx(9.0)
    assert dividend_yield.loc[date, "000002.SZ"] == pytest.approx(2.0)
    assert "000001.THS" not in dividend_yield.columns


def test_dividend_normalized_bundle_is_wired_to_generator_and_catalog() -> None:
    project_root = Path(__file__).resolve().parents[1]
    generator = (project_root / "ZXW因子" / "ZXW策略技术因子生成.py").read_text(
        encoding="utf-8"
    )
    catalog = json.loads(
        (project_root / "因子分类" / "factor_catalog.json").read_text(encoding="utf-8")
    )

    assert '"stock_dividend_normalized"' in generator
    assert "build_stock_dividend_normalized_factor_bundle" in generator
    groups = {group["group_id"]: group for group in catalog["groups"]}
    group = groups["stock_dividend_normalized"]
    assert group["group_name"] == "股票红利标准化与基础分"
    assert set(group["children"]) == set(DERIVED_FACTOR_NAME_MAP)
    assert "连续分红年数_近5年_百分位" in group["children"]
    assert "连续分红年数_近5年_标准分" in group["children"]
