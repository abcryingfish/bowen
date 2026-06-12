from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

from settings import run_zxw_backtest

from .strategy import HongZimingAvgPositionStrategy

ProgressCallback = Callable[[str, int, str], None]

_zxw_mod: Any | None = None


def _load_zxw_view_results() -> Any:
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
) -> dict[str, Any]:
    def p(stage: str, value: int, message: str) -> None:
        if progress:
            progress(stage, value, message)

    p("读取行情与信号", 25, f"加载 {len(codes)} 个标的行情与因子（洪梓铭平均仓位模型，数据管线 models.zxw_rule_backtest.zxw_view_results_full）")
    zxw = _load_zxw_view_results()
    bt_df, actual_codes = zxw.build_zxw_rule_bt_dataframe_for_range(codes, start_date, end_date)
    if bt_df.empty or not actual_codes:
        raise ValueError("目标标的和日期范围内没有有效回测数据")

    p("运行回测", 75, "Backtrader 执行 HongZimingAvgPositionStrategy（洪梓铭平均仓位模型）")
    result = run_zxw_backtest(
        target_codes=actual_codes,
        df_multi=bt_df,
        strategy_cls=HongZimingAvgPositionStrategy,
        benchmark_cls=zxw.BuyAndHoldBenchmarkStrategy,
        strategy_kwargs=None,
        backtest_start=start_date,
        backtest_end=end_date,
        backtest_end_inclusive=False,
        verbose=False,
        write_frontend_curves=True,
        run_name=run_name,
        create_cerebro_fn=zxw.create_cerebro,
    )

    config_payload: dict[str, Any] = {
        "codes": codes,
        "actual_codes": actual_codes,
        "start_date": start_date,
        "end_date": end_date,
        "buy_operator": "and",
        "sell_operator": "or",
        "run_name": run_name,
        "backtest_engine": "models/hong_ziming_avg_position + models.zxw_rule_backtest.zxw_view_results_full",
        "strategy_class": "HongZimingAvgPositionStrategy",
        "buy_rules": [],
        "sell_rules": [],
        "frontend_rules_ignored": True,
        "frontend_buy_rules": frontend_buy_rules,
        "frontend_sell_rules": frontend_sell_rules,
        "frontend_buy_operator": frontend_buy_operator,
        "frontend_sell_operator": frontend_sell_operator,
    }
    summary_payload = result.get("summary_payload", {})
    if isinstance(summary_payload, dict):
        summary_payload.update(
            {
                "回测标的": actual_codes,
                "买入组合逻辑": "HONG_ZIMING_AVG_POSITION",
                "卖出组合逻辑": "HONG_ZIMING_AVG_POSITION",
                "因子锁定说明": "前端因子配置已忽略；主策略为洪梓铭平均仓位模型，行情与因子合并同 models.zxw_rule_backtest.zxw_view_results_full。",
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
