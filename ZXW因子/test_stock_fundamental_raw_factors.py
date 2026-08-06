from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from 股票基本面原始因子 import (
    _events_to_daily,
    _read_quarter_table,
    _point_in_time_quarter_factor_events,
    build_stock_fundamental_raw_factor_bundle,
    get_factor_catalog,
    get_factor_lookback_config,
)


EXPECTED_FACTOR_MAP = {
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
    "盈利收益率_EY_TTM": "earnings_yield_ttm",
    "账面市值比_BM": "book_to_market_ratio",
    "销售收益率_SY_TTM": "sales_yield_ttm",
    "经营现金流收益率_OCFY_TTM": "operating_cashflow_yield_ttm",
    "自由现金流收益率_FCFY_TTM": "free_cashflow_yield_ttm",
    "净现金市值比": "net_cash_to_market_value",
}


def _quarter_ends() -> pd.DatetimeIndex:
    return pd.PeriodIndex(
        [f"{year}Q{quarter}" for year in range(2021, 2026) for quarter in range(1, 5)][:-3],
        freq="Q",
    ).to_timestamp(how="end").normalize()


def _write_sources(tmp_path: Path) -> dict[str, str]:
    report_dates = _quarter_ends()
    rows: list[dict[str, object]] = []
    for i, report_date in enumerate(report_dates):
        quarter = int(report_date.quarter)
        standalone_revenue = 100.0 + i
        standalone_profit = 10.0 + i
        standalone_consolidated_profit = 15.0 + i
        standalone_cfo = 20.0 + i
        standalone_gross_profit = 40.0 + i
        cumulative_revenue = sum(
            100.0 + j
            for j in range(i - quarter + 1, i + 1)
        )
        cumulative_profit = sum(
            10.0 + j
            for j in range(i - quarter + 1, i + 1)
        )
        cumulative_consolidated_profit = sum(
            15.0 + j
            for j in range(i - quarter + 1, i + 1)
        )
        cumulative_cfo = sum(
            20.0 + j
            for j in range(i - quarter + 1, i + 1)
        )
        cumulative_gross_profit = sum(
            40.0 + j
            for j in range(i - quarter + 1, i + 1)
        )
        announce_date = report_date + pd.Timedelta(days=30)
        rows.append(
            {
                "htsc_code": "000001.SZ",
                "report_date": report_date,
                "announce_date": announce_date,
                "period": f"Q{quarter}",
                "revenue": cumulative_revenue,
                "net_profit_excl_min_int_inc": cumulative_profit,
                "net_profit_incl_min_int_inc": cumulative_consolidated_profit,
                "net_cash_flows_oper_act": cumulative_cfo,
                "cash_pay_acq_const_fiolta": 5.0 * quarter,
                "tot_liab": 30.0 + i,
                "tot_assets": 100.0 + i,
                "tot_shrhldr_eqy_excl_min_int": 70.0 + i,
                "cash_equivalents": 300.0,
                "shortterm_loan": 100.0,
                "long_term_loans": 200.0,
                "bonds_payable": 50.0,
                "sales_gross_profit": cumulative_gross_profit / cumulative_revenue * 100,
                "gross_profit": None,
                "equity_roe": None,
                "net_roe": None,
            }
        )

    common = pd.DataFrame(rows)
    source_paths: dict[str, str] = {}
    for table, columns in {
        "Income": [
            "htsc_code",
            "report_date",
            "announce_date",
            "period",
            "revenue",
            "net_profit_excl_min_int_inc",
            "net_profit_incl_min_int_inc",
        ],
        "CashFlow": ["htsc_code", "report_date", "announce_date", "period", "net_cash_flows_oper_act", "cash_pay_acq_const_fiolta"],
        "Balance": ["htsc_code", "report_date", "announce_date", "period", "tot_liab", "tot_assets", "tot_shrhldr_eqy_excl_min_int", "cash_equivalents", "shortterm_loan", "long_term_loans", "bonds_payable"],
        "PershareIndex": ["htsc_code", "report_date", "announce_date", "period", "sales_gross_profit", "gross_profit", "equity_roe", "net_roe"],
    }.items():
        path = tmp_path / f"{table}.parquet"
        common[columns].to_parquet(path, index=False)
        source_paths[table] = str(path)

    valuation = pd.DataFrame(
        {
            "htsc_code": ["000001.SZ"],
            "time": [pd.Timestamp("2025-06-01")],
            "pe_ttm": [10.0],
            "pb": [2.5],
            "revenue_ttm": [400.0],
            "total_market_val": [1000.0],
        }
    )
    valuation_path = tmp_path / "valuation.parquet"
    valuation.to_parquet(valuation_path, index=False)
    source_paths["valuation"] = str(valuation_path)
    return source_paths


