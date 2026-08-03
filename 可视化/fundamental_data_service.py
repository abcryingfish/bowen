#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""基本面 parquet 查询服务 — 读取 D:\\database\\qmt_company_data。"""

from __future__ import annotations

import math
import os
import re
import threading
import time
from datetime import date, datetime
from typing import Any, Optional

import duckdb

from market_data_service import (
    MarketDataNotFoundError,
    MarketDataValidationError,
    _list_recent_merged_candidates,
)

FINANCIAL_ROOT = r"D:\database\qmt_company_data"
MERGED_GLOB = "**/merged.parquet"
CODE_PATTERN = re.compile(r"^\d{6}\.(SH|SZ|BJ)$", re.IGNORECASE)

STATEMENT_SUBDIRS = {
    "income": "table=Income",
    "balance": "table=Balance",
    "cashflow": "table=CashFlow",
}
INDICATOR_SUBDIR = "table=PershareIndex"
VALUATION_SUBDIR = "table=factor_fundamental_valuation"
EQUITY_SUBDIR = r"D:\database\qmt_turnover_data"

FieldSpec = dict[str, str]  # key -> label; format stored separately

INCOME_FIELDS: list[tuple[str, str, str]] = [
    ("revenue", "营业收入", "money"),
    ("total_expense", "营业总成本", "money"),
    ("operating_revenue", "营业成本", "money"),
    ("sale_expense", "销售费用", "money"),
    ("less_gerl_admin_exp", "管理费用", "money"),
    ("financial_expense", "财务费用", "money"),
    ("oper_profit", "营业利润", "money"),
    ("tot_profit", "利润总额", "money"),
    ("inc_tax", "所得税费用", "money"),
    ("net_profit_incl_min_int_inc", "净利润", "money"),
    ("net_profit_excl_min_int_inc", "归母净利润", "money"),
    ("net_profit_incl_min_int_inc_after", "扣非后净利润", "money"),
    ("s_fa_eps_basic", "基本每股收益", "number"),
    ("s_fa_eps_diluted", "稀释每股收益", "number"),
]

BALANCE_FIELDS: list[tuple[str, str, str]] = [
    ("cash_equivalents", "货币资金", "money"),
    ("account_receivable", "应收账款", "money"),
    ("inventories", "存货", "money"),
    ("total_current_assets", "流动资产合计", "money"),
    ("fix_assets", "固定资产净额", "money"),
    ("total_non_current_assets", "非流动资产合计", "money"),
    ("tot_assets", "资产总计", "money"),
    ("shortterm_loan", "短期借款", "money"),
    ("accounts_payable", "应付账款", "money"),
    ("total_current_liability", "流动负债合计", "money"),
    ("long_term_loans", "长期借款", "money"),
    ("non_current_liabilities", "非流动负债合计", "money"),
    ("tot_liab", "负债合计", "money"),
    ("cap_stk", "股本", "money"),
    ("cap_rsrv", "资本公积", "money"),
    ("undistributed_profit", "未分配利润", "money"),
    ("total_equity", "股东权益合计", "money"),
    ("tot_liab_shrhldr_eqy", "负债及股东权益总计", "money"),
]

CASHFLOW_FIELDS: list[tuple[str, str, str]] = [
    ("stot_cash_inflows_oper_act", "经营活动现金流入小计", "money"),
    ("stot_cash_outflows_oper_act", "经营活动现金流出小计", "money"),
    ("net_cash_flows_oper_act", "经营活动现金流量净额", "money"),
    ("stot_cash_inflows_inv_act", "投资活动现金流入小计", "money"),
    ("stot_cash_outflows_inv_act", "投资活动现金流出小计", "money"),
    ("net_cash_flows_inv_act", "投资活动现金流量净额", "money"),
    ("stot_cash_inflows_fnc_act", "筹资活动现金流入小计", "money"),
    ("stot_cash_outflows_fnc_act", "筹资活动现金流出小计", "money"),
    ("net_cash_flows_fnc_act", "筹资活动现金流量净额", "money"),
    ("eff_fx_flu_cash", "汇率变动影响", "money"),
    ("net_incr_cash_cash_equ", "现金及等价物净增加额", "money"),
    ("cash_cash_equ_end_period", "期末现金及等价物余额", "money"),
]

