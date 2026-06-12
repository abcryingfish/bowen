"""ZXW 组合规则（只采用强点交易策略）：总买入信号强买 + 可配置止损/止盈 + 回溯首日建仓。"""



from __future__ import annotations



from typing import Any



import backtrader as bt

import numpy as np

import pandas as pd



from models.zxw_rule_backtest.zxw_view_results_full import COMMISSION

from models.zxw_strong_adjusted_only.strategy_params import (

    DEFAULT_INVESTED_GATE,

    DEFAULT_MAX_WEIGHT,

    DEFAULT_PROFIT_TIERS,

    DEFAULT_STOP_LOSS_COST_MULTIPLIER,

    ProfitTier,

    profit_tiers_from_bt_param,

)





class StrongAdjustedZxwStrategy(bt.Strategy):

    """

    - 首日：runner 预计算 initial_target_weight_by_code（回溯 strong_buy_signal，信号日至 start 前无 strong_sell_signal）。

    - 止损：收盘价 < 持仓均价 × stop_loss_cost_multiplier → 预挂；宽表 total_sell_signal≥1 时清仓。

    - 止盈：浮盈超过档位阈值 → 预挂该档；profit_sell_line（默认 strong_sell_signal，前端卖出因子合成）≥1 时减仓/清仓。

    - 强买：strong_buy_signal≥1（前端买入因子合成）；单票目标市值不超过总市值×max_weight（默认 5%）；

      已满 5% 不再加仓；同日先 order_target 补至上限，inv_gate 不足时仅分现金（不再重复 target）；

      同 bar 内 _bar_planned_buy_value 计入待发单市值，避免 target 与分现金叠仓超 5%。

    """



    params = dict(

        max_weight=DEFAULT_MAX_WEIGHT,

        stop_loss_cost_multiplier=DEFAULT_STOP_LOSS_COST_MULTIPLIER,

        invested_gate=DEFAULT_INVESTED_GATE,

        drawdown_add_weight=0.025,

        profit_tiers=(),

        backtest_start="1900-01-01",

        initial_target_weight_by_code=None,

        profit_sell_line="strong_sell_signal",

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

            {str(k).strip().upper(): float(v) for k, v in raw_init.items()} if isinstance(raw_init, dict) else {}

        )

        self._init_deployed = False

        self._eod_invested_ratio: float | None = None

        self._stop_loss_pending: set[str] = set()

        self._original_position_size: dict[str, int] = {}

        self._profit_tier_done: dict[str, set[str]] = {}

        self._profit_tier_armed: dict[str, set[str]] = {}

        self._profit_tiers: tuple[ProfitTier, ...] = profit_tiers_from_bt_param(self.p.profit_tiers)

        if not self._profit_tiers:

            self._profit_tiers = DEFAULT_PROFIT_TIERS

        self._bar_planned_buy_value: dict[str, float] = {}



    def _clear_code_state(self, code: str) -> None:

        self._stop_loss_pending.discard(code)

        self._original_position_size.pop(code, None)

        self._profit_tier_done.pop(code, None)

        self._profit_tier_armed.pop(code, None)



    def _arm_profit_tier(self, code: str, tier_id: str) -> None:

        self._profit_tier_armed.setdefault(code, set()).add(tier_id)



    def _armed_profit_tiers(self, code: str) -> set[str]:

        return self._profit_tier_armed.get(code, set())



    def _ensure_original_size(self, code: str, pos_size: int) -> None:

        if code not in self._original_position_size and pos_size > 0:

            self._original_position_size[code] = int(abs(pos_size))



    def _tier_done(self, code: str, tier_id: str) -> bool:

        return tier_id in self._profit_tier_done.get(code, set())



    def _mark_tier_done(self, code: str, tier_id: str) -> None:

        self._profit_tier_done.setdefault(code, set()).add(tier_id)



    def _sorted_profit_tiers(self) -> list[ProfitTier]:

        return sorted(

            self._profit_tiers,

            key=lambda t: (-t.threshold, -t.sell_ratio_of_original),

        )



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
        if self._line_value(data, "strong_buy_signal") >= 1.0:
            return True
        return self._line_value(data, "total_buy_signal") >= 1.0

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

    def _datas_with_position_room(self, datas: list[Any]) -> list[Any]:
        return [d for d in datas if not self._is_at_position_cap(d)]

    def _distribute_cash_to_datas_with_room(
        self,
        datas: list[Any],
        cash: float,
        signal: str,
    ) -> None:
        eligible = self._datas_with_position_room(datas)
        if not eligible or cash <= 1e-6:
            return
        per = float(cash) * 0.99 / len(eligible)
        for d in eligible:
            self._submit_buy_value(d, per, signal)

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



    def _submit_buy_value(self, data: Any, buy_value: float, signal: str) -> None:

        close_px = float(data.close[0])

        if not np.isfinite(close_px) or close_px <= 0 or buy_value <= 0:

            return

        if self._is_at_position_cap(data):
            return
        room = self._position_room_value(data)
        buy_value = min(float(buy_value), room)
        if buy_value <= 1e-6:
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



    def _submit_profit_tier_sell(

        self,

        data: Any,

        *,

        code: str,

        pos_size: int,

        close_px: float,

        tier: ProfitTier,

    ) -> bool:

        orig = self._original_position_size.get(code, int(abs(pos_size)))

        if tier.sell_ratio_of_original >= 1.0 - 1e-12:

            sell_size = int(abs(pos_size))

            if sell_size <= 0:

                return False

            order = self.close(data=data)

            signal = tier.signal_name()

        else:

            sell_size = min(int(abs(pos_size)), int(orig * tier.sell_ratio_of_original))

            if sell_size <= 0:

                return False

            order = self.sell(data=data, size=sell_size)

            signal = tier.signal_name()

        if order is not None:

            self._mark_tier_done(code, tier.tier_id)

            remaining = max(0, int(abs(pos_size)) - sell_size)

            self.order_meta[order.ref] = {

                "signal": signal,

                "target_value": float(remaining * close_px),

                "date": self._dt_str(data),

            }

            return True

        return False



    def _backtest_start_date(self) -> pd.Timestamp:

        return pd.Timestamp(str(self.p.backtest_start)).normalize()



    def _before_backtest_window(self) -> bool:

        if not self.datas:

            return True

        cur = pd.Timestamp(bt.num2date(self.datas[0].datetime[0]).date())

        return cur.normalize() < self._backtest_start_date()



    def next(self) -> None:

        if self._before_backtest_window():

            return



        total_value = float(self.broker.getvalue())

        if total_value <= 0:

            return



        sorted_ds = sorted(self.datas, key=lambda x: str(x._name))



        for d in sorted_ds:

            if self.getposition(d).size <= 0:

                self._clear_code_state(str(d._name))



        v0 = total_value

        inv0 = 0.0

        for d in sorted_ds:

            pos = self.getposition(d)

            cx = float(d.close[0])

            if pos.size > 0 and np.isfinite(cx):

                inv0 += pos.size * cx

        inv_ratio_start = inv0 / v0 if v0 > 0 else 0.0



        if not self._init_deployed:

            if self._init_w:

                for d in sorted_ds:

                    code = str(d._name)

                    w = float(self._init_w.get(code, 0.0) or 0.0)

                    if w > 0:

                        self._submit_order_target_value(d, v0 * w, "INIT_BACKSCAN_TARGET_WEIGHT")

            self._init_deployed = True



        for d in sorted_ds:

            self._record_position_snapshot(d)



        for d in sorted_ds:

            pos = self.getposition(d)

            close_px = float(d.close[0])

            code = str(d._name)

            if not np.isfinite(close_px) or close_px <= 0:

                continue



            if pos.size <= 0 or float(pos.price) <= 0:

                continue



            self._ensure_original_size(code, int(pos.size))

            cost = float(pos.price)

            profit_ratio = close_px / cost - 1.0

            stop_price = cost * float(self.p.stop_loss_cost_multiplier)



            if close_px < stop_price:

                self._stop_loss_pending.add(code)



            for tier in self._sorted_profit_tiers():

                if self._tier_done(code, tier.tier_id):

                    continue

                if profit_ratio > tier.threshold:

                    self._arm_profit_tier(code, tier.tier_id)



            stop_tss = self._line_value(d, "total_sell_signal")

            if code in self._stop_loss_pending and stop_tss >= 1.0:

                order = self.close(data=d)

                if order is not None:

                    self._stop_loss_pending.discard(code)

                    self.order_meta[order.ref] = {

                        "signal": "STOP_LOSS_ON_TOTAL_SELL_SIGNAL",

                        "target_value": 0.0,

                        "date": self._dt_str(d),

                    }

                continue



            profit_tss = self._line_value(d, str(self.p.profit_sell_line or "strong_sell_signal"))

            if profit_tss >= 1.0:

                armed = self._armed_profit_tiers(code)

                for tier in self._sorted_profit_tiers():

                    if tier.tier_id not in armed:

                        continue

                    if self._tier_done(code, tier.tier_id):

                        continue

                    if self._submit_profit_tier_sell(

                        d,

                        code=code,

                        pos_size=int(pos.size),

                        close_px=close_px,

                        tier=tier,

                    ):

                        armed.discard(tier.tier_id)

                        break



        total_value = float(self.broker.getvalue())

        if total_value <= 0:

            return



        inv_gate = self._eod_invested_ratio if self._eod_invested_ratio is not None else inv_ratio_start

        gate = float(self.p.invested_gate)



        signals: list[Any] = []

        for d in sorted_ds:

            close_px = float(d.close[0])

            if not np.isfinite(close_px) or close_px <= 0:

                continue

            if self._line_value(d, "block_halving_future_buy") >= 1.0:

                continue

            if self._strong_buy_hit(d):

                signals.append(d)



        if not signals:

            return



        self._reset_bar_planned_buys()



        target_w = float(self.p.max_weight)

        for d in signals:

            if self._is_at_position_cap(d):

                continue

            target_value = total_value * target_w

            self._submit_order_target_value(d, target_value, "STRONG_ADJUSTED_PHASE1_TARGET_WEIGHT")



        if inv_gate < gate - 1e-9 and signals:

            cash = float(self.broker.getcash())
            self._distribute_cash_to_datas_with_room(
                signals,
                cash,
                "STRONG_ADJUSTED_PHASE2_EXC_FILL_LT80INV",
            )



        if inv_gate < gate - 1e-9:

            cash2 = float(self.broker.getcash())
            held = [x for x in sorted_ds if self.getposition(x).size > 0]
            self._distribute_cash_to_datas_with_room(
                held,
                cash2,
                "STRONG_ADJUSTED_PHASE3_HELD_REBALANCE",
            )



    def notify_cashvalue(self, cash: float, value: float) -> None:

        if len(self) <= 0:

            return

        if value > 0:

            self._eod_invested_ratio = float(value - cash) / float(value)

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

