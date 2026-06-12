"""ZXW 组合规则（只为了检验因子策略）：前端强买/强卖，单票 2%，卖出信号无条件清仓。"""

from __future__ import annotations

from typing import Any

import backtrader as bt
import numpy as np
import pandas as pd

from models.zxw_rule_backtest.zxw_view_results_full import COMMISSION
from models.zxw_factor_check_only.strategy_params import (
    DEFAULT_CASH_RATIO_GATE,
    DEFAULT_MAX_WEIGHT,
)


class FactorCheckZxwStrategy(bt.Strategy):
    """
    - 首日：回溯建仓（strong_buy_signal；信号日至 start 前无 strong_sell_signal），单票 2%。
    - 强卖：strong_sell_signal≥1 → 无条件清仓。
    - 强买：strong_buy_signal≥1 → 尽量买到 2%（满 2% 不买）；block_halving_future_buy 禁买。
    - 卖完且当日强买处理完后，若现金/总资产仍 ≥10%：
      - 有持仓 → 剩余现金等额分给持仓（可突破 2%，仅受整股与佣金限制）；
      - 无持仓 → 保持空仓。
    - 现金 <10% 时不做等额补仓，仅按强买信号买到 2%。
    """

    params = dict(
        max_weight=DEFAULT_MAX_WEIGHT,
        cash_ratio_gate=DEFAULT_CASH_RATIO_GATE,
        backtest_start="1900-01-01",
        initial_target_weight_by_code=None,
    )

    def __init__(self) -> None:
        self.order_meta: dict[Any, dict[str, Any]] = {}
        self.order_log: list[dict[str, Any]] = []
        self.trade_log: list[dict[str, Any]] = []
        self.position_log: list[dict[str, Any]] = []
        self._position_log_seen: set[tuple[str, str]] = set()
        self.daily_value_log: list[dict[str, Any]] = []
        raw_init = self.p.initial_target_weight_by_code
        self._init_w: dict[str, float] = (
            {str(k).strip().upper(): float(v) for k, v in raw_init.items()}
            if isinstance(raw_init, dict)
            else {}
        )
        self._init_deployed = False
        self._bar_planned_buy_value: dict[str, float] = {}

    def _dt_str(self, data: Any) -> str:
        return bt.num2date(data.datetime[0]).strftime("%Y-%m-%d")

    def _line_value(self, data: Any, line_name: str) -> float:
        try:
            ln = getattr(data.lines, line_name, None)
            if ln is None:
                return 0.0
            value = float(ln[0])
            return value if np.isfinite(value) else 0.0
        except Exception:
            return 0.0

    def _strong_buy_hit(self, data: Any) -> bool:
        return self._line_value(data, "strong_buy_signal") >= 1.0

    def _strong_sell_hit(self, data: Any) -> bool:
        return self._line_value(data, "strong_sell_signal") >= 1.0

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

    def _max_position_value_cap(self, data: Any) -> float:
        total_value = float(self.broker.getvalue())
        if total_value <= 0:
            return 0.0
        return total_value * float(self.p.max_weight)

    def _current_position_value(self, data: Any) -> float:
        close_px = float(data.close[0])
        if not np.isfinite(close_px) or close_px <= 0:
            return 0.0
        return float(self.getposition(data).size) * close_px

    def _code_key(self, data: Any) -> str:
        return str(data._name).strip().upper()

    def _reset_bar_planned_buys(self) -> None:
        self._bar_planned_buy_value.clear()

    def _planned_buy_value(self, data: Any) -> float:
        return float(self._bar_planned_buy_value.get(self._code_key(data), 0.0))

    def _add_planned_buy(self, data: Any, delta_value: float) -> None:
        if delta_value <= 1e-6:
            return
        key = self._code_key(data)
        self._bar_planned_buy_value[key] = self._planned_buy_value(data) + float(delta_value)

    def _effective_position_value(self, data: Any) -> float:
        return self._current_position_value(data) + self._planned_buy_value(data)

    def _position_room_value(self, data: Any) -> float:
        return self._max_position_value_cap(data) - self._effective_position_value(data)

    def _is_at_position_cap(self, data: Any) -> bool:
        return self._position_room_value(data) <= 1e-6

    def _estimated_post_normal_cash(self, sorted_ds: list[Any]) -> float:
        cash = float(self.broker.getcash())
        for d in sorted_ds:
            if not self._strong_sell_hit(d):
                continue
            pos = self.getposition(d)
            if pos.size <= 0:
                continue
            close_px = float(d.close[0])
            if not np.isfinite(close_px) or close_px <= 0:
                continue
            cash += float(pos.size) * close_px * (1.0 - COMMISSION)
        planned_spend = sum(self._bar_planned_buy_value.values())
        return max(0.0, cash - planned_spend)

    def _submit_order_target_value(self, data: Any, target_value: float, signal: str) -> None:
        cap = self._max_position_value_cap(data)
        if cap <= 0:
            return
        target_value = min(float(target_value), cap)
        if target_value < 0:
            return
        effective = self._effective_position_value(data)
        if effective >= cap - 1e-6 or target_value <= effective + 1e-6:
            return
        order = self.order_target_value(data=data, target=target_value)
        if order is not None:
            self._add_planned_buy(data, target_value - effective)
            self.order_meta[order.ref] = {
                "signal": signal,
                "target_value": float(target_value),
                "date": self._dt_str(data),
            }

    def _submit_buy_value_no_cap(self, data: Any, buy_value: float, signal: str) -> None:
        close_px = float(data.close[0])
        if not np.isfinite(close_px) or close_px <= 0 or buy_value <= 1e-6:
            return
        shares = int(buy_value / (close_px * (1.0 + COMMISSION)))
        if shares <= 0:
            return
        filled_value = float(shares * close_px)
        order = self.buy(data=data, size=shares)
        if order is not None:
            self._add_planned_buy(data, filled_value)
            self.order_meta[order.ref] = {
                "signal": signal,
                "target_value": filled_value,
                "date": self._dt_str(data),
            }

    def _distribute_cash_equal_emergency(
        self,
        held: list[Any],
        cash: float,
        signal: str,
    ) -> None:
        if not held or cash <= 1e-6:
            return
        per = float(cash) / len(held)
        for d in held:
            self._submit_buy_value_no_cap(d, per, signal)

    def _submit_sell_signal_close(self, data: Any) -> None:
        pos = self.getposition(data)
        if pos.size <= 0:
            return
        order = self.close(data=data)
        if order is not None:
            self.order_meta[order.ref] = {
                "signal": "FACTOR_CHECK_SELL_SIGNAL_FULL_CLOSE",
                "target_value": 0.0,
                "date": self._dt_str(data),
            }

    def _backtest_start_date(self) -> pd.Timestamp:
        return pd.Timestamp(str(self.p.backtest_start)).normalize()

    def _before_backtest_window(self) -> bool:
        if not self.datas:
            return True
        cur = pd.Timestamp(bt.num2date(self.datas[0].datetime[0]).date())
        return cur.normalize() < self._backtest_start_date()

    def _has_live_bar(self, data: Any) -> bool:
        try:
            if len(data) <= 0:
                return False
            dt0 = bt.num2date(data.datetime[0])
            if dt0 is None:
                return False
            close_px = float(data.close[0])
            return np.isfinite(close_px) and close_px > 0
        except Exception:
            return False

    def _active_datas(self) -> list[Any]:
        return [d for d in sorted(self.datas, key=lambda x: str(x._name)) if self._has_live_bar(d)]

    def _collect_strong_buy_signals(self, sorted_ds: list[Any]) -> list[Any]:
        signals: list[Any] = []
        for d in sorted_ds:
            close_px = float(d.close[0])
            if not np.isfinite(close_px) or close_px <= 0:
                continue
            if self._line_value(d, "block_halving_future_buy") >= 1.0:
                continue
            if self._strong_buy_hit(d):
                signals.append(d)
        return signals

    def _held_for_emergency(self, sorted_ds: list[Any]) -> list[Any]:
        held: list[Any] = []
        for d in sorted_ds:
            if self._strong_sell_hit(d):
                continue
            if self.getposition(d).size > 0 or self._planned_buy_value(d) > 1e-6:
                held.append(d)
        return held

    def _run_bar(self) -> None:
        if self._before_backtest_window():
            return

        total_value = float(self.broker.getvalue())
        if total_value <= 0:
            return

        sorted_ds = self._active_datas()
        if not sorted_ds:
            return

        for d in sorted_ds:
            self._record_position_snapshot(d)

        for d in sorted_ds:
            close_px = float(d.close[0])
            if not np.isfinite(close_px) or close_px <= 0:
                continue
            if self.getposition(d).size <= 0:
                continue
            if self._strong_sell_hit(d):
                self._submit_sell_signal_close(d)

        total_value = float(self.broker.getvalue())
        if total_value <= 0:
            return

        self._reset_bar_planned_buys()

        if not self._init_deployed:
            if self._init_w:
                for d in sorted_ds:
                    code = str(d._name)
                    w = float(self._init_w.get(code, 0.0) or 0.0)
                    if w > 0:
                        self._submit_order_target_value(
                            d, total_value * w, "INIT_BACKSCAN_TARGET_WEIGHT"
                        )
            self._init_deployed = True

        signals = self._collect_strong_buy_signals(sorted_ds)
        target_w = float(self.p.max_weight)
        for d in signals:
            if self._is_at_position_cap(d):
                continue
            self._submit_order_target_value(
                d,
                total_value * target_w,
                "FACTOR_CHECK_STRONG_BUY_TARGET_WEIGHT",
            )

        est_cash = self._estimated_post_normal_cash(sorted_ds)
        est_cash_ratio = est_cash / total_value if total_value > 0 else 0.0
        cash_gate = float(self.p.cash_ratio_gate)
        if est_cash_ratio <= cash_gate + 1e-9:
            return

        held = self._held_for_emergency(sorted_ds)
        if not held:
            return

        self._distribute_cash_equal_emergency(
            held,
            est_cash,
            "FACTOR_CHECK_CASH_EMERGENCY_EQUAL",
        )

    def prenext(self) -> None:
        self._run_bar()

    def next(self) -> None:
        self._run_bar()

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
