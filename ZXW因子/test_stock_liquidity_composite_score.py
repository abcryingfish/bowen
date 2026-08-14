from __future__ import annotations

import ast
import json
import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from 股票流动性综合评分 import (
    FACTOR_NAME_MAP,
    build_liquidity_composite_score_bundle,
    build_stock_liquidity_composite_bundle,
    get_factor_catalog,
    load_liquidity_raw_factor_frames,
)


RAW_FACTOR_KEYS = [
    "avg_trading_value_20d",
    "avg_trading_value_60d",
    "avg_turnover_20d",
    "avg_turnover_60d",
    "amihud_20d",
    "trading_value_volatility_20d",
    "zero_trading_value_ratio_20d",
]


def _aligned_inputs(
    *,
    date: str = "2026-08-03",
    extra_columns: bool = False,
) -> dict[str, pd.DataFrame]:
    columns = ["000001.SZ", "000002.SZ", "000003.SZ", "600000.SH"]
    increasing = [1.0, 2.0, 3.0, 4.0]
    decreasing = [4.0, 3.0, 2.0, 1.0]
    values = {
        "avg_trading_value_20d": increasing,
        "avg_trading_value_60d": increasing,
        "avg_turnover_20d": increasing,
        "avg_turnover_60d": increasing,
        "amihud_20d": decreasing,
        "trading_value_volatility_20d": decreasing,
        "zero_trading_value_ratio_20d": decreasing,
    }
    frames = {
        key: pd.DataFrame([row], index=[pd.Timestamp(date)], columns=columns)
        for key, row in values.items()
    }
    if extra_columns:
        for frame in frames.values():
            frame["430001.BJ"] = 999.0
            frame["000001.THS"] = 999.0
            frame["510300.SH"] = 999.0
            frame["159915.SZ"] = 999.0
            frame["000300.SH"] = 999.0
            frame["900901.SH"] = 999.0
            frame["200002.SZ"] = 999.0
    return frames


def test_composite_score_applies_approved_directions_and_weights() -> None:
    inputs = _aligned_inputs(extra_columns=True)

    result = build_liquidity_composite_score_bundle(inputs, min_valid_count=4)
    score = result["factor_dfs"]["liquidity_composite_score"]

    assert result["bundle_id"] == "stock_liquidity_composite"
    assert result["factor_name_map"] == FACTOR_NAME_MAP
    assert list(score.columns) == [
        "000001.SZ",
        "000002.SZ",
        "000003.SZ",
        "600000.SH",
    ]
    assert score.iloc[0].is_monotonic_increasing
    expected_high = (
        0.35 * 87.5
        + 0.30 * 87.5
        + 0.20 * (87.5 / 95.0 * 100.0)
        + 0.15 * 87.5
    )
    assert score.iloc[0, -1] == pytest.approx(expected_high)
    assert score.min().min() >= 0.0
    assert score.max().max() <= 100.0


def test_composite_score_preserves_average_ties_and_rejects_incomplete_rows() -> None:
    inputs = _aligned_inputs()
    for frame in inputs.values():
        frame.iloc[0, 2] = frame.iloc[0, 1]

    inputs["avg_trading_value_20d"].iloc[0, 0] = np.inf
    inputs["avg_trading_value_60d"].iloc[0, 0] = np.nan
    inputs["amihud_20d"].iloc[0, 3] = np.nan

    score = build_liquidity_composite_score_bundle(
        inputs,
        min_valid_count=2,
    )["factor_dfs"]["liquidity_composite_score"]

    assert pd.isna(score.iloc[0, 0])
    assert score.iloc[0, 1] == pytest.approx(score.iloc[0, 2])
    assert pd.isna(score.iloc[0, 3])


