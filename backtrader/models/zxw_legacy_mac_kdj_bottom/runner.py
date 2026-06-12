from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from settings import run_zxw_backtest

ProgressCallback = Callable[[str, int, str], None]

_legacy_mod: Any | None = None


def _load_legacy() -> Any:
    global _legacy_mod
    if _legacy_mod is not None:
        return _legacy_mod
    bt_dir = str(Path(__file__).resolve().parents[2])
    if bt_dir not in sys.path:
        sys.path.append(bt_dir)
    _legacy_mod = importlib.import_module("models.zxw_legacy_mac_kdj_bottom.zxw_view_results_legacy")
    return _legacy_mod


def build_legacy_bt_dataframe(legacy_mod: Any, codes: list[str], start_date: str, end_date: str) -> tuple[pd.DataFrame, list[str]]:
    codes_str = ", ".join([f"'{c}'" for c in codes])
    price_view_name = "price_day_merged"
    price_con = legacy_mod.create_duckdb_view(base_path=legacy_mod.PRICE_BASE_PATH, view_name=price_view_name)
    price_df = price_con.execute(
        f"""
        SELECT *
        FROM {price_view_name}
        WHERE htsc_code IN ({codes_str})
          AND time >= '{start_date}'
          AND time < '{end_date}'
        ORDER BY htsc_code, time
        """
    ).df()
    if price_df.empty:
        return pd.DataFrame(), []
    price_df["time"] = pd.to_datetime(price_df["time"]).dt.normalize()
    price_df["htsc_code"] = price_df["htsc_code"].astype(str).str.upper()

    signal_df = legacy_mod.load_signal_factor_wide(
        base_path=legacy_mod.SIGNAL_BASE_PATH,
        factor_names=list(legacy_mod.FACTOR_COLUMN_MAP.keys()),
        codes_sql_in_list=codes_str,
        backtest_start=start_date,
        backtest_end=end_date,
    )
    signal_factor_df = signal_df.rename(columns=legacy_mod.FACTOR_COLUMN_MAP)
    bt_df = price_df.merge(signal_factor_df, on=["time", "htsc_code"], how="left")
    for factor_col in legacy_mod.FACTOR_COLUMN_MAP.values():
        bt_df[factor_col] = pd.to_numeric(bt_df[factor_col], errors="coerce").fillna(0.0)

    actual_codes = sorted(bt_df["htsc_code"].astype(str).str.upper().unique().tolist())
    return bt_df, actual_codes


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
    variant_label: str = "zxw_legacy_mac_kdj_bottom",
) -> dict[str, Any]:
    def p(stage: str, value: int, message: str) -> None:
        if progress:
            progress(stage, value, message)

    legacy = _load_legacy()
    p("读取行情与信号", 25, f"加载 {len(codes)} 个标的（{variant_label}，原版因子合并）")
    bt_df, actual_codes = build_legacy_bt_dataframe(legacy, codes, start_date, end_date)
    if bt_df.empty or not actual_codes:
        raise ValueError("目标标的和日期范围内没有有效回测数据")

    p("运行回测", 75, "Backtrader 执行 MacKdjBottomScoreBuyAndHoldStrategy（原版）")
    result = run_zxw_backtest(
        target_codes=actual_codes,
        df_multi=bt_df,
        strategy_cls=legacy.MacKdjBottomScoreBuyAndHoldStrategy,
        benchmark_cls=legacy.BuyAndHoldBenchmarkStrategy,
        strategy_kwargs={"max_weight": 0.10},
        backtest_start=start_date,
        backtest_end=end_date,
        backtest_end_inclusive=False,
        verbose=False,
        write_frontend_curves=True,
        run_name=run_name,
        create_cerebro_fn=legacy.create_cerebro,
    )

    config_payload: dict[str, Any] = {
        "codes": codes,
        "actual_codes": actual_codes,
        "start_date": start_date,
        "end_date": end_date,
        "run_name": run_name,
        "backtest_engine": f"models/{variant_label} + models.zxw_legacy_mac_kdj_bottom.zxw_view_results_legacy",
        "strategy_class": "MacKdjBottomScoreBuyAndHoldStrategy",
        "frontend_rules_ignored": True,
        "frontend_buy_rules": frontend_buy_rules,
        "frontend_sell_rules": frontend_sell_rules,
        "frontend_buy_operator": frontend_buy_operator,
        "frontend_sell_operator": frontend_sell_operator,
        "variant": variant_label,
    }
    summary_payload = result.get("summary_payload", {})
    if isinstance(summary_payload, dict):
        summary_payload.update(
            {
                "回测标的": actual_codes,
                "买入组合逻辑": "LEGACY_MAC_KDJ_BOTTOM_SCORE",
                "卖出组合逻辑": "LEGACY_MAC_KDJ_BOTTOM_SCORE",
                "因子锁定说明": "MAC/KDJ/OBV/抄底分 与原版脚本一致；前端因子规则已接收但未使用。",
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
