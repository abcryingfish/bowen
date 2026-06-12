"""强点回测 / 穷举 trial 的 run_name 后缀与日期前缀（与 可视化/run_name_format 对齐）。"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from models.configurable_signal_rules.data import FactorRule

_INVALID = re.compile(r'[\\/:*?"<>|\s]+')


def _sanitize_factor_token(name: str) -> str:
    token = _INVALID.sub("_", str(name or "").strip())
    return token.rstrip("._") or "因子"


def build_buy_factor_run_suffix(buy_rules: list[FactorRule]) -> str:
    if not buy_rules:
        return ""
    names = [_sanitize_factor_token(r.factor) for r in buy_rules]
    return "_买" + "_".join(names)


def build_sell_factor_run_suffix(sell_rules: list[FactorRule]) -> str:
    if not sell_rules:
        return ""
    names = [_sanitize_factor_token(r.factor) for r in sell_rules]
    return "_卖" + "_".join(names)


def build_run_name_base(
    user_base: str,
    buy_rules: list[FactorRule],
    sell_rules: list[FactorRule] | None = None,
) -> str:
    """示例：ZXW强点_买A_B_卖X_Y（再由服务端加 202401_to_06 等日期前缀）。"""
    base = str(user_base or "").strip() or "ZXW强点"
    return f"{base}{build_buy_factor_run_suffix(buy_rules)}{build_sell_factor_run_suffix(sell_rules or [])}"


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def build_run_name_date_prefix(start_date: str, end_date: str) -> str:
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start is None or end is None:
        return ""
    if end < start:
        start, end = end, start
    one_year_after_start = date(start.year + 1, start.month, start.day)
    try:
        spans_more_than_one_year = end > one_year_after_start
    except ValueError:
        spans_more_than_one_year = (end - start) > timedelta(days=365)
    if spans_more_than_one_year:
        return f"{start.year}_to_{end.year}"
    if start.year == end.year:
        return f"{start.year:04d}{start.month:02d}_to_{end.month:02d}"
    return f"{start.year:04d}{start.month:02d}_to_{end.year:04d}{end.month:02d}"


def strip_run_name_date_prefix(name: str, start_date: str, end_date: str) -> str:
    """去掉名称上已有的日期前缀，避免重复拼接。"""
    text = str(name or "").strip()
    if not text:
        return text
    prefix = build_run_name_date_prefix(start_date, end_date)
    if prefix and text.startswith(prefix):
        return text[len(prefix) :].lstrip("_")
    return text


def build_full_run_name(
    *,
    start_date: str,
    end_date: str,
    user_base: str,
    buy_rules: list[FactorRule],
    sell_rules: list[FactorRule] | None = None,
) -> str:
    """完整名称：202401_to_06ZXW强点_买A_B_卖X_Y。"""
    prefix = build_run_name_date_prefix(start_date, end_date)
    clean_base = strip_run_name_date_prefix(user_base, start_date, end_date)
    body = build_run_name_base(clean_base, buy_rules, sell_rules)
    return f"{prefix}{body}" if prefix else body


def count_nonempty_buy_subsets(n_factors: int) -> int:
    if n_factors <= 0:
        return 0
    return (1 << n_factors) - 1


def count_nonempty_sell_subsets(n_factors: int) -> int:
    return count_nonempty_buy_subsets(n_factors)


def count_exhaustive_buy_sell_combos(n_buy_factors: int, n_sell_factors: int) -> int:
    return count_nonempty_buy_subsets(n_buy_factors) * count_nonempty_sell_subsets(n_sell_factors)
