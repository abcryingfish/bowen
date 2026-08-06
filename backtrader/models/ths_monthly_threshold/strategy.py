from __future__ import annotations

from typing import Any

import backtrader as bt
import numpy as np


ONE_WAY_COST_RATE = 0.0015


def build_equal_weight_target_sizes(
    *,
    eligible_codes: list[str],
    prices: dict[str, float],
    portfolio_value: float,
    lot_size: int,
    one_way_cost_rate: float,
    currently_held_codes: list[str] | None = None,
) -> dict[str, int]:
    codes = list(dict.fromkeys(str(code).strip().upper() for code in eligible_codes if str(code).strip()))
    held = list(dict.fromkeys(str(code).strip().upper() for code in (currently_held_codes or []) if str(code).strip()))
    targets = {code: 0 for code in held}
    if not codes or portfolio_value <= 0:
        return targets
    target_value = float(portfolio_value) / len(codes)
    lot = max(1, int(lot_size))
    for code in codes:
        price = float(prices.get(code, 0.0) or 0.0)
        if not np.isfinite(price) or price <= 0:
            targets[code] = 0
            continue
        raw_size = int(target_value / (price * (1.0 + float(one_way_cost_rate))))
        targets[code] = (raw_size // lot) * lot
    return targets


class ThsMonthlyThresholdStrategy(bt.Strategy):
    params = dict(lot_size=100, one_way_cost_rate=ONE_WAY_COST_RATE)

    def __init__(self) -> None:
        self.order_meta: dict[int, dict[str, Any]] = {}
        self.signal_log: list[dict[str, Any]] = []
        self.order_log: list[dict[str, Any]] = []
        self.trade_log: list[dict[str, Any]] = []
        self.position_log: list[dict[str, Any]] = []
        self.daily_value_log: list[dict[str, Any]] = []
        self._position_log_seen: set[tuple[str, str]] = set()
        self._commission = float(self.p.one_way_cost_rate)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if np.isfinite(parsed) else default

    def _dt_str(self, data: Any) -> str:
        return bt.num2date(data.datetime[0]).strftime("%Y-%m-%d")

    def _record_position(self, data: Any) -> None:
        dt_str = self._dt_str(data)
        key = (dt_str, data._name)
        if key in self._position_log_seen:
            return
        self._position_log_seen.add(key)
        pos = self.getposition(data)
        close_price = self._safe_float(data.close[0])
        market_value = float(pos.size) * close_price
        cost_basis = float(pos.size) * float(pos.price)
        self.position_log.append(
            {
                "date": dt_str,
                "code": data._name,
                "position_size": float(pos.size),
                "position_price": float(pos.price),
                "close": close_price,
                "market_value": market_value,
                "unrealized_pnl": market_value - cost_basis,
            }
        )

    def next(self) -> None:
        current_date = bt.num2date(self.datetime[0]).date()
        current_datas = [
            data
            for data in self.datas
            if len(data) > 0 and bt.num2date(data.datetime[0]).date() == current_date
        ]
        for data in current_datas:
            self._record_position(data)
        if not current_datas or not any(self._safe_float(data.sell_signal[0]) > 0 for data in current_datas):
            return

        eligible = [data._name for data in current_datas if self._safe_float(data.buy_signal[0]) > 0]
        prices = {data._name: self._safe_float(data.close[0]) for data in current_datas}
        held = [data._name for data in current_datas if self.getposition(data).size != 0]
        targets = build_equal_weight_target_sizes(
            eligible_codes=eligible,
            prices=prices,
            portfolio_value=float(self.broker.getvalue()),
            lot_size=int(self.p.lot_size),
            one_way_cost_rate=float(self.p.one_way_cost_rate),
            currently_held_codes=held,
        )
        data_by_code = {data._name: data for data in current_datas}
        changes: list[tuple[int, str, Any]] = []
        for code, target_size in targets.items():
            data = data_by_code.get(code)
            if data is None:
                continue
            delta = int(target_size) - int(self.getposition(data).size)
            if delta:
                changes.append((delta, code, data))
        changes.sort(key=lambda item: (item[0] >= 0, item[1]))
        for delta, code, data in changes:
            target_size = int(targets[code])
            order = self.order_target_size(data=data, target=target_size)
            if order is not None:
                self.order_meta[order.ref] = {
                    "signal": "MONTH_END_EQUAL_WEIGHT_REBALANCE",
                    "target_value": float(target_size * prices[code]),
                    "date": self._dt_str(data),
                }
        self.signal_log.append(
            {
                "date": current_date.isoformat(),
                "signal": "MONTH_END_EQUAL_WEIGHT_REBALANCE",
                "eligible_codes": eligible,
                "target_weight": 1.0 / len(eligible) if eligible else 0.0,
            }
        )

    def notify_order(self, order: Any) -> None:
        if order.status not in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            return
        meta = self.order_meta.get(order.ref, {})
        executed = order.executed
        execution_date = (
            bt.num2date(executed.dt).strftime("%Y-%m-%d")
            if executed.dt
            else self._dt_str(order.data)
        )
        self.order_log.append(
            {
                "date": execution_date,
                "signal_date": meta.get("date") or "",
                "code": order.data._name,
                "signal": meta.get("signal", ""),
                "status": order.getstatusname(),
                "side": "BUY" if order.isbuy() else "SELL",
                "created_size": float(order.created.size or 0.0),
                "executed_size": float(executed.size or 0.0),
                "executed_price": float(executed.price or 0.0),
                "executed_value": float(executed.value or 0.0),
                "commission": float(executed.comm or 0.0),
                "target_value": float(meta.get("target_value") or 0.0),
                "position_after": float(self.getposition(order.data).size),
                "cash_after": float(self.broker.getcash()),
                "portfolio_value_after": float(self.broker.getvalue()),
            }
        )

    def notify_trade(self, trade: Any) -> None:
        if trade.isclosed:
            self.trade_log.append(
                {
                    "code": trade.data._name,
                    "date_open": bt.num2date(trade.dtopen).strftime("%Y-%m-%d") if trade.dtopen else None,
                    "date_close": bt.num2date(trade.dtclose).strftime("%Y-%m-%d") if trade.dtclose else None,
                    "barlen": int(trade.barlen or 0),
                    "pnl": float(trade.pnl),
                    "pnlcomm": float(trade.pnlcomm),
                }
            )

    def notify_cashvalue(self, cash: float, value: float) -> None:
        if len(self) <= 0:
            return
        payload = {
            "date": bt.num2date(self.datetime[0]).strftime("%Y-%m-%d"),
            "cash_value": float(cash),
            "portfolio_value": float(value),
            "positions_value": float(value) - float(cash),
        }
        if self.daily_value_log and self.daily_value_log[-1]["date"] == payload["date"]:
            self.daily_value_log[-1].update(payload)
        else:
            self.daily_value_log.append(payload)


class ThsEqualWeightBuyHoldStrategy(bt.Strategy):
    def __init__(self) -> None:
        self.daily_value_log: list[dict[str, Any]] = []
        self._initialized = False

    def nextstart(self) -> None:
        if self._initialized or not self.datas:
            return
        investable = float(self.broker.getcash()) / (1.0 + ONE_WAY_COST_RATE)
        target = investable / len(self.datas)
        for data in self.datas:
            self.order_target_value(data=data, target=target)
        self._initialized = True

    def notify_cashvalue(self, cash: float, value: float) -> None:
        if len(self) <= 0:
            return
        payload = {
            "date": bt.num2date(self.datetime[0]).strftime("%Y-%m-%d"),
            "cash_value": float(cash),
            "portfolio_value": float(value),
            "positions_value": float(value) - float(cash),
        }
        if self.daily_value_log and self.daily_value_log[-1]["date"] == payload["date"]:
            self.daily_value_log[-1].update(payload)
        else:
            self.daily_value_log.append(payload)
