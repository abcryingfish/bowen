"""Immutable definitions and shared constants for style portfolio monitoring."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Literal

STYLE_MONITOR_DB_PATH = Path(r"D:\database\style_portfolio_monitor\style_monitor.duckdb")
INITIAL_DATE = date(2015, 1, 1)
INITIAL_CASH = 10_000_000.0
COMMISSION_RATE = 0.0003
LOT_SIZE = 100
MIN_HISTORY_DAYS = 120
LIQUIDITY_LOOKBACK_DAYS = 20
MIN_AVERAGE_TURNOVER = 20_000_000.0
SELECTION_RATIO = 0.20
MAX_SELECTION_COUNT = 200
MIN_FACTOR_COVERAGE = 0.80

RebalanceFrequency = Literal["weekly", "monthly", "quarterly"]


@dataclass(frozen=True, slots=True)
class StyleModelDefinition:
    """Stable model metadata used by the ledger and API."""

    model_id: str
    factor_name: str
    factor_key: str
    rebalance_frequency: RebalanceFrequency
    selection_side: Literal["both"] = "both"

    @property
    def display_name(self) -> str:
        return self.factor_name

    @property
    def title(self) -> str:
        return self.factor_name

    @property
    def name(self) -> str:
        return self.factor_name

    @property
    def frequency(self) -> RebalanceFrequency:
        return self.rebalance_frequency


MODEL_DEFINITIONS: tuple[StyleModelDefinition, ...] = (
    StyleModelDefinition("large_cap_raw", "大市值风格评分（纯市值）", "large_cap_style_score_pure", "weekly"),
    StyleModelDefinition("small_cap_raw", "小市值风格评分（纯市值）", "small_cap_style_score_pure", "weekly"),
    StyleModelDefinition("value_raw", "价值模型综合评分", "value_model_composite_score", "monthly"),
    StyleModelDefinition("value_industry_neutral", "价值模型综合评分(行业标准化)", "value_model_composite_score_industry_normalized", "monthly"),
    StyleModelDefinition("growth_raw", "成长风格评分", "growth_style_score", "monthly"),
    StyleModelDefinition("growth_industry_neutral", "成长风格综合评分(行业标准化)", "growth_style_composite_score_industry_normalized", "monthly"),
    StyleModelDefinition("momentum_raw", "动量风格评分", "momentum_style_score", "weekly"),
    StyleModelDefinition("low_volatility_raw", "低波风格评分", "low_volatility_style_score", "monthly"),
    StyleModelDefinition("dividend_raw", "红利基础百分位", "dividend_base_percentile", "quarterly"),
    StyleModelDefinition("liquidity_raw", "流动性综合评分", "liquidity_composite_score", "weekly"),
)

_BUSINESS_CONSTANTS = {
    "STYLE_MONITOR_DB_PATH": str(STYLE_MONITOR_DB_PATH),
    "INITIAL_DATE": INITIAL_DATE.isoformat(),
    "INITIAL_CASH": INITIAL_CASH,
    "COMMISSION_RATE": COMMISSION_RATE,
    "LOT_SIZE": LOT_SIZE,
    "MIN_HISTORY_DAYS": MIN_HISTORY_DAYS,
    "LIQUIDITY_LOOKBACK_DAYS": LIQUIDITY_LOOKBACK_DAYS,
    "MIN_AVERAGE_TURNOVER": MIN_AVERAGE_TURNOVER,
    "SELECTION_RATIO": SELECTION_RATIO,
    "MAX_SELECTION_COUNT": MAX_SELECTION_COUNT,
    "MIN_FACTOR_COVERAGE": MIN_FACTOR_COVERAGE,
}


def build_config_hash(model: StyleModelDefinition) -> str:
    payload = {"model": asdict(model), "constants": _BUSINESS_CONSTANTS}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _period_key(value: date, frequency: RebalanceFrequency) -> tuple[int, ...]:
    if frequency == "weekly":
        iso = value.isocalendar()
        return (iso.year, iso.week)
    if frequency == "monthly":
        return (value.year, value.month)
    if frequency == "quarterly":
        return (value.year, (value.month - 1) // 3 + 1)
    raise ValueError(f"Unsupported rebalance frequency: {frequency}")


def is_rebalance_day(
    trade_date: date,
    last_rebalance_date: date | None,
    frequency: RebalanceFrequency,
    calendar: Iterable[date],
) -> bool:
    """Return whether *trade_date* is the first available date of a new period."""
    # Validate the frequency even on the first run, where no prior date exists.
    _period_key(trade_date, frequency)
    trading_days = set(calendar)
    if trade_date not in trading_days:
        return False
    if last_rebalance_date is None:
        return True
    return _period_key(trade_date, frequency) != _period_key(last_rebalance_date, frequency)
