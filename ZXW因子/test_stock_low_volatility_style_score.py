from __future__ import annotations

import ast
import json
import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from 股票低波风格评分 import (
    BUNDLE_ID,
    EFFECTIVE_FACTOR_WEIGHTS,
    FACTOR_NAME_MAP,
    SOURCE_FACTOR_NAME_MAP,
    build_low_volatility_style_score_bundle,
    build_stock_low_volatility_style_bundle,
    get_factor_catalog,
    load_low_volatility_source_frames,
)


SOURCE_KEYS = (
    "annual_vol_20d",
    "annual_vol_60d",
    "annual_vol_252d",
    "downside_vol_20d",
    "downside_vol_60d",
    "max_drawdown_60d",
    "atr_volatility_14d",
)


def _factor_frames(
    values_by_key: dict[str, list[float]],
    *,
    codes: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    date = pd.Timestamp("2026-08-03")
    stock_codes = codes or ["000001.SZ", "000002.SZ", "600000.SH", "600001.SH"]
    return {
        key: pd.DataFrame([values_by_key[key]], index=[date], columns=stock_codes)
        for key in SOURCE_KEYS
    }


def test_all_lower_risks_receive_higher_low_volatility_scores() -> None:
    ascending = [1.0, 2.0, 3.0, 4.0]
    values = {key: ascending for key in SOURCE_KEYS}
    values["max_drawdown_60d"] = [-0.1, -0.2, -0.3, -0.4]

    result = build_low_volatility_style_score_bundle(
        _factor_frames(values), min_valid_count=4
    )
    score = result["factor_dfs"]["low_volatility_style_score"]

    assert result["bundle_id"] == BUNDLE_ID == "stock_low_volatility_style_score"
    assert result["factor_name_map"] == FACTOR_NAME_MAP
    assert score.iloc[0].tolist() == pytest.approx([87.5, 62.5, 37.5, 12.5])
    assert score.min().min() >= 0.0
    assert score.max().max() <= 100.0


def test_component_weights_match_the_approved_four_dimension_formula() -> None:
    permutations = {
        "annual_vol_20d": [1.0, 2.0, 3.0, 4.0],
        "annual_vol_60d": [2.0, 1.0, 4.0, 3.0],
        "annual_vol_252d": [3.0, 4.0, 1.0, 2.0],
        "downside_vol_20d": [4.0, 3.0, 2.0, 1.0],
        "downside_vol_60d": [1.0, 3.0, 4.0, 2.0],
        "max_drawdown_60d": [-0.2, -0.4, -0.1, -0.3],
        "atr_volatility_14d": [4.0, 1.0, 3.0, 2.0],
    }
    frames = _factor_frames(permutations)

    score = build_low_volatility_style_score_bundle(
        frames, min_valid_count=4
    )["factor_dfs"]["low_volatility_style_score"]

    expected = pd.Series(0.0, index=score.columns)
    for key, weight in EFFECTIVE_FACTOR_WEIGHTS.items():
        risk = frames[key].abs() if key == "max_drawdown_60d" else frames[key]
        rank = risk.rank(axis=1, method="average")
        component = (4.0 - rank + 0.5) / 4.0 * 100.0
        expected = expected.add(component.iloc[0] * weight, fill_value=0.0)
    assert EFFECTIVE_FACTOR_WEIGHTS == {
        "annual_vol_20d": 0.05,
        "annual_vol_60d": 0.125,
        "annual_vol_252d": 0.075,
        "downside_vol_20d": 0.075,
        "downside_vol_60d": 0.175,
        "max_drawdown_60d": 0.25,
        "atr_volatility_14d": 0.25,
    }
    assert score.iloc[0].tolist() == pytest.approx(expected.tolist())


def test_ties_use_average_rank() -> None:
    tied = [1.0, 2.0, 2.0, 4.0]
    values = {key: tied for key in SOURCE_KEYS}
    values["max_drawdown_60d"] = [-0.1, -0.2, -0.2, -0.4]

    score = build_low_volatility_style_score_bundle(
        _factor_frames(values), min_valid_count=4
    )["factor_dfs"]["low_volatility_style_score"]

    assert score.iloc[0].tolist() == pytest.approx([87.5, 50.0, 50.0, 12.5])


def test_incomplete_stock_is_removed_from_every_component_cross_section() -> None:
    ascending = [1.0, 2.0, 3.0, 4.0]
    values = {key: list(ascending) for key in SOURCE_KEYS}
    values["max_drawdown_60d"] = [-0.1, -0.2, -0.3, -0.4]
    values["atr_volatility_14d"][-1] = np.inf

    score = build_low_volatility_style_score_bundle(
        _factor_frames(values), min_valid_count=3
    )["factor_dfs"]["low_volatility_style_score"]

    assert score.iloc[0, :3].tolist() == pytest.approx(
        [100.0 * 2.5 / 3.0, 50.0, 100.0 * 0.5 / 3.0]
    )
    assert pd.isna(score.iloc[0, 3])


def test_day_below_minimum_complete_stock_count_is_not_scored() -> None:
    values = {key: [1.0, 2.0, 3.0, 4.0] for key in SOURCE_KEYS}
    values["max_drawdown_60d"] = [-0.1, -0.2, -0.3, -0.4]
    values["annual_vol_252d"][-1] = np.nan

    score = build_low_volatility_style_score_bundle(
        _factor_frames(values), min_valid_count=4
    )["factor_dfs"]["low_volatility_style_score"]

    assert score.iloc[0].isna().all()


def test_scoring_keeps_only_shanghai_and_shenzhen_stock_codes() -> None:
    codes = ["000001.SZ", "600000.SH", "430001.BJ", "881001.THS"]
    values = {key: [1.0, 2.0, 0.1, 0.1] for key in SOURCE_KEYS}
    values["max_drawdown_60d"] = [-0.1, -0.2, -0.01, -0.01]

    score = build_low_volatility_style_score_bundle(
        _factor_frames(values, codes=codes), min_valid_count=2
    )["factor_dfs"]["low_volatility_style_score"]

    assert list(score.columns) == ["000001.SZ", "600000.SH"]
    assert score.iloc[0].tolist() == pytest.approx([75.0, 25.0])


def test_scoring_normalizes_stock_code_case_and_whitespace() -> None:
    codes = [" 000001.sz ", "600000.sh"]
    values = {key: [1.0, 2.0] for key in SOURCE_KEYS}
    values["max_drawdown_60d"] = [-0.1, -0.2]

    score = build_low_volatility_style_score_bundle(
        _factor_frames(values, codes=codes), min_valid_count=2
    )["factor_dfs"]["low_volatility_style_score"]

    assert list(score.columns) == ["000001.SZ", "600000.SH"]


def test_invalid_minimum_stock_count_is_rejected() -> None:
    values = {key: [1.0] for key in SOURCE_KEYS}
    values["max_drawdown_60d"] = [-0.1]

    with pytest.raises(ValueError, match="min_valid_count"):
        build_low_volatility_style_score_bundle(
            _factor_frames(values, codes=["000001.SZ"]), min_valid_count=0
        )
    with pytest.raises(ValueError, match="min_valid_count.*整数"):
        build_low_volatility_style_score_bundle(
            _factor_frames(values, codes=["000001.SZ"]), min_valid_count=1.5
        )


def test_catalog_exposes_only_the_approved_output() -> None:
    assert get_factor_catalog()["factor_name_map"] == {
        "低波风格评分": "low_volatility_style_score"
    }


def test_loader_reads_all_sources_and_latest_part_overwrites_merged(
    tmp_path: Path,
) -> None:
    date = pd.Timestamp("2026-08-03")
    codes = [
        "000001.SZ",
        "600000.SH",
        "430001.BJ",
        "881001.THS",
        "510300.SH",
        "000001.SH",
    ]
    for factor_index, factor_name in enumerate(SOURCE_FACTOR_NAME_MAP):
        month_dir = (
            tmp_path
            / f"factor={factor_name}"
            / "year=2026"
            / "month=08"
        )
        month_dir.mkdir(parents=True)
        pd.DataFrame(
            {
                "time": [date] * len(codes),
                "htsc_code": codes,
                "value": [1.0 + factor_index, 2.0 + factor_index, 0.1, 0.1, 0.1, 0.1],
            }
        ).to_parquet(month_dir / "merged.parquet", index=False)
        pd.DataFrame(
            {
                "time": [date],
                "htsc_code": ["000001.SZ"],
                "value": [1.5 + factor_index],
            }
        ).to_parquet(month_dir / "part_001.parquet", index=False)

    frames = load_low_volatility_source_frames(
        base_dir=tmp_path,
        start_date=date,
        end_date=date,
    )

    assert set(frames) == set(SOURCE_FACTOR_NAME_MAP.values())
    for factor_index, factor_key in enumerate(SOURCE_FACTOR_NAME_MAP.values()):
        assert list(frames[factor_key].columns) == ["000001.SZ", "600000.SH"]
        assert frames[factor_key].loc[date, "000001.SZ"] == pytest.approx(
            1.5 + factor_index
        )

    result = build_stock_low_volatility_style_bundle(
        base_dir=tmp_path,
        start_date=date,
        end_date=date,
        min_valid_count=2,
    )
    assert result["factor_dfs"]["low_volatility_style_score"].notna().sum().sum() == 2


def test_loader_reports_missing_factor_and_month(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="20日年化波动率.*2026-08"):
        load_low_volatility_source_frames(
            base_dir=tmp_path,
            start_date="2026-08-01",
            end_date="2026-08-31",
        )


def test_loader_uses_sorted_parts_and_includes_date_range_endpoints(
    tmp_path: Path,
) -> None:
    dates = pd.to_datetime(["2026-08-01", "2026-08-31"])
    for factor_name in SOURCE_FACTOR_NAME_MAP:
        month_dir = (
            tmp_path / f"factor={factor_name}" / "year=2026" / "month=08"
        )
        month_dir.mkdir(parents=True)
        pd.DataFrame(
            {
                "time": dates,
                "htsc_code": ["000001.SZ", "000001.SZ"],
                "value": [1.0, 2.0],
            }
        ).to_parquet(month_dir / "merged.parquet", index=False)
        pd.DataFrame(
            {
                "time": [dates[0]],
                "htsc_code": ["000001.SZ"],
                "value": [3.0],
            }
        ).to_parquet(month_dir / "part_001.parquet", index=False)
        pd.DataFrame(
            {
                "time": [dates[0]],
                "htsc_code": ["000001.SZ"],
                "value": [4.0],
            }
        ).to_parquet(month_dir / "part_002.parquet", index=False)

    frames = load_low_volatility_source_frames(
        base_dir=tmp_path,
        start_date=dates[0],
        end_date=dates[1],
    )

    for frame in frames.values():
        assert list(frame.index) == list(dates)
        assert frame.loc[dates[0], "000001.SZ"] == pytest.approx(4.0)
        assert frame.loc[dates[1], "000001.SZ"] == pytest.approx(2.0)


def test_loader_rejects_reversed_date_range(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="start_date.*end_date"):
        load_low_volatility_source_frames(
            base_dir=tmp_path,
            start_date="2026-08-31",
            end_date="2026-08-01",
        )


def test_post_write_runner_splits_months_and_saves_sparse_score() -> None:
    script_path = Path(__file__).with_name("ZXW策略技术因子生成.py")
    tree = ast.parse(
        script_path.read_text(encoding="utf-8-sig"), filename=str(script_path)
    )
    names = {"_month_start_range", "_run_stock_low_volatility_style_post_write"}
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
            "bundle_id": BUNDLE_ID,
            "factor_dfs": {"low_volatility_style_score": frame},
        }

    def fake_save(*args, **kwargs):
        save_calls.append({"args": args, "kwargs": kwargs})

    namespace = {
        "pd": pd,
        "LOW_VOLATILITY_STYLE_FACTOR_NAME_MAP": FACTOR_NAME_MAP,
        "build_stock_low_volatility_style_bundle": fake_build,
        "save_factor_dfs_to_factor_partitioned_parquet": fake_save,
    }
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(script_path), "exec"),
        namespace,
    )
    plan = pd.DataFrame(
        [
            {
                "factor_en": "low_volatility_style_score",
                "status": "stale",
                "plan_start": pd.Timestamp("2026-01-31"),
                "plan_end": pd.Timestamp("2026-02-01"),
            }
        ]
    )

    result = namespace["_run_stock_low_volatility_style_post_write"](
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
        assert set(call["args"][0]) == {"low_volatility_style_score"}
        assert call["args"][1] == FACTOR_NAME_MAP
        assert call["kwargs"]["drop_null_factor_keys"] == {
            "low_volatility_style_score"
        }
    assert set(result["factor_dfs"]) == {"low_volatility_style_score"}


def test_low_volatility_style_is_registered_in_generator_and_catalog() -> None:
    project_root = Path(__file__).resolve().parents[1]
    generator = (project_root / "ZXW因子" / "ZXW策略技术因子生成.py").read_text(
        encoding="utf-8"
    )

    assert "get_stock_low_volatility_style_lookback_config" in generator
    assert "build_stock_low_volatility_style_bundle" in generator
    assert '"stock_low_volatility_style_score"' in generator
    assert "_run_stock_low_volatility_style_post_write" in generator
    assert (
        "STOCK_ONLY_FACTOR_KEYS.update(LOW_VOLATILITY_STYLE_FACTOR_NAME_MAP.values())"
        in generator
    )

    catalog = json.loads(
        (project_root / "因子分类" / "factor_catalog.json").read_text(
            encoding="utf-8"
        )
    )
    group = next(
        item for item in catalog["groups"] if item["group_id"] == "low_volatility"
    )
    assert group["core_factors"][0] == "低波风格评分"
    assert set(group["children"]) == {
        "低波风格评分",
        "20日年化波动率",
        "60日年化波动率_股票",
        "252日年化波动率",
        "20日下行波动率",
        "60日下行波动率",
        "60日最大回撤",
        "14日ATR波动率",
        "20_60日波动率比",
    }
