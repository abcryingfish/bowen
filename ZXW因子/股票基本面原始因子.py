"""股票基本面与绝对价值原始因子。"""
from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


BUNDLE_ID = "stock_fundamental_raw"
SOURCE_HISTORY_CALENDAR_DAYS = 1700
FINANCIAL_ROOT = r"D:\database\qmt_company_data"
DEFAULT_SOURCE_GLOBS = {
    "Income": rf"{FINANCIAL_ROOT}\table=Income\year=*\month=*\merged.parquet",
    "Balance": rf"{FINANCIAL_ROOT}\table=Balance\year=*\month=*\merged.parquet",
    "CashFlow": rf"{FINANCIAL_ROOT}\table=CashFlow\year=*\month=*\merged.parquet",
    "PershareIndex": rf"{FINANCIAL_ROOT}\table=PershareIndex\year=*\month=*\merged.parquet",
    "valuation": rf"{FINANCIAL_ROOT}\table=factor_fundamental_valuation\year=*\month=*\merged.parquet",
}
FACTOR_NAME_MAP = {
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

DAILY_VALUATION_FACTOR_KEYS = {
    "price_to_book_ratio",
    "earnings_yield_ttm",
    "book_to_market_ratio",
    "sales_yield_ttm",
}

# 每个财报因子只读取和计算自身需要的字段；稳定性因子复用对应的基础因子。
FACTOR_SOURCE_COLUMNS = {
    "return_on_equity_ttm": {
        "Income": ("net_profit_excl_min_int_inc",),
        "Balance": ("tot_shrhldr_eqy_excl_min_int",),
    },
    "sales_gross_margin_ttm": {
        "Income": ("revenue",),
        "PershareIndex": ("sales_gross_profit", "gross_profit"),
    },
    "operating_cashflow_to_revenue_ttm": {
        "Income": ("revenue",),
        "CashFlow": ("net_cash_flows_oper_act",),
    },
    "debt_to_asset_ratio": {
        "Balance": ("tot_liab", "tot_assets"),
    },
    "return_on_assets_ttm": {
        "Income": ("net_profit_incl_min_int_inc",),
        "Balance": ("tot_assets",),
    },
    "gross_profit_to_assets_ttm": {
        "Income": ("revenue",),
        "PershareIndex": ("sales_gross_profit", "gross_profit"),
        "Balance": ("tot_assets",),
    },
    "operating_cashflow_to_net_profit_ttm": {
        "Income": ("net_profit_incl_min_int_inc",),
        "CashFlow": ("net_cash_flows_oper_act",),
    },
    "accruals_to_assets_ttm": {
        "Income": ("net_profit_incl_min_int_inc",),
        "CashFlow": ("net_cash_flows_oper_act",),
        "Balance": ("tot_assets",),
    },
    "asset_turnover_ttm": {
        "Income": ("revenue",),
        "Balance": ("tot_assets",),
    },
    "return_on_equity_std_12q": {
        "Income": ("net_profit_excl_min_int_inc",),
        "Balance": ("tot_shrhldr_eqy_excl_min_int",),
    },
    "sales_gross_margin_std_12q": {
        "Income": ("revenue",),
        "PershareIndex": ("sales_gross_profit", "gross_profit"),
    },
    "operating_cashflow_yield_ttm": {
        "CashFlow": ("net_cash_flows_oper_act",),
    },
    "free_cashflow_yield_ttm": {
        "CashFlow": ("net_cash_flows_oper_act", "cash_pay_acq_const_fiolta"),
    },
    "net_cash_to_market_value": {
        "Balance": (
            "cash_equivalents",
            "shortterm_loan",
            "long_term_loans",
            "bonds_payable",
        ),
    },
}


def _source_columns_for_factor_keys(
    factor_keys: set[str],
) -> dict[str, list[str]]:
    columns_by_table: dict[str, set[str]] = {}
    for factor_key in factor_keys:
        for table, columns in FACTOR_SOURCE_COLUMNS.get(factor_key, {}).items():
            columns_by_table.setdefault(table, set()).update(columns)
    return {
        table: sorted(columns)
        for table, columns in columns_by_table.items()
    }


def get_factor_catalog() -> dict[str, dict[str, str]]:
    return {"factor_name_map": dict(FACTOR_NAME_MAP)}


def get_factor_lookback_config() -> dict[str, object]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": 0,
        "factor_lookback_days": {key: 0 for key in FACTOR_NAME_MAP.values()},
        "source_history_calendar_days": SOURCE_HISTORY_CALENDAR_DAYS,
    }


