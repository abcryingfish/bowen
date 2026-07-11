"""因子检验（双假设 + 卖出阈值）：成本 150% 半仓、200% 清仓。"""

from __future__ import annotations

from typing import Any

import numpy as np

from models.zxw_factor_check_profit_threshold_dual_assumption.daily_move_guard import (
    FactorCheckDailyMoveGuardStrategy,
)

DEFAULT_HALF_PROFIT_MULTIPLIER = 1.5
DEFAULT_FULL_PROFIT_MULTIPLIER = 2.0


class FactorCheckProfitThresholdDualAssumptionZxwStrategy(FactorCheckDailyMoveGuardStrategy):
    """
    在双假设因子检验基础上增加卖出阈值：
    - 收盘价 > 持仓均价 * 2.0：清仓，并允许下一轮买入。
    - 持仓均价 * 1.5 < 收盘价 < 持仓均价 * 2.0：卖出约一半；该票未清仓前不再买入。
    """

    params = dict(
        daily_move_limit=0.098,
        half_profit_multiplier=DEFAULT_HALF_PROFIT_MULTIPLIER,
        full_profit_multiplier=DEFAULT_FULL_PROFIT_MULTIPLIER,
    )

    def __init__(self) -> None:
        super().__init__()
        self._half_profit_sold_codes: set[str] = set()
        self._buy_locked_after_partial_sell: set[str] = set()

    def _refresh_threshold_state(self, data: Any) -> None:
        code = self._code_key(data)
        if self.getposition(data).size <= 0:
            self._half_profit_sold_codes.discard(code)
            self._buy_locked_after_partial_sell.discard(code)

    def _is_buy_locked_after_partial_sell(self, data: Any) -> bool:
        self._refresh_threshold_state(data)
        return self._code_key(data) in self._buy_locked_after_partial_sell

    def _collect_strong_buy_signals(self, sorted_ds: list[Any]) -> list[Any]:
        return [
            d
            for d in super()._collect_strong_buy_signals(sorted_ds)
            if not self._is_buy_locked_after_partial_sell(d)
        ]

    def _held_for_emergency(self, sorted_ds: list[Any]) -> list[Any]:
        held: list[Any] = []
        for d in sorted_ds:
            if self._is_buy_locked_after_partial_sell(d):
                continue
            if self.getposition(d).size > 0 or self._planned_buy_value(d) > 1e-6:
                held.append(d)
        return held

    def _estimated_post_normal_cash(self, sorted_ds: list[Any]) -> float:
        del sorted_ds
        planned_spend = sum(self._bar_planned_buy_value.values())
        return max(0.0, float(self.broker.getcash()) - planned_spend)

    def _profit_multiple(self, data: Any) -> float:
        pos = self.getposition(data)
        cost = float(pos.price)
        close_px = float(data.close[0])
        if pos.size <= 0 or not np.isfinite(close_px) or not np.isfinite(cost) or cost <= 0:
            return 0.0
        return close_px / cost

    def _submit_profit_threshold_sell(self, data: Any) -> bool:
        self._refresh_threshold_state(data)
        pos = self.getposition(data)
        if pos.size <= 0 or not self._can_trade_today(data):
            return False

        code = self._code_key(data)
        multiple = self._profit_multiple(data)
        full_line = float(self.p.full_profit_multiplier)
        half_line = float(self.p.half_profit_multiplier)

        if multiple > full_line:
            order = self.close(data=data)
            if order is not None:
                self._buy_locked_after_partial_sell.add(code)
                self.order_meta[order.ref] = {
                    "signal": "PROFIT_GT_200_FULL_CLOSE_UNLOCK_BUY",
                    "target_value": 0.0,
                    "date": self._dt_str(data),
                }
                return True
            return False

        if half_line < multiple < full_line and code not in self._half_profit_sold_codes:
            sell_size = max(1, int(abs(float(pos.size)) / 2.0))
            if sell_size <= 0:
                return False
            order = self.sell(data=data, size=sell_size)
            if order is not None:
                self._half_profit_sold_codes.add(code)
                self._buy_locked_after_partial_sell.add(code)
                close_px = float(data.close[0])
                self.order_meta[order.ref] = {
                    "signal": "PROFIT_GT_150_SELL_HALF_LOCK_BUY",
                    "target_value": max(0.0, (float(pos.size) - float(sell_size)) * close_px),
                    "date": self._dt_str(data),
                }
                return True
        return False

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

        threshold_sold_codes: set[str] = set()
        for d in sorted_ds:
            close_px = float(d.close[0])
            if not np.isfinite(close_px) or close_px <= 0:
                continue
            if self.getposition(d).size <= 0:
                self._refresh_threshold_state(d)
                continue
            if self._submit_profit_threshold_sell(d):
                threshold_sold_codes.add(self._code_key(d))

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
