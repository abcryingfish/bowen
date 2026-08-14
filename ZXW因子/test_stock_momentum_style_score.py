from __future__ import annotations

import ast
import json
import numpy as np
import pandas as pd
import pytest
from pathlib import Path
import warnings

from 股票动量风格评分 import (
    FACTOR_NAME_MAP,
    build_momentum_style_score_bundle,
    build_stock_momentum_style_bundle,
    get_factor_catalog,
    load_saved_factor_frame,
    load_stock_valid_bar,
)


def test_momentum_score_ranks_each_horizon_before_weighting() -> None:
    date = pd.Timestamp("2026-08-03")
    codes = ["000001.SZ", "000002.SZ", "000003.SZ", "600000.SH"]
    momentum_12_1 = pd.DataFrame(
        [[1.0, 2.0, 3.0, 4.0]], index=[date], columns=codes
    )
    momentum_6_1 = pd.DataFrame(
        [[40.0, 30.0, 20.0, 10.0]], index=[date], columns=codes
    )
    valid_bar = pd.DataFrame(True, index=[date], columns=codes)

    result = build_momentum_style_score_bundle(
        momentum_12_1,
        momentum_6_1,
        valid_bar=valid_bar,
        min_valid_count=4,
    )
    score = result["factor_dfs"]["momentum_style_score"]
    expected_12_1 = np.array([12.5, 37.5, 62.5, 87.5])
    expected_6_1 = np.array([87.5, 62.5, 37.5, 12.5])

    assert score.loc[date, codes].tolist() == pytest.approx(
        0.70 * expected_12_1 + 0.30 * expected_6_1
    )
    assert result["bundle_id"] == "stock_momentum_style"
    assert result["factor_name_map"] == FACTOR_NAME_MAP


def test_momentum_score_uses_average_ties_and_joint_valid_sample() -> None:
    date = pd.Timestamp("2026-08-03")
    codes = ["000001.SZ", "000002.SZ", "000003.SZ", "600000.SH", "600001.SH"]
    momentum_12_1 = pd.DataFrame(
        [[1.0, 2.0, 2.0, 4.0, 5.0]], index=[date], columns=codes
    )
    momentum_6_1 = pd.DataFrame(
        [[10.0, 20.0, 30.0, 40.0, np.nan]], index=[date], columns=codes
    )
    valid_bar = pd.DataFrame(True, index=[date], columns=codes)

    score = build_momentum_style_score_bundle(
        momentum_12_1,
        momentum_6_1,
        valid_bar=valid_bar,
        min_valid_count=4,
    )["factor_dfs"]["momentum_style_score"]

    expected_long = np.array([12.5, 50.0, 50.0, 87.5])
    expected_medium = np.array([12.5, 37.5, 62.5, 87.5])
    assert score.loc[date, codes[:4]].tolist() == pytest.approx(
        0.70 * expected_long + 0.30 * expected_medium
    )
    assert pd.isna(score.loc[date, "600001.SH"])


def test_invalid_bar_nonfinite_input_and_small_cross_section_are_not_scored() -> None:
    dates = pd.to_datetime(["2026-08-03", "2026-08-04"])
    codes = ["000001.SZ", "000002.SZ", "000003.SZ", "600000.SH"]
    momentum_12_1 = pd.DataFrame(
        [[1.0, 2.0, np.inf, 4.0], [1.0, 2.0, 3.0, 4.0]],
        index=dates,
        columns=codes,
    )
    momentum_6_1 = pd.DataFrame(
        [[1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0]],
        index=dates,
        columns=codes,
    )
    valid_bar = pd.DataFrame(True, index=dates, columns=codes)
    valid_bar.loc[dates[1], "600000.SH"] = False

    score = build_momentum_style_score_bundle(
        momentum_12_1,
        momentum_6_1,
        valid_bar=valid_bar,
        min_valid_count=4,
    )["factor_dfs"]["momentum_style_score"]

    assert score.isna().all().all()


