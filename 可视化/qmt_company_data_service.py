#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""QMT 公司数据 parquet 查询服务。"""

from __future__ import annotations

import math
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

from market_data_service import MarketDataNotFoundError, MarketDataValidationError

QMT_COMPANY_DATA_DIR = os.environ.get("QMT_COMPANY_DATA_DIR", r"D:\database\qmt_company_data")
CODE_PATTERN = re.compile(r"^\d{6}\.(SH|SZ|BJ)$", re.IGNORECASE)
DEFAULT_LIMIT = 12
TABLE_LABELS = {
    "Income": "利润表",
    "Balance": "资产负债表",
    "CashFlow": "现金流量表",
    "PershareIndex": "主要指标",
    "Capital": "股本结构",
}
TABLE_ORDER = ["Income", "Balance", "CashFlow", "PershareIndex", "Capital"]
META_COLUMNS = {"htsc_code", "table_name", "table", "year", "month"}
FIELD_LABELS = {
    # common
    "report_date": "报告期",
    "announce_date": "公告日期",
    "period": "季度",
    "name": "证券简称",
    "updated_at": "更新时间",
    "m_timetag": "QMT报告日期",
    "m_anntime": "QMT公告日期",
    # Capital
    "total_capital": "总股本",
    "circulating_capital": "流通股本",
    "restrict_circulating_capital": "限售流通股本",
    "freeFloatCapital": "自由流通股本",
    # Income
    "revenue": "营业总收入",
    "operating_revenue": "营业收入",
    "revenue_inc": "营业收入",
    "total_operating_cost": "营业总成本",
    "total_expense": "营业总成本",
    "oper_exp": "营业支出",
    "research_expenses": "研发费用",
    "sale_expense": "销售费用",
    "less_gerl_admin_exp": "管理费用",
    "financial_expense": "财务费用",
    "plus_net_invest_inc": "投资收益",
    "oper_profit": "营业利润",
    "tot_profit": "利润总额",
    "inc_tax": "所得税费用",
    "net_profit_incl_min_int_inc": "净利润",
    "net_profit_incl_min_int_inc_after": "归母净利润",
    "minority_int_inc": "少数股东损益",
    "s_fa_eps_basic": "基本每股收益",
    "s_fa_eps_diluted": "稀释每股收益",
    "total_income": "综合收益总额",
    # Balance
    "cash_equivalents": "货币资金",
    "tradable_fin_assets": "交易性金融资产",
    "bill_receivable": "应收票据",
    "account_receivable": "应收账款",
    "advance_payment": "预付款项",
    "other_receivable": "其他应收款",
    "inventories": "存货",
    "other_current_assets": "其他流动资产",
    "total_current_assets": "流动资产合计",
    "long_term_eqy_invest": "长期股权投资",
    "invest_real_estate": "投资性房地产",
    "fix_assets": "固定资产",
    "constru_in_process": "在建工程",
    "intang_assets": "无形资产",
    "goodwill": "商誉",
    "deferred_tax_assets": "递延所得税资产",
    "total_non_current_assets": "非流动资产合计",
    "tot_assets": "资产总计",
    "shortterm_loan": "短期借款",
    "notes_payable": "应付票据",
    "accounts_payable": "应付账款",
    "advance_peceipts": "预收款项",
    "empl_ben_payable": "应付职工薪酬",
    "taxes_surcharges_payable": "应交税费",
    "other_payable": "其他应付款",
    "total_current_liability": "流动负债合计",
    "long_term_loans": "长期借款",
    "bonds_payable": "应付债券",
    "deferred_tax_liab": "递延所得税负债",
    "non_current_liabilities": "非流动负债合计",
    "tot_liab": "负债合计",
    "cap_stk": "股本",
    "cap_rsrv": "资本公积",
    "surplus_rsrv": "盈余公积",
    "undistributed_profit": "未分配利润",
    "total_equity": "所有者权益合计",
    "tot_liab_shrhldr_eqy": "负债和所有者权益总计",
    # CashFlow
    "goods_sale_and_service_render_cash": "销售商品、提供劳务收到的现金",
    "stot_cash_inflows_oper_act": "经营活动现金流入小计",
    "goods_and_services_cash_paid": "购买商品、接受劳务支付的现金",
    "cash_pay_beh_empl": "支付给职工以及为职工支付的现金",
    "pay_all_typ_tax": "支付的各项税费",
    "stot_cash_outflows_oper_act": "经营活动现金流出小计",
    "net_cash_flows_oper_act": "经营活动现金流量净额",
    "cash_recp_return_invest": "取得投资收益收到的现金",
    "stot_cash_inflows_inv_act": "投资活动现金流入小计",
    "cash_pay_acq_const_fiolta": "购建固定资产等支付的现金",
    "stot_cash_outflows_inv_act": "投资活动现金流出小计",
    "net_cash_flows_inv_act": "投资活动现金流量净额",
    "cash_recp_borrow": "取得借款收到的现金",
    "stot_cash_inflows_fnc_act": "筹资活动现金流入小计",
    "cash_prepay_amt_borr": "偿还债务支付的现金",
    "cash_pay_dist_dpcp_int_exp": "分配股利、利润或偿付利息支付的现金",
    "stot_cash_outflows_fnc_act": "筹资活动现金流出小计",
    "net_cash_flows_fnc_act": "筹资活动现金流量净额",
    "eff_fx_flu_cash": "汇率变动对现金的影响",
    "net_incr_cash_cash_equ": "现金及现金等价物净增加额",
    "cash_cash_equ_beg_period": "期初现金及现金等价物余额",
    "cash_cash_equ_end_period": "期末现金及现金等价物余额",
    # PershareIndex
    "s_fa_ocfps": "每股经营现金流",
    "s_fa_bps": "每股净资产",
    "s_fa_undistributedps": "每股未分配利润",
    "s_fa_surpluscapitalps": "每股资本公积",
    "du_return_on_equity": "净资产收益率",
    "equity_roe": "ROE",
    "net_roe": "净资产收益率(摊薄)",
    "sales_gross_profit": "销售毛利率",
    "gross_profit": "毛利率",
    "net_profit": "净利率",
    "inc_revenue_rate": "营业收入同比",
    "inc_net_profit_rate": "净利润同比",
    "gear_ratio": "资产负债率",
    "inventory_turnover": "存货周转率",
    "sales_cash_flow": "销售现金比率",
}


