#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
回测通用配置和工具函数
后续回测中不需要修改的内容放在这里
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import backtrader as bt
import duckdb
import numpy as np
import pandas as pd
import polars as pl

# =============================================================================
# 常量配置
# =============================================================================

# 资金与回测基础配置
INITIAL_CASH = 10_000_000.0
COMMISSION = 0.0003  # 手续费率

# 曲线代码定义
PORTFOLIO_CURVE_CODE = "000000.YKRS"
CASH_CURVE_CODE = "0000000.YKRS"
BUY_HOLD_CURVE_CODE = "000001.YKRS"
PORTFOLIO_SECURITY_ID = "000000"
CASH_SECURITY_ID = "0000000"
BUY_HOLD_SECURITY_ID = "000001"

# 数据路径
STOCK_BASE_PATH = Path(r"D:\database\stock_portfolio_data_daily")
SAVE_DIR = Path(r"D:\database\bs_dialy")
TOTAL_RECORD_DIR = Path(r"D:\database\total_record")

# Run Tag 生成
RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M")


class FactorPandasData(bt.feeds.PandasData):
    """OHLCV feed with optional merged factor/signal columns."""

    lines = ("mac_total", "kdj_signal", "obv_bullish", "buy_signal", "sell_signal")
    params = (
        ("mac_total", -1),
        ("kdj_signal", -1),
        ("obv_bullish", -1),
        ("buy_signal", -1),
        ("sell_signal", -1),
    )

# =============================================================================
# 基础数据连接
# =============================================================================


def create_duckdb_view(
    base_path: str = r"D:\database\stock_basic_data_daily",
    view_name: str = "stock_day_merged",
) -> duckdb.DuckDBPyConnection:
    """创建 DuckDB 视图，用于读取历史数据。"""
    con = duckdb.connect()
    con.execute(f"""
    CREATE OR REPLACE VIEW {view_name} AS
    SELECT *
    FROM read_parquet('{base_path}/year=*/month=*/merged.parquet', hive_partitioning=1)
    """)
    return con


# =============================================================================
# Cerebro 初始化
# =============================================================================


def create_cerebro(
    target_codes: list[str],
    df_multi: pd.DataFrame,
    verbose: bool = True,
) -> bt.Cerebro:
    """创建并配置 Cerebro 实例。"""
    cerebro = bt.Cerebro()
    cerebro.broker.set_coc(True)  # 订单提交当天按收盘价成交；策略可延迟提交以实现次日收盘成交
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)

    for code in target_codes:
        code_df = df_multi[df_multi["htsc_code"] == code].copy()
        code_df = code_df.sort_values("time").reset_index(drop=True)
        if code_df.empty:
            print(f"⚠️ 股票 {code} 无数据，跳过添加数据 feed")
            continue

        data = FactorPandasData(
            dataname=code_df,
            datetime="time",
            open="open",
            high="high",
            low="low",
            close="close",
            volume="volume",
            openinterest=-1,
            mac_total="mac_total" if "mac_total" in code_df.columns else -1,
            kdj_signal="kdj_signal" if "kdj_signal" in code_df.columns else -1,
            obv_bullish="obv_bullish" if "obv_bullish" in code_df.columns else -1,
            buy_signal="buy_signal" if "buy_signal" in code_df.columns else -1,
            sell_signal="sell_signal" if "sell_signal" in code_df.columns else -1,
            timeframe=bt.TimeFrame.Days,
        )
        data._name = code
        cerebro.adddata(data)
        if verbose:
            print(f"✓ 已添加数据: {code} ({len(code_df)} 条记录)")

    return cerebro


