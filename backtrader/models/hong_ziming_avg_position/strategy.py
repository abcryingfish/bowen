"""
洪梓铭平均仓位模型（前端回测专用）

规则摘要：
- 起始空仓。
- 单票市值上限 cap = 总资产 / 50（与股票池数量无关）；每次加仓 increment = 总资产 / 100（即 cap 的一半），
  买到 cap 为止，加仓后市值不得超过 cap。
- 总买入信号 >=1 时可买；执行买入后进入 2 个交易日冷静期（该标的不再买）；**每次买点成交后**重置该标的卖点计数。
- 卖出条件：(sell_combo>=1) 或 (rsi_sell_combo>=1)。**连续交易日**出现卖点：第 1 日卖当前仓约 **50%**；若第 2 日仍连续有卖点则 **清仓**。
  非卖点日则重置连续计数。卖点与买点逻辑独立，先处理卖再处理买。
- 止损：有仓时若收盘价 < 持仓均价×0.8（低于成本约 20%），该股清仓。
- 基准策略仍由 run_zxw_backtest 外挂 BuyAndHold（与 ZXW 管线一致）。
"""

from __future__ import annotations

from typing import Any

import backtrader as bt
import numpy as np

COMMISSION = 0.0003


class HongZimingAvgPositionStrategy(bt.Strategy):
    """洪梓铭平均仓位模型：买点/冷静期/单票上限；卖点连续两日先减半再清仓；跌破成本约 20% 清仓。"""

    def __init__(self) -> None:
        self.order_meta: dict[Any, dict[str, Any]] = {}
        self.signal_log: list[dict[str, Any]] = []
        self.order_log: list[dict[str, Any]] = []
        self.trade_log: list[dict[str, Any]] = []
        self.position_log: list[dict[str, Any]] = []
        self._position_log_seen: set[tuple[str, str]] = set()
        self.daily_value_log: list[dict[str, Any]] = []

        self._sell_streak: dict[str, int] = {}
        self._last_buy_exec_bar: dict[str, int] = {}

    def _dt_str(self, data: Any) -> str:
        return bt.num2date(data.datetime[0]).strftime("%Y-%m-%d")

    @staticmethod
    def _line_value(data: Any, line_name: str) -> float:
        value = float(getattr(data, line_name)[0])
        return value if np.isfinite(value) else 0.0

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
                "position_size": pos.size,
                "position_price": float(pos.price),
                "close": close_px,
                "market_value": market_value,
                "unrealized_pnl": market_value - cost_basis,
            }
        )

    def _submit_buy_shares(self, data: Any, shares: int, signal: str) -> bool:
        if shares <= 0:
            return False
        order = self.buy(data=data, size=shares)
        if order is not None:
            close_px = float(data.close[0])
            self.order_meta[order.ref] = {
                "signal": signal,
                "target_value": float(shares * close_px),
                "date": self._dt_str(data),
            }
            return True
        return False

    def next(self) -> None:
        v0 = float(self.broker.getvalue())
        if v0 <= 0:
            return

        bar_ix = len(self) - 1
        cap = v0 / 50.0
        increment = v0 / 100.0

        sorted_ds = sorted(self.datas, key=lambda x: str(x._name))

        for d in sorted_ds:
            self._record_position_snapshot(d)
            close_px = float(d.close[0])
            code = str(d._name)
            if not np.isfinite(close_px) or close_px <= 0:
                continue

            pos = self.getposition(d)
            if pos.size > 0 and float(pos.price) > 0:
                cost = float(pos.price)
                if close_px < cost * 0.8:
                    order = self.close(data=d)
                    if order is not None:
                        self.order_meta[order.ref] = {
                            "signal": "HONG_STOP_LOSS_CLOSE_LT_80PCT_AVG_COST",
                            "target_value": 0.0,
                            "date": self._dt_str(d),
                        }
                    self._sell_streak.pop(code, None)
                    self._last_buy_exec_bar.pop(code, None)
                    continue

            sc = self._line_value(d, "sell_combo_signal")
            rc = self._line_value(d, "rsi_sell_combo")
            raw_sell = sc >= 1.0 or rc >= 1.0

            if pos.size <= 0:
                self._sell_streak[code] = 0
            elif raw_sell:
                streak = int(self._sell_streak.get(code, 0)) + 1
                self._sell_streak[code] = streak
                if streak >= 2:
                    order = self.close(data=d)
                    if order is not None:
                        self.order_meta[order.ref] = {
                            "signal": "HONG_SELL_CONSEC_DAY2_FULL_CLOSE_OR",
                            "target_value": 0.0,
                            "date": self._dt_str(d),
                        }
                    self._sell_streak[code] = 0
                else:
                    sell_sz = int(abs(pos.size) * 0.5)
                    if sell_sz < 1 and abs(pos.size) >= 1:
                        sell_sz = 1
                    if sell_sz > 0:
                        order = self.sell(data=d, size=sell_sz)
                        if order is not None:
                            self.order_meta[order.ref] = {
                                "signal": "HONG_SELL_CONSEC_DAY1_HALF_POSITION_OR",
                                "target_value": float(sell_sz * close_px),
                                "date": self._dt_str(d),
                            }
            else:
                self._sell_streak[code] = 0

            tbs = self._line_value(d, "total_buy_signal")
            raw_buy = tbs >= 1.0
            if not raw_buy:
                continue

            last_b = self._last_buy_exec_bar.get(code)
            if last_b is not None and (bar_ix - last_b) <= 2:
                continue

            pos2 = self.getposition(d)
            pos_mv2 = float(pos2.size) * close_px if pos2.size else 0.0
            room = cap - pos_mv2
            if room <= 1e-6:
                continue

            buy_cash_budget = min(increment, room, float(self.broker.getcash()) / (1.0 + COMMISSION))
            if buy_cash_budget <= 0:
                continue
            shares = int(buy_cash_budget / (close_px * (1.0 + COMMISSION)))
            if shares <= 0:
                continue
            if self._submit_buy_shares(d, shares, "HONG_BUY_INCREMENT_HALF_CAP_TOTAL_BUY_SIGNAL"):
                self._last_buy_exec_bar[code] = bar_ix
                self._sell_streak[code] = 0

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

    def notify_order(self, order: Any) -> None:
        if order.status not in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            return
        data = order.data
        meta = self.order_meta.get(order.ref, {})
        executed = order.executed
        self.order_log.append(
            {
                "date": meta.get("date") or self._dt_str(data),
                "code": data._name,
                "signal": meta.get("signal", ""),
                "status": order.getstatusname(),
                "side": "BUY" if order.isbuy() else "SELL",
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
