#!/usr/bin/python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parents[1]
FACTOR_DIR = ROOT_DIR / "实盘环境" / "实盘因子"
if str(CURRENT_DIR) not in sys.path:
    sys.path.append(str(CURRENT_DIR))
if str(FACTOR_DIR) not in sys.path:
    sys.path.append(str(FACTOR_DIR))

from realtime_factor_core import (  # noqa: E402
    CodeRuntimeState,
    factor_state_db_path,
    save_runtime_states,
)
from KDJ因子 import build_kdj_factor_bundle  # noqa: E402
from MACD因子 import build_d_class_factor_bundle  # noqa: E402
from 均线因子 import build_ma_class_zxw_bundle  # noqa: E402
from 抄底因子 import build_bottom_fishing_factor_bundle  # noqa: E402
from 筹码结构因子 import (  # noqa: E402
    CHOUMA_AC,
    CHOUMA_MIN_D,
    CHOUMA_USE_VOLUME,
    _COST_PERCENTILES,
    _fill_costs_from_chip_py,
    _safe_divide,
    build_chip_structure_factor_bundle,
    _update_chip_one_day_py,
)


DEFAULT_DAILY_BAR_DIR = Path(r"D:\database\stock_basic_data_daily")
DEFAULT_EQUITY_DIR = Path(r"D:\database\stock_financial_statements\market_equity_data")
HISTORY_DAYS = 1300


def _read_recent_daily(base_dir: Path, end_date: str, days: int) -> pd.DataFrame:
    pattern = (base_dir / "year=*" / "month=*" / "merged.parquet").as_posix()
    end_exclusive = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    query = f"""
        WITH src AS (
            SELECT
                htsc_code,
                time,
                TRY_CAST(open AS DOUBLE) AS open,
                TRY_CAST(high AS DOUBLE) AS high,
                TRY_CAST(low AS DOUBLE) AS low,
                TRY_CAST(close AS DOUBLE) AS close,
                TRY_CAST(volume AS DOUBLE) AS volume
            FROM read_parquet('{pattern}', hive_partitioning=1, union_by_name=true)
            WHERE time < TIMESTAMP '{end_exclusive}'
        ),
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY htsc_code ORDER BY time DESC
            ) AS rn
            FROM src
        )
        SELECT
            htsc_code,
            CAST(time AS DATE) AS time,
            open,
            high,
            low,
            close,
            volume
        FROM ranked
        WHERE rn <= {int(days)}
        ORDER BY htsc_code, time
    """
    return duckdb.connect().execute(query).fetch_df()


def _read_recent_equity(base_dir: Path, end_date: str, days: int) -> pd.DataFrame:
    pattern = (base_dir / "year=*" / "month=*" / "merged.parquet").as_posix()
    end_exclusive = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    query = f"""
        WITH src AS (
            SELECT
                htsc_code,
                time,
                TRY_CAST(turnover_rate AS DOUBLE) AS turnover_rate,
                TRY_CAST(floating_market_val AS DOUBLE) AS floating_market_val,
                TRY_CAST(close AS DOUBLE) AS close
            FROM read_parquet('{pattern}', hive_partitioning=1, union_by_name=true)
            WHERE time < TIMESTAMP '{end_exclusive}'
        ),
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY htsc_code ORDER BY time DESC
            ) AS rn
            FROM src
        )
        SELECT
            htsc_code,
            CAST(time AS DATE) AS time,
            turnover_rate,
            floating_market_val,
            close
        FROM ranked
        WHERE rn <= {int(days)}
        ORDER BY htsc_code, time
    """
    return duckdb.connect().execute(query).fetch_df()


def _compute_prior_super_strong_no_concentration(
    group: pd.DataFrame,
    equity_group: pd.DataFrame,
) -> np.ndarray:
    if len(group) == 0:
        return np.zeros(4, dtype=np.float64)
    pivot = group.set_index("time")
    code = str(group["htsc_code"].iloc[0])
    idx = pd.Index(pivot.index.astype(str).tolist())
    O = pd.DataFrame({code: pivot["open"].to_numpy(dtype=float)}, index=idx)
    H = pd.DataFrame({code: pivot["high"].to_numpy(dtype=float)}, index=idx)
    L = pd.DataFrame({code: pivot["low"].to_numpy(dtype=float)}, index=idx)
    C = pd.DataFrame({code: pivot["close"].to_numpy(dtype=float)}, index=idx)
    mac = build_d_class_factor_bundle(O=O, H=H, L=L, C=C)["factor_dfs"]
    kdj = build_kdj_factor_bundle(O=O, H=H, L=L, C=C)["factor_dfs"]
    bottom = build_bottom_fishing_factor_bundle(O=O, H=H, L=L, C=C)["factor_dfs"]
    ma = build_ma_class_zxw_bundle(C=C)["factor_dfs"]
    V = pd.DataFrame({code: pivot["volume"].to_numpy(dtype=float)}, index=idx)
    turnover_by_date = equity_group.set_index("time")["turnover_rate"]
    T = pd.DataFrame(
        {code: [float(turnover_by_date.get(day, 0.0) or 0.0) for day in group["time"]]},
        index=idx,
    )
    chip = build_chip_structure_factor_bundle(H=H, L=L, C=C, V=V, T=T)["factor_dfs"]
    base = (
        (mac["mac_total"].astype(float) > 0.0)
        & (bottom["kline_bottom"].astype(float) > 0.0)
        & (ma["ma_class_zxw"].astype(float) > 0.0)
        & kdj["r_condition"].astype(bool)
        & (chip["chip_peak_score"].astype(float) > 0.0)
        & (C.notna().cumsum() >= 250)
    )
    return base.astype(float).iloc[-4:, 0].to_numpy(dtype=np.float64)


