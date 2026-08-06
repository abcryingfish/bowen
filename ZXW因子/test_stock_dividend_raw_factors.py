from __future__ import annotations

import math
import json
from pathlib import Path

import pandas as pd

from 股票红利原始因子 import (
    build_stock_dividend_raw_factor_bundle,
    get_factor_catalog,
    get_factor_lookback_config,
)


EXPECTED_FACTOR_MAP = {
    "调整后每股现金分红_TTM": "cash_dividend_per_share_ttm_adjusted",
    "已实施股息率_TTM": "realized_dividend_yield_ttm",
    "现金分红次数_近3年": "cash_dividend_event_count_3y",
    "有分红年度占比_近5年": "cash_dividend_active_year_ratio_5y",
    "连续分红年数": "cash_dividend_consecutive_years",
    "每股分红三年复合增长率": "cash_dividend_cagr_3y",
    "分红削减次数_近5年": "cash_dividend_cut_count_5y",
}


def _write_events(path) -> None:
    pd.DataFrame(
        {
            "htsc_code": ["000001.SZ"] * 6,
            "event_date": pd.to_datetime(
                [
                    "2021-01-01",
                    "2022-01-01",
                    "2023-01-01",
                    "2024-01-01",
                    "2025-01-01",
                    "2026-01-01",
                ]
            ),
            "interest": [1.0, 1.0, 1.2, 1.5, 2.0, 0.6],
            "stockBonus": [0.0] * 6,
            "stockGift": [0.0, 0.0, 0.0, 0.0, 0.5, 0.0],
            "allotNum": [0.0] * 6,
            "allotPrice": [0.0] * 6,
            "gugai": [0.0] * 6,
            "dr": [1.0] * 6,
            "updated_at": ["2026-08-01"] * 6,
        }
    ).to_parquet(path, index=False)


def test_catalog_and_lookback_contract() -> None:
    assert get_factor_catalog()["factor_name_map"] == EXPECTED_FACTOR_MAP
    assert get_factor_lookback_config() == {
        "bundle_id": "stock_dividend_raw",
        "bundle_lookback_days": 0,
        "factor_lookback_days": {
            key: 0 for key in EXPECTED_FACTOR_MAP.values()
        },
        "source_history_start": "2010-01-01",
    }


def test_bundle_adjusts_past_dividends_for_stock_gift_and_excludes_incomplete_year(
    tmp_path,
) -> None:
    source = tmp_path / "dividends.parquet"
    _write_events(source)
    index = pd.to_datetime(["2026-08-03"])
    close = pd.DataFrame(
        {"000001.SZ": [10.0], "510300.SH": [4.0]}, index=index
    )

    result = build_stock_dividend_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_glob=str(source),
    )
    values = result["factor_dfs"]
    point = index[0]

    # The 2025 dividend is outside the TTM window. The 2026 dividend is
    # already quoted on the post-gift share basis and must not be adjusted
    # by the earlier gift a second time.
    assert math.isclose(
        values["cash_dividend_per_share_ttm_adjusted"].loc[point, "000001.SZ"],
        0.6,
        rel_tol=1e-9,
    )
    assert math.isclose(
        values["realized_dividend_yield_ttm"].loc[point, "000001.SZ"],
        0.6 / 10.0 * 100.0,
        rel_tol=1e-9,
    )
    assert values["cash_dividend_event_count_3y"].loc[point, "000001.SZ"] == 3
    assert values["cash_dividend_active_year_ratio_5y"].loc[point, "000001.SZ"] == 100.0
    assert values["cash_dividend_consecutive_years"].loc[point, "000001.SZ"] == 5
    assert math.isclose(
        values["cash_dividend_cagr_3y"].loc[point, "000001.SZ"],
        (2.0 / 1.5 / (1.0 / 1.5)) ** (1.0 / 3.0) * 100.0 - 100.0,
        rel_tol=1e-9,
    )
    assert values["cash_dividend_cut_count_5y"].loc[point, "000001.SZ"] == 0
    assert list(values["cash_dividend_per_share_ttm_adjusted"].columns) == [
        "000001.SZ"
    ]


def test_bundle_rejects_missing_required_event_column(tmp_path) -> None:
    source = tmp_path / "dividends.parquet"
    pd.DataFrame(
        {"htsc_code": ["000001.SZ"], "event_date": pd.to_datetime(["2026-01-01"])}
    ).to_parquet(source, index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0]}, index=pd.to_datetime(["2026-08-03"])
    )

    try:
        build_stock_dividend_raw_factor_bundle(
            C=close,
            stock_codes={"000001.SZ"},
            source_glob=str(source),
        )
    except ValueError as exc:
        assert "红利事件源缺少字段" in str(exc)
    else:
        raise AssertionError("缺少 interest 字段时必须明确失败")


def test_five_year_metrics_are_null_before_source_history_is_complete(tmp_path) -> None:
    source = tmp_path / "dividends.parquet"
    pd.DataFrame(
        {
            "htsc_code": ["000001.SZ"] * 5,
            "event_date": pd.to_datetime(
                ["2010-01-01", "2011-01-01", "2012-01-01", "2013-01-01", "2014-01-01"]
            ),
            "interest": [1.0] * 5,
            "stockBonus": [0.0] * 5,
            "stockGift": [0.0] * 5,
        }
    ).to_parquet(source, index=False)
    index = pd.to_datetime(["2014-08-03"])
    close = pd.DataFrame({"000001.SZ": [10.0]}, index=index)

    result = build_stock_dividend_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_glob=str(source),
    )
    values = result["factor_dfs"]
    point = index[0]
    assert pd.isna(
        values["cash_dividend_active_year_ratio_5y"].loc[point, "000001.SZ"]
    )
    assert pd.isna(
        values["cash_dividend_consecutive_years"].loc[point, "000001.SZ"]
    )
    assert pd.isna(
        values["cash_dividend_cut_count_5y"].loc[point, "000001.SZ"]
    )


def test_catalog_and_main_generator_register_dividend_bundle() -> None:
    project_root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (project_root / "因子分类" / "factor_catalog.json").read_text(encoding="utf-8")
    )
    groups = {str(group["group_id"]): group for group in payload["groups"]}
    assert groups["stock_dividend_raw"]["children"] == list(EXPECTED_FACTOR_MAP)
    source = (project_root / "ZXW因子" / "ZXW策略技术因子生成.py").read_text(
        encoding="utf-8"
    )
    assert '"stock_dividend_raw"' in source
    assert "build_stock_dividend_raw_factor_bundle" in source
