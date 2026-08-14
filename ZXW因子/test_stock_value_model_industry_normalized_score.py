from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from 股票价值模型行业标准化评分 import (
    FACTOR_NAME_MAP,
    RAW_FACTOR_NAME_MAP,
    build_value_model_industry_normalized_score,
    build_industry_frame,
    load_raw_value_factor_dfs,
    load_ths881_industry_snapshots,
)


def test_value_industry_score_uses_industry_ranks_weights_and_penalty() -> None:
    date = pd.Timestamp("2026-08-03")
    codes = [f"00000{i}.SZ" for i in range(1, 5)]
    raw_factor_dfs = {
        key: pd.DataFrame([[1.0, 2.0, 3.0, 4.0]], index=[date], columns=codes)
        for key in RAW_FACTOR_NAME_MAP.values()
    }
    raw_factor_dfs["net_cash_to_market_value"].loc[date, "000004.SZ"] = np.nan
    industries = pd.DataFrame([["881101"] * 4], index=[date], columns=codes)

    result = build_value_model_industry_normalized_score(
        raw_factor_dfs,
        industries,
        min_industry_count=3,
    )

    score = result["factor_dfs"]["value_model_composite_score_industry_normalized"]
    assert result["bundle_id"] == "stock_value_model_industry_normalized"
    assert result["factor_name_map"] == FACTOR_NAME_MAP
    assert score.loc[date, "000004.SZ"] == pytest.approx(78.75)
    assert score.min(axis=None) >= 0.0
    assert score.max(axis=None) <= 100.0


def test_value_industry_score_requires_four_valid_factors() -> None:
    date = pd.Timestamp("2026-08-03")
    codes = [f"00000{i}.SZ" for i in range(1, 5)]
    raw_factor_dfs = {
        key: pd.DataFrame([[1.0, 2.0, 3.0, 4.0]], index=[date], columns=codes)
        for key in RAW_FACTOR_NAME_MAP.values()
    }
    for key in list(RAW_FACTOR_NAME_MAP.values())[3:]:
        raw_factor_dfs[key].loc[date, "000004.SZ"] = np.nan
    industries = pd.DataFrame([["881101"] * 4], index=[date], columns=codes)

    result = build_value_model_industry_normalized_score(
        raw_factor_dfs,
        industries,
        min_industry_count=3,
    )

    score = result["factor_dfs"]["value_model_composite_score_industry_normalized"]
    assert pd.isna(score.loc[date, "000004.SZ"])


@pytest.mark.parametrize("min_valid_factors", [0, 7])
def test_value_industry_score_rejects_invalid_minimum_factor_count(
    min_valid_factors: int,
) -> None:
    date = pd.Timestamp("2026-08-03")
    codes = [f"00000{i}.SZ" for i in range(1, 5)]
    raw_factor_dfs = {
        key: pd.DataFrame([[1.0, 2.0, 3.0, 4.0]], index=[date], columns=codes)
        for key in RAW_FACTOR_NAME_MAP.values()
    }
    industries = pd.DataFrame([["881101"] * 4], index=[date], columns=codes)

    with pytest.raises(ValueError, match="min_valid_factors 必须在 1 至 6 之间"):
        build_value_model_industry_normalized_score(
            raw_factor_dfs,
            industries,
            min_valid_factors=min_valid_factors,
        )


def test_value_industry_score_ranks_each_industry_independently() -> None:
    date = pd.Timestamp("2026-08-03")
    codes = [f"00000{i}.SZ" for i in range(1, 7)]
    raw_factor_dfs = {
        key: pd.DataFrame([[1, 2, 3, 101, 102, 103]], index=[date], columns=codes)
        for key in RAW_FACTOR_NAME_MAP.values()
    }
    industries = pd.DataFrame(
        [["881101"] * 3 + ["881102"] * 3], index=[date], columns=codes
    )

    result = build_value_model_industry_normalized_score(
        raw_factor_dfs,
        industries,
        min_industry_count=3,
    )

    score = result["factor_dfs"]["value_model_composite_score_industry_normalized"]
    assert score.loc[date].tolist() == pytest.approx([100 / 6, 50, 500 / 6] * 2)


def test_value_industry_score_supports_history_from_2010() -> None:
    date = pd.Timestamp("2014-12-31")
    codes = [f"00000{i}.SZ" for i in range(1, 5)]
    raw_factor_dfs = {
        key: pd.DataFrame([[1.0, 2.0, 3.0, 4.0]], index=[date], columns=codes)
        for key in RAW_FACTOR_NAME_MAP.values()
    }
    industries = pd.DataFrame([["881101"] * 4], index=[date], columns=codes)

    result = build_value_model_industry_normalized_score(
        raw_factor_dfs,
        industries,
        min_industry_count=3,
    )

    score = result["factor_dfs"]["value_model_composite_score_industry_normalized"]
    assert score.loc[date].notna().all()


