"""因子检验模型：单票 2% 上限、现金≥10% 时等额补仓，无分档止盈/宽表止损。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

DEFAULT_MAX_WEIGHT = 0.02
DEFAULT_CASH_RATIO_GATE = 0.1


@dataclass
class FactorCheckStrategyParams:
    max_weight: float = DEFAULT_MAX_WEIGHT
    cash_ratio_gate: float = DEFAULT_CASH_RATIO_GATE

    def to_strategy_kwargs(
        self,
        *,
        backtest_start: str,
        initial_target_weight_by_code: dict[str, float],
    ) -> dict[str, Any]:
        return {
            "max_weight": self.max_weight,
            "cash_ratio_gate": self.cash_ratio_gate,
            "backtest_start": backtest_start,
            "initial_target_weight_by_code": initial_target_weight_by_code,
        }


def default_strategy_params(**overrides: Any) -> FactorCheckStrategyParams:
    base = FactorCheckStrategyParams()
    data = asdict(base)
    data.update({k: v for k, v in overrides.items() if v is not None})
    return FactorCheckStrategyParams(**data)
