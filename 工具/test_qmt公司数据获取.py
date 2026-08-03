from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).with_name("qmt公司数据获取.py")
SPEC = importlib.util.spec_from_file_location("qmt_company_data_download", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service)


def test_fundamental_valuation_uses_parent_profit_for_point_in_time_and_ttm():
    income = pd.DataFrame(
        [
            {
                "htsc_code": "600887.SH",
                "report_date": "2023-03-31",
                "announce_date": "2023-04-30",
                "revenue": 200.0,
                "net_profit_excl_min_int_inc": 10.0,
                "net_profit_incl_min_int_inc_after": 4.0,
            },
            {
                "htsc_code": "600887.SH",
                "report_date": "2023-12-31",
                "announce_date": "2024-04-29",
                "revenue": 1_000.0,
                "net_profit_excl_min_int_inc": 100.0,
                "net_profit_incl_min_int_inc_after": 40.0,
            },
            {
                "htsc_code": "600887.SH",
                "report_date": "2024-03-31",
                "announce_date": "2024-04-30",
                "revenue": 250.0,
                "net_profit_excl_min_int_inc": 20.0,
                "net_profit_incl_min_int_inc_after": 8.0,
            },
        ]
    )
    common_statement = pd.DataFrame(
        [
            {
                "htsc_code": "600887.SH",
                "report_date": "2024-03-31",
                "announce_date": "2024-04-30",
            }
        ]
    )
    balance = common_statement.assign(tot_shrhldr_eqy_excl_min_int=500.0)
    pershare = common_statement.assign(equity_roe=10.0, net_roe=9.0)
    capital = common_statement.assign(total_capital=100.0)
    daily = pd.DataFrame(
        [{"htsc_code": "600887.SH", "time": "2024-04-30", "close": 10.0}]
    )

    result = service.build_fundamental_valuation_frame(
        income, balance, pershare, capital, daily
    )

    assert result.loc[0, "net_profit_parent"] == 20.0
    assert result.loc[0, "net_profit_parent_ttm"] == 110.0


def test_normalize_qmt_table_frame_drops_invalid_announce_dates():
    raw = pd.DataFrame(
        {
            "m_timetag": ["20240331", "20240630", "20240930"],
            "m_anntime": ["20240430", None, "invalid-date"],
            "revenue": [100.0, 200.0, 300.0],
        }
    )

    result = service.normalize_qmt_table_frame(
        raw,
        table_name="Income",
        code="000001.SZ",
        name="平安银行",
        updated_at="2026-08-02T00:00:00",
    )

    assert result["report_date"].tolist() == [pd.Timestamp("2024-03-31")]
    assert result["announce_date"].tolist() == [pd.Timestamp("2024-04-30")]


def test_normalize_qmt_table_frame_drops_rows_when_announce_column_is_missing():
    raw = pd.DataFrame(
        {
            "m_timetag": ["20240331", "20240630"],
            "revenue": [100.0, 200.0],
        }
    )

    result = service.normalize_qmt_table_frame(
        raw,
        table_name="Income",
        code="000001.SZ",
        name="平安银行",
        updated_at="2026-08-02T00:00:00",
    )

    assert result.empty