def test_value_industry_score_does_not_depend_on_snapshot_start_date() -> None:
    dates = pd.to_datetime(["2026-07-14", "2026-07-15"])
    codes = [f"00000{i}.SZ" for i in range(1, 5)]
    raw_factor_dfs = {
        key: pd.DataFrame(
            [[1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0]],
            index=dates,
            columns=codes,
        )
        for key in RAW_FACTOR_NAME_MAP.values()
    }
    industries = pd.DataFrame(
        [["881101"] * 4, ["881101"] * 4], index=dates, columns=codes
    )

    result = build_value_model_industry_normalized_score(
        raw_factor_dfs,
        industries,
        min_industry_count=3,
    )

    score = result["factor_dfs"]["value_model_composite_score_industry_normalized"]
    assert score.loc[pd.Timestamp("2026-07-14")].notna().all()
    assert score.loc[pd.Timestamp("2026-07-15")].notna().all()


def test_value_snapshot_loader_ignores_future_partition_with_backdated_row(
    tmp_path: Path,
) -> None:
    current_dir = tmp_path / "analysis_date=2026-07-15"
    current_dir.mkdir()
    future_dir = tmp_path / "analysis_date=2026-08-03"
    future_dir.mkdir()
    base = {
        "analysis_date": ["2026-07-15"],
        "sector_code": ["881101.THS"],
        "stock_code": ["000001.SZ"],
        "eligible": [True],
    }
    pd.DataFrame(base).to_parquet(current_dir / "part-000.parquet", index=False)
    pd.DataFrame({**base, "sector_code": ["881102.THS"]}).to_parquet(
        future_dir / "part-000.parquet", index=False
    )

    result = load_ths881_industry_snapshots(
        snapshot_dir=tmp_path,
        end_date="2026-07-15",
    )

    assert result["industry_code"].tolist() == ["881101"]


def test_value_snapshot_loader_latest_only_ignores_score_end_date(tmp_path: Path) -> None:
    for date, industry in [("2026-07-15", "881101"), ("2026-08-03", "881102")]:
        partition = tmp_path / f"analysis_date={date}"
        partition.mkdir()
        pd.DataFrame(
            {
                "analysis_date": [date],
                "sector_code": [f"{industry}.THS"],
                "stock_code": ["000001.SZ"],
                "eligible": [True],
            }
        ).to_parquet(partition / "part-000.parquet", index=False)

    result = load_ths881_industry_snapshots(
        snapshot_dir=tmp_path,
        end_date="2026-05-31",
        latest_only=True,
    )

    assert result["analysis_date"].unique().tolist() == [pd.Timestamp("2026-08-03")]
    assert result["industry_code"].tolist() == ["881102"]


def test_value_industry_frame_can_fixed_fill_latest_snapshot_before_snapshot_date() -> None:
    snapshots = pd.DataFrame(
        {
            "analysis_date": [pd.Timestamp("2026-08-03")],
            "stock_code": ["000001.SZ"],
            "industry_code": ["881101"],
        }
    )
    result = build_industry_frame(
        dates=pd.to_datetime(["2010-01-05", "2026-08-03"]),
        stock_codes=pd.Index(["000001.SZ"]),
        snapshots=snapshots,
        fixed_latest=True,
    )

    assert result.loc[pd.Timestamp("2010-01-05"), "000001.SZ"] == "881101"


def test_value_raw_loader_rejects_conflicting_keys_inside_one_file(
    tmp_path: Path,
) -> None:
    date = pd.Timestamp("2026-08-03")
    for factor_name in RAW_FACTOR_NAME_MAP:
        month_dir = tmp_path / f"factor={factor_name}" / "year=2026" / "month=08"
        month_dir.mkdir(parents=True)
        values = [1.0, 1.0]
        if factor_name == "盈利收益率_EY_TTM":
            values = [1.0, 2.0]
        pd.DataFrame(
            {
                "time": [date, date],
                "htsc_code": ["000001.SZ", "000001.SZ"],
                "value": values,
            }
        ).to_parquet(month_dir / "merged.parquet", index=False)

    with pytest.raises(ValueError, match="同一文件存在冲突重复键"):
        load_raw_value_factor_dfs(
            base_dir=tmp_path,
            start_date=date,
            end_date=date,
        )


def test_value_industry_bundle_generator_and_catalog_contracts() -> None:
    project_root = Path(__file__).resolve().parents[1]
    generator = (project_root / "ZXW因子" / "ZXW策略技术因子生成.py").read_text(
        encoding="utf-8"
    )
    catalog = json.loads(
        (project_root / "因子分类" / "factor_catalog.json").read_text(encoding="utf-8")
    )

    assert '"stock_value_model_industry_normalized"' in generator
    assert "build_stock_value_model_industry_normalized_score_bundle" in generator
    assert "_run_stock_value_model_industry_normalized_post_write" in generator
    assert "drop_null_factor_keys=set(chunk_factor_dfs)" in generator
    groups = {group["group_id"]: group for group in catalog["groups"]}
    assert groups["stock_value_model_industry_normalized"]["children"] == list(FACTOR_NAME_MAP)
