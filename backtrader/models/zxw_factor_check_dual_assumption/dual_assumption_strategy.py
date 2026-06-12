"""因子检验（双假设）：去前视 + 单日涨跌幅超阈值禁交易。"""

from __future__ import annotations

from typing import Any

import numpy as np

from models.zxw_factor_check_only.factor_check_strategy import FactorCheckZxwStrategy

DEFAULT_DAILY_MOVE_LIMIT = 0.098


class FactorCheckDualAssumptionZxwStrategy(FactorCheckZxwStrategy):
    """
    在 FactorCheckZxwStrategy 基础上增加：
    当日 |收盘/昨收 - 1| > daily_move_limit（默认 9.8%）时，该标的当天不买也不卖。
    """

    params = dict(
        daily_move_limit=DEFAULT_DAILY_MOVE_LIMIT,
    )

    def _can_trade_today(self, data: Any) -> bool:
        if len(data) < 2:
            return True
        close_px = float(data.close[0])
        prev_close = float(data.close[-1])
        if not np.isfinite(close_px) or not np.isfinite(prev_close) or prev_close <= 0:
            return True
        move = close_px / prev_close - 1.0
        return abs(move) <= float(self.p.daily_move_limit)

    def _submit_order_target_value(self, data: Any, target_value: float, signal: str) -> None:
        if not self._can_trade_today(data):
            return
        super()._submit_order_target_value(data, target_value, signal)

    def _submit_buy_value_no_cap(self, data: Any, buy_value: float, signal: str) -> None:
        if not self._can_trade_today(data):
            return
        super()._submit_buy_value_no_cap(data, buy_value, signal)

    def _submit_sell_signal_close(self, data: Any) -> None:
        if not self._can_trade_today(data):
            return
        super()._submit_sell_signal_close(data)