def _validate_code(code: str | None) -> str:
    normalized = str(code or "").strip().upper()
    if not CODE_PATTERN.match(normalized):
        raise MarketDataValidationError("code 必须形如 601688.SH / 000001.SZ / 430000.BJ")
    return normalized


def _available_table_names() -> list[str]:
    root = Path(QMT_COMPANY_DATA_DIR)
    if not root.exists():
        return []
    names = []
    for child in root.glob("table=*"):
        if not child.is_dir():
            continue
        names.append(child.name.split("=", 1)[1])
    return sorted(names, key=lambda name: TABLE_ORDER.index(name) if name in TABLE_ORDER else len(TABLE_ORDER))


def _validate_table(table: str | None) -> str:
    name = str(table or "").strip()
    if not name:
        raise MarketDataValidationError("缺少 table 参数")
    known = {item.lower(): item for item in _available_table_names()}
    known.update({item.lower(): item for item in TABLE_ORDER})
    key = name.lower()
    if key not in known:
        raise MarketDataValidationError(f"未知 QMT 公司数据表: {name}")
    return known[key]


def _table_paths(table_name: str) -> list[str]:
    table_dir = Path(QMT_COMPANY_DATA_DIR) / f"table={table_name}"
    if not table_dir.exists():
        return []
    return [str(path).replace("\\", "/") for path in sorted(table_dir.glob("year=*/month=*/merged.parquet"))]


def _quote_paths(paths: list[str]) -> str:
    return "[" + ", ".join(repr(path) for path in paths) + "]"


def _to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    try:
        if hasattr(value, "to_pydatetime"):
            return value.to_pydatetime().strftime("%Y-%m-%d")
    except Exception:
        pass
    return value


def _rows_to_json(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: _to_jsonable(value) for key, value in row.items()} for row in rows]


def _infer_column_type(key: str, rows: list[dict[str, Any]]) -> str:
    if key in {"report_date", "announce_date", "updated_at"}:
        return "date"
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return "number"
    return "text"


def _build_columns(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not rows:
        return []
    keys = list(rows[0].keys())
    preferred = ["report_date", "announce_date", "period", "name"]
    ordered = [key for key in preferred if key in keys]
    ordered.extend(key for key in keys if key not in ordered and key not in META_COLUMNS)
    return [{"key": key, "label": FIELD_LABELS.get(key, key), "type": _infer_column_type(key, rows)} for key in ordered]


def query_qmt_company_tables() -> dict[str, Any]:
    names = _available_table_names()
    if not names:
        names = list(TABLE_ORDER)
    return {
        "base_dir": QMT_COMPANY_DATA_DIR,
        "tables": [{"key": name, "label": TABLE_LABELS.get(name, name)} for name in names],
    }


def query_qmt_company_table(code: str | None, table: str | None, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    normalized = _validate_code(code)
    table_name = _validate_table(table)
    paths = _table_paths(table_name)
    if not paths:
        raise MarketDataNotFoundError(f"未找到 QMT 公司数据表 {table_name}")
    safe_limit = max(1, min(int(limit or DEFAULT_LIMIT), 200))
    query = f"""
    SELECT *
    FROM read_parquet({_quote_paths(paths)}, union_by_name=true)
    WHERE UPPER(TRIM(CAST(htsc_code AS VARCHAR))) = ?
    ORDER BY CAST(report_date AS TIMESTAMP) DESC, CAST(announce_date AS TIMESTAMP) DESC
    LIMIT {safe_limit}
    """
    df = duckdb.connect(database=":memory:").execute(query, [normalized]).df()
    if df.empty:
        raise MarketDataNotFoundError(f"未找到 {normalized} 的 {table_name} 数据")
    rows = _rows_to_json(df.to_dict(orient="records"))
    rows.sort(key=lambda row: (str(row.get("report_date") or ""), str(row.get("announce_date") or "")), reverse=True)
    return {
        "meta": {
            "code": normalized,
            "name": rows[0].get("name") or "",
            "table": table_name,
            "label": TABLE_LABELS.get(table_name, table_name),
            "count": len(rows),
        },
        "columns": _build_columns(rows),
        "rows": rows,
    }


def query_qmt_company_summary(code: str | None) -> dict[str, Any]:
    normalized = _validate_code(code)
    latest_by_table: dict[str, Any] = {}
    name = ""
    latest_report = ""
    for table in _available_table_names() or TABLE_ORDER:
        try:
            payload = query_qmt_company_table(normalized, table, limit=1)
        except (MarketDataNotFoundError, MarketDataValidationError):
            continue
        row = payload["rows"][0] if payload["rows"] else None
        if not row:
            continue
        latest_by_table[table] = row
        name = name or str(row.get("name") or "")
        report = str(row.get("report_date") or "")
        if report and report > latest_report:
            latest_report = report
    if not latest_by_table:
        raise MarketDataNotFoundError(f"未找到 {normalized} 的 QMT 公司数据")
    return {
        "meta": {
            "code": normalized,
            "name": name,
            "latest_report": latest_report,
        },
        "tables": query_qmt_company_tables()["tables"],
        "latest_by_table": latest_by_table,
    }
