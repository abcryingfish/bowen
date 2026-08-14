from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from 股票成长行业标准化因子 import (
    FACTOR_NAME_MAP,
    RAW_FACTOR_NAME_MAP,
    build_growth_industry_normalized_factor_bundle,
    build_industry_frame,
    industry_rank_normalize,
    load_ths881_industry_snapshots,
)


def test_snapshot_loader_keeps_only_881_and_normalizes_codes(tmp_path: Path) -> None:
    month_dir = tmp_path / "analysis_date=2026-08-03"
    month_dir.mkdir()
    pd.DataFrame(
        {
            "analysis_date": ["2026-08-03"] * 3,
            "sector_code": ["881101.THS", "885001.THS", "881102"],
            "sector_name": ["行业甲", "概念甲", "行业乙"],
            "stock_code": ["000001.sz", "000001.SZ", "600000.sh"],
            "eligible": [True, True, True],
        }
    ).to_parquet(month_dir / "part-000.parquet", index=False)

    result = load_ths881_industry_snapshots(
        snapshot_dir=tmp_path,
        end_date="2026-08-03",
    )

    assert result.to_dict("records") == [
        {
            "analysis_date": pd.Timestamp("2026-08-03"),
            "stock_code": "000001.SZ",
            "industry_code": "881101",
        },
        {
            "analysis_date": pd.Timestamp("2026-08-03"),
            "stock_code": "600000.SH",
            "industry_code": "881102",
        },
    ]


def test_snapshot_loader_rejects_multiple_881_industries_for_one_stock(
    tmp_path: Path,
) -> None:
    month_dir = tmp_path / "analysis_date=2026-08-03"
    month_dir.mkdir()
    pd.DataFrame(
        {
            "analysis_date": ["2026-08-03", "2026-08-03"],
            "sector_code": ["881101.THS", "881102.THS"],
            "stock_code": ["000001.SZ", "000001.SZ"],
            "eligible": [True, True],
        }
    ).to_parquet(month_dir / "part-000.parquet", index=False)

    with pytest.raises(ValueError, match="多个 881 行业"):
        load_ths881_industry_snapshots(
            snapshot_dir=tmp_path,
            end_date="2026-08-03",
        )