def build_stock_performance_summary(
    order_log_df: pd.DataFrame,
    trade_log_df: pd.DataFrame,
    position_log_df: pd.DataFrame,
    final_value: float,
) -> dict[str, list[dict[str, Any]]]:
    """汇总已平仓与期末仍持仓股票表现，供结果展示页直接读取。"""
    final_position_df = pd.DataFrame()
    open_codes: set[str] = set()
    if not position_log_df.empty and {"date", "code"}.issubset(position_log_df.columns):
        final_date = str(position_log_df["date"].dropna().max())
        final_position_df = position_log_df[position_log_df["date"].astype(str) == final_date].copy()
        final_position_df["position_size"] = pd.to_numeric(final_position_df.get("position_size"), errors="coerce").fillna(0.0)
        final_position_df = final_position_df[final_position_df["position_size"] != 0.0]
        open_codes = set(final_position_df["code"].dropna().astype(str))

    buy_cost_by_code: dict[str, float] = {}
    if not order_log_df.empty and {"code", "side", "executed_value"}.issubset(order_log_df.columns):
        orders = order_log_df.copy()
        orders["side"] = orders["side"].astype(str).str.upper()
        if "status" in orders.columns:
            orders = orders[orders["status"].astype(str).str.upper() == "COMPLETED"]
        buy_orders = orders[orders["side"] == "BUY"].copy()
        buy_orders["executed_value"] = pd.to_numeric(buy_orders["executed_value"], errors="coerce").abs().fillna(0.0)
        if "commission" in buy_orders.columns:
            buy_orders["commission"] = pd.to_numeric(buy_orders["commission"], errors="coerce").fillna(0.0)
        else:
            buy_orders["commission"] = 0.0
        buy_cost_by_code = (buy_orders["executed_value"] + buy_orders["commission"]).groupby(buy_orders["code"].astype(str)).sum().to_dict()

    strategy_profit = float(final_value) - float(INITIAL_CASH)
    realized_pnl_by_code: dict[str, float] = {}
    trades = pd.DataFrame()
    if not trade_log_df.empty and {"code", "pnlcomm"}.issubset(trade_log_df.columns):
        trades = trade_log_df.copy()
        trades["code"] = trades["code"].astype(str)
        trades["pnlcomm"] = pd.to_numeric(trades["pnlcomm"], errors="coerce").fillna(0.0)
        realized_pnl_by_code = trades.groupby("code")["pnlcomm"].sum().to_dict()

    closed_items: list[dict[str, Any]] = []
    if not trades.empty:
        closed_trades = trades[~trades["code"].isin(open_codes)]
        if not closed_trades.empty:
            grouped = closed_trades.groupby("code", as_index=False).agg(
                realized_pnl=("pnlcomm", "sum"),
                trade_count=("pnlcomm", "size"),
                first_entry_date=("date_open", "min"),
                last_exit_date=("date_close", "max"),
                holding_days=("barlen", "sum"),
            )
            for row in grouped.sort_values("realized_pnl", ascending=False).to_dict("records"):
                code = str(row.get("code", ""))
                buy_cost = float(buy_cost_by_code.get(code, 0.0) or 0.0)
                realized_pnl = float(row.get("realized_pnl") or 0.0)
                closed_items.append(
                    {
                        "code": code,
                        "realized_pnl": normalize_summary_value(realized_pnl),
                        "buy_cost": normalize_summary_value(buy_cost),
                        "realized_return_pct": normalize_summary_percent(realized_pnl / buy_cost) if abs(buy_cost) > 1e-12 else None,
                        "contribution_pct": normalize_summary_percent(realized_pnl / strategy_profit) if abs(strategy_profit) > 1e-12 else None,
                        "trade_count": int(row.get("trade_count") or 0),
                        "first_entry_date": row.get("first_entry_date"),
                        "last_exit_date": row.get("last_exit_date"),
                        "holding_days": normalize_summary_value(row.get("holding_days")),
                    }
                )

    open_items: list[dict[str, Any]] = []
    if not final_position_df.empty:
        sort_col = "weight_pct" if "weight_pct" in final_position_df.columns else "market_value"
        for _, row in final_position_df.sort_values(sort_col, ascending=False).iterrows():
            market_value = float(row.get("market_value") or 0.0)
            weight_value = row.get("weight_pct")
            if weight_value is None or pd.isna(weight_value):
                weight_value = market_value / final_value if abs(final_value) > 1e-12 else np.nan
            return_value = row.get("unrealized_return_pct")
            if return_value is None or pd.isna(return_value):
                position_size = float(row.get("position_size") or 0.0)
                position_price = float(row.get("position_price") or 0.0)
                cost_basis = position_size * position_price
                return_value = float(row.get("unrealized_pnl") or 0.0) / cost_basis if abs(cost_basis) > 1e-12 else np.nan
            unrealized_pnl_value = row.get("unrealized_pnl")
            if unrealized_pnl_value is None or pd.isna(unrealized_pnl_value):
                position_size = float(row.get("position_size") or 0.0)
                position_price = float(row.get("position_price") or 0.0)
                cost_basis = position_size * position_price
                unrealized_pnl_value = market_value - cost_basis
            code = str(row.get("code", ""))
            realized_pnl_value = float(realized_pnl_by_code.get(code, 0.0) or 0.0)
            total_pnl_value = realized_pnl_value + float(unrealized_pnl_value or 0.0)
            open_items.append(
                {
                    "code": code,
                    "unrealized_return_pct": normalize_summary_percent(return_value),
                    "realized_pnl": normalize_summary_value(realized_pnl_value),
                    "unrealized_pnl": normalize_summary_value(unrealized_pnl_value),
                    "total_pnl": normalize_summary_value(total_pnl_value),
                    "contribution_pct": normalize_summary_percent(total_pnl_value / strategy_profit) if abs(strategy_profit) > 1e-12 else None,
                    "weight_pct": normalize_summary_percent(weight_value),
                    "market_value": normalize_summary_value(market_value),
                    "position_size": normalize_summary_value(row.get("position_size")),
                    "close": normalize_summary_value(row.get("close")),
                }
            )

    return {
        "已平仓股票表现": closed_items,
        "期末持仓股票表现": open_items,
    }


# =============================================================================
# ZXW 回测主流程（策略类放在 Notebook 中，此处只负责跑 cerebro、指标与落盘）
# =============================================================================