def test_catalog_and_lookback_contract() -> None:
    assert get_factor_catalog()["factor_name_map"] == EXPECTED_FACTOR_MAP
    lookback = get_factor_lookback_config()
    assert lookback["bundle_id"] == "stock_fundamental_raw"
    assert set(lookback["factor_lookback_days"].values()) == {0}
    assert lookback["source_history_calendar_days"] >= 1460


def test_bundle_only_builds_requested_factor(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    close = pd.DataFrame(
        {"000001.SZ": [10.0]},
        index=pd.to_datetime(["2025-06-01"]),
    )

    result = build_stock_fundamental_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_globs=sources,
        target_factor_keys={"return_on_assets_ttm"},
    )

    assert set(result["factor_dfs"]) == {"return_on_assets_ttm"}
    assert result["factor_name_map"] == {
        "总资产收益率_ROA": "return_on_assets_ttm"
    }


def test_bundle_reads_only_dependencies_for_requested_factor(tmp_path: Path, monkeypatch) -> None:
    sources = _write_sources(tmp_path)
    close = pd.DataFrame(
        {"000001.SZ": [10.0]},
        index=pd.to_datetime(["2025-06-01"]),
    )
    import 股票基本面原始因子 as fundamental_module

    calls: list[tuple[str, tuple[str, ...]]] = []
    original = fundamental_module._read_quarter_table

    def counted_reader(*, source_glob, columns, stock_codes, start_date, end_date):
        calls.append((Path(source_glob).name, tuple(columns)))
        return original(
            source_glob=source_glob,
            columns=columns,
            stock_codes=stock_codes,
            start_date=start_date,
            end_date=end_date,
        )

    monkeypatch.setattr(fundamental_module, "_read_quarter_table", counted_reader)
    build_stock_fundamental_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_globs=sources,
        target_factor_keys={"return_on_assets_ttm"},
    )

    assert set(calls) == {
        ("Income.parquet", ("net_profit_incl_min_int_inc",)),
        ("Balance.parquet", ("tot_assets",)),
    }


