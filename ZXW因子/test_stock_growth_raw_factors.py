from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from 股票成长原始因子 import (
    build_stock_growth_raw_factor_bundle,
    get_factor_catalog,
)


EXPECTED_FACTOR_MAP = {
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


def _quarter_ends() -> pd.DatetimeIndex:
    return pd.period_range("2021Q1", "2025Q1", freq="Q").to_timestamp(how="end").normalize()


def _cumulative(values: list[float], report_dates: pd.DatetimeIndex) -> list[float]:
    result: list[float] = []
    for i, date in enumerate(report_dates):
        quarter = int(date.quarter)
        result.append(sum(values[i - quarter + 1 : i + 1]))
    return result


def _write_sources(tmp_path: Path) -> dict[str, str]:
    report_dates = _quarter_ends()
    n = len(report_dates)
    standalone = {
        "revenue": [100.0 + i for i in range(n)],
        "oper_profit": [20.0 + i for i in range(n)],
        "adjusted": [10.0 + i for i in range(n)],
        "parent_profit": [12.0 + i for i in range(n)],
        "eps": [1.0 + i * 0.01 for i in range(n)],
        "cfo": [18.0 + i for i in range(n)],
        "research": [5.0 + i * 0.2 for i in range(n)],
    }
    rows: list[dict[str, object]] = []
    for i, report_date in enumerate(report_dates):
        quarter = int(report_date.quarter)
        rows.append(
            {
                "htsc_code": "000001.SZ",
                "report_date": report_date,
                "announce_date": report_date + pd.Timedelta(days=10),
                "period": f"Q{quarter}",
                "revenue": _cumulative(standalone["revenue"], report_dates)[i],
                "oper_profit": _cumulative(standalone["oper_profit"], report_dates)[i],
                "net_profit_incl_min_int_inc_after": _cumulative(standalone["adjusted"], report_dates)[i],
                "net_profit_excl_min_int_inc": _cumulative(standalone["parent_profit"], report_dates)[i],
                "s_fa_eps_basic": _cumulative(standalone["eps"], report_dates)[i],
                "research_expenses": _cumulative(standalone["research"], report_dates)[i],
                "net_cash_flows_oper_act": _cumulative(standalone["cfo"], report_dates)[i],
                "tot_shrhldr_eqy_excl_min_int": 100.0 + i,
                "sales_gross_profit": 40.0,
                "gross_profit": None,
            }
        )

    common = pd.DataFrame(rows)
    source_paths: dict[str, str] = {}
    columns = {
        "Income": [
            "htsc_code", "report_date", "announce_date", "period", "revenue", "oper_profit",
            "net_profit_incl_min_int_inc_after", "net_profit_excl_min_int_inc", "s_fa_eps_basic",
            "research_expenses",
        ],
        "CashFlow": ["htsc_code", "report_date", "announce_date", "period", "net_cash_flows_oper_act"],
        "Balance": ["htsc_code", "report_date", "announce_date", "period", "tot_shrhldr_eqy_excl_min_int"],
        "PershareIndex": ["htsc_code", "report_date", "announce_date", "period", "sales_gross_profit", "gross_profit"],
    }
    for table, table_columns in columns.items():
        path = tmp_path / f"{table}.parquet"
        common[table_columns].to_parquet(path, index=False)
        source_paths[table] = str(path)
    return source_paths


def test_catalog_has_twelve_growth_factors() -> None:
    assert get_factor_catalog()["factor_name_map"] == EXPECTED_FACTOR_MAP


def test_bundle_calculates_growth_and_research_factors(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    latest = pd.Timestamp("2025-05-01")
    close = pd.DataFrame({"000001.SZ": [10.0]}, index=[latest])

    result = build_stock_growth_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_globs=sources,
    )

    current_revenue = sum(100.0 + i for i in range(13, 17))
    prior_revenue = sum(100.0 + i for i in range(9, 13))
    current_research = sum(5.0 + i * 0.2 for i in range(13, 17))
    assert result["bundle_id"] == "stock_growth_raw"
    assert set(result["factor_dfs"]) == set(EXPECTED_FACTOR_MAP.values())
    assert result["factor_dfs"]["revenue_growth_yoy_ttm"].loc[latest, "000001.SZ"] == pytest.approx(
        (current_revenue / prior_revenue - 1) * 100
    )
    assert result["factor_dfs"]["revenue_cagr_3y_ttm"].loc[latest, "000001.SZ"] == pytest.approx(
        (current_revenue / sum(100.0 + i for i in range(1, 5))) ** (1 / 3) * 100 - 100
    )
    assert result["factor_dfs"]["research_expense_to_revenue_ttm"].loc[latest, "000001.SZ"] == pytest.approx(
        current_research / current_revenue * 100
    )
    assert np.isfinite(result["factor_dfs"]["research_expense_growth_yoy_ttm"].loc[latest, "000001.SZ"])
    expected_growth_inputs = {
        "operating_profit_growth_yoy_ttm": [20.0 + i for i in range(17)],
        "adjusted_net_profit_growth_yoy_ttm": [10.0 + i for i in range(17)],
        "basic_eps_growth_yoy_ttm": [1.0 + i * 0.01 for i in range(17)],
        "operating_cashflow_growth_yoy_ttm": [18.0 + i for i in range(17)],
        "research_expense_growth_yoy_ttm": [5.0 + i * 0.2 for i in range(17)],
    }
    for key, values in expected_growth_inputs.items():
        current = sum(values[13:17])
        prior = sum(values[9:13])
        assert result["factor_dfs"][key].loc[latest, "000001.SZ"] == pytest.approx(
            (current / prior - 1) * 100
        )
    previous_revenue_growth = (
        sum(100.0 + i for i in range(12, 16)) / sum(100.0 + i for i in range(8, 12)) - 1
    ) * 100
    assert result["factor_dfs"]["revenue_growth_acceleration_ttm"].loc[latest, "000001.SZ"] == pytest.approx(
        (current_revenue / prior_revenue - 1) * 100 - previous_revenue_growth
    )
    current_adjusted = sum(10.0 + i for i in range(13, 17))
    prior_adjusted = sum(10.0 + i for i in range(9, 13))
    previous_adjusted_growth = (
        sum(10.0 + i for i in range(12, 16)) / sum(10.0 + i for i in range(8, 12)) - 1
    ) * 100
    assert result["factor_dfs"]["adjusted_net_profit_growth_acceleration_ttm"].loc[latest, "000001.SZ"] == pytest.approx(
        (current_adjusted / prior_adjusted - 1) * 100 - previous_adjusted_growth
    )
    current_roe = sum(12.0 + i for i in range(13, 17)) / ((112.0 + 116.0) / 2) * 100
    prior_roe = sum(12.0 + i for i in range(9, 13)) / ((108.0 + 112.0) / 2) * 100
    assert result["factor_dfs"]["return_on_equity_change_yoy_ttm"].loc[latest, "000001.SZ"] == pytest.approx(
        current_roe - prior_roe
    )
    assert result["factor_dfs"]["sales_gross_margin_change_yoy_ttm"].loc[latest, "000001.SZ"] == pytest.approx(0.0)


def test_growth_returns_nan_when_prior_ttm_denominator_is_not_positive(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    income = pd.read_parquet(sources["Income"])
    prior_dates = income["report_date"].between("2023-06-30", "2024-03-31")
    income.loc[prior_dates, "net_profit_incl_min_int_inc_after"] = -100.0
    income.loc[prior_dates, "research_expenses"] = -100.0
    income.to_parquet(sources["Income"], index=False)
    close = pd.DataFrame({"000001.SZ": [10.0]}, index=[pd.Timestamp("2025-05-01")])

    result = build_stock_growth_raw_factor_bundle(C=close, stock_codes={"000001.SZ"}, source_globs=sources)

    assert pd.isna(result["factor_dfs"]["adjusted_net_profit_growth_yoy_ttm"].iloc[0, 0])
    assert pd.isna(result["factor_dfs"]["research_expense_growth_yoy_ttm"].iloc[0, 0])


def test_growth_uses_announce_date_as_effective_date(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    income = pd.read_parquet(sources["Income"])
    income.loc[income["report_date"] == income["report_date"].max(), "announce_date"] = pd.Timestamp("2025-06-01")
    income.to_parquet(sources["Income"], index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0, 10.0]},
        index=pd.to_datetime(["2025-05-01", "2025-06-02"]),
    )

    result = build_stock_growth_raw_factor_bundle(C=close, stock_codes={"000001.SZ"}, source_globs=sources)

    values = result["factor_dfs"]["revenue_growth_yoy_ttm"]["000001.SZ"]
    old_ttm = sum(100.0 + i for i in range(12, 16))
    old_prior = sum(100.0 + i for i in range(8, 12))
    new_ttm = sum(100.0 + i for i in range(13, 17))
    new_prior = sum(100.0 + i for i in range(9, 13))
    assert values.iloc[0] == pytest.approx((old_ttm / old_prior - 1) * 100)
    assert values.iloc[1] == pytest.approx((new_ttm / new_prior - 1) * 100)
