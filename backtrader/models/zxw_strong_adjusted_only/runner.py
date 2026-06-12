from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from settings import run_zxw_backtest

from models.zxw_strong_adjusted_only.init_alloc import compute_backscan_initial_weights
from models.configurable_signal_rules.data import normalize_rules
from models.zxw_strong_adjusted_only.run_naming import build_full_run_name, strip_run_name_date_prefix
from models.zxw_strong_adjusted_only.signal_data import (
    merge_strong_buy_signal,
    merge_strong_sell_signal,
    template_from_frontend,
)
from models.zxw_strong_adjusted_only.strategy_params import (
    StrongAdjustedStrategyParams,
    default_strategy_params,
    optuna_search_space,
)
from models.zxw_strong_adjusted_only.strong_adjusted_strategy import StrongAdjustedZxwStrategy

ProgressCallback = Callable[[str, int, str], None]

_zxw_mod: Any | None = None

INIT_LOOKBACK_CALENDAR_DAYS = 1100


def _load_zxw() -> Any:
    global _zxw_mod
    if _zxw_mod is not None:
        return _zxw_mod
    bt_dir = str(Path(__file__).resolve().parents[2])
    if bt_dir not in sys.path:
        sys.path.append(bt_dir)
    _zxw_mod = importlib.import_module("models.zxw_rule_backtest.zxw_view_results_full")
    return _zxw_mod


