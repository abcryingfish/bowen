from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from 股票基本面原始因子 import (
    build_stock_fundamental_raw_factor_bundle,
    get_factor_catalog,
)


EXPECTED_VALUE_FACTOR_MAP = {
    "盈利收益率_EY_TTM": "earnings_yield_ttm",
    "账面市值比_BM": "book_to_market_ratio",
    "销售收益率_SY_TTM": "sales_yield_ttm",
    "经营现金流收益率_OCFY_TTM": "operating_cashflow_yield_ttm",
    "自由现金流收益率_FCFY_TTM": "free_cashflow_yield_ttm",
    "净现金市值比": "net_cash_to_market_value",
}


def _write_sources(tmp_path: Path) -> dict[str, str]:
    report_dates = pd.date_range("2024-03-31", periods=5, freq="QE")
    rows: list[dict[str, object]] = []
    for i, report_date in enumerate(report_dates, start=1):
        announce_date = report_date + pd.Timedelta(days=30)
        quarter = ((i - 1) % 4) + 1
        rows.append(
            {
                "htsc_code": "000001.SZ",
                "report_date": report_date,
                "announce_date": announce_date,
                "period": f"Q{quarter}",
                "revenue": 100.0 * quarter,
                "net_cash_flows_oper_act": 30.0 * quarter,
                "cash_pay_acq_const_fiolta": 5.0 * quarter,
                "cash_equivalents": 300.0,
                "shortterm_loan": 100.0,
                "long_term_loans": 200.0,
                "bonds_payable": 50.0,
            }
        )
    common = pd.DataFrame(rows)
    source_paths: dict[str, str] = {}
    for table, columns in {
        "Income": ["htsc_code", "report_date", "announce_date", "period", "revenue"],
        "CashFlow": [
            "htsc_code",
            "report_date",
            "announce_date",
            "period",
            "net_cash_flows_oper_act",
            "cash_pay_acq_const_fiolta",
        ],
        "Balance": [
            "htsc_code",
            "report_date",
            "announce_date",
            "period",
            "cash_equivalents",
            "shortterm_loan",
            "long_term_loans",
            "bonds_payable",
        ],
        "PershareIndex": ["htsc_code", "report_date", "announce_date", "period"],
    }.items():
        path = tmp_path / f"{table}.parquet"
        common[columns].to_parquet(path, index=False)
        source_paths[table] = str(path)

    valuation = pd.DataFrame(
        {
            "htsc_code": ["000001.SZ"],
            "time": [pd.Timestamp("2025-06-01")],
            "pe_ttm": [10.0],
            "pb": [2.0],
            "revenue_ttm": [1000.0],
            "total_market_val": [1000.0],
        }
    )
    valuation_path = tmp_path / "valuation.parquet"
    valuation.to_parquet(valuation_path, index=False)
    source_paths["valuation"] = str(valuation_path)
    return source_paths


def test_value_factor_catalog_contains_absolute_value_factors() -> None:
    factor_map = get_factor_catalog()["factor_name_map"]
    for name, key in EXPECTED_VALUE_FACTOR_MAP.items():
        assert factor_map[name] == key


def test_build_absolute_value_factors_from_point_in_time_sources(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    close = pd.DataFrame(
        {"000001.SZ": [10.0]},
        index=pd.to_datetime(["2025-06-01"]),
    )

    result = build_stock_fundamental_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_globs=sources,
        target_factor_keys=set(EXPECTED_VALUE_FACTOR_MAP.values()),
    )
    values = result["factor_dfs"]
    point = pd.Timestamp("2025-06-01")

    assert values["earnings_yield_ttm"].loc[point, "000001.SZ"] == 0.1
    assert values["book_to_market_ratio"].loc[point, "000001.SZ"] == 0.5
    assert values["sales_yield_ttm"].loc[point, "000001.SZ"] == 1.0
    assert values["operating_cashflow_yield_ttm"].loc[point, "000001.SZ"] == 0.12
    assert values["free_cashflow_yield_ttm"].loc[point, "000001.SZ"] == 0.1
    assert values["net_cash_to_market_value"].loc[point, "000001.SZ"] == -0.05


def test_value_factors_reject_non_positive_valuation_denominators(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    valuation = pd.read_parquet(sources["valuation"])
    valuation[["pe_ttm", "pb", "total_market_val"]] = -1.0
    valuation.to_parquet(sources["valuation"], index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0]},
        index=pd.to_datetime(["2025-06-01"]),
    )

    result = build_stock_fundamental_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_globs=sources,
        target_factor_keys=set(EXPECTED_VALUE_FACTOR_MAP.values()),
    )
    values = result["factor_dfs"]
    point = pd.Timestamp("2025-06-01")
    for key in EXPECTED_VALUE_FACTOR_MAP.values():
        assert np.isnan(values[key].loc[point, "000001.SZ"])


def test_net_cash_treats_unreported_debt_components_as_zero_when_one_is_present(
    tmp_path: Path,
) -> None:
    sources = _write_sources(tmp_path)
    balance = pd.read_parquet(sources["Balance"])
    balance["shortterm_loan"] = np.nan
    balance["long_term_loans"] = np.nan
    balance.to_parquet(sources["Balance"], index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0]},
        index=pd.to_datetime(["2025-06-01"]),
    )

    result = build_stock_fundamental_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_globs=sources,
        target_factor_keys={"net_cash_to_market_value"},
    )

    assert result["factor_dfs"]["net_cash_to_market_value"].iloc[0, 0] == 0.25
