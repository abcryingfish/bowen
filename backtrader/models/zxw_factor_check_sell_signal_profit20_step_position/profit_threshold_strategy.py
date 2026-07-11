"""因子检验（双假设 + 20% 盈利门槛 + 卖出信号阶梯减仓）。"""

from __future__ import annotations

from typing import Any

import numpy as np

from models.zxw_factor_check_sell_signal_profit20_step_position.daily_move_guard import (
    FactorCheckDailyMoveGuardStrategy,
)

DEFAULT_MIN_SELL_PROFIT_MULTIPLIER = 1.2
DEFAULT_HALF_PROFIT_MULTIPLIER = 1.5
DEFAULT_FULL_PROFIT_MULTIPLIER = 2.0


class FactorCheckSellSignalProfit20StepPositionZxwStrategy(FactorCheckDailyMoveGuardStrategy):
    """
    在双假设因子检验基础上增加 20% 盈利门槛和卖出信号阶梯减仓：
    - 当前盈利超过 20% 且 strong_sell_signal>=1 时，卖出信号才有效。
    - 有效卖出信号默认按本轮最大持股数的 10% 减仓，累计最多 30%。
    - 盈利超过 50% 且低于 100% 时，累计最多卖出 80%。
    - 盈利超过 100% 时，累计卖出先补到 80%；之后再按 10% 继续减仓。
    - 本轮最大持股数在完全清仓前保持为卖出基准。
    """

    params = dict(
        daily_move_limit=0.098,
        min_sell_profit_multiplier=DEFAULT_MIN_SELL_PROFIT_MULTIPLIER,
        half_profit_multiplier=DEFAULT_HALF_PROFIT_MULTIPLIER,
        full_profit_multiplier=DEFAULT_FULL_PROFIT_MULTIPLIER,
    )

    def __init__(self) -> None:
        super().__init__()
        self._position_base_size_by_code: dict[str, float] = {}
        self._sold_from_base_size_by_code: dict[str, float] = {}
        self._buy_locked_after_partial_sell: set[str] = set()

    def _refresh_threshold_state(self, data: Any) -> None:
        code = self._code_key(data)
        pos_size = float(self.getposition(data).size)
        if pos_size <= 0:
            self._position_base_size_by_code.pop(code, None)
            self._sold_from_base_size_by_code.pop(code, None)
            self._buy_locked_after_partial_sell.discard(code)
            return
        cur_base = float(self._position_base_size_by_code.get(code, 0.0))
        if pos_size > cur_base:
            self._position_base_size_by_code[code] = pos_size

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

    def _target_sold_ratio_for_signal(self, data: Any) -> float:
        code = self._code_key(data)
        base_size = float(self._position_base_size_by_code.get(code, 0.0))
        if base_size <= 0:
            return 0.0
        sold_size = float(self._sold_from_base_size_by_code.get(code, 0.0))
        current_ratio = sold_size / base_size
        multiple = self._profit_multiple(data)
        full_line = float(self.p.full_profit_multiplier)
        half_line = float(self.p.half_profit_multiplier)

        if multiple > full_line:
            return min(1.0, max(0.8, current_ratio + 0.1))
        if multiple > half_line:
            return min(0.8, max(0.3, current_ratio + 0.1))
        return min(0.3, current_ratio + 0.1)

    def _submit_sell_signal_step_position(self, data: Any) -> bool:
        self._refresh_threshold_state(data)
        pos = self.getposition(data)
        if pos.size <= 0 or not self._strong_sell_hit(data) or not self._can_trade_today(data):
            return False
        if self._profit_multiple(data) <= float(self.p.min_sell_profit_multiplier):
            return False

        code = self._code_key(data)
        base_size = float(self._position_base_size_by_code.get(code, 0.0))
        if base_size <= 0:
            return False
        sold_size = float(self._sold_from_base_size_by_code.get(code, 0.0))
        target_sold_size = base_size * self._target_sold_ratio_for_signal(data)
        sell_size = int(round(target_sold_size - sold_size))
        if sell_size <= 0:
            return False
        sell_size = min(sell_size, int(abs(float(pos.size))))
        if sell_size <= 0:
            return False

        order = self.sell(data=data, size=sell_size)
        if order is not None:
            close_px = float(data.close[0])
            self._sold_from_base_size_by_code[code] = sold_size + float(sell_size)
            self._buy_locked_after_partial_sell.add(code)
            self.order_meta[order.ref] = {
                "signal": "FACTOR_CHECK_SELL_SIGNAL_PROFIT20_STEP_POSITION",
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

        for d in sorted_ds:
            close_px = float(d.close[0])
            if not np.isfinite(close_px) or close_px <= 0:
                continue
            if self.getposition(d).size <= 0:
                self._refresh_threshold_state(d)
                continue
            self._submit_sell_signal_step_position(d)

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