def _normalize_code(value: object) -> str:
    return str(value or "").strip().upper()


def _validate_source_columns(
    con: duckdb.DuckDBPyConnection,
    source: str | list[str],
    required_columns: list[str],
) -> None:
    available = {
        str(row[0])
        for row in con.execute(
            "DESCRIBE SELECT * FROM read_parquet(?, union_by_name=true)",
            [source],
        ).fetchall()
    }
    missing = [column for column in required_columns if column not in available]
    if missing:
        raise ValueError(
            f"基本面源缺少字段: {', '.join(missing)}；source={source}"
        )


def _resolve_paths(source_glob: str, start_date: pd.Timestamp, end_date: pd.Timestamp) -> list[str]:
    path = Path(source_glob)
    if path.is_file():
        return [str(path)]

    paths = [Path(item) for item in glob.glob(str(source_glob))]
    selected: list[tuple[tuple[int, int], Path]] = []
    unpartitioned: list[Path] = []
    start_key = (int(start_date.year), int(start_date.month))
    end_key = (int(end_date.year), int(end_date.month))
    for item in paths:
        try:
            year = int(item.parent.parent.name.split("=", 1)[1])
            month = int(item.parent.name.split("=", 1)[1])
        except (IndexError, ValueError):
            unpartitioned.append(item)
            continue
        if start_key <= (year, month) <= end_key:
            selected.append(((year, month), item))
    if selected:
        return [str(item) for _, item in sorted(selected)]
    return [str(item) for item in sorted(unpartitioned)]


