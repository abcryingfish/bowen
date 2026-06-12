from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from settings import create_cerebro, run_zxw_backtest

from .data import build_configurable_bt_dataframe, normalize_rules, _normalize_operator
from .strategy import BuyAndHoldBenchmarkStrategy, ConfigurableSignalStrategy

ProgressCallback = Callable[[str, int, str], None]


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
) -> dict[str, Any]:
    def p(stage: str, value: int, message: str) -> None:
        if progress:
            progress(stage, value, message)

    buy_rules = normalize_rules(frontend_buy_rules, "buy")
    sell_rules = normalize_rules(frontend_sell_rules, "sell")
    buy_op = _normalize_operator(frontend_buy_operator)
    sell_op = _normalize_operator(frontend_sell_operator)

    p("读取行情与信号", 25, f"加载 {len(codes)} 个标的（可配置因子买卖线 + MAC/KDJ/OBV）")
    bt_df = build_configurable_bt_dataframe(
        codes, start_date, end_date, buy_rules, sell_rules, buy_op, sell_op
    )
    if bt_df.empty:
        raise ValueError("目标标的和日期范围内没有有效回测数据")
    actual_codes = sorted(bt_df["htsc_code"].astype(str).str.upper().unique().tolist())

    p("运行回测", 75, "Backtrader 执行 ConfigurableSignalStrategy")
    result = run_zxw_backtest(
        target_codes=actual_codes,
        df_multi=bt_df,
        strategy_cls=ConfigurableSignalStrategy,
        benchmark_cls=BuyAndHoldBenchmarkStrategy,
        strategy_kwargs={"max_weight": 0.05, "drawdown_add_weight": 0.025, "lot_size": 100},
        backtest_start=start_date,
        backtest_end=end_date,
        backtest_end_inclusive=False,
        verbose=False,
        write_frontend_curves=True,
        run_name=run_name,
        create_cerebro_fn=create_cerebro,
    )

    config_payload: dict[str, Any] = {
        "codes": codes,
        "actual_codes": actual_codes,
        "start_date": start_date,
        "end_date": end_date,
        "run_name": run_name,
        "backtest_engine": "models/configurable_signal_rules",
        "strategy_class": "ConfigurableSignalStrategy",
        "frontend_rules_ignored": False,
        "buy_operator": buy_op,
        "sell_operator": sell_op,
        "buy_rules": frontend_buy_rules if isinstance(frontend_buy_rules, list) else [],
        "sell_rules": frontend_sell_rules if isinstance(frontend_sell_rules, list) else [],
        "frontend_buy_operator": frontend_buy_operator,
        "frontend_sell_operator": frontend_sell_operator,
    }
    summary_payload = result.get("summary_payload", {})
    if isinstance(summary_payload, dict):
        summary_payload.update(
            {
                "回测标的": actual_codes,
                "买入组合逻辑": f"CONFIGURABLE_SIGNAL_RULES ({buy_op})",
                "卖出组合逻辑": f"CONFIGURABLE_SIGNAL_RULES ({sell_op})",
                "因子锁定说明": "买卖信号由前端选择的因子与阈值合并为 buy_signal / sell_signal；MAC/KDJ/OBV 用于总买入调整与一年腰斩禁买逻辑。",
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