def test_turnover_percentile_is_capped_at_95_before_rescaling() -> None:
    date = pd.Timestamp("2026-08-03")
    columns = [f"{code:06d}.SZ" for code in range(1, 21)]
    constant = pd.DataFrame([[1.0] * 20], index=[date], columns=columns)
    increasing = pd.DataFrame(
        [np.arange(1.0, 21.0)],
        index=[date],
        columns=columns,
    )
    inputs = {
        "avg_trading_value_20d": constant.copy(),
        "avg_trading_value_60d": constant.copy(),
        "avg_turnover_20d": increasing.copy(),
        "avg_turnover_60d": increasing.copy(),
        "amihud_20d": constant.copy(),
        "trading_value_volatility_20d": pd.DataFrame(
            np.nan,
            index=[date],
            columns=columns,
        ),
        "zero_trading_value_ratio_20d": pd.DataFrame(
            np.nan,
            index=[date],
            columns=columns,
        ),
    }

    score = build_liquidity_composite_score_bundle(
        inputs,
        min_valid_count=20,
    )["factor_dfs"]["liquidity_composite_score"]

    expected_top = (0.35 * 50.0 + 0.30 * 50.0 + 0.20 * 100.0) / 0.85
    assert score.iloc[0, -1] == pytest.approx(expected_top)


def test_catalog_exposes_only_the_composite_output() -> None:
    assert get_factor_catalog()["factor_name_map"] == {
        "流动性综合评分": "liquidity_composite_score"
    }


def test_default_stock_gate_rejects_a_four_stock_cross_section() -> None:
    score = build_liquidity_composite_score_bundle(
        _aligned_inputs()
    )["factor_dfs"]["liquidity_composite_score"]

    assert score.isna().all().all()


def test_current_302_chinext_prefix_is_kept_as_an_a_share() -> None:
    inputs = _aligned_inputs()
    for frame in inputs.values():
        frame["302132.SZ"] = 5.0

    score = build_liquidity_composite_score_bundle(
        inputs,
        min_valid_count=4,
    )["factor_dfs"]["liquidity_composite_score"]

    assert "302132.SZ" in score.columns


def test_score_requires_at_least_one_optional_dimension() -> None:
    inputs = _aligned_inputs()
    for key in (
        "avg_turnover_20d",
        "avg_turnover_60d",
        "trading_value_volatility_20d",
        "zero_trading_value_ratio_20d",
    ):
        inputs[key].iloc[:, :] = np.nan

    score = build_liquidity_composite_score_bundle(
        inputs,
        min_valid_count=4,
    )["factor_dfs"]["liquidity_composite_score"]

    assert score.isna().all().all()


def test_composite_uses_the_available_child_and_ignores_constant_continuity() -> None:
    inputs = _aligned_inputs()
    inputs["avg_trading_value_20d"].iloc[0, 0] = np.nan
    inputs["zero_trading_value_ratio_20d"].iloc[0, :] = 0.0

    score = build_liquidity_composite_score_bundle(
        inputs,
        min_valid_count=4,
    )["factor_dfs"]["liquidity_composite_score"]

    assert score.iloc[0, 0] == pytest.approx(
        (
            0.35 * 12.5
            + 0.30 * 12.5
            + 0.20 * (12.5 / 95.0 * 100.0)
            + 0.15 * 12.5
        )
    )
    assert score.iloc[0, -1] == pytest.approx(
        (
            0.35 * 87.5
            + 0.30 * 87.5
            + 0.20 * (87.5 / 95.0 * 100.0)
            + 0.15 * 87.5
        )
    )


def _write_factor_month(
    base_dir: Path,
    factor_name: str,
    *,
    add_part: bool = False,
) -> None:
    date = pd.Timestamp("2026-08-03")
    month_dir = base_dir / f"factor={factor_name}" / "year=2026" / "month=08"
    month_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "time": [date, date, date, date],
            "htsc_code": ["000001.SZ", "600000.SH", "430001.BJ", "000001.THS"],
            "value": [1.0, 2.0, 3.0, 4.0],
        }
    ).to_parquet(month_dir / "merged.parquet", index=False)
    if add_part:
        pd.DataFrame(
            {"time": [date], "htsc_code": ["000001.SZ"], "value": [9.0]}
        ).to_parquet(month_dir / "part_001.parquet", index=False)