INDICATOR_TABLE_COLUMNS: list[tuple[str, str, str]] = [
    ("inc_revenue", "营业收入同比", "percent"),
    ("inc_net_profit", "净利润同比", "percent"),
    ("sales_gross_profit", "毛利率", "percent"),
    ("du_profit_rate", "净利率", "percent"),
    ("du_profit", "营业利润率", "percent"),
    ("equity_roe", "ROE", "percent"),
    ("net_roe", "净资产收益率", "percent"),
    ("s_fa_eps_basic", "基本 EPS", "number"),
    ("inc_revenue_rate", "营收同比", "percent"),
    ("inc_net_profit_rate", "净利润同比", "percent"),
    ("gear_ratio", "资产负债率", "ratio"),
    ("inventory_turnover", "存货周转率", "ratio"),
]

CHART_METRICS: list[tuple[str, str, str]] = [
    ("du_profit_rate", "净利率", "percent"),
    ("sales_gross_profit", "毛利率", "percent"),
    ("equity_roe", "ROE", "percent"),
    ("inc_revenue_rate", "营收同比", "percent"),
    ("s_fa_eps_basic", "基本 EPS", "number"),
    ("inc_net_profit_rate", "净利润同比", "percent"),
]

OVERVIEW_KPIS: list[tuple[str, str, str, Optional[str]]] = [
    ("revenue", "营业收入", "money", "inc_revenue_rate"),
    ("net_profit_excl_min_int_inc", "归母净利润", "money", "inc_net_profit_rate"),
    ("equity_roe", "ROE", "percent", None),
    ("du_profit_rate", "净利率", "percent", None),
    ("sales_gross_profit", "毛利率", "percent", None),
    ("s_fa_eps_basic", "基本 EPS", "number", None),
    ("gear_ratio", "资产负债率", "ratio", None),
]

MAX_QUARTER_ROWS = 12
RECENT_QUARTER_PARTITIONS = 16
RECENT_DAILY_PARTITIONS = 2
PANEL_CACHE_TTL_SECONDS = 30.0

_VIEW_CONN: Optional[duckdb.DuckDBPyConnection] = None
_VIEW_STAMP = -1.0
_VIEW_LOCK = threading.Lock()
_QUERY_LOCK = threading.Lock()
_PARTITION_PATH_CACHE: dict[tuple[str, int], tuple[float, list[str]]] = {}
_PARTITION_CACHE_LOCK = threading.Lock()
_PANEL_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_PANEL_CACHE_LOCK = threading.Lock()

VIEW_SPECS: list[tuple[str, str, int]] = [
    ("income", STATEMENT_SUBDIRS["income"], RECENT_QUARTER_PARTITIONS),
    ("balance", STATEMENT_SUBDIRS["balance"], RECENT_QUARTER_PARTITIONS),
    ("cashflow", STATEMENT_SUBDIRS["cashflow"], RECENT_QUARTER_PARTITIONS),
    ("indicator", INDICATOR_SUBDIR, RECENT_QUARTER_PARTITIONS),
    ("valuation", VALUATION_SUBDIR, RECENT_DAILY_PARTITIONS),
    ("equity", EQUITY_SUBDIR, RECENT_DAILY_PARTITIONS),
]

# parquet 中主字段常为空，用 Insight 实际有值的列回填
INDICATOR_VALUE_FALLBACKS: dict[str, list[str]] = {
    "equity_roe": ["net_roe"],
    "oper_revenue_yoy": ["inc_revenue_rate", "inc_revenue"],
    "net_profit_yoy": ["inc_net_profit_rate", "inc_net_profit"],
    "gross_profit_margin": ["sales_gross_profit", "gross_profit"],
    "profit_margin": ["du_profit_rate", "du_profit"],
}


def _get_indicator_field(row: dict[str, Any], key: str) -> Any:
    value = row.get(key)
    if _is_finite_number(value):
        return value
    for alt_key in INDICATOR_VALUE_FALLBACKS.get(key, []):
        alt = row.get(alt_key)
        if _is_finite_number(alt):
            return alt
    return value


def _subdir_glob(subdir: str) -> str:
    path = f"{FINANCIAL_ROOT}/{subdir}/{MERGED_GLOB}".replace("\\", "/")
    return path


