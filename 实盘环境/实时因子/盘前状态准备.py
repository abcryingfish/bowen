#!/usr/bin/python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import importlib
import sys
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parents[1]
FACTOR_DIR = ROOT_DIR / "ZXW因子"
if str(CURRENT_DIR) not in sys.path:
    sys.path.append(str(CURRENT_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))
if str(FACTOR_DIR) not in sys.path:
    sys.path.append(str(FACTOR_DIR))

from realtime_factor_core import (  # noqa: E402
    CodeRuntimeState,
    RealtimeFactorEngine,
    default_chip_provider_factory,
    default_fast_signal_provider_factory,
    default_sell_volume_provider_factory,
    factor_state_db_path,
    load_runtime_states,
    save_runtime_states,
)
def _load_zxw_module(filename: str):
    module_name = f"ZXW因子.{Path(filename).stem}"
    return importlib.import_module(module_name)


_zxw_kdj = _load_zxw_module("KDJ因子.py")
_zxw_macd = _load_zxw_module("MACD因子.py")
_zxw_ma = _load_zxw_module("均线因子.py")
_zxw_bottom = _load_zxw_module("抄底因子.py")
_zxw_chip = _load_zxw_module("筹码结构因子.py")
build_kdj_factor_bundle = _zxw_kdj.build_kdj_factor_bundle
build_d_class_factor_bundle = _zxw_macd.build_d_class_factor_bundle
build_ma_class_zxw_bundle = _zxw_ma.build_ma_class_zxw_bundle
build_bottom_fishing_factor_bundle = _zxw_bottom.build_bottom_fishing_factor_bundle
CHOUMA_AC = _zxw_chip.CHOUMA_AC
CHOUMA_MIN_D = _zxw_chip.CHOUMA_MIN_D
CHOUMA_USE_VOLUME = _zxw_chip.CHOUMA_USE_VOLUME
_COST_PERCENTILES = _zxw_chip._COST_PERCENTILES
build_chip_structure_factor_bundle = _zxw_chip.build_chip_structure_factor_bundle


def _compute_chouma_cost_series_with_state(*args, **kwargs):
    try:
        return _zxw_chip._compute_chouma_cost_series_with_state(*args, **kwargs)
    except ModuleNotFoundError as exc:
        if exc.name != "<dynamic>":
            raise
        dispatcher = _zxw_chip._compute_chouma_cost_series_numba_with_state
        dispatcher._cache.flush()
        return _zxw_chip._compute_chouma_cost_series_with_state(*args, **kwargs)


DEFAULT_DAILY_BAR_DIR = Path(r"D:\database\stock_basic_data_daily")
DEFAULT_EQUITY_DIR = Path(r"D:\database\qmt_turnover_data")
DEFAULT_ADJ_FACTOR_DIR = Path(r"D:\database\stock_adj_daily\adj_factor_daily")
DEFAULT_STATE_DB = Path(r"D:\database\realtime_factor_state\factor_state.sqlite")
HISTORY_DAYS = 1300


