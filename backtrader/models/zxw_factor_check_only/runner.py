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
from models.zxw_factor_check_only.strategy_params import (
    FactorCheckStrategyParams,
    default_strategy_params,
)
from models.zxw_factor_check_only.factor_check_strategy import FactorCheckZxwStrategy

ProgressCallback = Callable[[str, int, str], None]

_zxw_mod: Any | None = None

INIT_LOOKBACK_CALENDAR_DAYS = 1100
INIT_PER_STOCK_CAP = 0.02


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
    """因子检验：买入→strong_buy_signal；卖出→strong_sell_signal 清仓；单次运行，不穷举子集。"""
    del strategy_param_overrides

    def p(stage: str, value: int, message: str) -> None:
        if progress:
            progress(stage, value, message)

    buy_template = template_from_frontend(frontend_buy_rules)
    if not buy_template:
        raise ValueError("因子检验模型请至少配置一个买入因子")
    sell_template = normalize_rules(frontend_sell_rules, "sell")
    if not sell_template:
        raise ValueError("因子检验模型请至少配置一个卖出因子")

    user_base = str(run_name_user_base or "").strip() or strip_run_name_date_prefix(
        run_name, start_date, end_date
    ) or "ZXW因子检验"
    effective_run_name = build_full_run_name(
        start_date=start_date,
        end_date=end_date,
        user_base=user_base,
        buy_rules=buy_template,
        sell_rules=sell_template,
    )

    strat_params = default_strategy_params()

    p("读取行情与信号", 25, "加载宽表并合并前端买入/卖出因子（AND/OR）")
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
        per_stock_cap=INIT_PER_STOCK_CAP,
        total_cap=1.0,
    )

    start_ts = pd.Timestamp(start_date).normalize()
    clip_df = bt_df[bt_df["time"] >= start_ts].copy()
    if clip_df.empty:
        raise ValueError("裁剪到回测起点后宽表为空")

    p("运行回测", 75, "Backtrader 执行 FactorCheckZxwStrategy")
    result = run_zxw_backtest(
        target_codes=actual_codes,
        df_multi=clip_df,
        strategy_cls=FactorCheckZxwStrategy,
        benchmark_cls=zxw.BuyAndHoldBenchmarkStrategy,
        strategy_kwargs=strat_params.to_strategy_kwargs(
            backtest_start=start_date,
            initial_target_weight_by_code=init_w,
        ),
        backtest_start=start_date,
        backtest_end=end_date,
        backtest_end_inclusive=False,
        verbose=False,
        write_frontend_curves=True,
        run_name=effective_run_name,
        create_cerebro_fn=zxw.create_cerebro,
    )

    buy_rules_payload = [{"factor": r.factor, "threshold": r.threshold} for r in buy_template]
    sell_rules_payload = [{"factor": r.factor, "threshold": r.threshold} for r in sell_template]
    config_payload: dict[str, Any] = {
        "codes": codes,
        "actual_codes": actual_codes,
        "start_date": start_date,
        "end_date": end_date,
        "run_name": effective_run_name,
        "run_name_user_base": user_base,
        "backtest_engine": "models/zxw_factor_check_only + zxw_view_results_full 宽表",
        "strategy_class": "FactorCheckZxwStrategy",
        "init_lookback_calendar_days": INIT_LOOKBACK_CALENDAR_DAYS,
        "init_per_stock_cap": INIT_PER_STOCK_CAP,
        "initial_target_weight_by_code": init_w,
        "strategy_params": {
            "max_weight": strat_params.max_weight,
            "cash_ratio_gate": strat_params.cash_ratio_gate,
        },
        "frontend_rules_ignored": False,
        "frontend_buy_rules": buy_rules_payload,
        "frontend_sell_rules": sell_rules_payload,
        "frontend_buy_operator": frontend_buy_operator,
        "frontend_sell_operator": frontend_sell_operator,
        "exhaustive_traversal": False,
    }
    summary_payload = result.get("summary_payload", {})
    if isinstance(summary_payload, dict):
        summary_payload.update(
            {
                "回测标的": actual_codes,
                "买入组合逻辑": f"ZXW_FACTOR_CHECK_BUY ({frontend_buy_operator})",
                "卖出组合逻辑": f"ZXW_FACTOR_CHECK_SELL ({frontend_sell_operator})",
                "因子锁定说明": "强买=前端买入因子(strong_buy_signal)尽量买到2%；强卖=前端卖出因子(strong_sell_signal)≥1 无条件清仓；"
                "卖完且强买处理完后现金仍≥10%则等额补仓（可突破2%），无持仓则保持空仓；无参数穷举。",
                "回测配置": config_payload,
            }
        )
        summary_path = (
            result.get("saved_paths", {}).get("summary")
            if isinstance(result.get("saved_paths"), dict)
            else ""
        )
        if summary_path:
            Path(summary_path).write_text(
                json.dumps(summary_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    p("保存结果", 95, "整理回测输出")
    return {
        "run_tag": result.get("run_tag"),
        "summary": summary_payload,
        "saved_paths": result.get("saved_paths", {}),
        "curve_info": result.get("curve_info", {}),
        "config": config_payload,
    }
