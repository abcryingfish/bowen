from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import backtrader as bt
import duckdb
import numpy as np
import pandas as pd
import polars as pl

INITIAL_CASH = 10_000_000.0
COMMISSION = 0.0003

PORTFOLIO_CURVE_CODE = "000000.YKRS"
CASH_CURVE_CODE = "0000000.YKRS"
BUY_HOLD_CURVE_CODE = "000001.YKRS"
PORTFOLIO_SECURITY_ID = "000000"
CASH_SECURITY_ID = "0000000"
BUY_HOLD_SECURITY_ID = "000001"

STOCK_BASE_PATH = Path(r"D:\database\stock_portfolio_data_daily")
SAVE_DIR = Path(r"D:\database\bs_dialy")
TOTAL_RECORD_DIR = Path(r"D:\database\total_record")
PRICE_BASE_PATH = r"D:\database\stock_basic_data_daily"
SIGNAL_BASE_PATH = Path(r"D:\database\signal_daily")

FACTOR_COLUMN_MAP = {
    "MAC总": "mac_total",
    "KDJ信号": "kdj_signal",
    "OBV多头排列": "obv_bullish",
    "抄底总分": "bottom_score",
}

BACKTEST_YEARS = [2019, 2020, 2021]
_INVALID_FACTOR_DIR_CHARS = re.compile(r'[\\/:*?"<>|]')


class FactorPandasData(bt.feeds.PandasData):
    """OHLCV feed with merged factor/signal columns."""

    lines = ("mac_total", "kdj_signal", "obv_bullish", "bottom_score", "rsi6", "rsi24")
    params = (
        ("mac_total", -1),
        ("kdj_signal", -1),
        ("obv_bullish", -1),
        ("bottom_score", -1),
        ("rsi6", -1),
        ("rsi24", -1),
    )


def create_duckdb_view(base_path: str, view_name: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(
        f"""
        CREATE OR REPLACE VIEW {view_name} AS
        SELECT *
        FROM read_parquet('{base_path}/year=*/month=*/merged.parquet', hive_partitioning=1)
        """
    )
    return con


def create_cerebro(target_codes: list[str], df_multi: pd.DataFrame, verbose: bool = True) -> bt.Cerebro:
    cerebro = bt.Cerebro()
    cerebro.broker.set_coc(True)
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)

    for code in target_codes:
        code_df = df_multi[df_multi["htsc_code"] == code].copy()
        code_df = code_df.sort_values("time").reset_index(drop=True)
        if code_df.empty:
            if verbose:
                print(f"⚠️ 股票 {code} 无数据，跳过")
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
            bottom_score="bottom_score" if "bottom_score" in code_df.columns else -1,
            rsi6="rsi6" if "rsi6" in code_df.columns else -1,
            rsi24="rsi24" if "rsi24" in code_df.columns else -1,
            timeframe=bt.TimeFrame.Days,
        )
        data._name = code
        cerebro.adddata(data)
        if verbose:
            print(f"✓ 已添加数据: {code} ({len(code_df)} 条)")
    return cerebro


def _sanitize_factor_dir_name(factor_name: str) -> str:
    safe_name = _INVALID_FACTOR_DIR_CHARS.sub("_", str(factor_name).strip())
    safe_name = safe_name.rstrip(" .")
    return safe_name or "未命名因子"


def _iter_year_month(start_dt: pd.Timestamp, end_dt: pd.Timestamp) -> list[tuple[int, int]]:
    cursor = pd.Timestamp(year=start_dt.year, month=start_dt.month, day=1)
    end_cursor = pd.Timestamp(year=end_dt.year, month=end_dt.month, day=1)
    result: list[tuple[int, int]] = []
    while cursor <= end_cursor:
        result.append((int(cursor.year), int(cursor.month)))
        cursor = cursor + pd.offsets.MonthBegin(1)
    return result


def _existing_factor_partition_paths(
    base_path: Path,
    factor_name: str,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
) -> list[str]:
    factor_dir = _sanitize_factor_dir_name(factor_name)
    paths: list[str] = []
    for year, month in _iter_year_month(start_dt, end_dt):
        p = base_path / f"factor={factor_dir}" / f"year={year}" / f"month={month:02d}" / "merged.parquet"
        if p.exists():
            paths.append(p.as_posix())
    return paths


