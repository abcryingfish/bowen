"""股票成长原始因子：公告日点时的 TTM 成长、加速度和研发费用指标。"""
from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


BUNDLE_ID = "stock_growth_raw"
SOURCE_HISTORY_CALENDAR_DAYS = 1700
FINANCIAL_ROOT = r"D:\database\qmt_company_data"
DEFAULT_SOURCE_GLOBS = {
    "Income": rf"{FINANCIAL_ROOT}\table=Income\year=*\month=*\merged.parquet",
    "Balance": rf"{FINANCIAL_ROOT}\table=Balance\year=*\month=*\merged.parquet",
    "CashFlow": rf"{FINANCIAL_ROOT}\table=CashFlow\year=*\month=*\merged.parquet",
    "PershareIndex": rf"{FINANCIAL_ROOT}\table=PershareIndex\year=*\month=*\merged.parquet",
}
FACTOR_NAME_MAP = {
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
        raise ValueError(f"成长因子源没有可读取分区: {source_glob}")
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
        available = {
            str(row[0])
            for row in con.execute(
                "DESCRIBE SELECT * FROM read_parquet(?, union_by_name=true)", [source]
            ).fetchall()
        }
        missing = [column for column in ["htsc_code", "report_date", "announce_date", *columns] if column not in available]
        if missing:
            raise ValueError(f"成长因子源缺少字段: {', '.join(missing)}；source={source}")
        frame = con.execute(
            sql,
            [source, start_date.date(), end_date.date(), *stock_codes],
        ).df()
    frame["report_date"] = pd.to_datetime(frame["report_date"], errors="coerce").dt.floor("D")
    frame["announce_date"] = pd.to_datetime(frame["announce_date"], errors="coerce").dt.floor("D")
    frame = frame.dropna(subset=["report_date", "announce_date"])
    frame["htsc_code"] = frame["htsc_code"].map(_normalize_code)
    frame = frame.drop_duplicates(["htsc_code", "report_date", "announce_date"], keep="last")
    frame = frame.sort_values(["htsc_code", "report_date", "announce_date"]).reset_index(drop=True)
    groups = frame.groupby(["htsc_code", "report_date"], sort=False)
    previous = groups[columns].shift()
    unchanged = (frame[columns].eq(previous) | (frame[columns].isna() & previous.isna())).all(axis=1)
    return frame.loc[groups.cumcount().eq(0) | ~unchanged].reset_index(drop=True)


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


def _snapshot_factor_values(states: dict[str, dict[pd.Timestamp, dict[str, Any]]]) -> dict[str, float]:
    report_dates = sorted(set().union(*(set(table_state) for table_state in states.values())))
    result = {key: np.nan for key in FACTOR_NAME_MAP.values()}
    if not report_dates:
        return result

    def values(table: str, column: str) -> np.ndarray:
        output = []
        for report_date in report_dates:
            raw_value = states[table].get(report_date, {}).get(column)
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

    def rolling_sum(values_array: np.ndarray, window: int = 4) -> np.ndarray:
        output = np.full(len(values_array), np.nan, dtype=float)
        if len(values_array) < window:
            return output
        windows = np.lib.stride_tricks.sliding_window_view(values_array, window)
        ends = np.arange(window - 1, len(values_array))
        valid = np.isfinite(windows).all(axis=1) & (ordinal[ends] - ordinal[ends - window + 1] == window - 1)
        output[ends[valid]] = np.sum(windows[valid], axis=1)
        return output

    def average_lagged(values_array: np.ndarray, lag: int = 4) -> np.ndarray:
        output = np.full(len(values_array), np.nan, dtype=float)
        if len(values_array) <= lag:
            return output
        positions = np.arange(lag, len(values_array))
        valid = np.isfinite(values_array[positions]) & np.isfinite(values_array[positions - lag])
        valid &= ordinal[positions] - ordinal[positions - lag] == lag
        average = (values_array[positions] + values_array[positions - lag]) / 2.0
        valid &= average > 0
        output[positions[valid]] = average[valid]
        return output

    def safe_ratio(numerator: np.ndarray, denominator: np.ndarray, scale: float = 1.0) -> np.ndarray:
        output = np.full(len(numerator), np.nan, dtype=float)
        valid = np.isfinite(numerator) & np.isfinite(denominator) & (denominator > 0)
        output[valid] = numerator[valid] / denominator[valid] * scale
        return output

    def growth_rate(values_array: np.ndarray, lag: int = 4) -> np.ndarray:
        output = np.full(len(values_array), np.nan, dtype=float)
        if len(values_array) <= lag:
            return output
        positions = np.arange(lag, len(values_array))
        prior = values_array[positions - lag]
        valid = np.isfinite(values_array[positions]) & np.isfinite(prior) & (prior > 0)
        valid &= ordinal[positions] - ordinal[positions - lag] == lag
        output[positions[valid]] = (values_array[positions[valid]] / prior[valid] - 1.0) * 100.0
        return output

    def point_change(values_array: np.ndarray, lag: int = 4) -> np.ndarray:
        output = np.full(len(values_array), np.nan, dtype=float)
        if len(values_array) <= lag:
            return output
        positions = np.arange(lag, len(values_array))
        valid = np.isfinite(values_array[positions]) & np.isfinite(values_array[positions - lag])
        valid &= ordinal[positions] - ordinal[positions - lag] == lag
        output[positions[valid]] = values_array[positions[valid]] - values_array[positions[valid] - lag]
        return output

    def acceleration(values_array: np.ndarray) -> np.ndarray:
        output = np.full(len(values_array), np.nan, dtype=float)
        if len(values_array) <= 1:
            return output
        positions = np.arange(1, len(values_array))
        valid = np.isfinite(values_array[positions]) & np.isfinite(values_array[positions - 1])
        valid &= ordinal[positions] - ordinal[positions - 1] == 1
        output[positions[valid]] = values_array[positions[valid]] - values_array[positions[valid] - 1]
        return output

    revenue_cum = values("Income", "revenue")
    operating_profit_cum = values("Income", "oper_profit")
    adjusted_profit_cum = values("Income", "net_profit_incl_min_int_inc_after")
    parent_profit_cum = values("Income", "net_profit_excl_min_int_inc")
    eps_cum = values("Income", "s_fa_eps_basic")
    research_expense_cum = values("Income", "research_expenses")
    cfo_cum = values("CashFlow", "net_cash_flows_oper_act")
    margin = values("PershareIndex", "sales_gross_profit")
    margin_fallback = values("PershareIndex", "gross_profit")
    margin = np.where(np.isfinite(margin), margin, margin_fallback)
    gross_profit_cum = revenue_cum * margin / 100.0
    revenue_q = _standalone_values(revenue_cum, quarters, years)
    operating_profit_q = _standalone_values(operating_profit_cum, quarters, years)
    adjusted_profit_q = _standalone_values(adjusted_profit_cum, quarters, years)
    parent_profit_q = _standalone_values(parent_profit_cum, quarters, years)
    eps_q = _standalone_values(eps_cum, quarters, years)
    research_expense_q = _standalone_values(research_expense_cum, quarters, years)
    cfo_q = _standalone_values(cfo_cum, quarters, years)
    gross_profit_q = _standalone_values(gross_profit_cum, quarters, years)
    ttm_revenue = rolling_sum(revenue_q)
    ttm_operating_profit = rolling_sum(operating_profit_q)
    ttm_adjusted_profit = rolling_sum(adjusted_profit_q)
    ttm_parent_profit = rolling_sum(parent_profit_q)
    ttm_eps = rolling_sum(eps_q)
    ttm_research_expense = rolling_sum(research_expense_q)
    ttm_cfo = rolling_sum(cfo_q)
    ttm_gross_profit = rolling_sum(gross_profit_q)
    roe_ttm = safe_ratio(ttm_parent_profit, average_lagged(values("Balance", "tot_shrhldr_eqy_excl_min_int")), 100.0)
    gross_margin_ttm = safe_ratio(ttm_gross_profit, ttm_revenue, 100.0)
    revenue_growth = growth_rate(ttm_revenue)
    adjusted_growth = growth_rate(ttm_adjusted_profit)
    factor_values = {
        "revenue_growth_yoy_ttm": revenue_growth,
        "operating_profit_growth_yoy_ttm": growth_rate(ttm_operating_profit),
        "adjusted_net_profit_growth_yoy_ttm": adjusted_growth,
        "basic_eps_growth_yoy_ttm": growth_rate(ttm_eps),
        "operating_cashflow_growth_yoy_ttm": growth_rate(ttm_cfo),
        "revenue_growth_acceleration_ttm": acceleration(revenue_growth),
        "adjusted_net_profit_growth_acceleration_ttm": acceleration(adjusted_growth),
        "return_on_equity_change_yoy_ttm": point_change(roe_ttm),
        "sales_gross_margin_change_yoy_ttm": point_change(gross_margin_ttm),
        "research_expense_growth_yoy_ttm": growth_rate(ttm_research_expense),
        "research_expense_to_revenue_ttm": safe_ratio(ttm_research_expense, ttm_revenue, 100.0),
    }
    revenue_cagr = np.full(len(report_dates), np.nan, dtype=float)
    if len(report_dates) > 12:
        positions = np.arange(12, len(report_dates))
        old = ttm_revenue[positions - 12]
        valid = np.isfinite(ttm_revenue[positions]) & (ttm_revenue[positions] > 0)
        valid &= np.isfinite(old) & (old > 0) & (ordinal[positions] - ordinal[positions - 12] == 12)
        revenue_cagr[positions[valid]] = ((ttm_revenue[positions[valid]] / old[valid]) ** (1 / 3) - 1) * 100.0
    factor_values["revenue_cagr_3y_ttm"] = revenue_cagr

    required_tables = {
        "revenue_growth_yoy_ttm": ("Income",),
        "revenue_cagr_3y_ttm": ("Income",),
        "operating_profit_growth_yoy_ttm": ("Income",),
        "adjusted_net_profit_growth_yoy_ttm": ("Income",),
        "basic_eps_growth_yoy_ttm": ("Income",),
        "operating_cashflow_growth_yoy_ttm": ("CashFlow",),
        "revenue_growth_acceleration_ttm": ("Income",),
        "adjusted_net_profit_growth_acceleration_ttm": ("Income",),
        "return_on_equity_change_yoy_ttm": ("Income", "Balance"),
        "sales_gross_margin_change_yoy_ttm": ("Income", "PershareIndex"),
        "research_expense_growth_yoy_ttm": ("Income",),
        "research_expense_to_revenue_ttm": ("Income",),
    }
    for factor_key, tables in required_tables.items():
        disclosed = np.logical_and.reduce([np.asarray([date in states[table] for date in report_dates]) for table in tables])
        positions = np.flatnonzero(disclosed)
        if positions.size:
            result[factor_key] = float(factor_values[factor_key][positions[-1]])
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
) -> dict[str, pd.DataFrame]:
    updates_by_code: dict[str, list[tuple[pd.Timestamp, str, pd.Timestamp, dict[str, Any]]]] = {}
    for table_name, frame in (("Income", income), ("Balance", balance), ("CashFlow", cashflow), ("PershareIndex", pershare)):
        for row in frame.to_dict("records"):
            code = _normalize_code(row.get("htsc_code"))
            updates_by_code.setdefault(code, []).append((pd.Timestamp(row["announce_date"]), table_name, pd.Timestamp(row["report_date"]), row))
    available = set(FACTOR_NAME_MAP.values())
    selected = sorted(available if factor_keys is None else available & set(factor_keys))
    rows_by_factor: dict[str, list[dict[str, Any]]] = {key: [] for key in selected}
    for code, updates in updates_by_code.items():
        states: dict[str, dict[pd.Timestamp, dict[str, Any]]] = {"Income": {}, "Balance": {}, "CashFlow": {}, "PershareIndex": {}}
        previous = {key: np.nan for key in selected}
        updates.sort(key=lambda item: (item[0], item[1], item[2]))
        cursor = 0
        while cursor < len(updates):
            event_date = updates[cursor][0]
            while cursor < len(updates) and updates[cursor][0] == event_date:
                _, table_name, report_date, row = updates[cursor]
                states[table_name][report_date] = row
                cursor += 1
            current = _snapshot_factor_values(states)
            for factor_key in selected:
                value = current[factor_key]
                if _values_equal(previous[factor_key], value):
                    continue
                rows_by_factor[factor_key].append({"htsc_code": code, "effective_date": event_date, "value": value})
                previous[factor_key] = value
    return {key: pd.DataFrame(rows, columns=["htsc_code", "effective_date", "value"]) for key, rows in rows_by_factor.items()}


