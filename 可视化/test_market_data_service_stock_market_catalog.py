from __future__ import annotations

import market_data_service as service


def test_signal_factor_list_exposes_stock_market_data_group(tmp_path) -> None:
    factors = ["总市值", "流通市值", "自由流通市值", "换手率", "ln_自由流通市值"]
    for factor in factors:
        (tmp_path / f"factor={factor}").mkdir()

    result = service.list_signal_factors(base_path=str(tmp_path), refresh=True)
    group = next(
        item for item in result["groups"] if item["group_id"] == "stock_market_data"
    )

    assert group["group_name"] == "股票市场数据"
    assert group["children"] == factors