def _read_quarter_table(
    *,
    source_glob: str,
    columns: list[str],
    stock_codes: list[str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    paths = _resolve_paths(source_glob, start_date, end_date)
    if not paths:
        raise ValueError(f"基本面源没有可读取分区: {source_glob}")
    source: str | list[str] = paths[0] if len(paths) == 1 else paths
    placeholders = ", ".join("?" for _ in stock_codes)
    select_sql = ", ".join(
        [
            "UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code",
            "CAST(report_date AS DATE) AS report_date",
            "CAST(announce_date AS DATE) AS announce_date",
            *[f"TRY_CAST({column} AS DOUBLE) AS {column}" for column in columns],
        ]
    )
    sql = f"""
        SELECT {select_sql}
        FROM read_parquet(?, union_by_name=true)
        WHERE CAST(report_date AS DATE) BETWEEN ? AND ?
          AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN ({placeholders})
        ORDER BY htsc_code, report_date, announce_date
    """
    with duckdb.connect(database=":memory:") as con:
        _validate_source_columns(
            con,
            source,
            ["htsc_code", "report_date", "announce_date", *columns],
        )
        frame = con.execute(
            sql,
            [source, start_date.date(), end_date.date(), *stock_codes],
        ).df()
    frame["report_date"] = pd.to_datetime(frame["report_date"], errors="coerce").dt.floor("D")
    frame["announce_date"] = pd.to_datetime(frame["announce_date"], errors="coerce").dt.floor("D")
    frame = frame.dropna(subset=["report_date", "announce_date"])
    frame["htsc_code"] = frame["htsc_code"].map(_normalize_code)
    frame = frame.drop_duplicates(
        ["htsc_code", "report_date", "announce_date"], keep="last"
    )
    frame = frame.sort_values(
        ["htsc_code", "report_date", "announce_date"]
    ).reset_index(drop=True)
    groups = frame.groupby(["htsc_code", "report_date"], sort=False)
    previous = groups[columns].shift()
    current = frame[columns]
    unchanged = (current.eq(previous) | (current.isna() & previous.isna())).all(axis=1)
    first_version = groups.cumcount().eq(0)
    return frame.loc[first_version | ~unchanged].reset_index(drop=True)


def _read_valuation_daily(
    *,
    source_glob: str,
    stock_codes: list[str],
    index: pd.DatetimeIndex,
    columns: tuple[str, ...],
) -> dict[str, pd.DataFrame]:
    paths = _resolve_paths(source_glob, index.min(), index.max())
    if not paths:
        raise ValueError(f"估值源没有可读取分区: {source_glob}")
    source: str | list[str] = paths[0] if len(paths) == 1 else paths
    placeholders = ", ".join("?" for _ in stock_codes)
    with duckdb.connect(database=":memory:") as con:
        _validate_source_columns(con, source, ["htsc_code", "time", *columns])
        source_max = con.execute(
            "SELECT MAX(CAST(time AS DATE)) FROM read_parquet(?, union_by_name=true)",
            [source],
        ).fetchone()[0]
        if source_max is None or source_max < index.max().date():
            raise ValueError(
                "factor_fundamental_valuation 尚未更新到 "
                f"{index.max().date()}（当前查询分区最新 {source_max}），停止生成 PB 因子"
            )
        selected_columns = ",\n                ".join(
            f"TRY_CAST({column} AS DOUBLE) AS {column}" for column in columns
        )
        frame = con.execute(
            f"""
            SELECT
                UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                CAST(time AS DATE) AS time,
                {selected_columns}
            FROM read_parquet(?, union_by_name=true)
            WHERE CAST(time AS DATE) BETWEEN ? AND ?
              AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN ({placeholders})
            ORDER BY time, htsc_code
            """,
            [source, index.min().date(), index.max().date(), *stock_codes],
        ).df()
    if frame.empty:
        return {
            column: pd.DataFrame(index=index, columns=stock_codes, dtype=float)
            for column in columns
        }
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    frame = frame.drop_duplicates(["time", "htsc_code"], keep="last")
    output: dict[str, pd.DataFrame] = {}
    for column in columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        output[column] = (
            frame.pivot(index="time", columns="htsc_code", values=column)
            .reindex(index=index, columns=stock_codes)
            .astype(float)
        )
    return output


def _read_pb_daily(
    *,
    source_glob: str,
    stock_codes: list[str],
    index: pd.DatetimeIndex,
) -> pd.DataFrame:
    return _read_valuation_daily(
        source_glob=source_glob,
        stock_codes=stock_codes,
        index=index,
        columns=("pb",),
    )["pb"].where(lambda frame: np.isfinite(frame) & (frame > 0))


def _standalone_values(values: np.ndarray, quarters: np.ndarray, years: np.ndarray) -> np.ndarray:
    result = np.full(len(values), np.nan, dtype=float)
    finite = np.isfinite(values)
    first_quarter = finite & (quarters == 1)
    result[first_quarter] = values[first_quarter]
    if len(values) <= 1:
        return result
    sequential = (
        finite[1:]
        & np.isfinite(values[:-1])
        & (years[1:] == years[:-1])
        & (quarters[1:] == quarters[:-1] + 1)
    )
    result[1:][sequential] = values[1:][sequential] - values[:-1][sequential]
    return result


def _snapshot_factor_values(
    states: dict[str, dict[pd.Timestamp, dict[str, Any]]],
    factor_keys: set[str] | None = None,
    *,
    changed_tables: set[str] | None = None,
    previous_values: dict[str, float] | None = None,
    prepared_context: dict[str, Any] | None = None,
) -> dict[str, float]:
    available_factor_keys = set(FACTOR_SOURCE_COLUMNS)
    selected_factor_keys = sorted(
        available_factor_keys
        if factor_keys is None
        else available_factor_keys & set(factor_keys)
    )
    report_dates = (
        list(prepared_context["report_dates"])
        if prepared_context is not None
        else sorted(set().union(*(set(table_state) for table_state in states.values())))
    )
    dirty_factor_keys = {
        key
        for key in selected_factor_keys
        if changed_tables is None
        or bool(set(FACTOR_SOURCE_COLUMNS[key]) & set(changed_tables))
    }
    result = {
        key: (
            float(previous_values[key])
            if previous_values is not None and key not in dirty_factor_keys
            else np.nan
        )
        for key in selected_factor_keys
    }
    if not report_dates:
        return result

    def values(table: str, column: str) -> np.ndarray:
        if prepared_context is not None:
            cached = prepared_context["arrays"].get((table, column))
            if cached is None:
                return np.full(len(report_dates), np.nan, dtype=float)
            return cached
        output = []
        table_state = states[table]
        for report_date in report_dates:
            raw_value = table_state.get(report_date, {}).get(column)
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                value = np.nan
            output.append(value if np.isfinite(value) else np.nan)
        return np.asarray(output, dtype=float)

    dates = pd.DatetimeIndex(report_dates)
    quarters = dates.quarter.to_numpy(dtype=int)
    years = dates.year.to_numpy(dtype=int)
    ordinal = years * 4 + quarters

    def rolling_stat(values_array: np.ndarray, window: int, statistic: str) -> np.ndarray:
        output = np.full(len(values_array), np.nan, dtype=float)
        if len(values_array) < window:
            return output
        windows = np.lib.stride_tricks.sliding_window_view(values_array, window)
        end_positions = np.arange(window - 1, len(values_array))
        valid = (
            np.isfinite(windows).all(axis=1)
            & (ordinal[end_positions] - ordinal[end_positions - window + 1] == window - 1)
        )
        if statistic == "sum":
            computed = np.sum(windows, axis=1)
        elif statistic == "std":
            computed = np.std(windows, axis=1, ddof=0)
        else:
            raise ValueError(f"不支持的滚动统计: {statistic}")
        output[end_positions[valid]] = computed[valid]
        return output

    def average_lagged(values_array: np.ndarray, lag: int) -> np.ndarray:
        output = np.full(len(values_array), np.nan, dtype=float)
        if len(values_array) <= lag:
            return output
        positions = np.arange(lag, len(values_array))
        valid = (
            np.isfinite(values_array[positions])
            & np.isfinite(values_array[positions - lag])
            & (ordinal[positions] - ordinal[positions - lag] == lag)
        )
        averages = (values_array[positions] + values_array[positions - lag]) / 2.0
        valid &= averages > 0
        output[positions[valid]] = averages[valid]
        return output

    def safe_ratio(
        numerator: np.ndarray,
        denominator: np.ndarray,
        *,
        scale: float = 1.0,
        positive_denominator: bool = True,
    ) -> np.ndarray:
        output = np.full(len(numerator), np.nan, dtype=float)
        valid = np.isfinite(numerator) & np.isfinite(denominator)
        if positive_denominator:
            valid &= denominator > 0
        else:
            valid &= denominator != 0
        output[valid] = numerator[valid] / denominator[valid] * scale
        return output

    empty = lambda: np.full(len(report_dates), np.nan, dtype=float)
    compute_factor_keys = set(dirty_factor_keys)
    if "return_on_equity_std_12q" in compute_factor_keys:
        compute_factor_keys.add("return_on_equity_ttm")
    if "sales_gross_margin_std_12q" in compute_factor_keys:
        compute_factor_keys.add("sales_gross_margin_ttm")
    needs_revenue = bool(
        {"sales_gross_margin_ttm", "sales_gross_margin_std_12q",
         "operating_cashflow_to_revenue_ttm", "gross_profit_to_assets_ttm",
         "asset_turnover_ttm"} & compute_factor_keys
    )
    needs_parent_profit = bool(
        {"return_on_equity_ttm", "return_on_equity_std_12q"} & compute_factor_keys
    )
    needs_consolidated_profit = bool(
        {"return_on_assets_ttm", "operating_cashflow_to_net_profit_ttm",
         "accruals_to_assets_ttm"} & compute_factor_keys
    )
    needs_cfo = bool(
        {"operating_cashflow_to_revenue_ttm", "operating_cashflow_to_net_profit_ttm",
         "accruals_to_assets_ttm", "operating_cashflow_yield_ttm",
         "free_cashflow_yield_ttm"} & compute_factor_keys
    )
    needs_capex = "free_cashflow_yield_ttm" in compute_factor_keys
    needs_net_cash = "net_cash_to_market_value" in compute_factor_keys
    needs_margin = bool(
        {"sales_gross_margin_ttm", "sales_gross_margin_std_12q",
         "gross_profit_to_assets_ttm"} & compute_factor_keys
    )
    revenue_cum = values("Income", "revenue") if needs_revenue or needs_margin else empty()
    parent_profit_cum = values("Income", "net_profit_excl_min_int_inc") if needs_parent_profit else empty()
    consolidated_profit_cum = values("Income", "net_profit_incl_min_int_inc") if needs_consolidated_profit else empty()
    cfo_cum = values("CashFlow", "net_cash_flows_oper_act") if needs_cfo else empty()
    capex_cum = (
        np.abs(values("CashFlow", "cash_pay_acq_const_fiolta"))
        if needs_capex
        else empty()
    )
    margin = values("PershareIndex", "sales_gross_profit") if needs_margin else empty()
    margin_fallback = values("PershareIndex", "gross_profit") if needs_margin else empty()
    margin = np.where(np.isfinite(margin), margin, margin_fallback)
    gross_profit_cum = revenue_cum * margin / 100.0
    revenue_q = _standalone_values(revenue_cum, quarters, years)
    parent_profit_q = _standalone_values(parent_profit_cum, quarters, years)
    consolidated_profit_q = _standalone_values(consolidated_profit_cum, quarters, years)
    cfo_q = _standalone_values(cfo_cum, quarters, years)
    capex_q = _standalone_values(capex_cum, quarters, years)
    gross_profit_q = _standalone_values(gross_profit_cum, quarters, years)
    needs_equity = needs_parent_profit
    needs_liabilities = "debt_to_asset_ratio" in selected_factor_keys
    needs_assets = bool(
        {"debt_to_asset_ratio", "return_on_assets_ttm", "gross_profit_to_assets_ttm",
         "accruals_to_assets_ttm", "asset_turnover_ttm"} & compute_factor_keys
    )
    equity = values("Balance", "tot_shrhldr_eqy_excl_min_int") if needs_equity else empty()
    liabilities = values("Balance", "tot_liab") if needs_liabilities else empty()
    assets = values("Balance", "tot_assets") if needs_assets else empty()
    cash_equivalents = values("Balance", "cash_equivalents") if needs_net_cash else empty()
    shortterm_loan = values("Balance", "shortterm_loan") if needs_net_cash else empty()
    long_term_loans = values("Balance", "long_term_loans") if needs_net_cash else empty()
    bonds_payable = values("Balance", "bonds_payable") if needs_net_cash else empty()
    ttm_revenue = rolling_stat(revenue_q, 4, "sum") if needs_revenue or needs_margin else empty()
    ttm_parent_profit = rolling_stat(parent_profit_q, 4, "sum") if needs_parent_profit else empty()
    ttm_consolidated_profit = rolling_stat(consolidated_profit_q, 4, "sum") if needs_consolidated_profit else empty()
    ttm_cfo = rolling_stat(cfo_q, 4, "sum") if needs_cfo else empty()
    ttm_capex = rolling_stat(capex_q, 4, "sum") if needs_capex else empty()
    ttm_gross_profit = rolling_stat(gross_profit_q, 4, "sum") if needs_margin else empty()
    average_equity = average_lagged(equity, 4) if needs_equity else empty()
    average_assets = average_lagged(assets, 4) if needs_assets else empty()

    factor_values: dict[str, np.ndarray] = {}
    if "return_on_equity_ttm" in compute_factor_keys:
        factor_values["return_on_equity_ttm"] = safe_ratio(ttm_parent_profit, average_equity, scale=100.0)
    if "sales_gross_margin_ttm" in compute_factor_keys:
        factor_values["sales_gross_margin_ttm"] = safe_ratio(ttm_gross_profit, ttm_revenue, scale=100.0)
    if "operating_cashflow_to_revenue_ttm" in compute_factor_keys:
        factor_values["operating_cashflow_to_revenue_ttm"] = safe_ratio(ttm_cfo, ttm_revenue, scale=100.0)
    if "debt_to_asset_ratio" in compute_factor_keys:
        factor_values["debt_to_asset_ratio"] = safe_ratio(liabilities, assets, scale=100.0)
    if "return_on_assets_ttm" in compute_factor_keys:
        factor_values["return_on_assets_ttm"] = safe_ratio(ttm_consolidated_profit, average_assets, scale=100.0)
    if "gross_profit_to_assets_ttm" in compute_factor_keys:
        factor_values["gross_profit_to_assets_ttm"] = safe_ratio(ttm_gross_profit, average_assets, scale=100.0)
    if "operating_cashflow_to_net_profit_ttm" in compute_factor_keys:
        factor_values["operating_cashflow_to_net_profit_ttm"] = safe_ratio(ttm_cfo, ttm_consolidated_profit)
    if "accruals_to_assets_ttm" in compute_factor_keys:
        factor_values["accruals_to_assets_ttm"] = safe_ratio(ttm_consolidated_profit - ttm_cfo, average_assets, scale=100.0)
    if "asset_turnover_ttm" in compute_factor_keys:
        factor_values["asset_turnover_ttm"] = safe_ratio(ttm_revenue, average_assets)
    if "operating_cashflow_yield_ttm" in compute_factor_keys:
        factor_values["operating_cashflow_yield_ttm"] = ttm_cfo
    if "free_cashflow_yield_ttm" in compute_factor_keys:
        factor_values["free_cashflow_yield_ttm"] = ttm_cfo - ttm_capex
    if "net_cash_to_market_value" in compute_factor_keys:
        debt_components = np.vstack(
            [shortterm_loan, long_term_loans, bonds_payable]
        )
        debt_total = np.nansum(debt_components, axis=0)
        debt_present = np.isfinite(debt_components).any(axis=0)
        net_cash = cash_equivalents - debt_total
        net_cash[~(np.isfinite(cash_equivalents) & debt_present)] = np.nan
        factor_values["net_cash_to_market_value"] = net_cash
    if "return_on_equity_std_12q" in dirty_factor_keys:
        factor_values["return_on_equity_std_12q"] = rolling_stat(factor_values["return_on_equity_ttm"], 12, "std")
    if "sales_gross_margin_std_12q" in dirty_factor_keys:
        factor_values["sales_gross_margin_std_12q"] = rolling_stat(factor_values["sales_gross_margin_ttm"], 12, "std")
    disclosed_by_table = (
        prepared_context["present"]
        if prepared_context is not None
        else {
            table: np.asarray([date in states[table] for date in report_dates], dtype=bool)
            for table in states
        }
    )
    for factor_key in dirty_factor_keys:
        required_tables = tuple(FACTOR_SOURCE_COLUMNS[factor_key])
        disclosed = np.logical_and.reduce(
            [disclosed_by_table[table] for table in required_tables]
        )
        disclosed_positions = np.flatnonzero(disclosed)
        if disclosed_positions.size:
            result[factor_key] = float(
                factor_values[factor_key][disclosed_positions[-1]]
            )
    return result


def _values_equal(left: float, right: float) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True
    if pd.isna(left) or pd.isna(right):
        return False
    return bool(np.isclose(float(left), float(right), rtol=1e-12, atol=1e-12))


def _point_in_time_quarter_factor_events(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    cashflow: pd.DataFrame,
    pershare: pd.DataFrame,
    factor_keys: set[str] | None = None,
    *,
    incremental: bool = True,
) -> dict[str, pd.DataFrame]:
    updates_by_code: dict[str, list[tuple[pd.Timestamp, str, pd.Timestamp, dict[str, Any]]]] = {}
    for table_name, frame in (
        ("Income", income),
        ("Balance", balance),
        ("CashFlow", cashflow),
        ("PershareIndex", pershare),
    ):
        for row in frame.to_dict("records"):
            code = _normalize_code(row.get("htsc_code"))
            report_date = pd.Timestamp(row["report_date"])
            announce_date = pd.Timestamp(row["announce_date"])
            updates_by_code.setdefault(code, []).append(
                (announce_date, table_name, report_date, row)
            )

    available_factor_keys = {
        key
        for key in FACTOR_NAME_MAP.values()
        if key not in DAILY_VALUATION_FACTOR_KEYS
    }
    selected_factor_keys = sorted(
        available_factor_keys
        if factor_keys is None
        else available_factor_keys & set(factor_keys)
    )
    rows_by_factor: dict[str, list[dict[str, Any]]] = {
        key: [] for key in selected_factor_keys
    }
    for code, updates in updates_by_code.items():
        states: dict[str, dict[pd.Timestamp, dict[str, Any]]] = {
            "Income": {},
            "Balance": {},
            "CashFlow": {},
            "PershareIndex": {},
        }
        previous = {key: np.nan for key in selected_factor_keys}
        updates.sort(key=lambda item: (item[0], item[1], item[2]))
        prepared_context = None
        if incremental:
            report_dates = sorted({item[2] for item in updates})
            report_positions = {date: position for position, date in enumerate(report_dates)}
            source_columns = _source_columns_for_factor_keys(set(selected_factor_keys))
            prepared_context = {
                "report_dates": report_dates,
                "arrays": {
                    (table, column): np.full(len(report_dates), np.nan, dtype=float)
                    for table, columns in source_columns.items()
                    for column in columns
                },
                "present": {
                    table: np.zeros(len(report_dates), dtype=bool)
                    for table in ("Income", "Balance", "CashFlow", "PershareIndex")
                },
                "report_positions": report_positions,
            }
        cursor = 0
        while cursor < len(updates):
            event_date = updates[cursor][0]
            changed_tables: set[str] = set()
            while cursor < len(updates) and updates[cursor][0] == event_date:
                _, table_name, report_date, row = updates[cursor]
                states[table_name][report_date] = row
                changed_tables.add(table_name)
                if prepared_context is not None:
                    position = prepared_context["report_positions"][report_date]
                    prepared_context["present"][table_name][position] = True
                    for column in source_columns.get(table_name, ()):
                        raw_value = row.get(column)
                        try:
                            value = float(raw_value)
                        except (TypeError, ValueError):
                            value = np.nan
                        prepared_context["arrays"][(table_name, column)][position] = (
                            value if np.isfinite(value) else np.nan
                        )
                cursor += 1
            current = _snapshot_factor_values(
                states,
                factor_keys=selected_factor_keys,
                changed_tables=changed_tables if incremental else None,
                previous_values=previous if incremental else None,
                prepared_context=prepared_context,
            )
            for factor_key in selected_factor_keys:
                value = current[factor_key]
                if _values_equal(previous[factor_key], value):
                    continue
                rows_by_factor[factor_key].append(
                    {
                        "htsc_code": code,
                        "effective_date": event_date,
                        "value": value,
                    }
                )
                previous[factor_key] = value

    result: dict[str, pd.DataFrame] = {}
    for factor_key, rows in rows_by_factor.items():
        result[factor_key] = pd.DataFrame(
            rows, columns=["htsc_code", "effective_date", "value"]
        )
    return result


def _events_to_daily(
    events: pd.DataFrame,
    index: pd.DatetimeIndex,
    stock_codes: list[str],
) -> pd.DataFrame:
    normalized_index = pd.DatetimeIndex(index).as_unit("ns")
    if events.empty:
        return pd.DataFrame(index=normalized_index, columns=stock_codes, dtype=float)
    normalized_events = events.copy()
    normalized_events["htsc_code"] = normalized_events["htsc_code"].map(
        _normalize_code
    )
    normalized_events["effective_date"] = pd.DatetimeIndex(
        pd.to_datetime(normalized_events["effective_date"])
    ).as_unit("ns")
    normalized_events["value"] = pd.to_numeric(
        normalized_events["value"], errors="coerce"
    )
    normalized_events = normalized_events.dropna(subset=["effective_date"])
    normalized_events = normalized_events[
        normalized_events["htsc_code"].isin(stock_codes)
    ].drop_duplicates(["effective_date", "htsc_code"], keep="last")
    if normalized_events.empty:
        return pd.DataFrame(index=normalized_index, columns=stock_codes, dtype=float)

    normalized_events = normalized_events.reset_index(drop=True)
    normalized_events["event_id"] = np.arange(
        1, len(normalized_events) + 1, dtype=np.int64
    )
    event_ids = normalized_events.pivot(
        index="effective_date",
        columns="htsc_code",
        values="event_id",
    ).reindex(columns=stock_codes)
    timeline = event_ids.index.union(normalized_index).sort_values()
    aligned_ids = (
        event_ids.reindex(timeline)
        .ffill()
        .reindex(index=normalized_index, columns=stock_codes)
        .fillna(0)
        .to_numpy(dtype=np.int64)
    )
    value_lookup = np.full(len(normalized_events) + 1, np.nan, dtype=float)
    value_lookup[normalized_events["event_id"].to_numpy(dtype=np.int64)] = (
        normalized_events["value"].to_numpy(dtype=float)
    )
    return pd.DataFrame(
        value_lookup[aligned_ids],
        index=normalized_index,
        columns=stock_codes,
        dtype=float,
    )


def build_stock_fundamental_raw_factor_bundle(
    C: pd.DataFrame,
    *,
    stock_codes: set[str] | list[str] | tuple[str, ...],
    source_globs: dict[str, str] | None = None,
    target_factor_keys: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    index = pd.DatetimeIndex(pd.to_datetime(C.index)).floor("D")
    market_codes = {_normalize_code(code) for code in C.columns}
    target_codes = sorted(
        market_codes & {_normalize_code(code) for code in stock_codes if _normalize_code(code)}
    )
    requested_keys = (
        set(FACTOR_NAME_MAP.values())
        if target_factor_keys is None
        else {
            str(key).strip()
            for key in target_factor_keys
            if str(key).strip() in FACTOR_NAME_MAP.values()
        }
    )
    selected_factor_name_map = {
        name: key for name, key in FACTOR_NAME_MAP.items() if key in requested_keys
    }
    factor_dfs = {
        key: pd.DataFrame(index=index, columns=target_codes, dtype=float)
        for key in selected_factor_name_map.values()
    }
    if index.empty or not target_codes or not requested_keys:
        return {
            "bundle_id": BUNDLE_ID,
            "factor_dfs": factor_dfs,
            "factor_name_map": selected_factor_name_map,
        }

    sources = dict(DEFAULT_SOURCE_GLOBS)
    if source_globs:
        sources.update(source_globs)
    quarterly_factor_keys = requested_keys - DAILY_VALUATION_FACTOR_KEYS
    valuation_keys = requested_keys & (
        DAILY_VALUATION_FACTOR_KEYS
        | {"operating_cashflow_yield_ttm", "free_cashflow_yield_ttm", "net_cash_to_market_value"}
    )
    valuation_columns: list[str] = []
    if valuation_keys & {"price_to_book_ratio", "book_to_market_ratio"}:
        valuation_columns.append("pb")
    if "earnings_yield_ttm" in valuation_keys:
        valuation_columns.append("pe_ttm")
    if "sales_yield_ttm" in valuation_keys:
        valuation_columns.append("revenue_ttm")
    if valuation_keys & {
        "sales_yield_ttm",
        "operating_cashflow_yield_ttm",
        "free_cashflow_yield_ttm",
        "net_cash_to_market_value",
    }:
        valuation_columns.append("total_market_val")
    valuation_data = (
        _read_valuation_daily(
            source_glob=sources["valuation"],
            stock_codes=target_codes,
            index=index,
            columns=tuple(dict.fromkeys(valuation_columns)),
        )
        if valuation_columns
        else {}
    )
    market_value = (
        valuation_data["total_market_val"]
        .where(lambda frame: np.isfinite(frame) & (frame > 0))
        if "total_market_val" in valuation_data
        else None
    )
    if "price_to_book_ratio" in requested_keys:
        factor_dfs["price_to_book_ratio"] = valuation_data["pb"].where(
            lambda frame: np.isfinite(frame) & (frame > 0)
        )
    if "earnings_yield_ttm" in requested_keys:
        pe = valuation_data["pe_ttm"]
        factor_dfs["earnings_yield_ttm"] = pe.where(
            lambda frame: np.isfinite(frame) & (frame > 0)
        ).rdiv(1.0)
    if "book_to_market_ratio" in requested_keys:
        pb = valuation_data["pb"]
        factor_dfs["book_to_market_ratio"] = pb.where(
            lambda frame: np.isfinite(frame) & (frame > 0)
        ).rdiv(1.0)
    if "sales_yield_ttm" in requested_keys:
        revenue_ttm = valuation_data["revenue_ttm"]
        factor_dfs["sales_yield_ttm"] = revenue_ttm.where(
            lambda frame: np.isfinite(frame) & (frame > 0)
        ).div(market_value)
    if not quarterly_factor_keys:
        return {
            "bundle_id": BUNDLE_ID,
            "factor_dfs": factor_dfs,
            "factor_name_map": selected_factor_name_map,
        }
    history_start = index.min() - pd.Timedelta(days=SOURCE_HISTORY_CALENDAR_DAYS)
    history_end = index.max()
    source_columns = _source_columns_for_factor_keys(quarterly_factor_keys)
    empty_quarter = pd.DataFrame(
        columns=["htsc_code", "report_date", "announce_date"]
    )
    quarterly_frames: dict[str, pd.DataFrame] = {}
    for table in ("Income", "Balance", "CashFlow", "PershareIndex"):
        columns = source_columns.get(table)
        quarterly_frames[table] = (
            _read_quarter_table(
                source_glob=sources[table],
                columns=columns,
                stock_codes=target_codes,
                start_date=history_start,
                end_date=history_end,
            )
            if columns
            else empty_quarter.copy()
        )
    income = quarterly_frames["Income"]
    balance = quarterly_frames["Balance"]
    cashflow = quarterly_frames["CashFlow"]
    pershare = quarterly_frames["PershareIndex"]
    event_frames = _point_in_time_quarter_factor_events(
        income,
        balance,
        cashflow,
        pershare,
        factor_keys=quarterly_factor_keys,
    )
    for key, events in event_frames.items():
        numerator = _events_to_daily(events, index, target_codes)
        if key in {
            "operating_cashflow_yield_ttm",
            "free_cashflow_yield_ttm",
            "net_cash_to_market_value",
        }:
            factor_dfs[key] = numerator.div(market_value)
        else:
            factor_dfs[key] = numerator
    return {
        "bundle_id": BUNDLE_ID,
        "factor_dfs": factor_dfs,
        "factor_name_map": selected_factor_name_map,
    }