def _build_chip_state(
    group: pd.DataFrame,
    equity_group: pd.DataFrame,
) -> tuple[np.ndarray, float, int, np.ndarray, float, float]:
    eq = equity_group.set_index("time")
    chip = np.zeros(0, dtype=np.float64)
    base_low = 0.0
    n_bins = 0
    recent_abs: list[float] = []
    cum_high = np.nan
    cum_low = np.nan
    targets = _COST_PERCENTILES / 100.0
    for row in group.itertuples(index=False):
        h = float(row.high)
        l = float(row.low)
        c = float(row.close)
        v = float(row.volume) if row.volume == row.volume else 0.0
        turnover_pct = eq["turnover_rate"].get(row.time, 0.0)
        turnover_dec = float(turnover_pct or 0.0) / 100.0
        chip, base_low, n_bins = _update_chip_one_day_py(
            chip,
            base_low,
            n_bins,
            h,
            l,
            v,
            turnover_dec,
            CHOUMA_MIN_D,
            CHOUMA_AC,
            CHOUMA_USE_VOLUME,
        )
        cost_out = np.zeros((len(_COST_PERCENTILES), 1), dtype=np.float64)
        _fill_costs_from_chip_py(chip, base_low, CHOUMA_MIN_D, n_bins, targets, cost_out, 0)
        cost = {int(p): float(cost_out[i, 0]) for i, p in enumerate(_COST_PERCENTILES)}
        cum_high = np.nanmax([cum_high, h])
        cum_low = np.nanmin([cum_low, l])
        abs_conc = float(_safe_divide(
            np.array([(cost[95] - cost[5]) * 100.0]),
            np.array([cum_high - cum_low]),
        )[0])
        recent_abs.append(abs_conc)
    return chip, base_low, n_bins, np.asarray(recent_abs[-1200:], dtype=np.float64), float(cum_high), float(cum_low)


def _float_shares_from_equity(equity_group: pd.DataFrame, daily_group: pd.DataFrame) -> float:
    merged = equity_group.merge(
        daily_group[["time", "close"]],
        on="time",
        how="left",
        suffixes=("_eq", "_daily"),
    )
    for row in reversed(list(merged.itertuples(index=False))):
        close = getattr(row, "close_eq", None) or getattr(row, "close_daily", None)
        mv = getattr(row, "floating_market_val", None)
        if mv is not None and close is not None and close == close and close > 0:
            return float(mv) / float(close)
    return 0.0


def build_states(daily: pd.DataFrame, equity: pd.DataFrame, state_date: str) -> list[CodeRuntimeState]:
    equity_by_code = {code: g.copy() for code, g in equity.groupby("htsc_code")}
    states: list[CodeRuntimeState] = []
    for code, group in daily.groupby("htsc_code"):
        group = group.sort_values("time").copy()
        eq_group = equity_by_code.get(code)
        if eq_group is None or len(group) < 260:
            continue
        eq_group = eq_group.sort_values("time").copy()
        chip, base_low, n_bins, recent_abs, cum_high, cum_low = _build_chip_state(group, eq_group)
        float_shares = _float_shares_from_equity(eq_group, group)
        if float_shares <= 0:
            continue
        states.append(
            CodeRuntimeState(
                htsc_code=str(code),
                state_date=state_date,
                history_dates=[str(x)[:10] for x in group["time"].tolist()],
                open_history=group["open"].to_numpy(dtype=np.float64),
                high_history=group["high"].to_numpy(dtype=np.float64),
                low_history=group["low"].to_numpy(dtype=np.float64),
                close_history=group["close"].to_numpy(dtype=np.float64),
                volume_history=group["volume"].to_numpy(dtype=np.float64)[-124:],
                float_shares=float_shares,
                chip=chip,
                chip_base_low=base_low,
                chip_n_bins=n_bins,
                recent_abs_concentration=recent_abs,
                cum_high=cum_high,
                cum_low=cum_low,
                prior_super_strong_no_concentration=_compute_prior_super_strong_no_concentration(
                    group, eq_group
                ),
            )
        )
    return states


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="盘前准备实时三因子状态缓存")
    parser.add_argument("--state-date", default=datetime.now().strftime("%Y-%m-%d"), help="状态截止日期，默认今天")
    parser.add_argument("--trading-day", default=datetime.now().strftime("%Y-%m-%d"), help="实盘交易日，默认今天")
    parser.add_argument("--daily-dir", default=str(DEFAULT_DAILY_BAR_DIR), help="日线 parquet 根目录")
    parser.add_argument("--equity-dir", default=str(DEFAULT_EQUITY_DIR), help="日 basic/换手率 parquet 根目录")
    parser.add_argument("--state-db", default="", help="输出状态 SQLite，默认 D:\\database\\realtime_factor_state\\factor_state_YYYY-MM-DD.sqlite")
    parser.add_argument("--history-days", type=int, default=HISTORY_DAYS, help="每只股票读取历史天数")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    state_db = Path(args.state_db) if str(args.state_db).strip() else factor_state_db_path(args.trading_day)
    print(f"[READ] daily={args.daily_dir}")
    daily = _read_recent_daily(Path(args.daily_dir), args.state_date, int(args.history_days))
    print(f"[READ] equity={args.equity_dir}")
    equity = _read_recent_equity(Path(args.equity_dir), args.state_date, int(args.history_days))
    print(f"[BUILD] daily_rows={len(daily)} equity_rows={len(equity)}")
    states = build_states(daily, equity, args.state_date)
    saved = save_runtime_states(state_db, states, trading_day=args.trading_day)
    print(f"[OK] saved_states={saved} db={state_db}")


if __name__ == "__main__":
    main()