def test_quarterly_incremental_events_match_full_recompute(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    frames = {
        table: pd.read_parquet(sources[table])
        for table in ("Income", "Balance", "CashFlow", "PershareIndex")
    }
    revised = frames["Income"].loc[
        frames["Income"]["report_date"] == frames["Income"]["report_date"].max()
    ].copy()
    revised["announce_date"] = pd.Timestamp("2025-05-15")
    revised["net_profit_excl_min_int_inc"] += 20.0
    frames["Income"] = pd.concat([frames["Income"], revised], ignore_index=True)
    requested = {"return_on_equity_ttm", "return_on_equity_std_12q", "return_on_assets_ttm"}

    full = _point_in_time_quarter_factor_events(
        frames["Income"], frames["Balance"], frames["CashFlow"], frames["PershareIndex"],
        factor_keys=requested, incremental=False,
    )
    incremental = _point_in_time_quarter_factor_events(
        frames["Income"], frames["Balance"], frames["CashFlow"], frames["PershareIndex"],
        factor_keys=requested, incremental=True,
    )
    for key in requested:
        pd.testing.assert_frame_equal(full[key], incremental[key])


def test_bundle_calculates_ttm_and_filters_non_stocks(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    dates = pd.to_datetime(["2025-05-01", "2025-06-01"])
    close = pd.DataFrame(
        {
            "000001.SZ": [10.0, 10.0],
            "510300.SH": [4.0, 4.0],
            "881001.THS": [1.0, 1.0],
        },
        index=dates,
    )

    result = build_stock_fundamental_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_globs=sources,
    )

    assert result["bundle_id"] == "stock_fundamental_raw"
    assert list(result["factor_dfs"]["price_to_book_ratio"].columns) == ["000001.SZ"]
    assert result["factor_dfs"]["price_to_book_ratio"].loc[pd.Timestamp("2025-06-01"), "000001.SZ"] == 2.5
    assert pd.isna(result["factor_dfs"]["price_to_book_ratio"].loc[pd.Timestamp("2025-05-01"), "000001.SZ"])

    latest = pd.Timestamp("2025-06-01")
    ttm_revenue = 113.0 + 114.0 + 115.0 + 116.0
    assert result["factor_dfs"]["return_on_equity_ttm"].loc[
        latest, "000001.SZ"
    ] == pytest.approx((23.0 + 24.0 + 25.0 + 26.0) / ((82.0 + 86.0) / 2.0) * 100)
    assert result["factor_dfs"]["sales_gross_margin_ttm"].loc[
        latest, "000001.SZ"
    ] == pytest.approx((53.0 + 54.0 + 55.0 + 56.0) / ttm_revenue * 100)
    assert result["factor_dfs"]["operating_cashflow_to_revenue_ttm"].loc[
        latest, "000001.SZ"
    ] == pytest.approx((33.0 + 34.0 + 35.0 + 36.0) / ttm_revenue * 100)
    assert result["factor_dfs"]["debt_to_asset_ratio"].loc[
        latest, "000001.SZ"
    ] == pytest.approx(46.0 / 116.0 * 100)
    ttm_parent_profit = 23.0 + 24.0 + 25.0 + 26.0
    ttm_consolidated_profit = 28.0 + 29.0 + 30.0 + 31.0
    ttm_cfo = 33.0 + 34.0 + 35.0 + 36.0
    ttm_gross_profit = 53.0 + 54.0 + 55.0 + 56.0
    average_assets = (112.0 + 116.0) / 2.0
    assert result["factor_dfs"]["return_on_assets_ttm"].loc[
        latest, "000001.SZ"
    ] == pytest.approx(ttm_consolidated_profit / average_assets * 100)
    assert result["factor_dfs"]["gross_profit_to_assets_ttm"].loc[
        latest, "000001.SZ"
    ] == pytest.approx(ttm_gross_profit / average_assets * 100)
    assert result["factor_dfs"]["operating_cashflow_to_net_profit_ttm"].loc[
        latest, "000001.SZ"
    ] == pytest.approx(ttm_cfo / ttm_consolidated_profit)
    assert result["factor_dfs"]["accruals_to_assets_ttm"].loc[
        latest, "000001.SZ"
    ] == pytest.approx((ttm_consolidated_profit - ttm_cfo) / average_assets * 100)
    assert result["factor_dfs"]["asset_turnover_ttm"].loc[
        latest, "000001.SZ"
    ] == pytest.approx(ttm_revenue / average_assets)
    assert result["factor_dfs"]["return_on_equity_ttm"].loc[
        latest, "000001.SZ"
    ] == pytest.approx(ttm_parent_profit / ((82.0 + 86.0) / 2.0) * 100)

    roe_history = []
    margin_history = []
    for i in range(5, 17):
        revenue = sum(100.0 + j for j in range(i - 3, i + 1))
        profit = sum(10.0 + j for j in range(i - 3, i + 1))
        gross_profit = sum(40.0 + j for j in range(i - 3, i + 1))
        average_equity = ((70.0 + i - 4) + (70.0 + i)) / 2.0
        roe_history.append(profit / average_equity * 100)
        margin_history.append(gross_profit / revenue * 100)
    assert result["factor_dfs"]["return_on_equity_std_12q"].loc[
        latest, "000001.SZ"
    ] == pytest.approx(float(np.std(roe_history, ddof=0)))
    assert result["factor_dfs"]["sales_gross_margin_std_12q"].loc[
        latest, "000001.SZ"
    ] == pytest.approx(float(np.std(margin_history, ddof=0)))


def test_bundle_never_uses_report_before_announce_date(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    close = pd.DataFrame(
        {"000001.SZ": [10.0, 10.0]},
        index=pd.to_datetime(["2025-01-01", "2025-05-01"]),
    )

    result = build_stock_fundamental_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_globs=sources,
    )

    before = result["factor_dfs"]["return_on_equity_ttm"].loc[
        pd.Timestamp("2025-01-01"), "000001.SZ"
    ]
    after = result["factor_dfs"]["return_on_equity_ttm"].loc[
        pd.Timestamp("2025-05-01"), "000001.SZ"
    ]
    assert before != after


def test_bundle_returns_nan_for_non_positive_revenue_denominator(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    income = pd.read_parquet(sources["Income"])
    income["revenue"] = 0.0
    income.to_parquet(sources["Income"], index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0]},
        index=pd.to_datetime(["2025-06-01"]),
    )

    result = build_stock_fundamental_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_globs=sources,
    )

    assert pd.isna(
        result["factor_dfs"]["operating_cashflow_to_revenue_ttm"].iloc[0, 0]
    )


