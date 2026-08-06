from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from 股票价值模型多板块标准化评分 import (
    FACTOR_NAME_MAP,
    RAW_FACTOR_NAME_MAP,
    build_value_model_multi_board_normalized_score,
)


def _codes(count: int = 39) -> list[str]:
    return [f"{index:06d}.SZ" for index in range(1, count + 1)]


def _memberships(date: pd.Timestamp) -> pd.DataFrame:
    codes = _codes()
    return pd.DataFrame(
        {
            "time": [date] * 40,
            "stock_code": codes[:20] + [codes[0]] + codes[20:],
            "board_code": ["885001"] * 20 + ["886001"] * 20,
        }
    )


def test_value_multi_board_score_is_direct_mean_and_keeps_weights() -> None:
    date = pd.Timestamp("2026-08-03")
    codes = _codes()
    values = [20.0] + list(np.arange(1.0, 20.0)) + list(np.arange(21.0, 40.0))
    raw_factor_dfs = {
        key: pd.DataFrame([values], index=[date], columns=codes)
        for key in RAW_FACTOR_NAME_MAP.values()
    }

    result = build_value_model_multi_board_normalized_score(
        raw_factor_dfs,
        _memberships(date),
    )

    score = result["factor_dfs"][
        "value_model_composite_score_multi_board_normalized"
    ]
    count = result["diagnostics"]["valid_board_count"]
    assert result["factor_name_map"] == FACTOR_NAME_MAP
    assert score.loc[date, "000001.SZ"] == pytest.approx(50.0)
    assert count.loc[date, "000001.SZ"] == 2


def test_value_multi_board_requires_four_valid_factors() -> None:
    date = pd.Timestamp("2026-08-03")
    codes = _codes()
    raw_factor_dfs = {
        key: pd.DataFrame([np.arange(1.0, 40.0)], index=[date], columns=codes)
        for key in RAW_FACTOR_NAME_MAP.values()
    }
    for key in list(RAW_FACTOR_NAME_MAP.values())[3:]:
        raw_factor_dfs[key].loc[date, "000001.SZ"] = np.nan

    result = build_value_model_multi_board_normalized_score(
        raw_factor_dfs,
        _memberships(date),
    )

    score = result["factor_dfs"][
        "value_model_composite_score_multi_board_normalized"
    ]
    assert pd.isna(score.loc[date, "000001.SZ"])


@pytest.mark.parametrize("minimum", [0, 7])
def test_value_multi_board_rejects_invalid_minimum(minimum: int) -> None:
    date = pd.Timestamp("2026-08-03")
    codes = _codes()
    raw_factor_dfs = {
        key: pd.DataFrame([np.arange(1.0, 40.0)], index=[date], columns=codes)
        for key in RAW_FACTOR_NAME_MAP.values()
    }

    with pytest.raises(ValueError, match="min_valid_factors 必须在 1 至 6 之间"):
        build_value_model_multi_board_normalized_score(
            raw_factor_dfs,
            _memberships(date),
            min_valid_factors=minimum,
        )


def test_value_multi_board_is_empty_before_model_start() -> None:
    date = pd.Timestamp("2026-07-14")
    codes = _codes()
    raw_factor_dfs = {
        key: pd.DataFrame([np.arange(1.0, 40.0)], index=[date], columns=codes)
        for key in RAW_FACTOR_NAME_MAP.values()
    }

    result = build_value_model_multi_board_normalized_score(
        raw_factor_dfs,
        _memberships(date),
    )

    score = result["factor_dfs"][
        "value_model_composite_score_multi_board_normalized"
    ]
    assert score.isna().all().all()


def test_value_multi_board_generator_and_catalog_contracts() -> None:
    project_root = Path(__file__).resolve().parents[1]
    generator = (project_root / "ZXW因子" / "ZXW策略技术因子生成.py").read_text(
        encoding="utf-8"
    )
    catalog = json.loads(
        (project_root / "因子分类" / "factor_catalog.json").read_text(
            encoding="utf-8"
        )
    )

    assert '"stock_value_model_multi_board_normalized"' in generator
    assert "build_stock_value_model_multi_board_normalized_score_bundle" in generator
    assert "_run_stock_value_model_multi_board_normalized_post_write" in generator
    groups = {group["group_id"]: group for group in catalog["groups"]}
    assert groups["stock_value_model_multi_board_normalized"]["children"] == list(
        FACTOR_NAME_MAP
    )
