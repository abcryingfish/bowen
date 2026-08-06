from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import backtrader as bt
import pandas as pd

from settings import FactorPandasData, INITIAL_CASH, run_zxw_backtest

from .data import build_ths_bt_dataframe, normalize_codes, normalize_rules
from .strategy import ONE_WAY_COST_RATE, ThsEqualWeightBuyHoldStrategy, ThsMonthlyThresholdStrategy


ProgressCallback = Callable[[str, int, str], None]


def create_ths_cerebro(target_codes: list[str], df_multi: pd.DataFrame, verbose: bool = True) -> bt.Cerebro:
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=ONE_WAY_COST_RATE)
    for code in target_codes:
        frame = df_multi[df_multi["htsc_code"] == code].sort_values("time").reset_index(drop=True)
        if frame.empty:
            continue
        data = FactorPandasData(
            dataname=frame,
            datetime="time",
            open="open",
            high="high",
            low="low",
            close="close",
            volume="volume",
            openinterest=-1,
            mac_total="mac_total",
            kdj_signal="kdj_signal",
            obv_bullish="obv_bullish",
            buy_signal="buy_signal",
            sell_signal="sell_signal",
            timeframe=bt.TimeFrame.Days,
        )
        data._name = code
        cerebro.adddata(data)
        if verbose:
            print(f"已添加THS板块指数: {code} ({len(frame)} 条)")
    return cerebro


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
    def report(stage: str, value: int, message: str) -> None:
        if progress:
            progress(stage, value, message)

    normalized_codes = normalize_codes(codes)
    rules = normalize_rules(frontend_buy_rules)
    operator = "or" if str(frontend_buy_operator).strip().lower() == "or" else "and"
    report("读取行情与因子", 25, f"加载 {len(normalized_codes)} 个THS板块并计算月末截面")
    frame = build_ths_bt_dataframe(normalized_codes, start_date, end_date, rules, operator)
    actual_codes = [code for code in normalized_codes if code in set(frame["htsc_code"].astype(str))]
    if not actual_codes:
        raise ValueError("目标THS板块和日期范围内没有有效回测数据")

    report("运行回测", 70, "执行THS板块月度因子等权再平衡")
    result = run_zxw_backtest(
        target_codes=actual_codes,
        df_multi=frame,
        strategy_cls=ThsMonthlyThresholdStrategy,
        benchmark_cls=ThsEqualWeightBuyHoldStrategy,
        strategy_kwargs={"lot_size": 100, "one_way_cost_rate": ONE_WAY_COST_RATE},
        backtest_start=start_date,
        backtest_end=end_date,
        backtest_end_inclusive=False,
        verbose=False,
        write_frontend_curves=True,
        run_name=run_name,
        create_cerebro_fn=create_ths_cerebro,
    )
    config = {
        "codes": normalized_codes,
        "actual_codes": actual_codes,
        "start_date": start_date,
        "end_date": end_date,
        "run_name": run_name,
        "backtest_engine": "models/ths_monthly_threshold",
        "strategy_class": "ThsMonthlyThresholdStrategy",
        "buy_operator": operator,
        "buy_rules": rules,
        "sell_rules": [],
        "rebalance_frequency": "monthly",
        "rebalance_execution": "next_month_first_open",
        "allocation": "equal_weight_selected",
        "lot_size": 100,
        "one_way_cost_rate": ONE_WAY_COST_RATE,
        "round_trip_cost_rate": ONE_WAY_COST_RATE * 2,
        "price_source": r"D:\database\index_data_daily",
        "price_limit_enabled": False,
    }
    summary = result.get("summary_payload", {})
    if isinstance(summary, dict):
        summary.update(
            {
                "回测标的": actual_codes,
                "买入组合逻辑": f"THS_MONTHLY_THRESHOLD ({operator})",
                "卖出组合逻辑": "月末不再满足条件则退出；满足条件板块次月首日等权再平衡",
                "因子锁定说明": "支持因子数值阈值、截面比例与具体名次；月末判断，次月首个交易日开盘成交。",
                "回测配置": config,
            }
        )
        summary_path = result.get("saved_paths", {}).get("summary") if isinstance(result.get("saved_paths"), dict) else ""
        if summary_path:
            Path(summary_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report("保存结果", 95, "整理THS月度回测输出")
    return {
        "run_tag": result.get("run_tag"),
        "summary": summary,
        "saved_paths": result.get("saved_paths", {}),
        "curve_info": result.get("curve_info", {}),
        "config": config,
    }