def _events_to_daily(events: pd.DataFrame, index: pd.DatetimeIndex, stock_codes: list[str]) -> pd.DataFrame:
    normalized_index = pd.DatetimeIndex(index).as_unit("ns")
    if events.empty:
        return pd.DataFrame(index=normalized_index, columns=stock_codes, dtype=float)
    normalized = events.copy()
    normalized["htsc_code"] = normalized["htsc_code"].map(_normalize_code)
    normalized["effective_date"] = pd.DatetimeIndex(pd.to_datetime(normalized["effective_date"])).as_unit("ns")
    normalized["value"] = pd.to_numeric(normalized["value"], errors="coerce")
    normalized = normalized.dropna(subset=["effective_date"])
    normalized = normalized[normalized["htsc_code"].isin(stock_codes)].drop_duplicates(["effective_date", "htsc_code"], keep="last")
    if normalized.empty:
        return pd.DataFrame(index=normalized_index, columns=stock_codes, dtype=float)
    normalized = normalized.reset_index(drop=True)
    normalized["event_id"] = np.arange(1, len(normalized) + 1, dtype=np.int64)
    event_ids = normalized.pivot(index="effective_date", columns="htsc_code", values="event_id").reindex(columns=stock_codes)
    timeline = event_ids.index.union(normalized_index).sort_values()
    aligned = event_ids.reindex(timeline).ffill().reindex(index=normalized_index, columns=stock_codes).fillna(0).to_numpy(dtype=np.int64)
    lookup = np.full(len(normalized) + 1, np.nan, dtype=float)
    lookup[normalized["event_id"].to_numpy(dtype=np.int64)] = normalized["value"].to_numpy(dtype=float)
    return pd.DataFrame(lookup[aligned], index=normalized_index, columns=stock_codes, dtype=float)