def _configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def apply_backward_adjustment(daily: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    """按股票使用不晚于交易日的最近有效后复权因子。"""
    left = daily.copy()
    left["htsc_code"] = left["htsc_code"].astype(str).str.strip().str.upper()
    left["time"] = pd.to_datetime(left["time"]).dt.normalize()
    right = factors.copy()
    right["htsc_code"] = right["htsc_code"].astype(str).str.strip().str.upper()
    right["time"] = pd.to_datetime(right["time"]).dt.normalize()
    right["adj_factor"] = pd.to_numeric(right["adj_factor"], errors="coerce")
    right = right[np.isfinite(right["adj_factor"]) & (right["adj_factor"] > 0.0)].copy()
    right = right.rename(columns={"time": "adj_factor_date"})
    left = left.sort_values(["time", "htsc_code"]).reset_index(drop=True)
    right = right.sort_values(["adj_factor_date", "htsc_code"]).reset_index(drop=True)
    if right.empty:
        left["adj_factor"] = 1.0
        left["adj_factor_date"] = pd.NaT
    else:
        left = pd.merge_asof(
            left,
            right[["htsc_code", "adj_factor_date", "adj_factor"]],
            left_on="time",
            right_on="adj_factor_date",
            by="htsc_code",
            direction="backward",
        )
        left["adj_factor"] = pd.to_numeric(left["adj_factor"], errors="coerce").fillna(1.0)
    for column in ("open", "high", "low", "close"):
        if column in left.columns:
            left[column] = pd.to_numeric(left[column], errors="coerce") * left["adj_factor"]
    return left.sort_values(["htsc_code", "time"]).reset_index(drop=True)


def _quote_from_adjusted_row(row, day: pd.Timestamp) -> dict[str, object]:
    factor = float(getattr(row, "adj_factor", 1.0) or 1.0)
    if not np.isfinite(factor) or factor <= 0.0:
        factor = 1.0
    return {
        "htsc_code": str(row.htsc_code).upper(),
        "ts": f"{pd.Timestamp(day):%Y-%m-%d} 15:00:00",
        "last_price": float(row.close) / factor,
        "open": float(row.open) / factor,
        "high": float(row.high) / factor,
        "low": float(row.low) / factor,
        "volume": float(row.volume or 0.0),
        "pvolume": float(row.volume or 0.0),
    }


def append_history(dates: list[str], values: np.ndarray, day: str, value: float, *, limit: int = HISTORY_DAYS) -> tuple[list[str], np.ndarray]:
    next_dates = [*dates, str(day)][-int(limit):]
    next_values = np.append(np.asarray(values, dtype=np.float64), float(value))[-int(limit):]
    return next_dates, next_values


def state_latest_date(states: dict[str, CodeRuntimeState]) -> pd.Timestamp | None:
    dates = [pd.Timestamp(state.state_date).floor("D") for state in states.values() if str(state.state_date).strip()]
    return max(dates) if dates else None


def incremental_lookback_days(latest: pd.Timestamp, target_date: str) -> int:
    calendar_gap = max(0, (pd.Timestamp(target_date).floor("D") - pd.Timestamp(latest).floor("D")).days)
    return max(20, calendar_gap + 10)


def update_states_incremental(
    states: dict[str, CodeRuntimeState],
    daily: pd.DataFrame,
    equity: pd.DataFrame,
    *,
    history_days: int = HISTORY_DAYS,
) -> dict[str, CodeRuntimeState]:
    if daily.empty or not states:
        return states
    equity_work = equity.copy()
    equity_work["time"] = pd.to_datetime(equity_work["time"]).dt.normalize()
    equity_lookup = {(str(row.htsc_code).upper(), pd.Timestamp(row.time).floor("D")): row for row in equity_work.itertuples(index=False)}
    work = daily.copy()
    work["time"] = pd.to_datetime(work["time"]).dt.normalize()
    for day, day_rows in work.sort_values(["time", "htsc_code"]).groupby("time", sort=True):
        quotes = []
        rows_by_code = {}
        for row in day_rows.itertuples(index=False):
            code = str(row.htsc_code).upper()
            if code not in states:
                continue
            rows_by_code[code] = row
            factor = float(getattr(row, "adj_factor", 1.0) or 1.0)
            states[code].last_adj_factor = factor
            factor_date = getattr(row, "adj_factor_date", pd.NaT)
            if pd.notna(factor_date):
                states[code].last_adj_factor_date = f"{pd.Timestamp(factor_date):%Y-%m-%d}"
            quotes.append(_quote_from_adjusted_row(row, pd.Timestamp(day)))
        if not quotes:
            continue
        engine = RealtimeFactorEngine(
            code_order=sorted(states),
            fast_signal_provider=default_fast_signal_provider_factory(states),
            chip_provider=default_chip_provider_factory(states),
            sell_volume_provider=default_sell_volume_provider_factory(states),
            states=states,
        )
        _, stats = engine.evaluate_round(quotes=quotes, now=datetime.combine(pd.Timestamp(day).date(), datetime.min.time()).replace(hour=15))
        values = dict(stats.get("snapshot_values", {}))
        for code, row in rows_by_code.items():
            state = states[code]
            day_text = f"{pd.Timestamp(day):%Y-%m-%d}"
            state.history_dates, state.open_history = append_history(state.history_dates, state.open_history, day_text, float(row.open), limit=history_days)
            _, state.high_history = append_history(state.history_dates[:-1], state.high_history, day_text, float(row.high), limit=history_days)
            _, state.low_history = append_history(state.history_dates[:-1], state.low_history, day_text, float(row.low), limit=history_days)
            _, state.close_history = append_history(state.history_dates[:-1], state.close_history, day_text, float(row.close), limit=history_days)
            _, state.volume_history = append_history([], state.volume_history, day_text, float(row.volume or 0.0), limit=124)
            eq_row = equity_lookup.get((code, pd.Timestamp(day).floor("D")))
            turnover_pct = float(getattr(eq_row, "turnover_rate", 0.0) or 0.0) if eq_row is not None else 0.0
            if eq_row is not None:
                raw_close = float(getattr(eq_row, "close", 0.0) or 0.0)
                market_value = float(getattr(eq_row, "floating_market_val", 0.0) or 0.0)
                if raw_close > 0.0 and market_value > 0.0:
                    state.float_shares = market_value / raw_close
            chip_state = {
                "chip": state.chip, "base_low": state.chip_base_low, "n_bins": state.chip_n_bins,
                "cum_high": state.cum_high, "cum_low": state.cum_low,
                "abs_conc_tail": state.recent_abs_concentration,
                "last_dt": pd.Timestamp(state.state_date),
            }
            _, next_chip, _ = _compute_chouma_cost_series_with_state(
                np.asarray([float(row.high)]), np.asarray([float(row.low)]), np.asarray([float(row.close)]),
                np.asarray([float(row.volume or 0.0)]), np.asarray([turnover_pct]), _COST_PERCENTILES,
                pd.DatetimeIndex([pd.Timestamp(day)]), state=chip_state, min_d=CHOUMA_MIN_D, ac=CHOUMA_AC,
                use_volume=CHOUMA_USE_VOLUME,
            )
            state.chip = np.asarray(next_chip["chip"], dtype=np.float64)
            state.chip_base_low = float(next_chip["base_low"])
            state.chip_n_bins = int(next_chip["n_bins"])
            state.cum_high = float(next_chip["cum_high"])
            state.cum_low = float(next_chip["cum_low"])
            state.recent_abs_concentration = np.asarray(next_chip["abs_conc_tail"], dtype=np.float64)
            tdx_today = float(values.get((code, "tdx_base"), 0.0) > 0.0 and values.get((code, "chip_peak_score"), 0.0) > 0.0)
            state.prior_super_strong_no_concentration = np.append(state.prior_super_strong_no_concentration, tdx_today)[-4:]
            state.last_adj_factor = float(getattr(row, "adj_factor", state.last_adj_factor) or state.last_adj_factor)
            factor_date = getattr(row, "adj_factor_date", pd.NaT)
            if pd.notna(factor_date):
                state.last_adj_factor_date = f"{pd.Timestamp(factor_date):%Y-%m-%d}"
            state.state_date = day_text
    return states


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


def _read_recent_adj_factors(base_dir: Path, end_date: str, days: int) -> pd.DataFrame:
    pattern = (base_dir / "year=*" / "month=*" / "merged.parquet").as_posix()
    if not base_dir.exists() or not list(base_dir.glob("year=*/month=*/merged.parquet")):
        return pd.DataFrame(columns=["htsc_code", "time", "adj_factor"])
    query = f"""
        WITH ranked AS (
            SELECT
                UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                CAST(time AS DATE) AS time,
                TRY_CAST(adj_factor AS DOUBLE) AS adj_factor,
                ROW_NUMBER() OVER (PARTITION BY htsc_code ORDER BY time DESC) AS rn
            FROM read_parquet('{pattern}', hive_partitioning=1, union_by_name=true)
            WHERE time < TIMESTAMP '{(datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")}'
        )
        SELECT htsc_code, time, adj_factor FROM ranked
        WHERE rn <= {int(days) + 10}
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


def compute_prior_states_wide(daily: pd.DataFrame, equity: pd.DataFrame) -> dict[str, np.ndarray]:
    """全市场一次计算最近四日强底非筹码条件。"""
    base = daily.sort_values(["time", "htsc_code"]).drop_duplicates(["time", "htsc_code"], keep="last")
    wide = base.set_index(["time", "htsc_code"])[["open", "high", "low", "close", "volume"]].unstack("htsc_code")
    O = wide["open"].ffill().astype(float)
    H = wide["high"].ffill().astype(float)
    L = wide["low"].ffill().astype(float)
    C = wide["close"].ffill().astype(float)
    mac = build_d_class_factor_bundle(O=O, H=H, L=L, C=C)["factor_dfs"]
    kdj = build_kdj_factor_bundle(O=O, H=H, L=L, C=C)["factor_dfs"]
    bottom = build_bottom_fishing_factor_bundle(O=O, H=H, L=L, C=C)["factor_dfs"]
    ma = build_ma_class_zxw_bundle(C=C)["factor_dfs"]
    signal = (
        (mac["mac_total"].astype(float) > 0.0)
        & (bottom["kline_bottom"].astype(float) > 0.0)
        & (ma["ma_class_zxw"].astype(float) > 0.0)
        & kdj["r_condition"].astype(bool)
        & (C.notna().cumsum() >= 250)
    ).astype(float)
    return {str(code): signal[code].iloc[-4:].to_numpy(dtype=np.float64) for code in signal.columns}


def _chip_peak_score_from_costs(costs: np.ndarray, close: np.ndarray) -> np.ndarray:
    def cost(percentile: int) -> np.ndarray:
        return np.asarray(costs[int(percentile) - 1], dtype=np.float64)

    c1, c10, c15, c20, c30, c33, c40, c50 = (cost(x) for x in (1, 10, 15, 20, 30, 33, 40, 50))
    c60, c70, c80, c85, c90, c99 = (cost(x) for x in (60, 70, 80, 85, 90, 99))
    single = (_zxw_chip._safe_divide((c85 - c15) * 200.0, c85 + c15) < 20.0) & (_zxw_chip._safe_divide((c85 - c15) * 100.0, c99 - c1) < 50.0)
    above = np.asarray(close, dtype=np.float64) >= c33 * 0.98
    bounds = [(c1, c10), (c10, c20), (c20, c30), (c30, c40), (c40, c50), (c50, c60), (c60, c70), (c70, c80), (c80, c90), (c90, c99)]
    slopes = [_zxw_chip._safe_divide(np.full_like(close, 10.0), hi - lo) for lo, hi in bounds]
    avg = _zxw_chip._safe_divide(np.full_like(close, 100.0), c99 - c1)
    avg = np.where(avg > 0, avg, np.nan)
    peaks = [(_zxw_chip._safe_divide(slopes[i], avg) > 1.5) & (_zxw_chip._safe_divide(slopes[i + 1], avg) < 0.67) for i in range(9)]
    peaks.append((_zxw_chip._safe_divide(slopes[9], avg) > 1.5) & (_zxw_chip._safe_divide(slopes[8], avg) < 0.67))
    peak_count = sum((item.astype(np.float64) for item in peaks), np.zeros_like(close, dtype=np.float64))
    double = (~single) & (peak_count == 2.0)
    multi = (~single) & (~double)
    score = np.zeros_like(close, dtype=np.float64)
    score[single & above] = 1.0
    score[(score == 0) & double & above] = 2.0
    score[(score == 0) & multi & above] = 3.0
    return score


def _build_chip_state(
    group: pd.DataFrame,
    equity_group: pd.DataFrame,
) -> tuple[np.ndarray, float, int, np.ndarray, float, float, np.ndarray]:
    eq = equity_group.set_index("time")["turnover_rate"]
    turnover = np.asarray([float(eq.get(day, 0.0) or 0.0) for day in group["time"]], dtype=np.float64)
    costs, state, _ = _compute_chouma_cost_series_with_state(
        group["high"].to_numpy(dtype=np.float64),
        group["low"].to_numpy(dtype=np.float64),
        group["close"].to_numpy(dtype=np.float64),
        group["volume"].to_numpy(dtype=np.float64),
        turnover,
        _COST_PERCENTILES,
        pd.DatetimeIndex(group["time"]),
        state=None,
        min_d=CHOUMA_MIN_D,
        ac=CHOUMA_AC,
        use_volume=CHOUMA_USE_VOLUME,
    )
    return (
        np.asarray(state["chip"], dtype=np.float64),
        float(state["base_low"]),
        int(state["n_bins"]),
        np.asarray(state["abs_conc_tail"], dtype=np.float64),
        float(state["cum_high"]),
        float(state["cum_low"]),
        _chip_peak_score_from_costs(costs, group["close"].to_numpy(dtype=np.float64))[-4:],
    )


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


def build_states(daily: pd.DataFrame, equity: pd.DataFrame, state_date: str, prior_by_code: dict[str, np.ndarray] | None = None) -> list[CodeRuntimeState]:
    equity_by_code = {code: g.copy() for code, g in equity.groupby("htsc_code")}
    states: list[CodeRuntimeState] = []
    for code, group in daily.groupby("htsc_code"):
        group = group.sort_values("time").copy()
        eq_group = equity_by_code.get(code)
        if eq_group is None or len(group) < 260:
            continue
        eq_group = eq_group.sort_values("time").copy()
        factor_dates = group["adj_factor_date"].dropna() if "adj_factor_date" in group.columns else pd.Series(dtype="datetime64[ns]")
        chip, base_low, n_bins, recent_abs, cum_high, cum_low, chip_peak_tail = _build_chip_state(group, eq_group)
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
                prior_super_strong_no_concentration=(
                    ((prior_by_code or {}).get(str(code), np.zeros(4, dtype=np.float64)) > 0.0)
                    & (chip_peak_tail > 0.0)
                ).astype(np.float64),
                last_adj_factor=float(group["adj_factor"].iloc[-1]) if "adj_factor" in group.columns else 1.0,
                last_adj_factor_date=(
                    f"{pd.Timestamp(factor_dates.iloc[-1]):%Y-%m-%d}"
                    if not factor_dates.empty
                    else ""
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
    parser.add_argument("--adj-factor-dir", default=str(DEFAULT_ADJ_FACTOR_DIR), help="后复权因子 parquet 根目录")
    parser.add_argument("--state-db", default=str(DEFAULT_STATE_DB), help="滚动状态 SQLite")
    parser.add_argument("--history-days", type=int, default=HISTORY_DAYS, help="每只股票读取历史天数")
    return parser.parse_args()


def main() -> None:
    _configure_utf8_console()
    args = parse_args()
    state_db = Path(args.state_db) if str(args.state_db).strip() else DEFAULT_STATE_DB
    if state_db.exists():
        states_by_code = load_runtime_states(state_db)
        latest = state_latest_date(states_by_code)
        if latest is not None:
            incremental_days = incremental_lookback_days(latest, args.state_date)
            print(f"[MODE] incremental state_date={latest.date()} db={state_db}")
            daily = _read_recent_daily(Path(args.daily_dir), args.state_date, incremental_days)
            adj_factors = _read_recent_adj_factors(Path(args.adj_factor_dir), args.state_date, incremental_days)
            daily = apply_backward_adjustment(daily, adj_factors)
            daily = daily[pd.to_datetime(daily["time"]).dt.normalize() > latest].copy()
            if daily.empty:
                print(f"[OK] factor_state 已是最新，无新增正式交易日: {latest.date()}")
                return
            equity = _read_recent_equity(Path(args.equity_dir), args.state_date, incremental_days)
            states_by_code = update_states_incremental(states_by_code, daily, equity, history_days=int(args.history_days))
            actual_state_date = state_latest_date(states_by_code)
            saved = save_runtime_states(state_db, states_by_code.values(), trading_day=args.trading_day)
            print(f"[OK] incremental saved_states={saved} state_date={actual_state_date.date() if actual_state_date else None} db={state_db}")
            return
    print(f"[READ] daily={args.daily_dir}")
    daily = _read_recent_daily(Path(args.daily_dir), args.state_date, int(args.history_days))
    print(f"[READ] adj_factor={args.adj_factor_dir}")
    adj_factors = _read_recent_adj_factors(Path(args.adj_factor_dir), args.state_date, int(args.history_days))
    daily = apply_backward_adjustment(daily, adj_factors)
    print(f"[READ] equity={args.equity_dir}")
    equity = _read_recent_equity(Path(args.equity_dir), args.state_date, int(args.history_days))
    print(f"[BUILD] daily_rows={len(daily)} equity_rows={len(equity)}")
    actual_state_date = pd.Timestamp(daily["time"].max()).strftime("%Y-%m-%d")
    prior_by_code = compute_prior_states_wide(daily, equity)
    states = build_states(daily, equity, actual_state_date, prior_by_code=prior_by_code)
    saved = save_runtime_states(state_db, states, trading_day=args.trading_day)
    print(f"[OK] saved_states={saved} db={state_db}")


if __name__ == "__main__":
    main()