def test_loader_reads_all_factors_with_latest_part_override(tmp_path: Path) -> None:
    factor_names = {
        "20日平均成交额": "avg_trading_value_20d",
        "60日平均成交额": "avg_trading_value_60d",
        "20日平均换手率": "avg_turnover_20d",
        "60日平均换手率": "avg_turnover_60d",
        "20日Amihud非流动性": "amihud_20d",
        "20日成交额波动率": "trading_value_volatility_20d",
        "20日零成交额占比": "zero_trading_value_ratio_20d",
    }
    for index, factor_name in enumerate(factor_names):
        _write_factor_month(tmp_path, factor_name, add_part=index == 0)

    frames = load_liquidity_raw_factor_frames(
        base_dir=tmp_path,
        start_date="2026-08-03",
        end_date="2026-08-03",
    )

    assert set(frames) == set(factor_names.values())
    assert set(frames["avg_trading_value_20d"].columns) == {
        "000001.SZ",
        "600000.SH",
    }
    assert frames["avg_trading_value_20d"].loc[
        pd.Timestamp("2026-08-03"), "000001.SZ"
    ] == pytest.approx(9.0)

    result = build_stock_liquidity_composite_bundle(
        base_dir=tmp_path,
        start_date="2026-08-03",
        end_date="2026-08-03",
        min_valid_count=2,
    )
    assert set(result["factor_dfs"]) == {"liquidity_composite_score"}


def test_loader_names_the_missing_factor_month(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="20日平均成交额.*2026-08"):
        load_liquidity_raw_factor_frames(
            base_dir=tmp_path,
            start_date="2026-08-01",
            end_date="2026-08-31",
        )


def test_post_write_runner_splits_months_and_saves_sparse_score() -> None:
    script_path = Path(__file__).with_name("ZXW策略技术因子生成.py")
    tree = ast.parse(script_path.read_text(encoding="utf-8-sig"), filename=str(script_path))
    names = {"_month_start_range", "_run_stock_liquidity_composite_post_write"}
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    build_calls: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    save_calls: list[dict[str, object]] = []

    def fake_build(**kwargs):
        start = pd.Timestamp(kwargs["start_date"])
        end = pd.Timestamp(kwargs["end_date"])
        build_calls.append((start, end))
        frame = pd.DataFrame({"000001.SZ": [50.0]}, index=[start])
        return {
            "bundle_id": "stock_liquidity_composite",
            "factor_dfs": {"liquidity_composite_score": frame},
        }

    def fake_save(*args, **kwargs):
        save_calls.append({"args": args, "kwargs": kwargs})

    namespace = {
        "pd": pd,
        "LIQUIDITY_COMPOSITE_FACTOR_NAME_MAP": FACTOR_NAME_MAP,
        "build_stock_liquidity_composite_bundle": fake_build,
        "save_factor_dfs_to_factor_partitioned_parquet": fake_save,
    }
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(script_path), "exec"),
        namespace,
    )
    plan = pd.DataFrame(
        [
            {
                "factor_en": "liquidity_composite_score",
                "status": "stale",
                "plan_start": pd.Timestamp("2026-01-31"),
                "plan_end": pd.Timestamp("2026-02-01"),
            }
        ]
    )

    result = namespace["_run_stock_liquidity_composite_post_write"](
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
        assert set(call["args"][0]) == {"liquidity_composite_score"}
        assert call["args"][1] == FACTOR_NAME_MAP
        assert call["kwargs"]["drop_null_factor_keys"] == {
            "liquidity_composite_score"
        }
    assert set(result["factor_dfs"]) == {"liquidity_composite_score"}


def test_liquidity_composite_is_registered_in_generator_and_catalog() -> None:
    project_root = Path(__file__).resolve().parents[1]
    generator = (project_root / "ZXW因子" / "ZXW策略技术因子生成.py").read_text(
        encoding="utf-8"
    )

    assert "get_stock_liquidity_composite_lookback_config" in generator
    assert "build_stock_liquidity_composite_bundle" in generator
    assert '"stock_liquidity_composite"' in generator
    assert "_run_stock_liquidity_composite_post_write" in generator
    assert (
        "STOCK_ONLY_FACTOR_KEYS.update(LIQUIDITY_COMPOSITE_FACTOR_NAME_MAP.values())"
        in generator
    )
    assert "drop_null_factor_keys=set(chunk_factor_dfs)" in generator

    catalog = json.loads(
        (project_root / "因子分类" / "factor_catalog.json").read_text(encoding="utf-8")
    )
    groups = {group["group_id"]: group for group in catalog["groups"]}
    group = groups["stock_liquidity_composite"]
    assert group["group_name"] == "股票流动性综合评分"
    assert group["core_factors"] == ["流动性综合评分"]
    assert group["children"] == ["流动性综合评分"]