def run(
    *,
    codes: list[str],
    start_date: str,
    end_date: str,
    run_name: str,
    frontend_buy_rules: Any,
    frontend_sell_rules: Any,
    frontend_buy_operator: str,
    frontend_sell_operator: str,
    progress: ProgressCallback | None,
    strategy_param_overrides: dict[str, Any] | None = None,
    run_name_user_base: str | None = None,
) -> dict[str, Any]:
    """强点模型：买入→strong_buy_signal；卖出→strong_sell_signal(止盈)；宽表 total_sell_signal(止损)。"""
    del strategy_param_overrides  # 不再支持 Optuna 注入仓位/止盈参数

    def p(stage: str, value: int, message: str) -> None:
        if progress:
            progress(stage, value, message)

    buy_template = template_from_frontend(frontend_buy_rules)
    if not buy_template:
        raise ValueError("强点模型至少需要一个买入因子")
    sell_template = normalize_rules(frontend_sell_rules, "sell")
    user_base = str(run_name_user_base or "").strip() or strip_run_name_date_prefix(
        run_name, start_date, end_date
    ) or "ZXW强点"
    effective_run_name = build_full_run_name(
        start_date=start_date,
        end_date=end_date,
        user_base=user_base,
        buy_rules=buy_template,
        sell_rules=sell_template,
    )

    strat_params = default_strategy_params()
    profit_sell_line = "strong_sell_signal" if sell_template else "total_sell_signal"

    p("读取行情与信号", 25, "加载宽表并合并前端买入/卖出因子")
    zxw = _load_zxw()
    bt_df, actual_codes = zxw.build_zxw_rule_bt_dataframe_for_range(
        codes,
        start_date,
        end_date,
        init_lookback_calendar_days=INIT_LOOKBACK_CALENDAR_DAYS,
    )
    if bt_df.empty or not actual_codes:
        raise ValueError("目标标的和日期范围内没有有效回测数据")

    bt_df = merge_strong_buy_signal(bt_df, frontend_buy_rules, frontend_buy_operator)
    bt_df = merge_strong_sell_signal(bt_df, frontend_sell_rules, frontend_sell_operator)

    init_w = compute_backscan_initial_weights(
        bt_df,
        actual_codes,
        start_date,
        max_stocks=50,
        per_stock_cap=0.05,
        total_cap=1.0,
    )

    start_ts = pd.Timestamp(start_date).normalize()
    clip_df = bt_df[bt_df["time"] >= start_ts].copy()
    if clip_df.empty:
        raise ValueError("裁剪到回测起点后宽表为空")

    p("运行回测", 75, "Backtrader 执行 StrongAdjustedZxwStrategy")
    result = run_zxw_backtest(
        target_codes=actual_codes,
        df_multi=clip_df,
        strategy_cls=StrongAdjustedZxwStrategy,
        benchmark_cls=zxw.BuyAndHoldBenchmarkStrategy,
        strategy_kwargs=strat_params.to_strategy_kwargs(
            backtest_start=start_date,
            initial_target_weight_by_code=init_w,
            profit_sell_line=profit_sell_line,
        ),
        backtest_start=start_date,
        backtest_end=end_date,
        backtest_end_inclusive=False,
        verbose=False,
        write_frontend_curves=True,
        run_name=effective_run_name,
        create_cerebro_fn=zxw.create_cerebro,
    )

    buy_rules_payload = [
        {"factor": r.factor, "threshold": r.threshold} for r in buy_template
    ]
    sell_rules_payload = [
        {"factor": r.factor, "threshold": r.threshold} for r in sell_template
    ]
    config_payload: dict[str, Any] = {
        "codes": codes,
        "actual_codes": actual_codes,
        "start_date": start_date,
        "end_date": end_date,
        "run_name": effective_run_name,
        "run_name_user_base": user_base,
        "backtest_engine": "models/zxw_strong_adjusted_only + zxw_view_results_full 宽表",
        "strategy_class": "StrongAdjustedZxwStrategy",
        "init_lookback_calendar_days": INIT_LOOKBACK_CALENDAR_DAYS,
        "initial_target_weight_by_code": init_w,
        "strategy_params": _serialize_strategy_params(strat_params),
        "optuna_search_space": optuna_search_space(),
        "frontend_rules_ignored": False,
        "frontend_buy_rules": buy_rules_payload,
        "frontend_sell_rules": sell_rules_payload,
        "frontend_sell_rules_note": "止盈凭 strong_sell_signal（前端卖出因子合成）；止损凭宽表 total_sell_signal（不随卖出子集变化）",
        "frontend_buy_operator": frontend_buy_operator,
        "frontend_sell_operator": frontend_sell_operator,
    }
    summary_payload = result.get("summary_payload", {})
    if isinstance(summary_payload, dict):
        summary_payload.update(
            {
                "回测标的": actual_codes,
                "买入组合逻辑": f"ZXW_STRONG_BUY_FACTORS ({frontend_buy_operator})",
                "卖出组合逻辑": f"PROFIT_ON_{profit_sell_line.upper()} + STOP_ON_TOTAL_SELL_SIGNAL",
                "因子锁定说明": "强买=前端买入因子(strong_buy_signal)；止盈=前端卖出子集(strong_sell_signal)；"
                "止损=宽表 total_sell_signal（固定，不随卖出因子遍历变化）。",
                "回测配置": config_payload,
            }
        )
        summary_path = result.get("saved_paths", {}).get("summary") if isinstance(result.get("saved_paths"), dict) else ""
        if summary_path:
            Path(summary_path).write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    p("保存结果", 95, "整理回测输出")
    return {
        "run_tag": result.get("run_tag"),
        "summary": summary_payload,
        "saved_paths": result.get("saved_paths", {}),
        "curve_info": result.get("curve_info", {}),
        "config": config_payload,
    }


def _serialize_strategy_params(params: StrongAdjustedStrategyParams) -> dict[str, Any]:
    return {
        "max_weight": params.max_weight,
        "stop_loss_cost_multiplier": params.stop_loss_cost_multiplier,
        "invested_gate": params.invested_gate,
        "drawdown_add_weight": params.drawdown_add_weight,
        "profit_tiers": [
            {
                "tier_id": t.tier_id,
                "threshold": t.threshold,
                "sell_ratio_of_original": t.sell_ratio_of_original,
            }
            for t in params.profit_tiers
        ],
        "profit_sell_line": params.profit_sell_line,
    }
