from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import pytest

from 股票纯市值风格评分 import (
    FACTOR_NAME_MAP,
    build_size_style_score_bundle,
    build_stock_size_style_pure_bundle,
    get_factor_catalog,
    load_ln_free_float_market_value,
)


def test_size_scores_rank_daily_cross_section_with_average_ties() -> None:
    date = pd.Timestamp("2026-08-03")
    codes = ["000001.SZ", "000002.SZ", "000003.SZ", "600000.SH", "600001.SH"]
    raw = pd.DataFrame(
        [[10.0, 20.0, 20.0, 40.0, np.nan]],
        index=[date],
        columns=codes,
    )

    result = build_size_style_score_bundle(raw, min_valid_count=4)
    large = result["factor_dfs"]["large_cap_style_score_pure"]
    small = result["factor_dfs"]["small_cap_style_score_pure"]

    assert result["bundle_id"] == "stock_size_style_pure"
    assert result["factor_name_map"] == FACTOR_NAME_MAP
    assert large.loc[date, codes[:4]].tolist() == pytest.approx(
        [12.5, 50.0, 50.0, 87.5]
    )
    assert small.loc[date, codes[:4]].tolist() == pytest.approx(
        [87.5, 50.0, 50.0, 12.5]
    )
    assert pd.isna(large.loc[date, "600001.SH"])
    assert pd.isna(small.loc[date, "600001.SH"])
    assert (large + small).dropna(axis=1).to_numpy() == pytest.approx(100.0)


def test_nonfinite_values_are_missing_and_incomplete_day_is_not_scored() -> None:
    dates = pd.to_datetime(["2026-08-03", "2026-08-04"])
    raw = pd.DataFrame(
        [[1.0, 2.0, np.inf, -np.inf], [1.0, 2.0, 3.0, np.nan]],
        index=dates,
        columns=["000001.SZ", "000002.SZ", "000003.SZ", "600000.SH"],
    )

    result = build_size_style_score_bundle(raw, min_valid_count=3)
    large = result["factor_dfs"]["large_cap_style_score_pure"]

    assert large.loc[dates[0]].isna().all()
    assert large.loc[dates[1], "000001.SZ"] == pytest.approx(100.0 / 6.0)
    assert pd.isna(large.loc[dates[1], "600000.SH"])


def test_size_score_rejects_invalid_minimum_stock_count() -> None:
    raw = pd.DataFrame([[1.0]], index=[pd.Timestamp("2026-08-03")])

    with pytest.raises(ValueError, match="min_valid_count"):
        build_size_style_score_bundle(raw, min_valid_count=0)


def test_size_score_catalog_has_only_the_two_approved_outputs() -> None:
    assert get_factor_catalog()["factor_name_map"] == {
        "大市值风格评分（纯市值）": "large_cap_style_score_pure",
        "小市值风格评分（纯市值）": "small_cap_style_score_pure",
    }


def test_loader_reads_merged_and_latest_part_for_shenzhen_shanghai_only(
    tmp_path: Path,
) -> None:
    date = pd.Timestamp("2026-08-03")
    month_dir = (
        tmp_path
        / "factor=ln_自由流通市值"
        / "year=2026"
        / "month=08"
    )
    month_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "time": [date, date, date, date],
            "htsc_code": ["000001.SZ", "600000.SH", "430001.BJ", "000001.THS"],
            "value": [10.0, 20.0, 30.0, 40.0],
        }
    ).to_parquet(month_dir / "merged.parquet", index=False)
    pd.DataFrame(
        {"time": [date], "htsc_code": ["000001.SZ"], "value": [15.0]}
    ).to_parquet(month_dir / "part_001.parquet", index=False)

    frame = load_ln_free_float_market_value(
        base_dir=tmp_path,
        start_date=date,
        end_date=date,
    )

    assert frame.loc[date, "000001.SZ"] == pytest.approx(15.0)
    assert frame.loc[date, "600000.SH"] == pytest.approx(20.0)
    assert set(frame.columns) == {"000001.SZ", "600000.SH"}

    result = build_stock_size_style_pure_bundle(
        base_dir=tmp_path,
        start_date=date,
        end_date=date,
        min_valid_count=2,
    )
    assert result["factor_dfs"]["large_cap_style_score_pure"].loc[
        date, "600000.SH"
    ] == pytest.approx(75.0)


def test_loader_requires_every_requested_month(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="2026-07.*2026-08"):
        load_ln_free_float_market_value(
            base_dir=tmp_path,
            start_date="2026-07-01",
            end_date="2026-08-31",
        )