def test_missing_valid_bar_date_does_not_emit_future_warning() -> None:
    dates = pd.to_datetime(["2026-08-03", "2026-08-04"])
    frame = pd.DataFrame([[1.0], [2.0]], index=dates, columns=["000001.SZ"])
    valid_bar = pd.DataFrame(True, index=dates[:1], columns=frame.columns)

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        score = build_momentum_style_score_bundle(
            frame,
            frame,
            valid_bar=valid_bar,
            min_valid_count=1,
        )["factor_dfs"]["momentum_style_score"]

    assert pd.isna(score.loc[dates[1], "000001.SZ"])


def test_momentum_score_rejects_invalid_minimum_stock_count() -> None:
    frame = pd.DataFrame([[1.0]], index=[pd.Timestamp("2026-08-03")])
    valid_bar = pd.DataFrame(True, index=frame.index, columns=frame.columns)

    with pytest.raises(ValueError, match="min_valid_count"):
        build_momentum_style_score_bundle(
            frame,
            frame,
            valid_bar=valid_bar,
            min_valid_count=0,
        )


def test_momentum_score_catalog_has_only_the_approved_output() -> None:
    assert get_factor_catalog()["factor_name_map"] == {
        "动量风格评分": "momentum_style_score"
    }


def _write_factor_month(
    base_dir: Path,
    factor_name: str,
    filename: str,
    frame: pd.DataFrame,
) -> None:
    month_dir = base_dir / f"factor={factor_name}" / "year=2026" / "month=08"
    month_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(month_dir / filename, index=False)


def test_disk_bundle_uses_latest_parts_and_authoritative_stock_daily_mask(
    tmp_path: Path,
) -> None:
    date = pd.Timestamp("2026-08-03")
    signal_dir = tmp_path / "signal"
    market_dir = tmp_path / "market"
    codes = [
        "000001.SZ",
        "600000.SH",
        "000003.SZ",
        "510300.SH",
        "881001.THS",
    ]
    _write_factor_month(
        signal_dir,
        "252日纯动量",
        "merged.parquet",
        pd.DataFrame(
            {"time": [date] * 5, "htsc_code": codes, "value": [0.1, 0.2, 0.3, 0.9, 0.8]}
        ),
    )
    _write_factor_month(
        signal_dir,
        "252日纯动量",
        "part_001.parquet",
        pd.DataFrame(
            {"time": [date], "htsc_code": ["000001.SZ"], "value": [0.4]}
        ),
    )
    _write_factor_month(
        signal_dir,
        "纯动量",
        "merged.parquet",
        pd.DataFrame(
            {"time": [date] * 5, "htsc_code": codes, "value": [0.1, 0.4, 0.3, 0.9, 0.8]}
        ),
    )
    market_month = market_dir / "year=2026" / "month=08"
    market_month.mkdir(parents=True)
    pd.DataFrame(
        {
            "time": [date, date],
            "htsc_code": ["000001.SZ", "600000.SH"],
            "close": [10.0, 20.0],
        }
    ).to_parquet(market_month / "merged.parquet", index=False)

    long_frame = load_saved_factor_frame(
        base_dir=signal_dir,
        factor_name="252日纯动量",
        start_date=date,
        end_date=date,
    )
    valid_bar = load_stock_valid_bar(
        base_dir=market_dir,
        start_date=date,
        end_date=date,
    )
    result = build_stock_momentum_style_bundle(
        signal_base_dir=signal_dir,
        market_base_dir=market_dir,
        start_date=date,
        end_date=date,
        min_valid_count=2,
    )
    score = result["factor_dfs"]["momentum_style_score"]

    assert long_frame.loc[date, "000001.SZ"] == pytest.approx(0.4)
    assert valid_bar.loc[date].all()
    assert set(score.columns) == {"000001.SZ", "600000.SH"}
    assert score.loc[date, "000001.SZ"] == pytest.approx(60.0)
    assert score.loc[date, "600000.SH"] == pytest.approx(40.0)
    assert "000003.SZ" not in score.columns
    assert "510300.SH" not in score.columns
    assert "881001.THS" not in score.columns