def test_cash_conversion_is_nan_when_ttm_net_profit_is_not_positive(
    tmp_path: Path,
) -> None:
    sources = _write_sources(tmp_path)
    income = pd.read_parquet(sources["Income"])
    latest_report = income["report_date"].max()
    income.loc[
        income["report_date"] == latest_report,
        "net_profit_incl_min_int_inc",
    ] = -1000.0
    income.to_parquet(sources["Income"], index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0]},
        index=pd.to_datetime(["2025-06-01"]),
    )

    result = build_stock_fundamental_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_globs=sources,
    )

    assert pd.isna(
        result["factor_dfs"]["operating_cashflow_to_net_profit_ttm"].iloc[0, 0]
    )


@pytest.mark.parametrize(
    ("table", "columns", "factor_key"),
    [
        ("Income", ["net_profit_excl_min_int_inc"], "return_on_equity_ttm"),
        (
            "PershareIndex",
            ["sales_gross_profit", "gross_profit"],
            "sales_gross_margin_ttm",
        ),
        (
            "CashFlow",
            ["net_cash_flows_oper_act"],
            "operating_cashflow_to_revenue_ttm",
        ),
        ("Balance", ["tot_assets"], "debt_to_asset_ratio"),
    ],
)
def test_latest_missing_input_does_not_reuse_older_factor_value(
    tmp_path: Path,
    table: str,
    columns: list[str],
    factor_key: str,
) -> None:
    sources = _write_sources(tmp_path)
    source = pd.read_parquet(sources[table])
    latest_report = source["report_date"].max()
    source.loc[source["report_date"] == latest_report, columns] = float("nan")
    source.to_parquet(sources[table], index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0]},
        index=pd.to_datetime(["2025-06-01"]),
    )

    result = build_stock_fundamental_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_globs=sources,
    )

    assert pd.isna(result["factor_dfs"][factor_key].iloc[0, 0])


def test_factor_keeps_prior_value_until_all_required_tables_publish(
    tmp_path: Path,
) -> None:
    sources = _write_sources(tmp_path)
    balance = pd.read_parquet(sources["Balance"])
    latest_report = balance["report_date"].max()
    balance.loc[
        balance["report_date"] == latest_report,
        "announce_date",
    ] = pd.Timestamp("2025-05-15")
    balance.to_parquet(sources["Balance"], index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0]},
        index=pd.to_datetime(["2025-05-01"]),
    )

    result = build_stock_fundamental_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_globs=sources,
    )

    expected_prior_roe = (22.0 + 23.0 + 24.0 + 25.0) / (
        (81.0 + 85.0) / 2.0
    ) * 100
    assert result["factor_dfs"]["return_on_equity_ttm"].iloc[
        0, 0
    ] == pytest.approx(expected_prior_roe)