def _sql_quote_string(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def load_signal_factor_wide(
    base_path: Path,
    factor_names: list[str],
    codes_sql_in_list: str,
    backtest_start: str,
    backtest_end: str,
) -> pd.DataFrame:
    start_dt = pd.Timestamp(backtest_start).floor("D")
    end_dt = pd.Timestamp(backtest_end).floor("D")
    con = duckdb.connect(database=":memory:")
    try:
        frames: list[pd.DataFrame] = []
        for factor_name in factor_names:
            paths = _existing_factor_partition_paths(base_path, factor_name, start_dt, end_dt)
            if not paths:
                continue

            path_list_sql = ", ".join([_sql_quote_string(p) for p in paths])
            factor_sql = f"""
                SELECT
                    CAST(time AS TIMESTAMP) AS time,
                    CAST(htsc_code AS VARCHAR) AS htsc_code,
                    TRY_CAST(value AS DOUBLE) AS value
                FROM read_parquet([{path_list_sql}], union_by_name=true)
                WHERE CAST(htsc_code AS VARCHAR) IN ({codes_sql_in_list})
                  AND CAST(time AS DATE) >= DATE '{backtest_start}'
                  AND CAST(time AS DATE) < DATE '{backtest_end}'
                ORDER BY htsc_code, time
            """
            factor_df = con.execute(factor_sql).df()
            if factor_df.empty:
                continue
            factor_df["time"] = pd.to_datetime(factor_df["time"]).dt.normalize()
            factor_df["htsc_code"] = factor_df["htsc_code"].astype(str)
            factor_df = factor_df.rename(columns={"value": factor_name})
            frames.append(factor_df[["time", "htsc_code", factor_name]])

        if not frames:
            return pd.DataFrame(columns=["time", "htsc_code", *factor_names])

        merged = frames[0]
        for frame in frames[1:]:
            merged = merged.merge(frame, on=["time", "htsc_code"], how="outer")
        for factor_name in factor_names:
            if factor_name not in merged.columns:
                merged[factor_name] = np.nan
        return merged.sort_values(["htsc_code", "time"]).reset_index(drop=True)
    finally:
        con.close()


class MacKdjBottomScoreBuyAndHoldStrategy(bt.Strategy):
    params = dict(max_weight=0.10)

    def __init__(self) -> None:
        self.order_meta = {}
        self.signal_log = []
        self.order_log = []
        self.trade_log = []
        self.position_log = []
        self._position_log_seen = set()
        self.daily_value_log = []
        self.pending_buy_signals = {}
        self.pending_sell_signals = {}
        self.pending_reinvest_after_sell = False
        self.recent_sold_codes: set[str] = set()

    def _reinvest_cash_after_sell(self, cash_available: float) -> None:
        """把现金均分后尝试买入未被卖出的其余持仓，买不动则跳过。"""
        if cash_available <= 0:
            return
        candidates: list[tuple[Any, float]] = []
        for d in self.datas:
            if d._name in self.recent_sold_codes:
                continue
            pos = self.getposition(d)
            if pos.size <= 0:
                continue
            close_px = float(d.close[0])
            if not np.isfinite(close_px) or close_px <= 0:
                continue
            candidates.append((d, close_px))

        if not candidates:
            return

        per_stock_cash = cash_available / len(candidates)
        if per_stock_cash <= 0:
            return

        lot_size = 100
        for d, close_px in candidates:
            # 按一手(100股)取整，确保“买不了就不买”
            shares = int(per_stock_cash / (close_px * (1.0 + COMMISSION)))
            shares = (shares // lot_size) * lot_size
            if shares < lot_size:
                continue
            dt_str = self._dt_str(d)
            order = self.buy(data=d, size=shares)
            if order is not None:
                self.order_meta[order.ref] = {
                    "signal": "REINVEST_AFTER_SELL_AVG_CASH",
                    "target_value": float(shares * close_px),
                    "date": dt_str,
                }

    def _dt_str(self, data: Any) -> str:
        return bt.num2date(data.datetime[0]).strftime("%Y-%m-%d")

    def _record_position_snapshot(self, data: Any) -> None:
        dt_str = self._dt_str(data)
        key = (dt_str, data._name)
        if key in self._position_log_seen:
            return
        self._position_log_seen.add(key)
        pos = self.getposition(data)
        close_px = float(data.close[0])
        market_value = pos.size * close_px
        cost_basis = pos.size * float(pos.price)
        self.position_log.append(
            {
                "date": dt_str,
                "code": data._name,
                "position_size": pos.size,
                "position_price": float(pos.price),
                "close": close_px,
                "market_value": market_value,
                "unrealized_pnl": market_value - cost_basis,
            }
        )

    def next(self) -> None:
        total_value = self.broker.getvalue()
        cash_before = self.broker.getcash()
        candidates = []
        next_buy_signals = {}
        next_sell_signals = {}

        for d in self.datas:
            self._record_position_snapshot(d)
            pos = self.getposition(d)
            close_px = float(d.close[0])
            if not np.isfinite(close_px) or close_px <= 0:
                continue

            mac_total = float(d.mac_total[0]) if np.isfinite(float(d.mac_total[0])) else 0.0
            kdj_signal = float(d.kdj_signal[0]) if np.isfinite(float(d.kdj_signal[0])) else 0.0
            obv_bullish = float(d.obv_bullish[0]) if np.isfinite(float(d.obv_bullish[0])) else 0.0
            bottom_score = float(d.bottom_score[0]) if np.isfinite(float(d.bottom_score[0])) else 0.0

            pending_sell = self.pending_sell_signals.pop(d._name, None)
            pending_buy = self.pending_buy_signals.pop(d._name, None)
            dt_str = self._dt_str(d)

            if pending_sell is not None and pos.size > 0:
                order = self.close(data=d)
                if order is not None:
                    self.order_meta[order.ref] = {"signal": "SELL_OBV_BULLISH_NEXT_CLOSE", "target_value": 0.0, "date": dt_str}
                continue

            if pending_buy is not None and pos.size == 0:
                candidates.append((d, close_px, pending_buy))
                continue

            if pos.size > 0 and obv_bullish > 0:
                next_sell_signals[d._name] = {"signal_date": dt_str, "mac_total": mac_total, "kdj_signal": kdj_signal, "obv_bullish": obv_bullish, "bottom_score": bottom_score}
            elif pos.size == 0 and obv_bullish <= 0 and mac_total > 0 and kdj_signal > 0 and bottom_score > 0:
                next_buy_signals[d._name] = {"signal_date": dt_str, "mac_total": mac_total, "kdj_signal": kdj_signal, "obv_bullish": obv_bullish, "bottom_score": bottom_score}

        if self.pending_reinvest_after_sell and cash_before > 0:
            self._reinvest_cash_after_sell(cash_before)
            self.pending_reinvest_after_sell = False
            self.recent_sold_codes.clear()

        if candidates and cash_before > 0 and total_value > 0:
            per_stock_cash = cash_before / len(candidates)
            max_target_value = total_value * self.p.max_weight
            for d, _close_px, _pending_buy in candidates:
                dt_str = self._dt_str(d)
                target_value = min(per_stock_cash, max_target_value)
                if target_value <= 0:
                    continue
                order = self.order_target_value(data=d, target=target_value)
                if order is not None:
                    self.order_meta[order.ref] = {"signal": "BUY_MAC_KDJ_BOTTOM_SCORE_NEXT_CLOSE", "target_value": target_value, "date": dt_str}

        self.pending_buy_signals = next_buy_signals
        self.pending_sell_signals = next_sell_signals

    def notify_cashvalue(self, cash: float, value: float) -> None:
        if len(self) <= 0:
            return
        dt_str = bt.num2date(self.datetime[0]).strftime("%Y-%m-%d")
        payload = {"date": dt_str, "cash_value": float(cash), "portfolio_value": float(value), "positions_value": float(value) - float(cash)}
        if self.daily_value_log and self.daily_value_log[-1]["date"] == dt_str:
            self.daily_value_log[-1].update(payload)
        else:
            self.daily_value_log.append(payload)

    def notify_order(self, order: Any) -> None:
        if order.status not in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            return
        data = order.data
        meta = self.order_meta.get(order.ref, {})
        executed = order.executed
        self.order_log.append(
            {
                "date": meta.get("date") or self._dt_str(data),
                "code": data._name,
                "signal": meta.get("signal", ""),
                "status": order.getstatusname(),
                "side": "BUY" if order.isbuy() else "SELL",
                "created_size": float(order.created.size or 0.0),
                "executed_size": float(executed.size or 0.0),
                "executed_price": float(executed.price or 0.0),
                "executed_value": float(executed.value or 0.0),
                "commission": float(executed.comm or 0.0),
                "target_value": float(meta.get("target_value") or 0.0),
                "position_after": float(self.getposition(data).size),
                "cash_after": float(self.broker.getcash()),
                "portfolio_value_after": float(self.broker.getvalue()),
            }
        )
        if order.status == order.Completed and order.issell():
            self.pending_reinvest_after_sell = True
            self.recent_sold_codes.add(data._name)

    def notify_trade(self, trade: Any) -> None:
        if not trade.isclosed:
            return
        self.trade_log.append(
            {
                "code": trade.data._name,
                "date_open": bt.num2date(trade.dtopen).strftime("%Y-%m-%d") if trade.dtopen else None,
                "date_close": bt.num2date(trade.dtclose).strftime("%Y-%m-%d") if trade.dtclose else None,
                "barlen": int(trade.barlen or 0),
                "pnl": float(trade.pnl),
                "pnlcomm": float(trade.pnlcomm),
            }
        )


class BuyAndHoldBenchmarkStrategy(bt.Strategy):
    def __init__(self) -> None:
        self.daily_value_log = []
        self._initialized = False

    def nextstart(self) -> None:
        if self._initialized:
            return
        valid_datas = [d for d in self.datas if len(d) > 0 and np.isfinite(float(d.close[0])) and float(d.close[0]) > 0]
        if not valid_datas:
            return
        target_weight = 1.0 / len(valid_datas)
        for d in valid_datas:
            self.order_target_percent(data=d, target=target_weight)
        self._initialized = True

    def notify_cashvalue(self, cash: float, value: float) -> None:
        if len(self) <= 0:
            return
        dt_str = bt.num2date(self.datetime[0]).strftime("%Y-%m-%d")
        payload = {"date": dt_str, "cash_value": float(cash), "portfolio_value": float(value), "positions_value": float(value) - float(cash)}
        if self.daily_value_log and self.daily_value_log[-1]["date"] == dt_str:
            self.daily_value_log[-1].update(payload)
        else:
            self.daily_value_log.append(payload)


def _normalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.floating, float, np.integer, int)):
        if not math.isfinite(float(value)):
            return None
        return round(float(value), 4)
    return value