def _subdir_base(subdir: str) -> str:
    if re.match(r"^[A-Za-z]:[\\/]", subdir):
        return subdir.replace("\\", "/")
    return f"{FINANCIAL_ROOT}/{subdir}".replace("\\", "/")


def _unique_columns(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    columns: list[str] = []
    for group in groups:
        for key in group:
            if key in seen:
                continue
            seen.add(key)
            columns.append(key)
    return columns


def _statement_columns(field_specs: list[tuple[str, str, str]]) -> list[str]:
    return _unique_columns(
        ["report_date AS end_date", "period", "name"],
        [key for key, _, _ in field_specs],
    )


def _indicator_columns() -> list[str]:
    return _unique_columns(
        ["report_date AS end_date", "period", "name"],
        [key for key, _, _ in INDICATOR_TABLE_COLUMNS],
        [key for key, _, _ in CHART_METRICS],
        [alt for alts in INDICATOR_VALUE_FALLBACKS.values() for alt in alts],
    )


VALUATION_COLUMNS = [
    "htsc_code",
    "time",
    "pe_ttm AS pettm",
    "pb",
    "total_market_val",
]
EQUITY_COLUMNS = [
    "htsc_code",
    "time",
    "name",
    "close",
    "turnover_rate",
    "value",
    "volume",
    "day_change",
]


def _parquet_reader(paths: list[str]) -> tuple[str, list[str]]:
    if not paths:
        return "", []
    placeholders = ", ".join("?" for _ in paths)
    return f"read_parquet([{placeholders}], union_by_name=true)", list(paths)


def _quote_parquet_paths(paths: list[str]) -> str:
    return "[" + ", ".join(repr(path) for path in paths) + "]"


def _empty_view_sql(view_name: str) -> str:
    if view_name in {"income", "balance", "cashflow", "indicator"}:
        return (
            "SELECT CAST(NULL AS VARCHAR) AS htsc_code, CAST(NULL AS DATE) AS report_date, "
            "CAST(NULL AS VARCHAR) AS period, CAST(NULL AS VARCHAR) AS name WHERE false"
        )
    return "SELECT CAST(NULL AS VARCHAR) AS htsc_code, CAST(NULL AS TIMESTAMP) AS time WHERE false"


def _financial_data_stamp() -> float:
    stamps: list[float] = []
    for _, subdir, _ in VIEW_SPECS:
        try:
            stamps.append(os.path.getmtime(_subdir_base(subdir)))
        except OSError:
            continue
    return max(stamps) if stamps else 0.0


def _ensure_views() -> duckdb.DuckDBPyConnection:
    global _VIEW_CONN, _VIEW_STAMP
    stamp = _financial_data_stamp()
    with _VIEW_LOCK:
        if _VIEW_CONN is not None and _VIEW_STAMP == stamp:
            return _VIEW_CONN
        if _VIEW_CONN is None:
            _VIEW_CONN = duckdb.connect(database=":memory:")
        for view_name, subdir, recent_count in VIEW_SPECS:
            paths = _resolve_partition_paths(subdir, recent_count=recent_count)
            if paths:
                view_sql = f"SELECT * FROM read_parquet({_quote_parquet_paths(paths)}, hive_partitioning=true, union_by_name=true)"
            else:
                view_sql = _empty_view_sql(view_name)
            _VIEW_CONN.execute("CREATE OR REPLACE VIEW fin_" f"{view_name} AS {view_sql}")
        _VIEW_STAMP = stamp
        return _VIEW_CONN


def warmup_fundamental_views() -> None:
    """预建 DuckDB 视图并预热 parquet 页缓存，降低 API 首请求延迟。"""
    _ensure_views()
    try:
        _fetch_panel_dataset("688002.SH")
    except Exception:
        pass


def _resolve_partition_paths(subdir: str, *, recent_count: int) -> list[str]:
    base = _subdir_base(subdir)
    try:
        stamp = os.path.getmtime(base)
    except OSError:
        stamp = 0.0
    cache_key = (subdir, recent_count)
    with _PARTITION_CACHE_LOCK:
        cached = _PARTITION_PATH_CACHE.get(cache_key)
        if cached and cached[0] == stamp:
            return list(cached[1])

    recent_paths = _list_recent_merged_candidates(base, max_count=recent_count)
    paths = recent_paths if recent_paths else [_subdir_glob(subdir)]
    paths = [path for path in paths if "*" in path or os.path.exists(path)]
    with _PARTITION_CACHE_LOCK:
        _PARTITION_PATH_CACHE[cache_key] = (stamp, list(paths))
    return paths


def _validate_code(code: Optional[str]) -> str:
    normalized = str(code or "").strip().upper()
    if not normalized or not CODE_PATTERN.match(normalized):
        raise MarketDataValidationError("code 格式无效，示例：688002.SH")
    return normalized


def _is_finite_number(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    try:
        num = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(num)


def _serialize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()[:10]
    if hasattr(value, "item"):
        try:
            return _serialize_value(value.item())
        except Exception:
            pass
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def _period_label(end_date: Any, period: Any) -> str:
    end_text = _serialize_value(end_date) or ""
    period_text = str(period or "").strip().upper()
    if end_text and period_text:
        year = end_text[:4]
        return f"{year}-{period_text}"
    return end_text or period_text or ""


def _rows_from_df(df: Any) -> list[dict[str, Any]]:
    if df.empty:
        return []
    records = df.to_dict(orient="records")
    records.reverse()
    return [{k: _serialize_value(v) for k, v in row.items()} for row in records]


def _fetch_quarterly_from_view(
    con: duckdb.DuckDBPyConnection,
    view_name: str,
    code: str,
    columns: list[str],
    *,
    limit: int = MAX_QUARTER_ROWS,
) -> list[dict[str, Any]]:
    select_sql = ", ".join(columns)
    sql = (
        f"SELECT {select_sql} FROM fin_{view_name} "
        "WHERE htsc_code = ? ORDER BY report_date DESC, period DESC LIMIT ?"
    )
    try:
        df = con.execute(sql, [code, limit]).fetchdf()
    except Exception:
        return []
    return _rows_from_df(df)


def _fetch_latest_daily_from_view(
    con: duckdb.DuckDBPyConnection,
    view_name: str,
    code: str,
    columns: list[str],
) -> Optional[dict[str, Any]]:
    select_sql = ", ".join(columns)
    sql = (
        f"SELECT {select_sql} FROM fin_{view_name} "
        "WHERE htsc_code = ? ORDER BY time DESC NULLS LAST LIMIT 1"
    )
    try:
        df = con.execute(sql, [code]).fetchdf()
    except Exception:
        return None
    if df.empty:
        return None
    row = df.iloc[0].to_dict()
    return {k: _serialize_value(v) for k, v in row.items()}


def _fetch_quarterly_df(
    con: duckdb.DuckDBPyConnection,
    subdir: str,
    code: str,
    columns: list[str],
    *,
    limit: int = MAX_QUARTER_ROWS,
    paths: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    select_sql = ", ".join(columns)
    recent_paths = paths if paths is not None else _resolve_partition_paths(
        subdir, recent_count=RECENT_QUARTER_PARTITIONS
    )
    reader_sql, reader_params = _parquet_reader(recent_paths)
    if not reader_sql:
        return []
    sql = (
        f"SELECT {select_sql} FROM {reader_sql} "
        "WHERE htsc_code = ? ORDER BY report_date DESC, period DESC LIMIT ?"
    )
    try:
        df = con.execute(sql, [*reader_params, code, limit]).fetchdf()
    except Exception:
        return []
    rows = _rows_from_df(df)
    if rows or len(recent_paths) == 1:
        return rows

    glob_path = _subdir_glob(subdir)
    fallback_sql = (
        f"SELECT {select_sql} FROM read_parquet(?, hive_partitioning=true, union_by_name=true) "
        "WHERE htsc_code = ? ORDER BY report_date DESC, period DESC LIMIT ?"
    )
    try:
        df = con.execute(fallback_sql, [glob_path, code, limit]).fetchdf()
    except Exception:
        return []
    return _rows_from_df(df)


def _fetch_latest_daily_row(
    con: duckdb.DuckDBPyConnection,
    subdir: str,
    code: str,
    columns: list[str],
    *,
    paths: Optional[list[str]] = None,
) -> Optional[dict[str, Any]]:
    select_sql = ", ".join(columns)
    recent_paths = paths if paths is not None else _resolve_partition_paths(
        subdir, recent_count=RECENT_DAILY_PARTITIONS
    )
    reader_sql, reader_params = _parquet_reader(recent_paths)
    if not reader_sql:
        return None
    sql = (
        f"SELECT {select_sql} FROM {reader_sql} "
        "WHERE htsc_code = ? ORDER BY time DESC NULLS LAST LIMIT 1"
    )
    try:
        df = con.execute(sql, [*reader_params, code]).fetchdf()
    except Exception:
        df = None
    if df is not None and not df.empty:
        row = df.iloc[0].to_dict()
        return {k: _serialize_value(v) for k, v in row.items()}

    if len(recent_paths) == 1:
        return None

    glob_path = _subdir_glob(subdir)
    fallback_sql = (
        f"SELECT {select_sql} FROM read_parquet(?, hive_partitioning=true, union_by_name=true) "
        "WHERE htsc_code = ? ORDER BY time DESC NULLS LAST LIMIT 1"
    )
    try:
        df = con.execute(fallback_sql, [glob_path, code]).fetchdf()
    except Exception:
        return None
    if df.empty:
        return None
    row = df.iloc[0].to_dict()
    return {k: _serialize_value(v) for k, v in row.items()}


def _build_statement_section(
    rows: list[dict[str, Any]],
    field_specs: list[tuple[str, str, str]],
) -> Optional[dict[str, Any]]:
    if not rows:
        return None
    fields = [{"key": key, "label": label, "format": fmt} for key, label, fmt in field_specs]
    out_rows: list[dict[str, Any]] = []
    for row in rows:
        period = row.get("period")
        end_date = row.get("end_date")
        item: dict[str, Any] = {
            "end_date": end_date,
            "period": period,
            "period_label": _period_label(end_date, period),
        }
        for key, _, _ in field_specs:
            item[key] = row.get(key)
        out_rows.append(item)
    return {"fields": fields, "rows": out_rows}


def _build_indicator_section(rows: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not rows:
        return None
    columns = [{"key": k, "label": label, "format": fmt} for k, label, fmt in INDICATOR_TABLE_COLUMNS]
    table_rows: list[dict[str, Any]] = []
    for row in rows:
        period = row.get("period")
        end_date = row.get("end_date")
        item: dict[str, Any] = {
            "end_date": end_date,
            "period": period,
            "period_label": _period_label(end_date, period),
        }
        for key, _, _ in INDICATOR_TABLE_COLUMNS:
            item[key] = _get_indicator_field(row, key)
        table_rows.append(item)

    chart_metrics: list[dict[str, Any]] = []
    for key, label, fmt in CHART_METRICS:
        points: list[dict[str, Any]] = []
        for row in rows:
            value = _get_indicator_field(row, key)
            if not _is_finite_number(value):
                continue
            points.append(
                {
                    "t": _period_label(row.get("end_date"), row.get("period")),
                    "v": float(value),
                }
            )
        if points:
            chart_metrics.append({"key": key, "label": label, "format": fmt, "points": points})

    return {
        "columns": columns,
        "rows": table_rows,
        "chart_metrics": chart_metrics,
    }


def _build_overview(rows: list[dict[str, Any]], income_rows: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    latest = rows[-1] if rows else None
    if latest is None and income_rows:
        latest = income_rows[-1]
    if latest is None:
        return None

    kpis: list[dict[str, Any]] = []
    for key, label, fmt, yoy_key in OVERVIEW_KPIS:
        value = _get_indicator_field(latest, key)
        if not _is_finite_number(value) and income_rows:
            income_latest = income_rows[-1]
            if key == "revenue":
                value = income_latest.get("revenue") or income_latest.get("total_income")
            elif key == "net_profit_excl_min_int_inc":
                value = income_latest.get("net_profit_excl_min_int_inc")
        yoy = latest.get(yoy_key) if yoy_key else None
        if not _is_finite_number(value) and not _is_finite_number(yoy):
            continue
        kpis.append(
            {
                "key": key,
                "label": label,
                "format": fmt,
                "value": float(value) if _is_finite_number(value) else None,
                "yoy": float(yoy) if _is_finite_number(yoy) else None,
            }
        )
    return {"kpis": kpis}


def _build_valuation_snapshot(
    valuation_row: Optional[dict[str, Any]],
    equity_row: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    if valuation_row is None and equity_row is None:
        return None
    snapshot: dict[str, Any] = {}
    if valuation_row:
        snapshot["time"] = valuation_row.get("time")
        for key in ("pe", "pettm", "pb", "ps", "psttm", "floating_market_val", "total_market_val"):
            if key in valuation_row:
                snapshot[key] = valuation_row.get(key)
    if equity_row:
        if not snapshot.get("time"):
            snapshot["time"] = equity_row.get("time")
        snapshot["name"] = equity_row.get("name")
        for key in ("close", "turnover_rate", "value", "volume", "day_change"):
            if key in equity_row:
                snapshot[key] = equity_row.get(key)
    return snapshot


def _resolve_name(
    income_rows: list[dict[str, Any]],
    indicator_rows: list[dict[str, Any]],
    equity_row: Optional[dict[str, Any]],
) -> Optional[str]:
    for source in (indicator_rows, income_rows):
        if source:
            name = source[-1].get("name")
            if name:
                return str(name)
    if equity_row and equity_row.get("name"):
        return str(equity_row["name"])
    return None


def _latest_report_label(indicator_rows: list[dict[str, Any]], income_rows: list[dict[str, Any]]) -> Optional[str]:
    source = indicator_rows or income_rows
    if not source:
        return None
    latest = source[-1]
    return _period_label(latest.get("end_date"), latest.get("period"))


def _latest_report_label(indicator_rows: list[dict[str, Any]], income_rows: list[dict[str, Any]]) -> Optional[str]:
    source = indicator_rows or income_rows
    if not source:
        return None
    latest = source[-1]
    return _period_label(latest.get("end_date"), latest.get("period"))


def _fetch_panel_dataset(normalized: str) -> dict[str, Any]:
    con = _ensure_views()
    with _QUERY_LOCK:
        income_rows = _fetch_quarterly_from_view(
            con, "income", normalized, _statement_columns(INCOME_FIELDS)
        )
        balance_rows = _fetch_quarterly_from_view(
            con, "balance", normalized, _statement_columns(BALANCE_FIELDS)
        )
        cashflow_rows = _fetch_quarterly_from_view(
            con, "cashflow", normalized, _statement_columns(CASHFLOW_FIELDS)
        )
        indicator_rows = _fetch_quarterly_from_view(con, "indicator", normalized, _indicator_columns())
        valuation_row = _fetch_latest_daily_from_view(con, "valuation", normalized, VALUATION_COLUMNS)
        equity_row = _fetch_latest_daily_from_view(con, "equity", normalized, EQUITY_COLUMNS)

    if not any((income_rows, balance_rows, cashflow_rows, indicator_rows, valuation_row, equity_row)):
        raise MarketDataNotFoundError(f"未找到 {normalized} 的基本面数据")

    name = _resolve_name(income_rows, indicator_rows, equity_row)
    data_as_of = None
    if valuation_row and valuation_row.get("time"):
        data_as_of = valuation_row["time"]
    elif equity_row and equity_row.get("time"):
        data_as_of = equity_row["time"]

    return {
        "meta": {
            "code": normalized,
            "name": name,
            "latest_report": _latest_report_label(indicator_rows, income_rows),
            "data_as_of": data_as_of,
        },
        "valuation_snapshot": _build_valuation_snapshot(valuation_row, equity_row),
        "overview": _build_overview(indicator_rows, income_rows),
        "indicators": _build_indicator_section(indicator_rows),
        "statements": {
            "income": _build_statement_section(income_rows, INCOME_FIELDS),
            "balance": _build_statement_section(balance_rows, BALANCE_FIELDS),
            "cashflow": _build_statement_section(cashflow_rows, CASHFLOW_FIELDS),
        },
    }


def query_fundamental_panel(code: Optional[str]) -> dict[str, Any]:
    """查询单只股票基本面面板数据。"""
    normalized = _validate_code(code)
    now = time.monotonic()
    with _PANEL_CACHE_LOCK:
        cached = _PANEL_CACHE.get(normalized)
        if cached and now - cached[0] < PANEL_CACHE_TTL_SECONDS:
            return cached[1]

    payload = _fetch_panel_dataset(normalized)
    with _PANEL_CACHE_LOCK:
        _PANEL_CACHE[normalized] = (now, payload)
    return payload