def test_cash_conversion_waits_for_cashflow_before_clearing_prior_value(
    tmp_path: Path,
) -> None:
    sources = _write_sources(tmp_path)
    income = pd.read_parquet(sources["Income"])
    latest_report = income["report_date"].max()
    income.loc[
        income["report_date"] == latest_report,
        "net_profit_incl_min_int_inc",
    ] = -1000.0
    income.to_parquet(sources["Income"], index=False)
    cashflow = pd.read_parquet(sources["CashFlow"])
    cashflow.loc[
        cashflow["report_date"] == latest_report,
        "announce_date",
    ] = pd.Timestamp("2025-05-15")
    cashflow.to_parquet(sources["CashFlow"], index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0]},
        index=pd.to_datetime(["2025-05-01"]),
    )

    result = build_stock_fundamental_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_globs=sources,
    )

    expected_prior_cash_conversion = (32.0 + 33.0 + 34.0 + 35.0) / (
        27.0 + 28.0 + 29.0 + 30.0
    )
    assert result["factor_dfs"]["operating_cashflow_to_net_profit_ttm"].iloc[
        0, 0
    ] == pytest.approx(expected_prior_cash_conversion)


def test_partial_new_quarter_disclosure_keeps_last_complete_quality_values(
    tmp_path: Path,
) -> None:
    sources = _write_sources(tmp_path)
    latest_report = _quarter_ends().max()
    for table in ("Balance", "CashFlow", "PershareIndex"):
        frame = pd.read_parquet(sources[table])
        frame.loc[frame["report_date"] == latest_report, "announce_date"] = pd.Timestamp(
            "2025-05-20"
        )
        frame.to_parquet(sources[table], index=False)
    income = pd.read_parquet(sources["Income"])
    income.loc[income["report_date"] == latest_report, "announce_date"] = pd.Timestamp(
        "2025-04-15"
    )
    income.to_parquet(sources["Income"], index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0]},
        index=pd.to_datetime(["2025-05-01"]),
    )

    result = build_stock_fundamental_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_globs=sources,
    )

    for factor_key in (
        "return_on_assets_ttm",
        "gross_profit_to_assets_ttm",
        "operating_cashflow_to_net_profit_ttm",
        "accruals_to_assets_ttm",
        "asset_turnover_ttm",
    ):
        assert pd.notna(result["factor_dfs"][factor_key].iloc[0, 0])