def run_zxw_backtest(
    target_codes: list[str],
    df_multi: pd.DataFrame,
    strategy_cls: type[bt.Strategy],
    benchmark_cls: type[bt.Strategy],
    *,
    strategy_kwargs: dict[str, Any] | None = None,
    backtest_start: str | None = None,
    backtest_end: str | None = None,
    backtest_end_inclusive: bool = False,
    verbose: bool = True,
    write_frontend_curves: bool = True,
    run_name: str = "",
    create_cerebro_fn: Callable[..., bt.Cerebro] | None = None,
) -> dict[str, Any]:
    """
    运行主策略 + 等权买入持有基准，计算指标、写 position_log / summary、upsert 曲线。

    每次调用生成独立 run_tag（含秒），避免同分钟内覆盖文件。
    """
    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    TOTAL_RECORD_DIR.mkdir(parents=True, exist_ok=True)

    _mk_cerebro = create_cerebro_fn or create_cerebro
    cerebro = _mk_cerebro(target_codes, df_multi, verbose=verbose)
    if strategy_kwargs:
        cerebro.addstrategy(strategy_cls, **strategy_kwargs)
    else:
        cerebro.addstrategy(strategy_cls)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="dd")

    print(f"初始资金: {cerebro.broker.getvalue():,.2f}")

    results = cerebro.run()
    strat = results[0]

    benchmark_cerebro = _mk_cerebro(target_codes, df_multi, verbose=False)
    benchmark_cerebro.addstrategy(benchmark_cls)
    benchmark_results = benchmark_cerebro.run()
    benchmark_strat = benchmark_results[0]

    returns_analysis = dict(strat.analyzers.returns.get_analysis())
    dd_analysis = strat.analyzers.dd.get_analysis()
    max_dd = dd_analysis.get("max", {}) if isinstance(dd_analysis, dict) else {}

    signal_log_df = pd.DataFrame(getattr(strat, "signal_log", []) or [])
    order_log_df = pd.DataFrame(strat.order_log)
    trade_log_df = pd.DataFrame(strat.trade_log)
    position_log_raw_df = pd.DataFrame(strat.position_log)
    curve_base_df = build_daily_curve_base(strat.daily_value_log)
    position_log_schema = {
        "date": pl.Utf8,
        "code": pl.Utf8,
        "position_size": pl.Float64,
        "position_price": pl.Float64,
        "close": pl.Float64,
        "market_value": pl.Float64,
        "unrealized_pnl": pl.Float64,
        "cash_value": pl.Float64,
        "portfolio_value": pl.Float64,
        "positions_value": pl.Float64,
        "cost_basis": pl.Float64,
        "unrealized_return_pct": pl.Float64,
        "weight_pct": pl.Float64,
        "daily_pnl": pl.Float64,
        "daily_pnl_pct": pl.Float64,
        "contribution_pct": pl.Float64,
        "run_tag": pl.Utf8,
    }
    curve_value_pl_df = pl.from_pandas(
        curve_base_df[["date", "cash_value", "portfolio_value", "positions_value"]].copy(),
        include_index=False,
    ).with_columns(
        pl.col("date").cast(pl.Utf8),
        pl.col("cash_value").cast(pl.Float64, strict=False),
        pl.col("portfolio_value").cast(pl.Float64, strict=False),
        pl.col("positions_value").cast(pl.Float64, strict=False),
    )
    if not position_log_raw_df.empty:
        position_log_pl_df = (
            pl.from_pandas(position_log_raw_df, include_index=False)
            .with_columns(
                pl.col("date").cast(pl.Utf8),
                pl.col("code").cast(pl.Utf8),
                pl.col("position_size").cast(pl.Float64, strict=False),
                pl.col("position_price").cast(pl.Float64, strict=False),
                pl.col("close").cast(pl.Float64, strict=False),
                pl.col("market_value").cast(pl.Float64, strict=False),
                pl.col("unrealized_pnl").cast(pl.Float64, strict=False),
            )
            .join(curve_value_pl_df, on="date", how="left")
            .sort(["code", "date"])
            .with_columns(
                (pl.col("position_size") * pl.col("position_price")).alias("cost_basis"),
                pl.col("close").shift(1).over("code").alias("prev_close"),
                pl.col("market_value").shift(1).over("code").alias("prev_market_value"),
            )
            .with_columns(
                pl.when(pl.col("cost_basis").is_not_null() & (pl.col("cost_basis").abs() > 1e-12))
                .then(pl.col("unrealized_pnl") / pl.col("cost_basis"))
                .otherwise(None)
                .alias("unrealized_return_pct"),
                pl.when(pl.col("portfolio_value").is_not_null() & (pl.col("portfolio_value").abs() > 1e-12))
                .then(pl.col("market_value") / pl.col("portfolio_value"))
                .otherwise(None)
                .alias("weight_pct"),
                pl.when(pl.col("prev_close").is_not_null())
                .then(pl.col("position_size") * (pl.col("close") - pl.col("prev_close")))
                .otherwise(None)
                .alias("daily_pnl"),
                pl.when(pl.col("prev_market_value").is_not_null() & (pl.col("prev_market_value").abs() > 1e-12))
                .then(
                    (pl.col("position_size") * (pl.col("close") - pl.col("prev_close")))
                    / pl.col("prev_market_value")
                )
                .otherwise(None)
                .alias("daily_pnl_pct"),
                pl.when(pl.col("portfolio_value").is_not_null() & (pl.col("portfolio_value").abs() > 1e-12))
                .then(pl.col("unrealized_pnl") / pl.col("portfolio_value"))
                .otherwise(None)
                .alias("contribution_pct"),
            )
            .filter(pl.col("position_size").fill_null(0.0) != 0.0)
            .drop(["prev_close", "prev_market_value"])
            .with_columns(pl.lit(run_tag).alias("run_tag"))
            .sort(["date", "market_value", "code"], descending=[False, True, False])
        )
    else:
        position_log_pl_df = pl.DataFrame(schema=position_log_schema)
    position_log_df = position_log_pl_df.to_pandas()

    buy_hold_curve_base_df = build_daily_curve_base(benchmark_strat.daily_value_log)
    strategy_daily_returns_df = build_daily_returns(curve_base_df, "portfolio_value")
    benchmark_daily_returns_df = build_daily_returns(buy_hold_curve_base_df, "portfolio_value")
    aligned_return_df = strategy_daily_returns_df[["date", "daily_return"]].rename(
        columns={"daily_return": "strategy_daily_return"}
    ).merge(
        benchmark_daily_returns_df[["date", "daily_return"]].rename(columns={"daily_return": "benchmark_daily_return"}),
        on="date",
        how="inner",
    )

    annualized_return_pct = float(returns_analysis.get("rnorm100", np.nan))
    final_value = float(cerebro.broker.getvalue())
    total_commission = (
        float(pd.to_numeric(order_log_df["commission"], errors="coerce").fillna(0.0).sum())
        if "commission" in order_log_df.columns
        else 0.0
    )
    gross_final_value = final_value + total_commission
    cumulative_return_net_of_commission = final_value / INITIAL_CASH - 1.0
    cumulative_return_before_commission = gross_final_value / INITIAL_CASH - 1.0
    benchmark_cumulative_return = float(benchmark_cerebro.broker.getvalue()) / INITIAL_CASH - 1.0
    max_drawdown_pct = float(max_dd.get("drawdown", np.nan))
    sharpe_ratio = calc_sharpe_ratio(strategy_daily_returns_df.get("daily_return", pd.Series(dtype=float)))
    sortino_ratio = calc_sortino_ratio(strategy_daily_returns_df.get("daily_return", pd.Series(dtype=float)))
    calmar_ratio = calc_calmar_ratio(annualized_return_pct, max_drawdown_pct)
    information_ratio = calc_information_ratio(
        aligned_return_df.get("strategy_daily_return", pd.Series(dtype=float)),
        aligned_return_df.get("benchmark_daily_return", pd.Series(dtype=float)),
    )
    excess_return_downside_variance_ratio = calc_excess_return_downside_variance_ratio(
        cumulative_return_net_of_commission,
        benchmark_cumulative_return,
        aligned_return_df.get("strategy_daily_return", pd.Series(dtype=float)),
        aligned_return_df.get("benchmark_daily_return", pd.Series(dtype=float)),
    )
    weighted_risk_score = calc_weighted_risk_score(
        calmar_ratio=calmar_ratio,
        sortino_ratio=sortino_ratio,
        sharpe_ratio=sharpe_ratio,
    )

    trade_pnl_series = (
        pd.to_numeric(trade_log_df["pnlcomm"], errors="coerce").dropna()
        if "pnlcomm" in trade_log_df.columns
        else pd.Series(dtype=float)
    )
    win_rate = float((trade_pnl_series > 0).mean()) if len(trade_pnl_series) > 0 else np.nan
    profit_loss_ratio = calc_profit_loss_ratio(trade_log_df, pnl_col="pnlcomm")
    annual_turnover_rate = calc_annual_turnover_rate(order_log_df, curve_base_df, value_col="portfolio_value")
    avg_holding_days = (
        float(pd.to_numeric(trade_log_df.get("barlen"), errors="coerce").dropna().mean())
        if "barlen" in trade_log_df.columns
        else np.nan
    )
    median_holding_days = (
        float(pd.to_numeric(trade_log_df.get("barlen"), errors="coerce").dropna().median())
        if "barlen" in trade_log_df.columns
        else np.nan
    )
    avg_cash_ratio = calc_avg_cash_ratio(curve_base_df)
    stock_performance_summary = build_stock_performance_summary(
        order_log_df=order_log_df,
        trade_log_df=trade_log_df,
        position_log_df=position_log_df,
        final_value=final_value,
    )

    portfolio_curve_df = build_curve_rows(
        curve_base_df,
        htsc_code=PORTFOLIO_CURVE_CODE,
        security_id=PORTFOLIO_SECURITY_ID,
        security_type="portfolio_curve",
        value_col="portfolio_value",
    )
    cash_ratio_curve_base_df = curve_base_df.copy()
    cash_ratio_curve_base_df["cash_ratio"] = np.where(
        cash_ratio_curve_base_df["portfolio_value"].astype(float).abs() > 1e-12,
        cash_ratio_curve_base_df["cash_value"].astype(float) / cash_ratio_curve_base_df["portfolio_value"].astype(float),
        np.nan,
    )
    cash_curve_df = build_curve_rows(
        cash_ratio_curve_base_df,
        htsc_code=CASH_CURVE_CODE,
        security_id=CASH_SECURITY_ID,
        security_type="cash_ratio_curve",
        value_col="cash_ratio",
        normalize_by_initial_cash=False,
    )
    buy_hold_curve_df = build_curve_rows(
        buy_hold_curve_base_df,
        htsc_code=BUY_HOLD_CURVE_CODE,
        security_id=BUY_HOLD_SECURITY_ID,
        security_type="buy_hold_curve",
        value_col="portfolio_value",
    )
    curve_rows_df = pd.concat([portfolio_curve_df, cash_curve_df, buy_hold_curve_df], ignore_index=True)
    if write_frontend_curves:
        curve_base_path = STOCK_BASE_PATH / f"run_tag={run_tag}"
        curve_partition_paths = upsert_curve_rows_to_stock_daily(curve_rows_df, curve_base_path)
    else:
        curve_partition_paths = []

    summary_payload = {
        "backtest_start": backtest_start,
        "backtest_end": backtest_end,
        "backtest_end_inclusive": backtest_end_inclusive,
        "回测名称": str(run_name or "").strip(),
        "回测开始日期": backtest_start,
        "回测结束日期": backtest_end,
        "回测结束日期是否包含": backtest_end_inclusive,
        "初始资金": normalize_summary_value(INITIAL_CASH),
        "策略最终总资产（扣手续费）": normalize_summary_value(final_value),
        "扣手续费前最终资产": normalize_summary_value(gross_final_value),
        "总手续费": normalize_summary_value(total_commission),
        "买入持有最终资产": normalize_summary_value(float(benchmark_cerebro.broker.getvalue())),
        "最大回撤 (%)": normalize_summary_percent(max_drawdown_pct, already_percent=True),
        "最大回撤金额": normalize_summary_value(float(max_dd.get("moneydown", np.nan))),
        "夏普比率": normalize_summary_value(sharpe_ratio),
        "索提诺比率": normalize_summary_value(sortino_ratio),
        "卡玛比率": normalize_summary_value(calmar_ratio),
        "信息比率 IR": normalize_summary_value(information_ratio),
        "log((Rp-Rb)/下半方差（P）)": normalize_summary_value(excess_return_downside_variance_ratio),
        "0.45卡玛+0.4索提诺+0.15夏普": normalize_summary_value(weighted_risk_score),
        "胜率": normalize_summary_percent(win_rate),
        "盈亏比": normalize_summary_value(profit_loss_ratio),
        "总交易次数": normalize_summary_value(len(trade_log_df)),
        "年化换手率": normalize_summary_percent(annual_turnover_rate),
        "平均持仓天数": normalize_summary_value(avg_holding_days),
        "持仓天数中位数": normalize_summary_value(median_holding_days),
        "平均现金比例": normalize_summary_percent(avg_cash_ratio),
        "年化收益率 (%)": normalize_summary_percent(annualized_return_pct, already_percent=True),
        "累计收益率（扣手续费）": normalize_summary_percent(cumulative_return_net_of_commission),
        "扣手续费前累计收益": normalize_summary_percent(cumulative_return_before_commission),
        **stock_performance_summary,
    }
    summary_df = pd.DataFrame([summary_payload])

    position_log_path = SAVE_DIR / f"position_log_{run_tag}.parquet"
    order_log_path = SAVE_DIR / f"order_log_{run_tag}.parquet"
    summary_path = TOTAL_RECORD_DIR / f"summary_{run_tag}.json"

    position_log_write_pl_df = position_log_pl_df
    if position_log_write_pl_df.height > 0:
        position_log_write_pl_df = position_log_write_pl_df.unique(subset=["date", "code"], keep="last").sort(
            ["date", "market_value", "code"],
            descending=[False, True, False],
        )
    position_log_df = position_log_write_pl_df.to_pandas()
    position_log_write_pl_df.write_parquet(str(position_log_path), compression="zstd")
    order_log_columns = [
        "date",
        "code",
        "signal",
        "status",
        "side",
        "created_size",
        "executed_size",
        "executed_price",
        "executed_value",
        "commission",
        "target_value",
        "position_after",
        "cash_after",
        "portfolio_value_after",
    ]
    order_log_write_df = order_log_df.copy()
    for col in order_log_columns:
        if col not in order_log_write_df.columns:
            order_log_write_df[col] = pd.Series(dtype=object)
    order_log_write_df = order_log_write_df[order_log_columns]
    pl.from_pandas(order_log_write_df, include_index=False).write_parquet(str(order_log_path), compression="zstd")
    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    saved_paths = {
        "position_log": str(position_log_path),
        "order_log": str(order_log_path),
        "summary": str(summary_path),
    }
    curve_info = {
        "portfolio_curve_code": PORTFOLIO_CURVE_CODE,
        "cash_curve_code": CASH_CURVE_CODE,
        "buy_hold_curve_code": BUY_HOLD_CURVE_CODE,
        "stock_base_path": str(STOCK_BASE_PATH),
        "partition_paths": curve_partition_paths,
    }

    print(f"期末权益: {cerebro.broker.getvalue():,.2f}")
    print(f"Buy & Hold 期末权益: {benchmark_cerebro.broker.getvalue():,.2f}")
    print("收益统计:", returns_analysis)
    print("回撤:", dd_analysis)
    print("position_log 保存目录:", SAVE_DIR)
    print("summary 保存目录:", TOTAL_RECORD_DIR)
    print("保存文件:", saved_paths)
    print(
        "曲线代码:",
        curve_info["portfolio_curve_code"],
        curve_info["cash_curve_code"],
        curve_info["buy_hold_curve_code"],
    )
    if write_frontend_curves:
        print("写入 stock_portfolio_data_daily 分区:", curve_partition_paths)
    else:
        print("跳过写入 stock_portfolio_data_daily 分区（调参试跑）")

    return {
        "run_tag": run_tag,
        "cerebro": cerebro,
        "benchmark_cerebro": benchmark_cerebro,
        "strat": strat,
        "benchmark_strat": benchmark_strat,
        "returns_analysis": returns_analysis,
        "dd_analysis": dd_analysis,
        "signal_log_df": signal_log_df,
        "order_log_df": order_log_df,
        "trade_log_df": trade_log_df,
        "position_log_df": position_log_df,
        "curve_base_df": curve_base_df,
        "buy_hold_curve_base_df": buy_hold_curve_base_df,
        "summary_df": summary_df,
        "summary_payload": summary_payload,
        "portfolio_curve_df": portfolio_curve_df,
        "cash_curve_df": cash_curve_df,
        "buy_hold_curve_df": buy_hold_curve_df,
        "saved_paths": saved_paths,
        "curve_info": curve_info,
    }