def test_factor_writer_can_drop_null_and_nonfinite_values_for_sparse_scores() -> None:
    script_path = Path(__file__).with_name("ZXW策略技术因子生成.py")
    tree = ast.parse(script_path.read_text(encoding="utf-8-sig"), filename=str(script_path))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "_factor_month_to_long_polars"
    )
    namespace = {"pd": pd, "pl": pl, "np": np}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(script_path), "exec"), namespace)
    frame = pd.DataFrame(
        [[1.0, np.nan, np.inf]],
        index=[pd.Timestamp("2026-08-03")],
        columns=["000001.SZ", "000002.SZ", "000003.SZ"],
    )

    dense = namespace["_factor_month_to_long_polars"](
        frame,
        pd.Timestamp("2026-08-01"),
        pd.Timestamp("2026-08-31"),
    )
    sparse = namespace["_factor_month_to_long_polars"](
        frame,
        pd.Timestamp("2026-08-01"),
        pd.Timestamp("2026-08-31"),
        drop_null_values=True,
    )

    assert dense.height == 3
    assert sparse.select("htsc_code", "value").to_dicts() == [
        {"htsc_code": "000001.SZ", "value": 1.0}
    ]


def test_post_write_runner_handles_cross_month_single_output_with_sparse_save() -> None:
    script_path = Path(__file__).with_name("ZXW策略技术因子生成.py")
    tree = ast.parse(script_path.read_text(encoding="utf-8-sig"), filename=str(script_path))
    names = {"_month_start_range", "_run_stock_size_style_pure_post_write"}
    nodes = [
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name in names
    ]
    build_calls: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    save_calls: list[dict[str, object]] = []

    def fake_build(**kwargs):
        start = pd.Timestamp(kwargs["start_date"])
        end = pd.Timestamp(kwargs["end_date"])
        build_calls.append((start, end))
        frame = pd.DataFrame({"000001.SZ": [50.0]}, index=[start])
        return {
            "bundle_id": "stock_size_style_pure",
            "factor_dfs": {
                "large_cap_style_score_pure": frame,
                "small_cap_style_score_pure": 100.0 - frame,
            },
        }

    def fake_save(*args, **kwargs):
        save_calls.append({"args": args, "kwargs": kwargs})

    namespace = {
        "pd": pd,
        "SIZE_STYLE_PURE_FACTOR_NAME_MAP": FACTOR_NAME_MAP,
        "build_stock_size_style_pure_bundle": fake_build,
        "save_factor_dfs_to_factor_partitioned_parquet": fake_save,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(script_path), "exec"), namespace)
    plan = pd.DataFrame(
        [
            {
                "factor_en": "small_cap_style_score_pure",
                "status": "stale",
                "plan_start": pd.Timestamp("2026-01-31"),
                "plan_end": pd.Timestamp("2026-02-01"),
            }
        ]
    )

    result = namespace["_run_stock_size_style_pure_post_write"](
        base_dir="unused",
        plan_df=plan,
        factor_last_dt_map=None,
    )

    assert build_calls == [
        (pd.Timestamp("2026-01-31"), pd.Timestamp("2026-01-31")),
        (pd.Timestamp("2026-02-01"), pd.Timestamp("2026-02-01")),
    ]
    assert len(save_calls) == 2
    for call in save_calls:
        factor_dfs = call["args"][0]
        factor_name_map = call["args"][1]
        assert set(factor_dfs) == {"small_cap_style_score_pure"}
        assert factor_name_map == {
            "小市值风格评分（纯市值）": "small_cap_style_score_pure"
        }
        assert call["kwargs"]["drop_null_factor_keys"] == {
            "small_cap_style_score_pure"
        }
    assert set(result["factor_dfs"]) == {"small_cap_style_score_pure"}


def test_size_style_bundle_is_registered_in_generator_and_factor_catalog() -> None:
    project_root = Path(__file__).resolve().parents[1]
    generator = (project_root / "ZXW因子" / "ZXW策略技术因子生成.py").read_text(
        encoding="utf-8"
    )

    assert "get_stock_size_style_pure_lookback_config" in generator
    assert "build_stock_size_style_pure_bundle" in generator
    assert '"stock_size_style_pure"' in generator
    assert "POST_WRITE_DERIVED_BUNDLES" in generator
    assert "STOCK_ONLY_FACTOR_KEYS.update(SIZE_STYLE_PURE_FACTOR_NAME_MAP.values())" in generator
    assert "_run_stock_size_style_pure_post_write" in generator
    assert "drop_null_factor_keys=set(chunk_factor_dfs)" in generator

    catalog = json.loads(
        (project_root / "因子分类" / "factor_catalog.json").read_text(encoding="utf-8")
    )
    groups = {group["group_id"]: group for group in catalog["groups"]}
    group = groups["stock_size_style_pure"]
    expected = ["大市值风格评分（纯市值）", "小市值风格评分（纯市值）"]
    assert group["group_name"] == "股票纯市值风格评分"
    assert group["core_factors"] == expected
    assert group["children"] == expected
