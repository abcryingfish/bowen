#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""基本面 parquet 查询服务 — 读取 D:\\database\\stock_financial_statements。"""

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

FINANCIAL_ROOT = r"D:\database\stock_financial_statements"
MERGED_GLOB = "**/merged.parquet"
CODE_PATTERN = re.compile(r"^\d{6}\.(SH|SZ|BJ)$", re.IGNORECASE)

STATEMENT_SUBDIRS = {
    "income": "income_statements",
    "balance": "balance_sheet",
    "cashflow": "cash_flow_statement",
}
INDICATOR_SUBDIR = "financial_indicators"
VALUATION_SUBDIR = "stock_valuation_data"
EQUITY_SUBDIR = "market_equity_data"

FieldSpec = dict[str, str]  # key -> label; format stored separately

INCOME_FIELDS: list[tuple[str, str, str]] = [
    ("oper_revenue", "营业收入", "money"),
    ("total_oper_cost", "营业总成本", "money"),
    ("oper_cost", "营业成本", "money"),
    ("sell_expense", "销售费用", "money"),
    ("admin_expense", "管理费用", "money"),
    ("fin_cost", "财务费用", "money"),
    ("oper_profit", "营业利润", "money"),
    ("total_profit", "利润总额", "money"),
    ("income_tax_expense", "所得税费用", "money"),
    ("net_profit", "净利润", "money"),
    ("net_profit_coms", "归母净利润", "money"),
    ("basic_eps", "基本每股收益", "number"),
    ("diluted_eps", "稀释每股收益", "number"),
]

BALANCE_FIELDS: list[tuple[str, str, str]] = [
    ("monetary_fund", "货币资金", "money"),
    ("account_rec", "应收账款", "money"),
    ("inventory", "存货", "money"),
    ("total_cur_asset", "流动资产合计", "money"),
    ("fixed_asset_net", "固定资产净额", "money"),
    ("total_non_cur_asset", "非流动资产合计", "money"),
    ("total_asset", "资产总计", "money"),
    ("st_borrowing", "短期借款", "money"),
    ("account_pay", "应付账款", "money"),
    ("total_cur_liab", "流动负债合计", "money"),
    ("lt_borrowing", "长期借款", "money"),
    ("total_non_cur_liab", "非流动负债合计", "money"),
    ("total_liab", "负债合计", "money"),
    ("share_capital", "股本", "money"),
    ("capital_reserve", "资本公积", "money"),
    ("retained_earning", "未分配利润", "money"),
    ("total_sh_equity", "股东权益合计", "money"),
    ("total_liab_sh_equity", "负债及股东权益总计", "money"),
]

CASHFLOW_FIELDS: list[tuple[str, str, str]] = [
    ("sub_total_cash_in_oper", "经营活动现金流入小计", "money"),
    ("sub_total_cash_out_oper", "经营活动现金流出小计", "money"),
    ("net_cash_flow_oper", "经营活动现金流量净额", "money"),
    ("sub_total_cash_in_inv", "投资活动现金流入小计", "money"),
    ("sub_total_cash_out_inv", "投资活动现金流出小计", "money"),
    ("net_cash_flow_inv", "投资活动现金流量净额", "money"),
    ("sub_total_cash_in_fina", "筹资活动现金流入小计", "money"),
    ("sub_total_cash_out_fina", "筹资活动现金流出小计", "money"),
    ("net_cash_flow_fina", "筹资活动现金流量净额", "money"),
    ("effect_foreign_ex_rate", "汇率变动影响", "money"),
    ("cash_equi_net_incr", "现金及等价物净增加额", "money"),
    ("cashequiending", "期末现金及等价物余额", "money"),
]

INDICATOR_TABLE_COLUMNS: list[tuple[str, str, str]] = [
    ("oper_revenue", "营业收入", "money"),
    ("net_profit_parent_com", "归母净利润", "money"),
    ("gross_profit_margin", "毛利率", "percent"),
    ("profit_margin", "净利率", "percent"),
    ("oper_profit_margin", "营业利润率", "percent"),
    ("roe", "ROE", "percent"),
    ("roa", "ROA", "percent"),
    ("basic_eps", "基本 EPS", "number"),
    ("oper_revenue_yoy", "营收同比", "percent"),
    ("net_profit_yoy", "净利润同比", "percent"),
    ("current_ratio", "流动比率", "ratio"),
    ("equity_ratio", "产权比率", "ratio"),
    ("total_asset", "总资产", "money"),
]

CHART_METRICS: list[tuple[str, str, str]] = [
    ("profit_margin", "净利率", "percent"),
    ("gross_profit_margin", "毛利率", "percent"),
    ("roe", "ROE", "percent"),
    ("oper_revenue_yoy", "营收同比", "percent"),
    ("basic_eps", "基本 EPS", "number"),
    ("total_asset_yoy", "总资产同比", "percent"),
]

OVERVIEW_KPIS: list[tuple[str, str, str, Optional[str]]] = [
    ("oper_revenue", "营业收入", "money", "oper_revenue_yoy"),
    ("net_profit_parent_com", "归母净利润", "money", "net_profit_yoy"),
    ("roe", "ROE", "percent", None),
    ("profit_margin", "净利率", "percent", None),
    ("gross_profit_margin", "毛利率", "percent", None),
    ("total_asset", "总资产", "money", "total_asset_yoy"),
    ("basic_eps", "基本 EPS", "number", None),
    ("current_ratio", "流动比率", "ratio", None),
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
    "roe": ["weighted_roe", "cut_roe"],
    "roa": ["roa_ebit"],
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
        ["end_date", "period", "name"],
        [key for key, _, _ in field_specs],
    )


def _indicator_columns() -> list[str]:
    return _unique_columns(
        ["end_date", "period", "name"],
        [key for key, _, _ in INDICATOR_TABLE_COLUMNS],
        [key for key, _, _ in CHART_METRICS],
        [key for key, _, _, _ in OVERVIEW_KPIS],
        [alt for alts in INDICATOR_VALUE_FALLBACKS.values() for alt in alts],
    )


VALUATION_COLUMNS = [
    "htsc_code",
    "time",
    "pe",
    "pettm",
    "pb",
    "ps",
    "psttm",
    "floating_market_val",
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
            _VIEW_CONN.execute(
                "CREATE OR REPLACE VIEW fin_"
                f"{view_name} AS SELECT * FROM read_parquet({_quote_parquet_paths(paths)}, union_by_name=true)"
            )
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
        "WHERE htsc_code = ? ORDER BY end_date DESC, period DESC LIMIT ?"
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
        "WHERE htsc_code = ? ORDER BY end_date DESC, period DESC LIMIT ?"
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
        "WHERE htsc_code = ? ORDER BY end_date DESC, period DESC LIMIT ?"
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
            if key == "oper_revenue":
                value = income_latest.get("oper_revenue") or income_latest.get("total_oper_revenue")
            elif key == "net_profit_parent_com":
                value = income_latest.get("net_profit_coms") or income_latest.get("net_profit")
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
