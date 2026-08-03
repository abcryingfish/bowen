from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from test_factor_auto_plan_valid_values import _load_planner_functions


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FACTOR_MAP = {
    "净资产收益率_ROE": "return_on_equity_ttm",
    "销售毛利率": "sales_gross_margin_ttm",
    "经营现金流营业收入比": "operating_cashflow_to_revenue_ttm",
    "资产负债率": "debt_to_asset_ratio",
    "总资产收益率_ROA": "return_on_assets_ttm",
    "毛利润资产比": "gross_profit_to_assets_ttm",
    "净利润现金含量": "operating_cashflow_to_net_profit_ttm",
    "应计利润率": "accruals_to_assets_ttm",
    "总资产周转率": "asset_turnover_ttm",
    "ROE标准差_12季度": "return_on_equity_std_12q",
    "销售毛利率标准差_12季度": "sales_gross_margin_std_12q",
    "市净率_PB": "price_to_book_ratio",
}

VALUE_FACTOR_MAP = {
    "盈利收益率_EY_TTM": "earnings_yield_ttm",
    "账面市值比_BM": "book_to_market_ratio",
    "销售收益率_SY_TTM": "sales_yield_ttm",
    "经营现金流收益率_OCFY_TTM": "operating_cashflow_yield_ttm",
    "自由现金流收益率_FCFY_TTM": "free_cashflow_yield_ttm",
    "净现金市值比": "net_cash_to_market_value",
}

GROWTH_FACTOR_MAP = {
    "营业收入同比_TTM": "revenue_growth_yoy_ttm",
    "营业收入三年复合增长率": "revenue_cagr_3y_ttm",
    "营业利润同比_TTM": "operating_profit_growth_yoy_ttm",
    "扣非净利润同比_TTM": "adjusted_net_profit_growth_yoy_ttm",
    "基本每股收益同比_TTM": "basic_eps_growth_yoy_ttm",
    "经营现金流同比_TTM": "operating_cashflow_growth_yoy_ttm",
    "营业收入增速变化": "revenue_growth_acceleration_ttm",
    "扣非净利润增速变化": "adjusted_net_profit_growth_acceleration_ttm",
    "净资产收益率同比变化": "return_on_equity_change_yoy_ttm",
    "销售毛利率同比变化": "sales_gross_margin_change_yoy_ttm",
    "研发费用同比增速_TTM": "research_expense_growth_yoy_ttm",
    "研发费用率_TTM": "research_expense_to_revenue_ttm",
}


def test_catalog_contains_stock_fundamental_raw_group() -> None:
    payload = json.loads(
        (PROJECT_ROOT / "因子分类" / "factor_catalog.json").read_text(encoding="utf-8")
    )
    groups = {str(group.get("group_id")): group for group in payload.get("groups", [])}
    group = groups["stock_fundamental_raw"]
    assert group["group_name"] == "股票基本面原始因子"
    assert group["children"] == list(FACTOR_MAP)


def test_catalog_contains_stock_value_raw_group() -> None:
    payload = json.loads(
        (PROJECT_ROOT / "因子分类" / "factor_catalog.json").read_text(encoding="utf-8")
    )
    groups = {str(group.get("group_id")): group for group in payload.get("groups", [])}
    group = groups["stock_value_raw"]
    assert group["group_name"] == "股票绝对价值原始因子"
    assert group["children"] == list(VALUE_FACTOR_MAP)


def test_main_generator_registers_fundamental_bundle() -> None:
    source = (PROJECT_ROOT / "ZXW因子" / "ZXW策略技术因子生成.py").read_text(
        encoding="utf-8"
    )
    assert '"stock_fundamental_raw"' in source
    assert "build_stock_fundamental_raw_factor_bundle" in source


def test_main_generator_registers_growth_bundle() -> None:
    source = (PROJECT_ROOT / "ZXW因子" / "ZXW策略技术因子生成.py").read_text(
        encoding="utf-8"
    )
    assert '"stock_growth_raw"' in source
    assert "build_stock_growth_raw_factor_bundle" in source


def test_catalog_contains_stock_growth_raw_group() -> None:
    payload = json.loads(
        (PROJECT_ROOT / "因子分类" / "factor_catalog.json").read_text(encoding="utf-8")
    )
    groups = {str(group.get("group_id")): group for group in payload.get("groups", [])}
    group = groups["stock_growth_raw"]
    assert group["group_name"] == "股票成长原始因子"
    assert group["children"] == list(GROWTH_FACTOR_MAP)


def test_fundamental_factors_plan_only_stock_codes() -> None:
    planner = _load_planner_functions()
    plan_df = pd.DataFrame(
        [
            {
                "factor_en": "return_on_equity_ttm",
                "status": "missing",
                "plan_start": pd.Timestamp("2026-07-30"),
                "plan_end": pd.Timestamp("2026-07-30"),
            }
        ]
    )
    plans = planner["_build_factor_scope_execution_plans"](
        factor_plan_df=plan_df,
        bundle_factor_catalog={"stock_fundamental_raw": FACTOR_MAP},
        selected_bundles=["stock_fundamental_raw"],
        standard_market_codes={"000001.SZ", "510300.SH"},
        all_market_codes={"000001.SZ", "510300.SH", "881001.THS"},
        stock_codes={"000001.SZ"},
        sector_codes={"881001.THS"},
        factor_lookback_days={"return_on_equity_ttm": 0},
        buffer_days=20,
    )
    assert len(plans) == 1
    assert plans[0]["scope"] == "stock_market"
    assert plans[0]["codes"] == ["000001.SZ"]
