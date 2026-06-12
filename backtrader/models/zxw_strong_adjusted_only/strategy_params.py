"""StrongAdjustedZxwStrategy 可调参数（供 runner / 后续 Optuna 遍历）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProfitTier:
    """止盈档：浮盈超过 threshold 后预挂；strong_sell_signal≥1 时按原仓比例卖出（每档每票仅一次）。"""

    tier_id: str
    threshold: float
    sell_ratio_of_original: float

    def signal_name(self) -> str:
        return f"PROFIT_TIER_{self.tier_id.upper()}"


# 默认三档（单票、相对首次记仓股数）：+100% 清仓；+60% 卖原仓 85%；+30% 卖原仓 60%
DEFAULT_PROFIT_TIERS: tuple[ProfitTier, ...] = (
    ProfitTier("100pct_full", 1.0, 1.0),
    ProfitTier("60pct_85orig", 0.6, 0.85),
    ProfitTier("30pct_60orig", 0.3, 0.60),
)

DEFAULT_MAX_WEIGHT = 0.05
DEFAULT_STOP_LOSS_COST_MULTIPLIER = 0.8
DEFAULT_INVESTED_GATE = 0.8
DEFAULT_DRAWDOWN_ADD_WEIGHT = 0.025


@dataclass
class StrongAdjustedStrategyParams:
    max_weight: float = DEFAULT_MAX_WEIGHT
    stop_loss_cost_multiplier: float = DEFAULT_STOP_LOSS_COST_MULTIPLIER
    invested_gate: float = DEFAULT_INVESTED_GATE
    drawdown_add_weight: float = DEFAULT_DRAWDOWN_ADD_WEIGHT
    profit_tiers: tuple[ProfitTier, ...] = field(default_factory=lambda: DEFAULT_PROFIT_TIERS)
    profit_sell_line: str = "strong_sell_signal"

    def to_strategy_kwargs(
        self,
        *,
        backtest_start: str,
        initial_target_weight_by_code: dict[str, float],
        profit_sell_line: str | None = None,
    ) -> dict[str, Any]:
        return {
            "max_weight": self.max_weight,
            "stop_loss_cost_multiplier": self.stop_loss_cost_multiplier,
            "invested_gate": self.invested_gate,
            "drawdown_add_weight": self.drawdown_add_weight,
            "profit_tiers": profit_tiers_to_bt_param(self.profit_tiers),
            "profit_sell_line": str(profit_sell_line or self.profit_sell_line).strip() or "strong_sell_signal",
            "backtest_start": backtest_start,
            "initial_target_weight_by_code": initial_target_weight_by_code,
        }


def profit_tiers_to_bt_param(tiers: Any) -> tuple[tuple[str, float, float], ...]:
    """接受 ProfitTier / tuple / list[dict]（如 asdict 产物），统一转为 Backtrader params 元组。"""
    normalized = profit_tiers_from_bt_param(tiers)
    return tuple((t.tier_id, t.threshold, t.sell_ratio_of_original) for t in normalized)


def profit_tiers_from_bt_param(raw: Any) -> tuple[ProfitTier, ...]:
    if not raw:
        return DEFAULT_PROFIT_TIERS
    out: list[ProfitTier] = []
    for item in raw:
        if isinstance(item, ProfitTier):
            out.append(item)
        elif isinstance(item, dict):
            out.append(
                ProfitTier(
                    str(item["tier_id"]),
                    float(item["threshold"]),
                    float(item["sell_ratio_of_original"]),
                )
            )
        else:
            tier_id, threshold, ratio = item
            out.append(ProfitTier(str(tier_id), float(threshold), float(ratio)))
    return tuple(out)


def default_strategy_params(**overrides: Any) -> StrongAdjustedStrategyParams:
    """构建默认参数；overrides 键名同 StrongAdjustedStrategyParams 字段，供 Optuna trial 注入。"""
    base = StrongAdjustedStrategyParams()
    # 勿直接用 asdict(base) 的 profit_tiers：dataclasses.asdict 会把 ProfitTier 递归成 dict。
    data = asdict(base)
    data["profit_tiers"] = profit_tiers_from_bt_param(data["profit_tiers"])
    if "profit_tiers" in overrides and overrides["profit_tiers"] is not None:
        overrides = {**overrides, "profit_tiers": profit_tiers_from_bt_param(overrides["profit_tiers"])}
    data.update({k: v for k, v in overrides.items() if v is not None})
    return StrongAdjustedStrategyParams(**data)


def optuna_search_space() -> dict[str, dict[str, Any]]:
    """强点模型 Optuna 仅遍历买入因子子集（阈值固定为面板值）；风控参数写死。"""
    return {
        "buy_factor_subset": {
            "type": "note",
            "description": "每个 trial 对模板买入因子做 include/exclude，至少保留 1 个；不扫阈值区间。",
        },
        "fixed_stop_loss_cost_multiplier": DEFAULT_STOP_LOSS_COST_MULTIPLIER,
        "fixed_profit_tiers": [
            {"threshold": t.threshold, "sell_ratio_of_original": t.sell_ratio_of_original}
            for t in DEFAULT_PROFIT_TIERS
        ],
        "sell_logic": "止盈：前端卖出因子→strong_sell_signal；止损：宽表 total_sell_signal 不变",
    }