def test_snapshot_loader_ignores_future_partition_with_backdated_row(
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


def test_snapshot_loader_latest_only_ignores_score_end_date(tmp_path: Path) -> None:
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


def test_industry_frame_can_fixed_fill_latest_snapshot_before_snapshot_date() -> None:
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


def test_snapshot_loader_rejects_partition_date_mismatch(tmp_path: Path) -> None:
    month_dir = tmp_path / "analysis_date=2026-07-15"
    month_dir.mkdir()
    pd.DataFrame(
        {
            "analysis_date": ["2026-07-14"],
            "sector_code": ["881101.THS"],
            "stock_code": ["000001.SZ"],
            "eligible": [True],
        }
    ).to_parquet(month_dir / "part-000.parquet", index=False)

    with pytest.raises(ValueError, match="分区日期与 analysis_date 不一致"):
        load_ths881_industry_snapshots(
            snapshot_dir=tmp_path,
            end_date="2026-07-15",
        )


def test_industry_frame_uses_latest_snapshot_not_after_score_date() -> None:
    snapshots = pd.DataFrame(
        {
            "analysis_date": pd.to_datetime(["2026-07-15", "2026-07-20"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "industry_code": ["881101", "881102"],
        }
    )
    dates = pd.to_datetime(["2026-07-14", "2026-07-15", "2026-07-21"])

    result = build_industry_frame(
        dates=dates,
        stock_codes=pd.Index(["000001.SZ", "600000.SH"]),
        snapshots=snapshots,
    )

    assert pd.isna(result.loc[pd.Timestamp("2026-07-14"), "000001.SZ"])
    assert result.loc[pd.Timestamp("2026-07-15"), "000001.SZ"] == "881101"
    assert result.loc[pd.Timestamp("2026-07-21"), "000001.SZ"] == "881102"
    assert result["600000.SH"].isna().all()


def test_industry_rank_normalize_ranks_each_881_industry_independently() -> None:
    date = pd.Timestamp("2026-08-03")
    codes = [f"00000{i}.SZ" for i in range(1, 7)]
    raw = pd.DataFrame([[1, 2, 3, 101, 102, 103]], index=[date], columns=codes)
    industries = pd.DataFrame(
        [["881101"] * 3 + ["881102"] * 3], index=[date], columns=codes
    )

    percentiles, scores = industry_rank_normalize(
        raw,
        industries,
        min_industry_count=3,
    )

    expected = [1 / 6, 0.5, 5 / 6] * 2
    assert percentiles.loc[date].tolist() == pytest.approx(expected)
    assert np.isfinite(scores.loc[date]).all()


def test_industry_rank_normalize_keeps_ties_and_rejects_too_small_group() -> None:
    date = pd.Timestamp("2026-08-03")
    codes = [f"00000{i}.SZ" for i in range(1, 6)]
    raw = pd.DataFrame([[1.0, 2.0, 2.0, 10.0, 20.0]], index=[date], columns=codes)
    industries = pd.DataFrame(
        [["881101"] * 3 + ["881102"] * 2], index=[date], columns=codes
    )

    percentiles, scores = industry_rank_normalize(
        raw,
        industries,
        min_industry_count=3,
    )

    assert percentiles.loc[date, codes[:3]].tolist() == pytest.approx(
        [1 / 6, 2 / 3, 2 / 3]
    )
    assert percentiles.loc[date, codes[3:]].isna().all()
    assert scores.loc[date, codes[3:]].isna().all()


def test_growth_industry_score_reuses_weights_and_missing_penalty() -> None:
    date = pd.Timestamp("2026-08-03")
    codes = [f"00000{i}.SZ" for i in range(1, 5)]
    raw_factor_dfs = {
        key: pd.DataFrame([[1.0, 2.0, 3.0, 4.0]], index=[date], columns=codes)
        for key in RAW_FACTOR_NAME_MAP.values()
    }
    for key in ("research_expense_growth_yoy_ttm", "research_expense_to_revenue_ttm"):
        raw_factor_dfs[key].loc[date, "000004.SZ"] = np.nan
    industries = pd.DataFrame([["881101"] * 4], index=[date], columns=codes)

    result = build_growth_industry_normalized_factor_bundle(
        raw_factor_dfs,
        industries,
        min_industry_count=3,
    )

    score = result["factor_dfs"]["growth_style_composite_score_industry_normalized"]
    assert result["bundle_id"] == "stock_growth_industry_normalized"
    assert result["factor_name_map"] == FACTOR_NAME_MAP
    assert score.loc[date, "000004.SZ"] == pytest.approx(83.125)
    assert score.min(axis=None) >= 0.0
    assert score.max(axis=None) <= 100.0


def test_growth_bundle_rejects_duplicate_stock_columns() -> None:
    date = pd.Timestamp("2026-08-03")
    duplicate_columns = ["000001.SZ", "000001.SZ", "000002.SZ"]
    raw_factor_dfs = {
        key: pd.DataFrame([[1.0, 2.0, 3.0]], index=[date], columns=duplicate_columns)
        for key in RAW_FACTOR_NAME_MAP.values()
    }
    industries = pd.DataFrame(
        [["881101", "881101", "881101"]],
        index=[date],
        columns=duplicate_columns,
    )

    with pytest.raises(ValueError, match="重复股票列"):
        build_growth_industry_normalized_factor_bundle(raw_factor_dfs, industries)


def test_growth_raw_loader_rejects_conflicting_keys_inside_one_file(
    tmp_path: Path,
) -> None:
    from 股票成长行业标准化因子 import load_raw_growth_factor_dfs

    date = pd.Timestamp("2026-08-03")
    for factor_name in RAW_FACTOR_NAME_MAP:
        month_dir = tmp_path / f"factor={factor_name}" / "year=2026" / "month=08"
        month_dir.mkdir(parents=True)
        values = [1.0, 1.0]
        if factor_name == "营业收入同比_TTM":
            values = [1.0, 2.0]
        pd.DataFrame(
            {
                "time": [date, date],
                "htsc_code": ["000001.SZ", "000001.SZ"],
                "value": values,
            }
        ).to_parquet(month_dir / "merged.parquet", index=False)

    with pytest.raises(ValueError, match="同一文件存在冲突重复键"):
        load_raw_growth_factor_dfs(
            base_dir=tmp_path,
            start_date=date,
            end_date=date,
        )


def test_growth_industry_bundle_generator_and_catalog_contracts() -> None:
    project_root = Path(__file__).resolve().parents[1]
    generator = (project_root / "ZXW因子" / "ZXW策略技术因子生成.py").read_text(
        encoding="utf-8"
    )
    catalog = json.loads(
        (project_root / "因子分类" / "factor_catalog.json").read_text(encoding="utf-8")
    )

    assert '"stock_growth_industry_normalized"' in generator
    assert "build_stock_growth_industry_normalized_factor_bundle" in generator
    assert "_run_stock_growth_industry_normalized_post_write" in generator
    assert "drop_null_factor_keys=set(chunk_factor_dfs)" in generator
    groups = {group["group_id"]: group for group in catalog["groups"]}
    assert groups["stock_growth_industry_normalized"]["children"] == list(FACTOR_NAME_MAP)
