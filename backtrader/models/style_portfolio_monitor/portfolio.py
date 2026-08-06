"""Pure portfolio selection and theoretical close execution functions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from .config import LOT_SIZE


@dataclass(frozen=True, slots=True)
class PortfolioState:
    cash: float
    positions: dict[str, int]
    last_prices: dict[str, float]


@dataclass(frozen=True, slots=True)
class SelectedStock:
    code: str
    score: float
    rank: int


@dataclass(frozen=True, slots=True)
class Trade:
    code: str
    side: str
    shares: int
    price: float
    trade_value: float
    commission: float


@dataclass(frozen=True, slots=True)
class RebalanceResult:
    state: PortfolioState
    trades: list[Trade]
    total_commission: float
    turnover: float


@dataclass(frozen=True, slots=True)
class ValuationResult:
    total_asset: float
    market_value: float
    prices: dict[str, float]
    stale_codes: list[str]


def select_style_legs(snapshot, ratio: float, max_count: int) -> dict[str, list[SelectedStock]]:
    valid = snapshot.dropna(subset=["score"]).copy()
    valid["score"] = valid["score"].astype(float)
    valid["htsc_code"] = valid["htsc_code"].astype(str)
    count = min(max(0, math.ceil(len(valid) * float(ratio))), int(max_count))
    high = valid.sort_values(["score", "htsc_code"], ascending=[False, True]).head(count)
    low = valid.sort_values(["score", "htsc_code"], ascending=[True, True]).head(count)
    return {
        "high": [SelectedStock(str(row.htsc_code), float(row.score), index + 1) for index, row in enumerate(high.itertuples())],
        "low": [SelectedStock(str(row.htsc_code), float(row.score), index + 1) for index, row in enumerate(low.itertuples())],
    }


def build_target_shares(codes, prices: Mapping[str, float], portfolio_value: float, commission_rate: float, lot_size: int) -> dict[str, int]:
    usable = [str(code) for code in codes if float(prices.get(code, 0.0) or 0.0) > 0]
    if not usable or portfolio_value <= 0:
        return {str(code): 0 for code in codes}
    budget = float(portfolio_value) / len(usable)
    targets = {str(code): 0 for code in codes}
    for code in usable:
        gross_per_share = float(prices[code]) * (1.0 + float(commission_rate))
        targets[code] = int(math.floor(budget / gross_per_share / int(lot_size))) * int(lot_size)
    return targets


def rebalance_at_close(state: PortfolioState, target_shares: Mapping[str, int], prices: Mapping[str, float], commission_rate: float) -> RebalanceResult:
    cash = float(state.cash)
    positions = dict(state.positions)
    last_prices = dict(state.last_prices)
    trades: list[Trade] = []
    universe = sorted(set(positions) | set(target_shares))

    def execute(code: str, side: str, shares: int) -> None:
        nonlocal cash
        price = float(prices[code])
        value = float(shares) * price
        commission = value * float(commission_rate)
        if side == "SELL":
            cash += value - commission
            positions[code] = positions.get(code, 0) - shares
        else:
            cash -= value + commission
            positions[code] = positions.get(code, 0) + shares
        last_prices[code] = price
        trades.append(Trade(code, side, shares, price, value, commission))

    for code in universe:
        current = int(positions.get(code, 0))
        target = int(target_shares.get(code, 0))
        if current > target and code in prices and float(prices[code]) > 0:
            execute(code, "SELL", current - target)

    for code in universe:
        current = int(positions.get(code, 0))
        target = int(target_shares.get(code, 0))
        if target <= current or code not in prices or float(prices[code]) <= 0:
            continue
        lot = LOT_SIZE
        requested = target - current
        affordable = int(max(0.0, cash) // (float(prices[code]) * (1.0 + float(commission_rate)) * lot)) * lot
        execute(code, "BUY", min(requested, affordable)) if affordable else None

    positions = {code: shares for code, shares in positions.items() if shares > 0}
    pre_asset = float(state.cash) + sum(int(shares) * float(prices.get(code, state.last_prices.get(code, 0.0))) for code, shares in state.positions.items())
    turnover = sum(item.trade_value for item in trades) / pre_asset if pre_asset > 0 else 0.0
    return RebalanceResult(PortfolioState(cash, positions, last_prices), trades, sum(item.commission for item in trades), turnover)


def mark_to_market(state: PortfolioState, prices: Mapping[str, float]) -> ValuationResult:
    effective: dict[str, float] = {}
    stale: list[str] = []
    for code, shares in state.positions.items():
        value = float(prices.get(code, 0.0) or 0.0)
        if value <= 0:
            value = float(state.last_prices.get(code, 0.0) or 0.0)
            stale.append(code)
        if value > 0:
            effective[code] = value
    market_value = sum(int(shares) * effective.get(code, 0.0) for code, shares in state.positions.items())
    return ValuationResult(float(state.cash) + market_value, market_value, effective, sorted(stale))


def calculate_relative_nav(high_nav: float, low_nav: float) -> float | None:
    return float(high_nav) / float(low_nav) * 100.0 if float(low_nav) != 0 else None
