from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from test_factor_auto_plan_valid_values import _load_planner_functions


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_factor_catalog_contains_stock_market_data_group() -> None:
    catalog_path = PROJECT_ROOT / "因子分类" / "factor_catalog.json"
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    groups = {
        str(group.get("group_id")): group
        for group in payload.get("groups", [])
    }

    group = groups["stock_market_data"]
    assert group["group_name"] == "股票市场数据"
    assert group["core_factors"] == [
        "总市值",
        "流通市值",
        "自由流通市值",
        "换手率",
        "ln_自由流通市值",
    ]
    assert group["children"] == [
        "总市值",
        "流通市值",
        "自由流通市值",
        "换手率",
        "ln_自由流通市值",
    ]


def test_main_generator_registers_stock_only_scope() -> None:
    source_path = PROJECT_ROOT / "ZXW因子" / "ZXW策略技术因子生成.py"
    source = source_path.read_text(encoding="utf-8")

    assert '"stock_market_data"' in source
    assert '"stock_market"' in source
    assert "STOCK_ONLY_FACTOR_KEYS" in source
    assert "build_stock_market_data_factor_bundle" in source


def test_stock_market_factors_plan_only_stock_source_codes() -> None:
    planner = _load_planner_functions()
    plan_df = pd.DataFrame(
        [
            {
                "factor_en": "ln_free_float_market_value",
                "status": "missing",
                "plan_start": pd.Timestamp("2026-07-30"),
                "plan_end": pd.Timestamp("2026-07-30"),
            }
        ]
    )

    plans = planner["_build_factor_scope_execution_plans"](
        factor_plan_df=plan_df,
        bundle_factor_catalog={
            "stock_market_data": {"ln_自由流通市值": "ln_free_float_market_value"}
        },
        selected_bundles=["stock_market_data"],
        standard_market_codes={"000001.SZ", "510300.SH"},
        all_market_codes={"000001.SZ", "510300.SH", "881001.THS"},
        stock_codes={"000001.SZ"},
        sector_codes={"881001.THS"},
        factor_lookback_days={"ln_free_float_market_value": 0},
        buffer_days=20,
    )

    assert len(plans) == 1
    assert plans[0]["scope"] == "stock_market"
    assert plans[0]["codes"] == ["000001.SZ"]