def test_loaders_require_every_requested_month(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="2026-07.*2026-08"):
        load_saved_factor_frame(
            base_dir=tmp_path,
            factor_name="252日纯动量",
            start_date="2026-07-01",
            end_date="2026-08-31",
        )
    with pytest.raises(FileNotFoundError, match="2026-07.*2026-08"):
        load_stock_valid_bar(
            base_dir=tmp_path,
            start_date="2026-07-01",
            end_date="2026-08-31",
        )


def test_loaders_reject_reversed_date_range(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="start_date"):
        load_saved_factor_frame(
            base_dir=tmp_path,
            factor_name="纯动量",
            start_date="2026-08-31",
            end_date="2026-08-01",
        )
    with pytest.raises(ValueError, match="start_date"):
        load_stock_valid_bar(
            base_dir=tmp_path,
            start_date="2026-08-31",
            end_date="2026-08-01",
        )


def test_momentum_style_bundle_is_registered_in_generator_and_catalog() -> None:
    project_root = Path(__file__).resolve().parents[1]
    generator = (project_root / "ZXW因子" / "ZXW策略技术因子生成.py").read_text(
        encoding="utf-8"
    )

    assert "get_stock_momentum_style_lookback_config" in generator
    assert "build_stock_momentum_style_bundle" in generator
    assert '"stock_momentum_style"' in generator
    assert "POST_WRITE_DERIVED_BUNDLES" in generator
    assert (
        "STOCK_ONLY_FACTOR_KEYS.update(MOMENTUM_STYLE_FACTOR_NAME_MAP.values())"
        in generator
    )
    assert "_run_stock_momentum_style_post_write" in generator

    catalog = json.loads(
        (project_root / "因子分类" / "factor_catalog.json").read_text(
            encoding="utf-8"
        )
    )
    groups = {group["group_id"]: group for group in catalog["groups"]}
    group = groups["stock_momentum_style"]
    assert group["group_name"] == "股票动量风格评分"
    assert group["core_factors"] == ["动量风格评分"]
    assert group["children"] == ["动量风格评分"]


def test_post_write_runner_saves_only_finite_momentum_scores() -> None:
    script_path = Path(__file__).with_name("ZXW策略技术因子生成.py")
    tree = ast.parse(
        script_path.read_text(encoding="utf-8-sig"),
        filename=str(script_path),
    )
    names = {"_month_start_range", "_run_stock_momentum_style_post_write"}
    nodes = [
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name in names
    ]
    save_calls: list[dict[str, object]] = []

    def fake_build(**kwargs):
        start = pd.Timestamp(kwargs["start_date"])
        frame = pd.DataFrame(
            {"000001.SZ": [50.0], "000002.SZ": [np.nan]},
            index=[start],
        )
        return {
            "bundle_id": "stock_momentum_style",
            "factor_dfs": {"momentum_style_score": frame},
        }

    def fake_save(*args, **kwargs):
        save_calls.append({"args": args, "kwargs": kwargs})

    namespace = {
        "pd": pd,
        "BASE_PATH": "market",
        "MOMENTUM_STYLE_FACTOR_NAME_MAP": FACTOR_NAME_MAP,
        "build_stock_momentum_style_bundle": fake_build,
        "save_factor_dfs_to_factor_partitioned_parquet": fake_save,
    }
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(script_path), "exec"),
        namespace,
    )
    plan = pd.DataFrame(
        [
            {
                "factor_en": "momentum_style_score",
                "status": "stale",
                "plan_start": pd.Timestamp("2026-08-03"),
                "plan_end": pd.Timestamp("2026-08-03"),
            }
        ]
    )

    result = namespace["_run_stock_momentum_style_post_write"](
        base_dir="signal",
        plan_df=plan,
        factor_last_dt_map=None,
    )

    assert result is not None
    assert len(save_calls) == 1
    assert save_calls[0]["kwargs"]["drop_null_factor_keys"] == {
        "momentum_style_score"
    }
