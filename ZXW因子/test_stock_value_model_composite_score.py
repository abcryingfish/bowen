from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from 股票价值模型综合评分 import (
    INPUT_FACTOR_NAME_MAP,
    build_stock_value_model_composite_score_bundle,
    build_value_model_composite_score,
    get_factor_catalog,
    load_value_percentile_factor_dfs,
)


def _frames(values: dict[str, float], date: str = "2025-06-03") -> dict[str, pd.DataFrame]:
    index = pd.to_datetime([date])
    return {
        key: pd.DataFrame({"000001.SZ": [values.get(key, np.nan)]}, index=index)
        for key in INPUT_FACTOR_NAME_MAP.values()
    }


def test_full_six_factor_score_uses_approved_weights_without_penalty() -> None:
    values = {
        "earnings_yield_ttm_percentile": 0.9,
        "book_to_market_ratio_percentile": 0.8,
        "sales_yield_ttm_percentile": 0.7,
        "operating_cashflow_yield_ttm_percentile": 0.6,
        "free_cashflow_yield_ttm_percentile": 0.5,
        "net_cash_to_market_value_percentile": 0.4,
    }

    result = build_value_model_composite_score(_frames(values))
    actual = result["factor_dfs"]["value_model_composite_score"].iloc[0, 0]
    expected = (
        0.9 / 6
        + 0.8 / 6
        + 0.7 / 6
        + 0.6 * 0.15
        + 0.5 * 0.15
        + 0.4 * 0.20
    ) * 100

    assert actual == pytest.approx(expected)


@pytest.mark.parametrize(
    ("missing_key", "expected_completeness"),
    [
        ("net_cash_to_market_value_percentile", 0.80),
        ("earnings_yield_ttm_percentile", 5 / 6),
    ],
)
def test_missing_factor_applies_weighted_penalty(
    missing_key: str,
    expected_completeness: float,
) -> None:
    values = {key: 0.8 for key in INPUT_FACTOR_NAME_MAP.values()}
    values[missing_key] = np.nan

    result = build_value_model_composite_score(_frames(values))
    actual = result["factor_dfs"]["value_model_composite_score"].iloc[0, 0]

    assert actual == pytest.approx(80 * (0.5 + 0.5 * expected_completeness))


def test_exactly_four_factors_score_but_three_factors_do_not() -> None:
    keys = list(INPUT_FACTOR_NAME_MAP.values())
    four_values = {key: (0.5 if i < 4 else np.nan) for i, key in enumerate(keys)}
    three_values = {key: (0.5 if i < 3 else np.nan) for i, key in enumerate(keys)}
    four = build_value_model_composite_score(_frames(four_values))
    three = build_value_model_composite_score(_frames(three_values))

    assert np.isfinite(four["factor_dfs"]["value_model_composite_score"].iloc[0, 0])
    assert np.isnan(three["factor_dfs"]["value_model_composite_score"].iloc[0, 0])


def test_nonfinite_values_are_missing_but_out_of_range_values_raise() -> None:
    values = {key: 0.5 for key in INPUT_FACTOR_NAME_MAP.values()}
    values["earnings_yield_ttm_percentile"] = np.inf
    result = build_value_model_composite_score(_frames(values))
    assert np.isfinite(result["factor_dfs"]["value_model_composite_score"].iloc[0, 0])

    values["earnings_yield_ttm_percentile"] = 1.01
    with pytest.raises(ValueError, match="百分位必须在"):
        build_value_model_composite_score(_frames(values))


def test_dates_before_2015_are_not_scored() -> None:
    values = {key: 0.5 for key in INPUT_FACTOR_NAME_MAP.values()}
    result = build_value_model_composite_score(_frames(values, date="2014-12-31"))

    assert np.isnan(result["factor_dfs"]["value_model_composite_score"].iloc[0, 0])


def test_loader_uses_latest_part_for_duplicate_key(tmp_path: Path) -> None:
    for factor_name in INPUT_FACTOR_NAME_MAP:
        month_dir = tmp_path / f"factor={factor_name}" / "year=2025" / "month=06"
        month_dir.mkdir(parents=True)
        base = pd.DataFrame(
            {
                "time": [pd.Timestamp("2025-06-03")],
                "htsc_code": ["000001.SZ"],
                "value": [0.2],
            }
        )
        base.to_parquet(month_dir / "merged.parquet", index=False)
        if factor_name == "盈利收益率_EY_TTM_百分位":
            base.assign(value=0.8).to_parquet(month_dir / "part_new.parquet", index=False)

    frames = load_value_percentile_factor_dfs(
        base_dir=tmp_path,
        start_date="2025-06-01",
        end_date="2025-06-30",
    )

    assert frames["earnings_yield_ttm_percentile"].iloc[0, 0] == 0.8


def test_bundle_catalog_generator_and_factor_catalog_contracts() -> None:
    catalog = get_factor_catalog()["factor_name_map"]
    assert catalog == {"价值模型综合评分": "value_model_composite_score"}

    module_dir = Path(__file__).resolve().parent
    generator = (module_dir / "ZXW策略技术因子生成.py").read_text(encoding="utf-8")
    assert '"stock_value_model"' in generator
    assert "build_stock_value_model_composite_score_bundle" in generator
    assert "_run_stock_value_model_post_write" in generator

    groups = {
        group["group_id"]: group
        for group in json.loads(
            (module_dir.parent / "因子分类" / "factor_catalog.json").read_text(
                encoding="utf-8"
            )
        )["groups"]
    }
    assert groups["stock_value_model"]["children"] == ["价值模型综合评分"]


def test_disk_bundle_builds_only_the_composite_factor(tmp_path: Path) -> None:
    for factor_name in INPUT_FACTOR_NAME_MAP:
        month_dir = tmp_path / f"factor={factor_name}" / "year=2025" / "month=06"
        month_dir.mkdir(parents=True)
        pd.DataFrame(
            {
                "time": [pd.Timestamp("2025-06-03")],
                "htsc_code": ["000001.SZ"],
                "value": [0.5],
            }
        ).to_parquet(month_dir / "merged.parquet", index=False)

    result = build_stock_value_model_composite_score_bundle(
        base_dir=tmp_path,
        start_date="2025-06-01",
        end_date="2025-06-30",
    )

    assert set(result["factor_dfs"]) == {"value_model_composite_score"}