def _normalize_value(value: Any, digits: int = 2) -> Any:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value
    if not math.isfinite(numeric):
        return None
    return round(numeric, digits)


def _normalize_percent(value: Any) -> str | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return f"{round(numeric * 100, 2)}%"


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
                        "realized_pnl": _normalize_value(realized_pnl),
                        "buy_cost": _normalize_value(buy_cost),
                        "realized_return_pct": _normalize_percent(realized_pnl / buy_cost) if abs(buy_cost) > 1e-12 else None,
                        "contribution_pct": _normalize_percent(realized_pnl / strategy_profit) if abs(strategy_profit) > 1e-12 else None,
                        "trade_count": int(row.get("trade_count") or 0),
                        "first_entry_date": row.get("first_entry_date"),
                        "last_exit_date": row.get("last_exit_date"),
                        "holding_days": _normalize_value(row.get("holding_days"), 0),
                    }
                )

    open_items: list[dict[str, Any]] = []
    if not final_position_df.empty:
        for _, row in final_position_df.sort_values("market_value", ascending=False).iterrows():
            market_value = float(row.get("market_value") or 0.0)
            position_size = float(row.get("position_size") or 0.0)
            position_price = float(row.get("position_price") or 0.0)
            close = float(row.get("close") or 0.0)
            cost_basis = position_size * position_price
            unrealized_pnl = market_value - cost_basis
            code = str(row.get("code", ""))
            realized_pnl = float(realized_pnl_by_code.get(code, 0.0) or 0.0)
            total_pnl = realized_pnl + unrealized_pnl
            open_items.append(
                {
                    "code": code,
                    "unrealized_return_pct": _normalize_percent(unrealized_pnl / cost_basis) if abs(cost_basis) > 1e-12 else None,
                    "realized_pnl": _normalize_value(realized_pnl),
                    "unrealized_pnl": _normalize_value(unrealized_pnl),
                    "total_pnl": _normalize_value(total_pnl),
                    "contribution_pct": _normalize_percent(total_pnl / strategy_profit) if abs(strategy_profit) > 1e-12 else None,
                    "weight_pct": _normalize_percent(market_value / final_value) if abs(final_value) > 1e-12 else None,
                    "market_value": _normalize_value(market_value),
                    "position_size": _normalize_value(position_size, 0),
                    "close": _normalize_value(close),
                }
            )

    return {
        "已平仓股票表现": closed_items,
        "期末持仓股票表现": open_items,
    }