# =============================================================================
# 曲线数据处理
# =============================================================================


def build_daily_curve_base(daily_value_log: list[dict]) -> pd.DataFrame:
    """从 daily_value_log 构建每日曲线基础数据。"""
    if not daily_value_log:
        return pd.DataFrame(columns=["date", "cash_value", "portfolio_value", "positions_value"])
    return pd.DataFrame(daily_value_log).sort_values("date").drop_duplicates(subset=["date"], keep="last")


def build_daily_returns(curve_df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """构建每日收益率序列。"""
    if curve_df.empty or value_col not in curve_df.columns:
        return pd.DataFrame(columns=["date", value_col, "daily_return"])

    out = curve_df[["date", value_col]].copy()
    out["date"] = pd.to_datetime(out["date"])
    out[value_col] = pd.to_numeric(out[value_col], errors="coerce")
    out = out.dropna(subset=[value_col]).sort_values("date").drop_duplicates(subset=["date"], keep="last")
    out["daily_return"] = out[value_col].pct_change()
    return out.dropna(subset=["daily_return"]).reset_index(drop=True)


def build_curve_rows(
    curve_df: pd.DataFrame,
    htsc_code: str,
    security_id: str,
    security_type: str,
    value_col: str,
    normalize_by_initial_cash: bool = True,
) -> pd.DataFrame:
    """构建曲线行数据用于输出到 Parquet。"""
    if curve_df.empty:
        return pd.DataFrame(columns=[
            "htsc_code", "time", "security_id", "frequency", "open", "close", "high", "low",
            "num_trades", "volume", "value", "security_type", "exchange", "month", "year",
        ])

    out = curve_df[["date", value_col]].copy()
    out["time"] = pd.to_datetime(out["date"]).dt.floor("D")
    if normalize_by_initial_cash:
        out["curve_price"] = out[value_col].astype(float) / INITIAL_CASH
    else:
        out["curve_price"] = out[value_col].astype(float)
    out["htsc_code"] = htsc_code
    out["security_id"] = security_id
    out["frequency"] = "daily"
    out["open"] = out["curve_price"]
    out["close"] = out["curve_price"]
    out["high"] = out["curve_price"]
    out["low"] = out["curve_price"]
    out["num_trades"] = 0.0
    out["volume"] = 0.0
    out["value"] = out[value_col].astype(float)
    out["security_type"] = security_type
    out["exchange"] = "YKRS"
    out["month"] = out["time"].dt.strftime("%m")
    out["year"] = out["time"].dt.strftime("%Y")
    out = out.drop(columns=["date", value_col, "curve_price"])

    return out[[
        "htsc_code", "time", "security_id", "frequency", "open", "close", "high", "low",
        "num_trades", "volume", "value", "security_type", "exchange", "month", "year",
    ]]


def write_parquet_overwrite(df: pd.DataFrame, target_path: Path) -> None:
    """原子写入 Parquet 文件。"""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_suffix(".tmp.parquet")
    if tmp_path.exists():
        tmp_path.unlink()
    pl_df = pl.from_pandas(df)
    pl_df.write_parquet(str(tmp_path), compression="zstd")
    tmp_path.replace(target_path)


def upsert_curve_rows_to_stock_daily(curve_rows_df: pd.DataFrame, base_path: Path) -> list[str]:
    """将曲线数据 upsert 到按年月分区的 Parquet。"""
    if curve_rows_df.empty:
        return []

    touched_paths: list[str] = []
    for (year, month), part_df in curve_rows_df.groupby(["year", "month"], sort=True):
        partition_dir = base_path / f"year={year}" / f"month={month}"
        partition_dir.mkdir(parents=True, exist_ok=True)
        merged_path = partition_dir / "merged.parquet"

        write_df = part_df.drop(columns=["year", "month"], errors="ignore")

        if merged_path.exists():
            existing_pl_df = pl.read_parquet(str(merged_path))
            existing_df = existing_pl_df.to_pandas()
            combined_df = pd.concat([existing_df, write_df], ignore_index=True)
            combined_df = combined_df.drop_duplicates(subset=["htsc_code", "time"], keep="last")
            combined_df = combined_df.sort_values(["htsc_code", "time"]).reset_index(drop=True)
        else:
            combined_df = write_df.sort_values(["htsc_code", "time"]).reset_index(drop=True)

        write_parquet_overwrite(combined_df, merged_path)
        touched_paths.append(str(merged_path))

    return touched_paths


# =============================================================================
# 指标计算函数
# =============================================================================


def calc_sharpe_ratio(return_series: pd.Series, annual_periods: int = 252, risk_free_rate_annual: float = 0.0) -> float:
    """计算夏普比率。"""
    if return_series is None or len(return_series) < 2:
        return np.nan
    clean = pd.to_numeric(return_series, errors="coerce").dropna()
    if len(clean) < 2:
        return np.nan
    daily_rf = risk_free_rate_annual / annual_periods
    excess = clean - daily_rf
    volatility = excess.std(ddof=1)
    if not np.isfinite(volatility) or volatility == 0:
        return np.nan
    return float(excess.mean() / volatility * np.sqrt(annual_periods))


def calc_sortino_ratio(return_series: pd.Series, annual_periods: int = 252, risk_free_rate_annual: float = 0.0) -> float:
    """计算索提诺比率。"""
    if return_series is None or len(return_series) < 2:
        return np.nan
    clean = pd.to_numeric(return_series, errors="coerce").dropna()
    if len(clean) < 2:
        return np.nan
    daily_rf = risk_free_rate_annual / annual_periods
    excess = clean - daily_rf
    downside = np.minimum(excess, 0.0)
    downside_dev = float(np.sqrt(np.mean(np.square(downside))))
    if not np.isfinite(downside_dev) or downside_dev == 0:
        return np.nan
    return float(excess.mean() / downside_dev * np.sqrt(annual_periods))


def calc_information_ratio(
    strategy_returns: pd.Series, benchmark_returns: pd.Series, annual_periods: int = 252
) -> float:
    """计算信息比率。"""
    aligned = pd.concat([
        pd.to_numeric(strategy_returns, errors="coerce").rename("strategy_return"),
        pd.to_numeric(benchmark_returns, errors="coerce").rename("benchmark_return"),
    ], axis=1).dropna()
    if len(aligned) < 2:
        return np.nan
    active_return = aligned["strategy_return"] - aligned["benchmark_return"]
    tracking_error = active_return.std(ddof=1)
    if not np.isfinite(tracking_error) or tracking_error == 0:
        return np.nan
    return float(active_return.mean() / tracking_error * np.sqrt(annual_periods))


def calc_excess_return_downside_variance_ratio(
    strategy_cumulative_return: float,
    benchmark_cumulative_return: float,
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
) -> float:
    """计算 sign(x) * log1p(abs(x))，x=(Rp - Rb) / 下半方差(P)。"""
    aligned = pd.concat([
        pd.to_numeric(strategy_returns, errors="coerce").rename("strategy_return"),
        pd.to_numeric(benchmark_returns, errors="coerce").rename("benchmark_return"),
    ], axis=1).dropna()
    if len(aligned) < 2:
        return np.nan
    active_return = aligned["strategy_return"] - aligned["benchmark_return"]
    downside = np.minimum(active_return, 0.0)
    downside_variance = float(np.mean(np.square(downside)))
    if not np.isfinite(downside_variance) or downside_variance == 0:
        return np.nan
    excess_return = float(strategy_cumulative_return) - float(benchmark_cumulative_return)
    if not np.isfinite(excess_return):
        return np.nan
    raw_ratio = float(excess_return / downside_variance)
    return float(np.sign(raw_ratio) * np.log1p(abs(raw_ratio)))


def calc_calmar_ratio(annual_return_pct: float, max_drawdown_pct: float) -> float:
    """计算卡玛比率。"""
    if not np.isfinite(annual_return_pct) or not np.isfinite(max_drawdown_pct):
        return np.nan
    max_drawdown_decimal = abs(max_drawdown_pct) / 100.0
    if max_drawdown_decimal == 0:
        return np.nan
    annual_return_decimal = annual_return_pct / 100.0
    return float(annual_return_decimal / max_drawdown_decimal)


def calc_weighted_risk_score(calmar_ratio: float, sortino_ratio: float, sharpe_ratio: float) -> float:
    """计算 0.45 * 卡玛 + 0.4 * 索提诺 + 0.15 * 夏普。"""
    values = [calmar_ratio, sortino_ratio, sharpe_ratio]
    if any(not np.isfinite(float(value)) for value in values):
        return np.nan
    return float(0.45 * calmar_ratio + 0.4 * sortino_ratio + 0.15 * sharpe_ratio)


def calc_profit_loss_ratio(trade_log_df: pd.DataFrame, pnl_col: str = "pnlcomm") -> float:
    """计算盈亏比。"""
    if pnl_col not in trade_log_df.columns or trade_log_df.empty:
        return np.nan
    profits = trade_log_df[trade_log_df[pnl_col] > 0][pnl_col].sum()
    losses = abs(trade_log_df[trade_log_df[pnl_col] < 0][pnl_col].sum())
    if losses == 0:
        return np.inf if profits > 0 else np.nan
    return profits / losses


def calc_avg_cash_ratio(curve_base_df: pd.DataFrame) -> float:
    """计算平均现金比例。"""
    if curve_base_df.empty or "portfolio_value" not in curve_base_df.columns:
        return np.nan
    total_value = curve_base_df["portfolio_value"].replace(0, np.nan)
    cash_ratio = curve_base_df["cash_value"] / total_value
    return float(cash_ratio.mean())


def calc_annual_turnover_rate(
    order_df: pd.DataFrame, curve_df: pd.DataFrame, value_col: str = "portfolio_value"
) -> float:
    """计算年化换手率。"""
    if order_df.empty or curve_df.empty or value_col not in curve_df.columns or "executed_value" not in order_df.columns:
        return np.nan

    executed_value = pd.to_numeric(order_df["executed_value"], errors="coerce").dropna().abs().sum()
    portfolio_values = pd.to_numeric(curve_df[value_col], errors="coerce").dropna()
    if executed_value <= 0 or portfolio_values.empty:
        return np.nan

    date_series = pd.to_datetime(curve_df["date"], errors="coerce").dropna().sort_values()
    if date_series.empty:
        return np.nan
    span_days = max((date_series.iloc[-1] - date_series.iloc[0]).days, 1)
    span_years = span_days / 365.25
    avg_portfolio_value = portfolio_values.mean()
    if not np.isfinite(avg_portfolio_value) or avg_portfolio_value <= 0 or span_years <= 0:
        return np.nan
    return float(executed_value / avg_portfolio_value / span_years)


# =============================================================================
# 数据序列化
# =============================================================================


def serialize_top_trade_records(trade_log_df: pd.DataFrame, top_n: int = 10, pnl_col: str = "pnlcomm") -> str:
    """序列化 Top N 交易记录。"""
    if trade_log_df.empty or pnl_col not in trade_log_df.columns:
        return "[]"
    out = trade_log_df.copy()
    out[pnl_col] = pd.to_numeric(out[pnl_col], errors="coerce")
    out = out.dropna(subset=[pnl_col])
    if out.empty:
        return "[]"
    out = out.sort_values(pnl_col, ascending=False).head(top_n)
    cols = [col for col in ["code", "date_open", "date_close", "barlen", pnl_col] if col in out.columns]
    return json.dumps(out[cols].to_dict(orient="records"), ensure_ascii=False)


def serialize_per_stock_total_pnl(trade_log_df: pd.DataFrame, pnl_col: str = "pnlcomm") -> str:
    """按股票序列化累计盈亏。"""
    if trade_log_df.empty or "code" not in trade_log_df.columns or pnl_col not in trade_log_df.columns:
        return "[]"
    out = trade_log_df[["code", pnl_col]].copy()
    out[pnl_col] = pd.to_numeric(out[pnl_col], errors="coerce")
    out = out.dropna(subset=[pnl_col])
    if out.empty:
        return "[]"
    grouped = (
        out.groupby("code", as_index=False)[pnl_col]
        .sum()
        .sort_values(pnl_col, ascending=False)
        .reset_index(drop=True)
    )
    return json.dumps(grouped.to_dict(orient="records"), ensure_ascii=False)


# =============================================================================
# 数据格式化
# =============================================================================


def normalize_summary_value(value: Any) -> Any:
    """标准化数值输出（保留两位小数）。"""
    if value is None:
        return None
    if isinstance(value, (np.floating, float, np.integer, int)):
        if not math.isfinite(float(value)):
            return None
        return round(float(value), 2)
    return value


def normalize_summary_percent(value: Any, already_percent: bool = False) -> Any:
    """标准化百分比输出（转为百分数字符串）。"""
    if value is None:
        return None
    if isinstance(value, (np.floating, float, np.integer, int)):
        if not math.isfinite(float(value)):
            return None
        v = float(value)
        if not already_percent:
            v = v * 100
        return f"{round(v, 2)}%"
    return value
