from __future__ import annotations

import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from 股票价值标准化因子 import (
    DERIVED_FACTOR_NAME_MAP,
    RAW_FACTOR_NAME_MAP,
    build_stock_value_normalized_factor_bundle,
    build_value_normalized_factor_bundle,
    cross_sectional_value_normalize,
    load_raw_value_factor_dfs,
)


def test_mad_winsorization_keeps_missing_and_normalizes_cross_section() -> None:
    date = pd.Timestamp("2026-08-04")
    columns = [
        "000001.SZ",
        "000002.SZ",
        "000003.SZ",
        "000004.SZ",
        "600000.SH",
        "600001.SH",
    ]
    raw = pd.DataFrame(
        [[-100.0, 0.0, 1.0, 2.0, 100.0, np.nan]],
        index=[date],
        columns=columns,
    )

    winsorized, percentiles, scores = cross_sectional_value_normalize(
        raw,
        min_valid_count=5,
        min_coverage_ratio=0.8,
    )

    robust_sigma = 1.4826
    assert winsorized.loc[date, "000001.SZ"] == pytest.approx(1.0 - 3.0 * robust_sigma)
    assert winsorized.loc[date, "600000.SH"] == pytest.approx(1.0 + 3.0 * robust_sigma)
    assert pd.isna(winsorized.loc[date, "600001.SH"])
    expected_low_percentile = 0.1
    assert percentiles.loc[date, "000001.SZ"] == pytest.approx(expected_low_percentile)
    assert scores.loc[date, "000001.SZ"] == pytest.approx(norm.ppf(expected_low_percentile))


def test_mad_zero_uses_quantile_fallback_and_constant_row_is_unchanged() -> None:
    dates = pd.to_datetime(["2026-08-03", "2026-08-04"])
    raw = pd.DataFrame(
        [
            [0.0, 0.0, 0.0, 0.0, 100.0],
            [2.0, 2.0, 2.0, 2.0, 2.0],
        ],
        index=dates,
        columns=["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ", "600000.SH"],
    )

    winsorized, _, _ = cross_sectional_value_normalize(
        raw,
        min_valid_count=5,
        min_coverage_ratio=1.0,
    )

    assert winsorized.loc[dates[0], "600000.SH"] == pytest.approx(96.0)
    assert winsorized.loc[dates[1]].tolist() == pytest.approx([2.0] * 5)


def test_sample_count_and_coverage_ratio_both_gate_all_outputs() -> None:
    dates = pd.to_datetime(["2026-08-03", "2026-08-04"])
    raw = pd.DataFrame(
        [
            [1.0, 2.0, np.nan, np.nan, np.nan, np.nan],
            [1.0, 2.0, 3.0, np.nan, np.nan, np.nan],
        ],
        index=dates,
        columns=[f"00000{i}.SZ" for i in range(1, 7)],
    )

    winsorized, percentiles, scores = cross_sectional_value_normalize(
        raw,
        min_valid_count=3,
        min_coverage_ratio=0.6,
    )

    assert winsorized.isna().all(axis=1).tolist() == [True, True]
    assert percentiles.isna().all(axis=1).tolist() == [True, True]
    assert scores.isna().all(axis=1).tolist() == [True, True]


def test_bundle_outputs_six_factors_times_three_and_keeps_negative_direction() -> None:
    date = pd.Timestamp("2026-08-04")
    codes = ["000001.SZ", "000002.SZ", "000003.SZ", "600000.SH"]
    raw_factor_dfs = {
        factor_key: pd.DataFrame(
            [[-1.0, 0.0, 1.0, 2.0]],
            index=[date],
            columns=codes,
        )
        for factor_key in RAW_FACTOR_NAME_MAP.values()
    }

    result = build_value_normalized_factor_bundle(
        raw_factor_dfs,
        min_valid_count=4,
        min_coverage_ratio=1.0,
    )

    assert result["bundle_id"] == "stock_value_normalized"
    assert set(result["factor_dfs"]) == set(DERIVED_FACTOR_NAME_MAP.values())
    assert len(result["factor_dfs"]) == 18
    earnings_percentile = result["factor_dfs"]["earnings_yield_ttm_percentile"]
    assert earnings_percentile.loc[date, "000001.SZ"] < earnings_percentile.loc[date, "600000.SH"]


def test_public_configuration_rejects_invalid_thresholds() -> None:
    raw = pd.DataFrame([[1.0]], index=[pd.Timestamp("2026-08-04")], columns=["000001.SZ"])

    with pytest.raises(ValueError, match="min_valid_count"):
        cross_sectional_value_normalize(raw, min_valid_count=0)
    with pytest.raises(ValueError, match="min_coverage_ratio"):
        cross_sectional_value_normalize(raw, min_coverage_ratio=0.0)


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


def test_loader_reads_full_a_share_cross_section_and_latest_part_wins(tmp_path: Path) -> None:
    date = pd.Timestamp("2026-08-04")
    for factor_name in RAW_FACTOR_NAME_MAP:
        merged = pd.DataFrame(
            {
                "time": [date, date, date, date],
                "htsc_code": ["000001.SZ", "600000.SH", "430001.BJ", "000001.THS"],
                "value": [1.0, 2.0, 3.0, 999.0],
            }
        )
        part = None
        if factor_name == "盈利收益率_EY_TTM":
            part = pd.DataFrame(
                {"time": [date], "htsc_code": ["000001.SZ"], "value": [9.0]}
            )
        _write_factor_partition(tmp_path, factor_name, merged, part)

    frames = load_raw_value_factor_dfs(
        base_dir=tmp_path,
        start_date=date,
        end_date=date,
    )

    earnings = frames["earnings_yield_ttm"]
    assert earnings.loc[date, "000001.SZ"] == pytest.approx(9.0)
    assert set(earnings.columns) == {"000001.SZ", "600000.SH", "430001.BJ"}
    assert set(frames) == set(RAW_FACTOR_NAME_MAP.values())
    assert "stock_codes" not in inspect.signature(load_raw_value_factor_dfs).parameters
    assert "stock_codes" not in inspect.signature(
        build_stock_value_normalized_factor_bundle
    ).parameters


def test_value_normalized_bundle_is_wired_to_generator_and_catalog() -> None:
    project_root = Path(__file__).resolve().parents[1]
    generator = (project_root / "ZXW因子" / "ZXW策略技术因子生成.py").read_text(
        encoding="utf-8"
    )
    catalog = json.loads(
        (project_root / "因子分类" / "factor_catalog.json").read_text(encoding="utf-8")
    )

    assert '"stock_value_normalized"' in generator
    assert "build_stock_value_normalized_factor_bundle" in generator
    assert "_run_stock_value_normalized_post_write" in generator
    groups = {group["group_id"]: group for group in catalog["groups"]}
    group = groups["stock_value_normalized"]
    assert group["group_name"] == "股票价值去极值与标准化因子"
    assert set(group["children"]) == set(DERIVED_FACTOR_NAME_MAP)
    assert set(group["core_factors"]) == {
        f"{factor_name}_标准分" for factor_name in RAW_FACTOR_NAME_MAP
    }