def build_stock_growth_raw_factor_bundle(
    C: pd.DataFrame,
    *,
    stock_codes: set[str] | list[str] | tuple[str, ...],
    source_globs: dict[str, str] | None = None,
    target_factor_keys: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    index = pd.DatetimeIndex(pd.to_datetime(C.index)).floor("D")
    market_codes = {_normalize_code(code) for code in C.columns}
    target_codes = sorted(market_codes & {_normalize_code(code) for code in stock_codes if _normalize_code(code)})
    requested = set(FACTOR_NAME_MAP.values()) if target_factor_keys is None else {str(key).strip() for key in target_factor_keys if str(key).strip() in FACTOR_NAME_MAP.values()}
    selected_map = {name: key for name, key in FACTOR_NAME_MAP.items() if key in requested}
    factor_dfs = {key: pd.DataFrame(index=index, columns=target_codes, dtype=float) for key in selected_map.values()}
    if index.empty or not target_codes or not requested:
        return {"bundle_id": BUNDLE_ID, "factor_dfs": factor_dfs, "factor_name_map": selected_map}
    sources = dict(DEFAULT_SOURCE_GLOBS)
    if source_globs:
        sources.update(source_globs)
    history_start = index.min() - pd.Timedelta(days=SOURCE_HISTORY_CALENDAR_DAYS)
    history_end = index.max()
    income = _read_quarter_table(source_glob=sources["Income"], columns=["revenue", "oper_profit", "net_profit_incl_min_int_inc_after", "net_profit_excl_min_int_inc", "s_fa_eps_basic", "research_expenses"], stock_codes=target_codes, start_date=history_start, end_date=history_end)
    balance = _read_quarter_table(source_glob=sources["Balance"], columns=["tot_shrhldr_eqy_excl_min_int"], stock_codes=target_codes, start_date=history_start, end_date=history_end)
    cashflow = _read_quarter_table(source_glob=sources["CashFlow"], columns=["net_cash_flows_oper_act"], stock_codes=target_codes, start_date=history_start, end_date=history_end)
    pershare = _read_quarter_table(source_glob=sources["PershareIndex"], columns=["sales_gross_profit", "gross_profit"], stock_codes=target_codes, start_date=history_start, end_date=history_end)
    events = _point_in_time_quarter_factor_events(income, balance, cashflow, pershare, requested)
    for key, frame in events.items():
        factor_dfs[key] = _events_to_daily(frame, index, target_codes)
    return {"bundle_id": BUNDLE_ID, "factor_dfs": factor_dfs, "factor_name_map": selected_map}