def test_event_alignment_uses_vectorized_event_ids_without_asof_join(monkeypatch) -> None:
    calls = 0
    original = pd.merge_asof

    def counted_merge_asof(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(pd, "merge_asof", counted_merge_asof)
    events = pd.DataFrame(
        {
            "htsc_code": ["000001.SZ", "000002.SZ"],
            "effective_date": pd.to_datetime(["2025-01-01", "2025-01-01"]),
            "value": [1.0, 2.0],
        }
    )
    result = _events_to_daily(
        events,
        pd.DatetimeIndex([pd.Timestamp("2025-01-02")]),
        ["000001.SZ", "000002.SZ"],
    )

    assert calls == 0
    assert result.loc[pd.Timestamp("2025-01-02"), "000001.SZ"] == 1.0
    assert result.loc[pd.Timestamp("2025-01-02"), "000002.SZ"] == 2.0


def test_event_alignment_normalizes_datetime_precision() -> None:
    events = pd.DataFrame(
        {
            "htsc_code": ["000001.SZ"],
            "effective_date": pd.DatetimeIndex(["2025-01-01"]).as_unit("ns"),
            "value": [1.0],
        }
    )
    index = pd.DatetimeIndex(["2025-01-02"]).as_unit("us")

    result = _events_to_daily(events, index, ["000001.SZ"])

    assert result.loc[pd.Timestamp("2025-01-02"), "000001.SZ"] == 1.0


def test_restatement_only_changes_factor_after_restatement_announce(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    income = pd.read_parquet(sources["Income"])
    revised = income.loc[income["report_date"] == income["report_date"].max()].copy()
    revised["announce_date"] = pd.Timestamp("2025-05-15")
    revised["revenue"] = revised["revenue"] + 100.0
    revised["net_profit_excl_min_int_inc"] = revised["net_profit_excl_min_int_inc"] + 20.0
    pd.concat([income, revised], ignore_index=True).to_parquet(sources["Income"], index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0, 10.0]},
        index=pd.to_datetime(["2025-05-01", "2025-05-20"]),
    )

    result = build_stock_fundamental_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_globs=sources,
    )

    roe = result["factor_dfs"]["return_on_equity_ttm"]["000001.SZ"]
    assert roe.loc[pd.Timestamp("2025-05-01")] == pytest.approx(
        (23.0 + 24.0 + 25.0 + 26.0) / ((82.0 + 86.0) / 2.0) * 100
    )
    assert roe.loc[pd.Timestamp("2025-05-20")] == pytest.approx(
        (23.0 + 24.0 + 25.0 + 46.0) / ((82.0 + 86.0) / 2.0) * 100
    )


def test_quarter_reader_drops_unchanged_repeat_disclosures(tmp_path: Path) -> None:
    path = tmp_path / "income.parquet"
    pd.DataFrame(
        {
            "htsc_code": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "report_date": pd.to_datetime(["2024-12-31"] * 3),
            "announce_date": pd.to_datetime(["2025-03-01", "2025-04-01", "2025-05-01"]),
            "period": ["Q4"] * 3,
            "revenue": [100.0, 100.0, 110.0],
        }
    ).to_parquet(path, index=False)

    result = _read_quarter_table(
        source_glob=str(path),
        columns=["revenue"],
        stock_codes=["000001.SZ"],
        start_date=pd.Timestamp("2024-01-01"),
        end_date=pd.Timestamp("2025-12-31"),
    )

    assert result["announce_date"].tolist() == [
        pd.Timestamp("2025-03-01"),
        pd.Timestamp("2025-05-01"),
    ]


def test_bundle_reports_missing_required_source_column(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    income = pd.read_parquet(sources["Income"]).drop(
        columns=["net_profit_excl_min_int_inc"]
    )
    income.to_parquet(sources["Income"], index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0]},
        index=pd.to_datetime(["2025-06-01"]),
    )

    with pytest.raises(ValueError, match="基本面源缺少字段.*net_profit_excl_min_int_inc"):
        build_stock_fundamental_raw_factor_bundle(
            C=close,
            stock_codes={"000001.SZ"},
            source_globs=sources,
        )


def test_bundle_does_not_require_unused_pershare_roe_columns(
    tmp_path: Path,
) -> None:
    sources = _write_sources(tmp_path)
    pershare = pd.read_parquet(sources["PershareIndex"]).drop(
        columns=["equity_roe", "net_roe"]
    )
    pershare.to_parquet(sources["PershareIndex"], index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0]},
        index=pd.to_datetime(["2025-06-01"]),
    )

    result = build_stock_fundamental_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_globs=sources,
    )

    assert np.isfinite(result["factor_dfs"]["sales_gross_margin_ttm"].iloc[0, 0])


def test_bundle_does_not_require_unused_period_column(tmp_path: Path) -> None:
    sources = _write_sources(tmp_path)
    for table in ("Income", "Balance", "CashFlow", "PershareIndex"):
        source = pd.read_parquet(sources[table]).drop(columns=["period"])
        source.to_parquet(sources[table], index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0]},
        index=pd.to_datetime(["2025-06-01"]),
    )

    result = build_stock_fundamental_raw_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_globs=sources,
    )

    assert np.isfinite(result["factor_dfs"]["return_on_equity_ttm"].iloc[0, 0])