def run_zxw_backtest(
    target_codes: list[str],
    df_multi: pd.DataFrame,
    backtest_start: str,
    backtest_end: str,
) -> dict[str, Any]:
    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    TOTAL_RECORD_DIR.mkdir(parents=True, exist_ok=True)

    cerebro = create_cerebro(target_codes, df_multi, verbose=False)
    cerebro.addstrategy(MacKdjBottomScoreBuyAndHoldStrategy, max_weight=0.10)
    results = cerebro.run()
    strat = results[0]

    benchmark_cerebro = create_cerebro(target_codes, df_multi, verbose=False)
    benchmark_cerebro.addstrategy(BuyAndHoldBenchmarkStrategy)
    benchmark_cerebro.run()

    final_value = float(cerebro.broker.getvalue())
    benchmark_value = float(benchmark_cerebro.broker.getvalue())
    order_log_df = pd.DataFrame(strat.order_log)
    trade_log_df = pd.DataFrame(strat.trade_log)
    position_log_df = pd.DataFrame(strat.position_log)
    stock_performance = build_stock_performance_summary(
        order_log_df=order_log_df,
        trade_log_df=trade_log_df,
        position_log_df=position_log_df,
        final_value=final_value,
    )
    summary_payload = {
        "backtest_start": backtest_start,
        "backtest_end": backtest_end,
        "初始资金": _normalize(INITIAL_CASH),
        "策略最终总资产（扣手续费）": _normalize(final_value),
        "买入持有最终资产": _normalize(benchmark_value),
        "累计收益率（扣手续费）": _normalize(final_value / INITIAL_CASH - 1.0),
        **stock_performance,
    }

    summary_path = TOTAL_RECORD_DIR / f"summary_{run_tag}.json"
    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"run_tag": run_tag, "summary": summary_payload, "summary_path": str(summary_path)}


