from __future__ import annotations

from typing import Any

import backtrader as bt
import numpy as np
import pandas as pd

from .data import BACKTEST_COMMISSION_RATE


class ConfigurableSignalStrategy(bt.Strategy):
    params = dict(
        max_weight=0.05,
        drawdown_add_weight=0.025,
        lot_size=100,
    )

    def __init__(self) -> None:
        self.order_meta: dict[int, dict[str, Any]] = {}
        self.signal_log: list[dict[str, Any]] = []
        self.order_log: list[dict[str, Any]] = []
        self.trade_log: list[dict[str, Any]] = []
        self.position_log: list[dict[str, Any]] = []
        self._position_log_seen: set[tuple[str, str]] = set()
        self.daily_value_log: list[dict[str, Any]] = []
        self._commission: float = float(BACKTEST_COMMISSION_RATE)
        self._initialized = False
        self._drawdown_20_added: set[str] = set()
        self._drawdown_30_added: set[str] = set()
        self._blocked_after_one_year_drop: set[str] = set()
        self._first_entry_date: dict[str, pd.Timestamp] = {}
        self._first_entry_price: dict[str, float] = {}

    def _dt_str(self, data: Any) -> str:
        return bt.num2date(data.datetime[0]).strftime("%Y-%m-%d")

    def _current_dt(self, data: Any) -> pd.Timestamp:
        return pd.Timestamp(bt.num2date(data.datetime[0])).normalize()

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if np.isfinite(parsed) else default

    def _record_position_snapshot(self, data: Any) -> None:
        dt_str = self._dt_str(data)
        key = (dt_str, data._name)
        if key in self._position_log_seen:
            return
        self._position_log_seen.add(key)
        pos = self.getposition(data)
        close_px = float(data.close[0])
        market_value = pos.size * close_px
        cost_basis = pos.size * float(pos.price)
        self.position_log.append(
            {
                "date": dt_str,
                "code": data._name,
                "position_size": float(pos.size),
                "position_price": float(pos.price),
                "close": close_px,
                "market_value": market_value,
                "unrealized_pnl": market_value - cost_basis,
            }
        )

    def _submit_equal_weight_buys(self, buy_datas: list[Any], cash_budget: float, signal_name: str, dt_str: str) -> None:
        comm = float(BACKTEST_COMMISSION_RATE)
        if not buy_datas or cash_budget <= 0:
            return
        per_stock_cash = cash_budget / len(buy_datas)
        if per_stock_cash <= 0:
            return
        lot_size = int(max(1, self.p.lot_size))
        for data in buy_datas:
            close_px = self._safe_float(data.close[0], default=np.nan)
            if not np.isfinite(close_px) or close_px <= 0:
                continue
            shares = int(per_stock_cash / (close_px * (1.0 + comm)))
            shares = (shares // lot_size) * lot_size
            if shares < lot_size:
                continue
            order = self.buy(data=data, size=shares)
            if order is not None:
                self.order_meta[order.ref] = {
                    "signal": signal_name,
                    "target_value": float(shares * close_px),
                    "date": dt_str,
                }

    def _submit_buy_value(self, data: Any, buy_value: float, signal_name: str) -> None:
        comm = float(BACKTEST_COMMISSION_RATE)
        if buy_value <= 0:
            return
        close_px = self._safe_float(data.close[0], default=np.nan)
        if not np.isfinite(close_px) or close_px <= 0:
            return
        lot_size = int(max(1, self.p.lot_size))
        shares = int(buy_value / (close_px * (1.0 + comm)))
        shares = (shares // lot_size) * lot_size
        if shares < lot_size:
            return
        order = self.buy(data=data, size=shares)
        if order is not None:
            self.order_meta[order.ref] = {
                "signal": signal_name,
                "target_value": float(shares * close_px),
                "date": self._dt_str(data),
            }

    def _submit_target_value(self, data: Any, target_value: float, signal_name: str) -> None:
        if target_value < 0:
            return
        order = self.order_target_value(data=data, target=target_value)
        if order is not None:
            self.order_meta[order.ref] = {
                "signal": signal_name,
                "target_value": float(target_value),
                "date": self._dt_str(data),
            }

    def _update_one_year_drop_block(self, data: Any, close_px: float) -> None:
        code = data._name
        pos = self.getposition(data)
        if pos.size <= 0:
            return
        if code not in self._first_entry_date:
            self._first_entry_date[code] = self._current_dt(data)
            self._first_entry_price[code] = float(pos.price) if pos.price else close_px
        entry_date = self._first_entry_date.get(code)
        entry_price = self._first_entry_price.get(code, 0.0)
        if entry_date is None or entry_price <= 0:
            return
        if self._current_dt(data) >= entry_date + pd.Timedelta(days=365) and close_px <= entry_price * 0.5:
            self._blocked_after_one_year_drop.add(code)

    def nextstart(self) -> None:
        if self._initialized:
            return
        dt_str = bt.num2date(self.datetime[0]).strftime("%Y-%m-%d")
        valid_datas = [d for d in self.datas if len(d) > 0 and np.isfinite(float(d.close[0])) and float(d.close[0]) > 0]
        if not valid_datas:
            return
        self._submit_equal_weight_buys(
            buy_datas=valid_datas,
            cash_budget=float(self.broker.getcash()),
            signal_name="INIT_EQUAL_WEIGHT_100PCT",
            dt_str=dt_str,
        )
        self._initialized = True

    def next(self) -> None:
        total_value = float(self.broker.getvalue())
        if not self._initialized:
            return

        for data in self.datas:
            self._record_position_snapshot(data)
            pos = self.getposition(data)
            close_px = float(data.close[0])
            if not np.isfinite(close_px) or close_px <= 0 or total_value <= 0:
                continue

            sell_signal = self._safe_float(data.sell_signal[0], default=0.0)
            buy_signal = self._safe_float(data.buy_signal[0], default=0.0)
            adjusted_buy_signal = self._safe_float(data.mac_total[0], default=0.0)
            code = data._name
            self._update_one_year_drop_block(data, close_px)

            if pos.size > 0 and float(pos.price) > 0:
                profit_ratio = (close_px / float(pos.price) - 1.0) if float(pos.price) > 0 else 0.0
                if sell_signal > 0 and profit_ratio > 0.5:
                    order = self.close(data=data)
                    if order is not None:
                        self.order_meta[order.ref] = {
                            "signal": "FULL_SELL_PROFIT_GT_50_AND_LOCKED_SELL_FACTORS",
                            "target_value": 0.0,
                            "date": self._dt_str(data),
                        }
                    continue
                if sell_signal > 0 and profit_ratio > 0.3:
                    sell_size = int(abs(pos.size) * 0.5)
                    if sell_size > 0:
                        order = self.sell(data=data, size=sell_size)
                        if order is not None:
                            self.order_meta[order.ref] = {
                                "signal": "HALF_SELL_PROFIT_GT_30_AND_LOCKED_SELL_FACTORS",
                                "target_value": max((pos.size - sell_size) * close_px, 0.0),
                                "date": self._dt_str(data),
                            }
                    continue

                drawdown_ratio = close_px / float(pos.price) - 1.0
                if buy_signal > 0 and drawdown_ratio <= -0.3 and code not in self._drawdown_30_added:
                    self._submit_buy_value(data, total_value * self.p.drawdown_add_weight, "ADD_POSITION_DRAWDOWN_30_TOTAL_BUY_SIGNAL")
                    self._drawdown_30_added.add(code)
                    continue
                if buy_signal > 0 and drawdown_ratio <= -0.2 and code not in self._drawdown_20_added:
                    self._submit_buy_value(data, total_value * self.p.drawdown_add_weight, "ADD_POSITION_DRAWDOWN_20_TOTAL_BUY_SIGNAL")
                    self._drawdown_20_added.add(code)
                    continue

            if adjusted_buy_signal > 0 and code not in self._blocked_after_one_year_drop:
                current_value = pos.size * close_px
                target_value = total_value * self.p.max_weight
                if current_value < target_value:
                    self._submit_target_value(data, target_value, "BUY_TOTAL_BUY_SIGNAL_ADJUSTED_TARGET_5_PERCENT")

    def notify_order(self, order: Any) -> None:
        if order.status not in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            return
        data = order.data
        meta = self.order_meta.get(order.ref, {})
        side = "BUY" if order.isbuy() else "SELL"
        executed = order.executed
        self.order_log.append(
            {
                "date": meta.get("date") or self._dt_str(data),
                "code": data._name,
                "signal": meta.get("signal", ""),
                "status": order.getstatusname(),
                "side": side,
                "created_size": float(order.created.size or 0.0),
                "executed_size": float(executed.size or 0.0),
                "executed_price": float(executed.price or 0.0),
                "executed_value": float(executed.value or 0.0),
                "commission": float(executed.comm or 0.0),
                "target_value": float(meta.get("target_value") or 0.0),
                "position_after": float(self.getposition(data).size),
                "cash_after": float(self.broker.getcash()),
                "portfolio_value_after": float(self.broker.getvalue()),
            }
        )

    def notify_trade(self, trade: Any) -> None:
        if not trade.isclosed:
            return
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
        dt_str = bt.num2date(self.datetime[0]).strftime("%Y-%m-%d")
        payload = {
            "date": dt_str,
            "cash_value": float(cash),
            "portfolio_value": float(value),
            "positions_value": float(value) - float(cash),
        }
        if self.daily_value_log and self.daily_value_log[-1]["date"] == dt_str:
            self.daily_value_log[-1].update(payload)
        else:
            self.daily_value_log.append(payload)


class BuyAndHoldBenchmarkStrategy(bt.Strategy):
    def __init__(self) -> None:
        self.daily_value_log: list[dict[str, Any]] = []
        self._initialized = False
        self._commission: float = float(BACKTEST_COMMISSION_RATE)

    def nextstart(self) -> None:
        if self._initialized:
            return
        valid_datas = [d for d in self.datas if len(d) > 0 and np.isfinite(float(d.close[0])) and float(d.close[0]) > 0]
        if not valid_datas:
            return
        target_weight = 1.0 / len(valid_datas)
        investable_value = self.broker.getcash() / (1.0 + self._commission)
        for data in valid_datas:
            self.order_target_value(data=data, target=investable_value * target_weight)
        self._initialized = True

    def notify_cashvalue(self, cash: float, value: float) -> None:
        if len(self) <= 0:
            return
        dt_str = bt.num2date(self.datetime[0]).strftime("%Y-%m-%d")
        payload = {
            "date": dt_str,
            "cash_value": float(cash),
            "portfolio_value": float(value),
            "positions_value": float(value) - float(cash),
        }
        if self.daily_value_log and self.daily_value_log[-1]["date"] == dt_str:
            self.daily_value_log[-1].update(payload)
        else:
            self.daily_value_log.append(payload)
