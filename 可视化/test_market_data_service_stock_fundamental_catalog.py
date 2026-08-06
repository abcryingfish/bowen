from __future__ import annotations

import market_data_service as service


def test_signal_factor_list_exposes_stock_fundamental_group(tmp_path) -> None:
    factors = [
        "净资产收益率_ROE",
        "销售毛利率",
        "经营现金流营业收入比",
        "资产负债率",
        "总资产收益率_ROA",
        "毛利润资产比",
        "净利润现金含量",
        "应计利润率",
        "总资产周转率",
        "ROE标准差_12季度",
        "销售毛利率标准差_12季度",
        "市净率_PB",
    ]
    for factor in factors:
        (tmp_path / f"factor={factor}").mkdir()

    result = service.list_signal_factors(base_path=str(tmp_path), refresh=True)
    group = next(
        item for item in result["groups"] if item["group_id"] == "stock_fundamental_raw"
    )

    assert group["group_name"] == "股票基本面原始因子"
    assert group["children"] == factors

    growth_factors = [
        "营业收入同比_TTM",
        "营业收入三年复合增长率",
        "营业利润同比_TTM",
        "扣非净利润同比_TTM",
        "基本每股收益同比_TTM",
        "经营现金流同比_TTM",
        "营业收入增速变化",
        "扣非净利润增速变化",
        "净资产收益率同比变化",
        "销售毛利率同比变化",
        "研发费用同比增速_TTM",
        "研发费用率_TTM",
    ]
    for factor in growth_factors:
        (tmp_path / f"factor={factor}").mkdir()
    result = service.list_signal_factors(base_path=str(tmp_path), refresh=True)
    growth_group = next(
        item for item in result["groups"] if item["group_id"] == "stock_growth_raw"
    )
    assert growth_group["group_name"] == "股票成长原始因子"
    assert growth_group["children"] == growth_factors
