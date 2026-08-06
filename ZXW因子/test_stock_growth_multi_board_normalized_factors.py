from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from 股票成长多板块标准化因子 import (
    FACTOR_NAME_MAP,
    RAW_FACTOR_NAME_MAP,
    average_board_scores,
    board_rank_normalize,
    build_board_memberships,
    build_growth_multi_board_normalized_factor_bundle,
    load_ths_multi_board_snapshots,
)


def _codes(count: int = 39) -> list[str]:
    return [f"{index:06d}.SZ" for index in range(1, count + 1)]


def _overlapping_memberships(date: pd.Timestamp) -> pd.DataFrame:
    codes = _codes()
    return pd.DataFrame(
        {
            "time": [date] * 40,
            "stock_code": codes[:20] + [codes[0]] + codes[20:],
            "board_code": ["885001"] * 20 + ["886001"] * 20,
        }
    )


def test_snapshot_loader_keeps_885_886_and_allows_multiple_boards(
    tmp_path: Path,
) -> None:
    partition = tmp_path / "analysis_date=2026-08-03"
    partition.mkdir()
    pd.DataFrame(
        {
            "analysis_date": ["2026-08-03"] * 5,
            "sector_code": [
                "881101.THS",
                "882001.THS",
                "885001.THS",
                "886001",
                "885001.THS",
            ],
            "stock_code": ["000001.SZ"] * 5,
            "eligible": [True] * 5,
        }
    ).to_parquet(partition / "part-000.parquet", index=False)

    result = load_ths_multi_board_snapshots(
        snapshot_dir=tmp_path,
        end_date="2026-08-03",
    )

    assert result[["stock_code", "board_code"]].to_records(index=False).tolist() == [
        ("000001.SZ", "885001"),
        ("000001.SZ", "886001"),
    ]


def test_snapshot_loader_rejects_partition_date_mismatch(tmp_path: Path) -> None:
    partition = tmp_path / "analysis_date=2026-08-03"
    partition.mkdir()
    pd.DataFrame(
        {
            "analysis_date": ["2026-08-02"],
            "sector_code": ["885001.THS"],
            "stock_code": ["000001.SZ"],
            "eligible": [True],
        }
    ).to_parquet(partition / "part-000.parquet", index=False)

    with pytest.raises(ValueError, match="分区日期与 analysis_date 不一致"):
        load_ths_multi_board_snapshots(
            snapshot_dir=tmp_path,
            end_date="2026-08-03",
        )


def test_memberships_use_latest_snapshot_not_after_score_date() -> None:
    snapshots = pd.DataFrame(
        {
            "analysis_date": pd.to_datetime(
                ["2026-07-15", "2026-07-15", "2026-07-29"]
            ),
            "stock_code": ["000001.SZ"] * 3,
            "board_code": ["885001", "886001", "885002"],
        }
    )

    result = build_board_memberships(
        dates=pd.to_datetime(["2026-07-14", "2026-07-15", "2026-07-30"]),
        stock_codes=pd.Index(["000001.SZ"]),
        snapshots=snapshots,
    )

    by_date = result.groupby("time")["board_code"].apply(list).to_dict()
    assert pd.Timestamp("2026-07-14") not in by_date
    assert by_date[pd.Timestamp("2026-07-15")] == ["885001", "886001"]
    assert by_date[pd.Timestamp("2026-07-30")] == ["885002"]


def test_board_rank_requires_20_valid_stocks() -> None:
    date = pd.Timestamp("2026-08-03")
    codes = _codes(20)
    raw = pd.DataFrame([np.arange(1.0, 21.0)], index=[date], columns=codes)
    memberships = pd.DataFrame(
        {
            "time": [date] * 39,
            "stock_code": codes + codes[:19],
            "board_code": ["885001"] * 20 + ["886001"] * 19,
        }
    )

    percentiles, scores = board_rank_normalize(raw, memberships)

    assert percentiles.xs("885001", level="board_code").notna().sum() == 20
    assert "886001" not in percentiles.index.get_level_values("board_code")
    assert np.isfinite(scores.to_numpy()).all()


def test_average_board_scores_uses_only_finite_board_scores() -> None:
    date = pd.Timestamp("2026-08-03")
    index = pd.MultiIndex.from_tuples(
        [
            (date, "000001.SZ", "885001"),
            (date, "000001.SZ", "886001"),
            (date, "000002.SZ", "885001"),
        ],
        names=["time", "stock_code", "board_code"],
    )
    scores = pd.Series([90.0, 60.0, np.nan], index=index)

    average, count = average_board_scores(
        scores,
        dates=pd.DatetimeIndex([date]),
        stock_codes=pd.Index(["000001.SZ", "000002.SZ", "000003.SZ"]),
    )

    assert average.loc[date, "000001.SZ"] == 75.0
    assert count.loc[date, "000001.SZ"] == 2
    assert pd.isna(average.loc[date, "000002.SZ"])
    assert count.loc[date, "000002.SZ"] == 0
    assert pd.isna(average.loc[date, "000003.SZ"])


def test_growth_multi_board_score_is_direct_mean_of_board_scores() -> None:
    date = pd.Timestamp("2026-08-03")
    codes = _codes()
    values = [20.0] + list(np.arange(1.0, 20.0)) + list(np.arange(21.0, 40.0))
    raw_factor_dfs = {
        key: pd.DataFrame([values], index=[date], columns=codes)
        for key in RAW_FACTOR_NAME_MAP.values()
    }

    result = build_growth_multi_board_normalized_factor_bundle(
        raw_factor_dfs,
        _overlapping_memberships(date),
    )

    score = result["factor_dfs"][
        "growth_style_composite_score_multi_board_normalized"
    ]
    count = result["diagnostics"]["valid_board_count"]
    assert result["factor_name_map"] == FACTOR_NAME_MAP
    assert score.loc[date, "000001.SZ"] == pytest.approx(50.0)
    assert count.loc[date, "000001.SZ"] == 2
    assert score.min(axis=None) >= 0.0
    assert score.max(axis=None) <= 100.0


def test_growth_multi_board_generator_and_catalog_contracts() -> None:
    project_root = Path(__file__).resolve().parents[1]
    generator = (project_root / "ZXW因子" / "ZXW策略技术因子生成.py").read_text(
        encoding="utf-8"
    )
    catalog = json.loads(
        (project_root / "因子分类" / "factor_catalog.json").read_text(
            encoding="utf-8"
        )
    )

    assert '"stock_growth_multi_board_normalized"' in generator
    assert "build_stock_growth_multi_board_normalized_factor_bundle" in generator
    assert "_run_stock_growth_multi_board_normalized_post_write" in generator
    groups = {group["group_id"]: group for group in catalog["groups"]}
    assert groups["stock_growth_multi_board_normalized"]["children"] == list(
        FACTOR_NAME_MAP
    )
