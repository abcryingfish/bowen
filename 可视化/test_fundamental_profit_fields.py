from __future__ import annotations

import fundamental_data_service as fundamental_service
import qmt_company_data_service as qmt_service


def test_qmt_income_columns_label_parent_profit_by_correct_field():
    columns = qmt_service._build_columns(
        [
            {
                "net_profit_excl_min_int_inc": 5_922_815_000.0,
                "net_profit_incl_min_int_inc_after": 3_727_609_925.9,
            }
        ]
    )
    labels = {column["key"]: column["label"] for column in columns}

    assert labels["net_profit_excl_min_int_inc"] == "归母净利润"
    assert labels["net_profit_incl_min_int_inc_after"] == "扣非后净利润"


def test_fundamental_overview_uses_parent_profit_excluding_minority_interest():
    overview = fundamental_service._build_overview(
        rows=[],
        income_rows=[
            {
                "net_profit_excl_min_int_inc": 5_922_815_000.0,
                "net_profit_incl_min_int_inc_after": 3_727_609_925.9,
            }
        ],
    )
    kpis = {item["label"]: item for item in overview["kpis"]}

    assert kpis["归母净利润"]["key"] == "net_profit_excl_min_int_inc"
    assert kpis["归母净利润"]["value"] == 5_922_815_000.0
