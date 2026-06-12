"""强点模型：将前端买入/卖出因子合并为 strong_buy_signal、strong_sell_signal 列。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from models.configurable_signal_rules.data import (
    FactorRule,
    _combine_rule_columns,
    _load_factor_frame,
    _normalize_operator,
    normalize_rules,
)

STRONG_BUY_LINE = "strong_buy_signal"
STRONG_SELL_LINE = "strong_sell_signal"


def _coerce_buy_rules(buy_rules: Any) -> list[FactorRule]:
    if not buy_rules:
        return []
    if isinstance(buy_rules, list) and buy_rules and isinstance(buy_rules[0], FactorRule):
        return list(buy_rules)
    return normalize_rules(buy_rules, "buy")


def merge_strong_buy_signal(
    bt_df: pd.DataFrame,
    buy_rules: Any,
    buy_operator: Any,
) -> pd.DataFrame:
    """在 ZXW 宽表上写入 strong_buy_signal（>=1 视为强买触发）。"""
    out = bt_df.copy()
    rules = _coerce_buy_rules(buy_rules)
    if not rules:
        if "total_buy_signal" in out.columns:
            out[STRONG_BUY_LINE] = pd.to_numeric(out["total_buy_signal"], errors="coerce").fillna(0.0)
        else:
            out[STRONG_BUY_LINE] = 0.0
        return out

    out["time"] = pd.to_datetime(out["time"], errors="coerce").dt.normalize()
    out["htsc_code"] = out["htsc_code"].astype(str).str.strip().str.upper()
    codes = sorted(out["htsc_code"].dropna().unique().tolist())
    if not codes:
        out[STRONG_BUY_LINE] = 0.0
        return out

    t_min = out["time"].min()
    t_max = out["time"].max()
    if pd.isna(t_min) or pd.isna(t_max):
        out[STRONG_BUY_LINE] = 0.0
        return out

    start_date = pd.Timestamp(t_min).strftime("%Y-%m-%d")
    end_date = (pd.Timestamp(t_max) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    operator = _normalize_operator(buy_operator)

    factor_df = _load_factor_frame(rules, codes, start_date, end_date)
    merged = out.merge(factor_df, on=["time", "htsc_code"], how="left")
    for rule in rules:
        if rule.column not in merged.columns:
            merged[rule.column] = 0.0
        merged[rule.column] = pd.to_numeric(merged[rule.column], errors="coerce").fillna(0.0)

    hit = _combine_rule_columns(merged, rules, operator)
    merged[STRONG_BUY_LINE] = hit.astype(float).to_numpy()
    # 宽表 feed 已注册 total_buy_signal 线，写入同值避免改 zxw_view_results_full
    merged["total_buy_signal"] = merged[STRONG_BUY_LINE]
    return merged


def active_rules_from_template(template: list[FactorRule], mask: dict[str, bool]) -> list[FactorRule]:
    """按因子名掩码筛选仍启用的规则（保持模板顺序）。"""
    out: list[FactorRule] = []
    for rule in template:
        if mask.get(rule.factor, False):
            out.append(rule)
    return out


def template_from_frontend(buy_rules: Any) -> list[FactorRule]:
    return normalize_rules(buy_rules, "buy")


def _coerce_sell_rules(sell_rules: Any) -> list[FactorRule]:
    if not sell_rules:
        return []
    if isinstance(sell_rules, list) and sell_rules and isinstance(sell_rules[0], FactorRule):
        return list(sell_rules)
    return normalize_rules(sell_rules, "sell")


def merge_strong_sell_signal(
    bt_df: pd.DataFrame,
    sell_rules: Any,
    sell_operator: Any,
) -> pd.DataFrame:
    """写入 strong_sell_signal（前端卖出因子合成，供止盈执行）；不改动宽表 total_sell_signal（止损）。"""
    out = bt_df.copy()
    rules = _coerce_sell_rules(sell_rules)
    if "total_sell_signal" not in out.columns:
        out["total_sell_signal"] = 0.0
    else:
        out["total_sell_signal"] = pd.to_numeric(out["total_sell_signal"], errors="coerce").fillna(0.0)

    if not rules:
        out[STRONG_SELL_LINE] = 0.0
        return out

    out["time"] = pd.to_datetime(out["time"], errors="coerce").dt.normalize()
    out["htsc_code"] = out["htsc_code"].astype(str).str.strip().str.upper()
    codes = sorted(out["htsc_code"].dropna().unique().tolist())
    if not codes:
        out[STRONG_SELL_LINE] = 0.0
        return out

    t_min = out["time"].min()
    t_max = out["time"].max()
    if pd.isna(t_min) or pd.isna(t_max):
        out[STRONG_SELL_LINE] = 0.0
        return out

    start_date = pd.Timestamp(t_min).strftime("%Y-%m-%d")
    end_date = (pd.Timestamp(t_max) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    operator = _normalize_operator(sell_operator)

    factor_df = _load_factor_frame(rules, codes, start_date, end_date)
    merged = out.merge(factor_df, on=["time", "htsc_code"], how="left")
    for rule in rules:
        if rule.column not in merged.columns:
            merged[rule.column] = 0.0
        merged[rule.column] = pd.to_numeric(merged[rule.column], errors="coerce").fillna(0.0)

    hit = _combine_rule_columns(merged, rules, operator)
    merged[STRONG_SELL_LINE] = hit.astype(float).to_numpy()
    return merged


def sell_template_from_frontend(sell_rules: Any) -> list[FactorRule]:
    return normalize_rules(sell_rules, "sell")