def run_yearly_backtests(years: list[int]) -> pd.DataFrame:
    price_view_name = "price_day_merged"
    price_con = create_duckdb_view(base_path=PRICE_BASE_PATH, view_name=price_view_name)

    summary_rows: list[dict[str, Any]] = []
    for year in years:
        backtest_start = f"{year}-01-01"
        backtest_end = f"{year + 1}-01-01"
        pool_path = Path(rf"D:\database\{year}.csv")
        if not pool_path.exists():
            print(f"⚠️ 股票池不存在，跳过 {year}: {pool_path}")
            continue

        code_df = duckdb.read_csv(str(pool_path)).df()
        target_codes = code_df["证券代码"].dropna().astype(str).tolist()
        if not target_codes:
            print(f"⚠️ 股票池为空，跳过 {year}")
            continue

        codes_str = ", ".join([f"'{code}'" for code in target_codes])
        print("=" * 80)
        print(f"开始回测 {year}: 区间=[{backtest_start}, {backtest_end})")

        price_df = price_con.execute(
            f"""
            SELECT *
            FROM {price_view_name}
            WHERE htsc_code IN ({codes_str})
              AND time >= '{backtest_start}'
              AND time < '{backtest_end}'
            ORDER BY htsc_code, time
            """
        ).df()
        price_df["time"] = pd.to_datetime(price_df["time"]).dt.normalize()

        signal_df = load_signal_factor_wide(
            base_path=SIGNAL_BASE_PATH,
            factor_names=list(FACTOR_COLUMN_MAP.keys()),
            codes_sql_in_list=codes_str,
            backtest_start=backtest_start,
            backtest_end=backtest_end,
        )
        signal_factor_df = signal_df.rename(columns=FACTOR_COLUMN_MAP)
        bt_df = price_df.merge(signal_factor_df, on=["time", "htsc_code"], how="left")
        for factor_col in FACTOR_COLUMN_MAP.values():
            bt_df[factor_col] = pd.to_numeric(bt_df[factor_col], errors="coerce").fillna(0.0)

        out = run_zxw_backtest(target_codes=target_codes, df_multi=bt_df, backtest_start=backtest_start, backtest_end=backtest_end)
        row = {"year": year, **out["summary"], "summary_path": out["summary_path"]}
        summary_rows.append(row)
        print(f"{year} 回测完成，summary: {out['summary_path']}")

    return pd.DataFrame(summary_rows)


if __name__ == "__main__":
    result_df = run_yearly_backtests(BACKTEST_YEARS)
    print("=" * 80)
    print("年度回测汇总:")
    if result_df.empty:
        print("无可用回测结果。")
    else:
        print(result_df.to_string(index=False))
