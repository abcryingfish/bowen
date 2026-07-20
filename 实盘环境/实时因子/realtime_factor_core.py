from __future__ import annotations

import json
import math
import sqlite3
import sys
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[2]
FACTOR_DIR = ROOT_DIR / "实盘环境" / "实盘因子"
if str(FACTOR_DIR) not in sys.path:
    sys.path.append(str(FACTOR_DIR))

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
    _score_by_threshold,
    _tdx_relative_concentration,
    _update_chip_one_day_py,
)


SIGNAL_NAMES = (
    "tdx_five_day_level6_no_concentration",
    "total_buy_signal",
    "sell_factor_1_5_120",
)
TURNOVER_METHOD_LINEAR = "linear_time_scaled"


def elapsed_trading_ratio(now: datetime) -> float:
    """A股 240 分钟交易日进度；午休不计入，开盘瞬间给 1/240 下限。"""
    current = now.time()
    sessions = (
        (dt_time(9, 30), dt_time(11, 30)),
        (dt_time(13, 0), dt_time(15, 0)),
    )
    elapsed_minutes = 0.0
    for start_t, end_t in sessions:
        start_dt = now.replace(hour=start_t.hour, minute=start_t.minute, second=0, microsecond=0)
        end_dt = now.replace(hour=end_t.hour, minute=end_t.minute, second=0, microsecond=0)
        if current <= start_t:
            break
        if current >= end_t:
            elapsed_minutes += (end_dt - start_dt).total_seconds() / 60.0
            continue
        elapsed_minutes += (now - start_dt).total_seconds() / 60.0
        break
    return min(1.0, max(1.0 / 240.0, elapsed_minutes / 240.0))


def estimate_full_day_turnover(
    current_volume: float | None,
    float_shares: float | None,
    now: datetime,
) -> float:
    if current_volume is None or float_shares is None or float_shares <= 0:
        return 0.0
    current_turnover = max(float(current_volume), 0.0) / float(float_shares)
    return min(1.0, current_turnover / elapsed_trading_ratio(now))


def signal_db_path(trading_day: str | None = None) -> Path:
    day = trading_day or datetime.now().strftime("%Y-%m-%d")
    return Path(r"D:\database\temp_today_data") / f"realtime_signal_{day}.sqlite"


def factor_state_db_path(trading_day: str | None = None) -> Path:
    return Path(r"D:\database\realtime_factor_state\factor_state.sqlite")


def _connect_sqlite(path: str | Path, *, read_only: bool = False) -> sqlite3.Connection:
    db_path = Path(path)
    if read_only:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=30.0)
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    if not read_only:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")
    return conn


def ensure_signal_schema(db_path: str | Path) -> None:
    conn = _connect_sqlite(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trading_day TEXT NOT NULL,
                calc_round_id INTEGER NOT NULL,
                signal_time TEXT NOT NULL,
                source_tick_ts TEXT,
                htsc_code TEXT NOT NULL,
                signal_name TEXT NOT NULL,
                signal_value REAL NOT NULL,
                last_price REAL,
                volume REAL,
                turnover_estimate REAL,
                turnover_method TEXT,
                is_estimated INTEGER NOT NULL DEFAULT 1,
                calc_elapsed_ms REAL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_signal_events_day_code ON signal_events(trading_day, htsc_code)"
        )
        conn.commit()
    finally:
        conn.close()


def append_signal_events(db_path: str | Path, events: Iterable[dict[str, Any]]) -> int:
    rows = list(events)
    if not rows:
        return 0
    ensure_signal_schema(db_path)
    conn = _connect_sqlite(db_path)
    try:
        conn.executemany(
            """
            INSERT INTO signal_events (
                trading_day, calc_round_id, signal_time, source_tick_ts, htsc_code,
                signal_name, signal_value, last_price, volume, turnover_estimate,
                turnover_method, is_estimated, calc_elapsed_ms
            )
            VALUES (
                :trading_day, :calc_round_id, :signal_time, :source_tick_ts, :htsc_code,
                :signal_name, :signal_value, :last_price, :volume, :turnover_estimate,
                :turnover_method, :is_estimated, :calc_elapsed_ms
            )
            """,
            rows,
        )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def _array_to_blob(values: np.ndarray) -> bytes:
    arr = np.ascontiguousarray(values, dtype=np.float64)
    return zlib.compress(arr.tobytes())


def _blob_to_array(blob: bytes | None) -> np.ndarray:
    if not blob:
        return np.array([], dtype=np.float64)
    raw = zlib.decompress(blob)
    return np.frombuffer(raw, dtype=np.float64).copy()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@dataclass
class CodeRuntimeState:
    htsc_code: str
    state_date: str
    history_dates: list[str]
    open_history: np.ndarray
    high_history: np.ndarray
    low_history: np.ndarray
    close_history: np.ndarray
    volume_history: np.ndarray
    float_shares: float
    chip: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.float64))
    chip_base_low: float = 0.0
    chip_n_bins: int = 0
    recent_abs_concentration: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.float64))
    cum_high: float = math.nan
    cum_low: float = math.nan
    prior_super_strong_no_concentration: np.ndarray = field(
        default_factory=lambda: np.zeros(4, dtype=np.float64)
    )
    last_adj_factor: float = 1.0
    last_adj_factor_date: str = ""


def ensure_state_schema(db_path: str | Path) -> None:
    conn = _connect_sqlite(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS state_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS code_state (
                htsc_code TEXT PRIMARY KEY,
                state_date TEXT NOT NULL,
                history_dates_json TEXT NOT NULL,
                open_blob BLOB NOT NULL,
                high_blob BLOB NOT NULL,
                low_blob BLOB NOT NULL,
                close_blob BLOB NOT NULL,
                volume_blob BLOB NOT NULL,
                float_shares REAL NOT NULL,
                chip_blob BLOB,
                chip_base_low REAL,
                chip_n_bins INTEGER,
                recent_abs_concentration_blob BLOB,
                cum_high REAL,
                cum_low REAL,
                prior_super_strong_no_concentration_blob BLOB
                ,last_adj_factor REAL NOT NULL DEFAULT 1.0
                ,last_adj_factor_date TEXT NOT NULL DEFAULT ''
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def save_runtime_states(
    db_path: str | Path,
    states: Iterable[CodeRuntimeState],
    *,
    trading_day: str,
    algorithm_version: str = "realtime_factor_v1",
) -> int:
    ensure_state_schema(db_path)
    rows = []
    for state in states:
        rows.append(
            {
                "htsc_code": state.htsc_code,
                "state_date": state.state_date,
                "history_dates_json": _json_dumps(state.history_dates),
                "open_blob": _array_to_blob(state.open_history),
                "high_blob": _array_to_blob(state.high_history),
                "low_blob": _array_to_blob(state.low_history),
                "close_blob": _array_to_blob(state.close_history),
                "volume_blob": _array_to_blob(state.volume_history),
                "float_shares": float(state.float_shares),
                "chip_blob": _array_to_blob(state.chip),
                "chip_base_low": float(state.chip_base_low),
                "chip_n_bins": int(state.chip_n_bins),
                "recent_abs_concentration_blob": _array_to_blob(state.recent_abs_concentration),
                "cum_high": float(state.cum_high) if np.isfinite(state.cum_high) else None,
                "cum_low": float(state.cum_low) if np.isfinite(state.cum_low) else None,
                "prior_super_strong_no_concentration_blob": _array_to_blob(
                    state.prior_super_strong_no_concentration
                ),
                "last_adj_factor": float(state.last_adj_factor),
                "last_adj_factor_date": str(state.last_adj_factor_date or ""),
            }
        )
    conn = _connect_sqlite(db_path)
    try:
        state_dates = [str(row["state_date"]) for row in rows if str(row["state_date"]).strip()]
        meta_values = {
            "schema_version": "2",
            "algorithm_version": algorithm_version,
            "trading_day": trading_day,
            "state_date": max(state_dates) if state_dates else "",
            "adjust_mode": "backward",
            "code_count": str(len(rows)),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        conn.executemany(
            "INSERT OR REPLACE INTO state_meta(key, value) VALUES(?, ?)",
            list(meta_values.items()),
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO code_state (
                htsc_code, state_date, history_dates_json, open_blob, high_blob,
                low_blob, close_blob, volume_blob, float_shares, chip_blob,
                chip_base_low, chip_n_bins, recent_abs_concentration_blob,
                cum_high, cum_low, prior_super_strong_no_concentration_blob
                ,last_adj_factor, last_adj_factor_date
            )
            VALUES (
                :htsc_code, :state_date, :history_dates_json, :open_blob, :high_blob,
                :low_blob, :close_blob, :volume_blob, :float_shares, :chip_blob,
                :chip_base_low, :chip_n_bins, :recent_abs_concentration_blob,
                :cum_high, :cum_low, :prior_super_strong_no_concentration_blob
                ,:last_adj_factor, :last_adj_factor_date
            )
            """,
            rows,
        )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def load_runtime_states(db_path: str | Path) -> dict[str, CodeRuntimeState]:
    conn = _connect_sqlite(db_path, read_only=True)
    try:
        rows = conn.execute("SELECT * FROM code_state").fetchall()
    finally:
        conn.close()
    states: dict[str, CodeRuntimeState] = {}
    for row in rows:
        code = str(row["htsc_code"])
        states[code] = CodeRuntimeState(
            htsc_code=code,
            state_date=str(row["state_date"]),
            history_dates=list(json.loads(row["history_dates_json"])),
            open_history=_blob_to_array(row["open_blob"]),
            high_history=_blob_to_array(row["high_blob"]),
            low_history=_blob_to_array(row["low_blob"]),
            close_history=_blob_to_array(row["close_blob"]),
            volume_history=_blob_to_array(row["volume_blob"]),
            float_shares=float(row["float_shares"] or 0.0),
            chip=_blob_to_array(row["chip_blob"]),
            chip_base_low=float(row["chip_base_low"] or 0.0),
            chip_n_bins=int(row["chip_n_bins"] or 0),
            recent_abs_concentration=_blob_to_array(row["recent_abs_concentration_blob"]),
            cum_high=float(row["cum_high"]) if row["cum_high"] is not None else math.nan,
            cum_low=float(row["cum_low"]) if row["cum_low"] is not None else math.nan,
            prior_super_strong_no_concentration=_blob_to_array(
                row["prior_super_strong_no_concentration_blob"]
            ),
            last_adj_factor=float(row["last_adj_factor"] or 1.0),
            last_adj_factor_date=str(row["last_adj_factor_date"] or ""),
        )
    return states


def quote_rows_from_market_db(db_path: str | Path) -> list[dict[str, Any]]:
    conn = _connect_sqlite(db_path, read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT htsc_code, ts, last_price, open, high, low, last_close,
                   amount, volume, pvolume
            FROM latest_quote
            WHERE last_price IS NOT NULL AND last_price > 0
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _frame_for_codes(
    states: dict[str, CodeRuntimeState],
    quotes_by_code: dict[str, dict[str, Any]],
    codes: list[str],
    field: str,
) -> pd.DataFrame:
    series_by_code: dict[str, pd.Series] = {}
    all_dates: set[str] = set()
    for code in codes:
        state = states[code]
        history = np.asarray(getattr(state, f"{field}_history"), dtype=float)
        history_length = min(len(history), len(state.history_dates))
        dates = list(state.history_dates[-history_length:]) if history_length else []
        values = list(history[-history_length:]) if history_length else []
        quote = quotes_by_code.get(code, {})
        if field == "close":
            current = quote.get("last_price")
        elif field == "volume":
            current = quote.get("pvolume", quote.get("volume"))
        else:
            current = quote.get(field)
        if field in {"open", "high", "low", "close"} and current is not None:
            current = float(current) * float(state.last_adj_factor or 1.0)
        values.append(float(current) if current is not None else math.nan)
        dates.append("TODAY")
        all_dates.update(dates[:-1])
        series_by_code[code] = pd.Series(values, index=dates, dtype=float)
    index = pd.Index([*sorted(all_dates), "TODAY"])
    return pd.DataFrame(series_by_code).reindex(index)


def _positive(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.fillna(0.0).astype(float) > 0.0


def default_fast_signal_provider_factory(states: dict[str, CodeRuntimeState]) -> Callable[[list[dict[str, Any]]], dict[str, dict[str, bool]]]:
    def provider(quotes: list[dict[str, Any]]) -> dict[str, dict[str, bool]]:
        quotes_by_code = {str(q.get("htsc_code", "")).upper(): q for q in quotes}
        codes = [code for code in quotes_by_code if code in states]
        if not codes:
            return {}
        O = _frame_for_codes(states, quotes_by_code, codes, "open")
        H = _frame_for_codes(states, quotes_by_code, codes, "high")
        L = _frame_for_codes(states, quotes_by_code, codes, "low")
        C = _frame_for_codes(states, quotes_by_code, codes, "close")
        mac = build_d_class_factor_bundle(O=O, H=H, L=L, C=C)["factor_dfs"]
        kdj = build_kdj_factor_bundle(O=O, H=H, L=L, C=C)["factor_dfs"]
        bottom = build_bottom_fishing_factor_bundle(O=O, H=H, L=L, C=C)["factor_dfs"]
        ma = build_ma_class_zxw_bundle(C=C)["factor_dfs"]
        last = C.index[-1]
        out: dict[str, dict[str, bool]] = {}
        for code in codes:
            mac_total = float(mac["mac_total"].loc[last, code] or 0.0)
            r_condition = bool(kdj["r_condition"].loc[last, code])
            j_overbought = bool(kdj["j_overbought_factor"].loc[last, code])
            bottom_score = float(bottom["bottom_fishing_score"].loc[last, code] or 0.0)
            kline_bottom = float(bottom["kline_bottom"].loc[last, code] or 0.0)
            top_escape = float(bottom["top_escape_score"].loc[last, code] or 0.0)
            ma_class = float(ma["ma_class_zxw"].loc[last, code] or 0.0)
            bar_count = int(np.isfinite(states[code].close_history).sum()) + 1
            out[code] = {
                "total_buy_base": mac_total > 0.0 and r_condition and bottom_score > 0.0,
                "tdx_base": (
                    mac_total > 0.0
                    and kline_bottom > 0.0
                    and ma_class > 0.0
                    and r_condition
                    and bar_count >= 250
                ),
                "sell_base": mac_total > 0.0 and top_escape > 0.0 and j_overbought,
            }
        return out

    return provider


def _compute_selected_chip_outputs(
    state: CodeRuntimeState,
    quote: dict[str, Any],
    now: datetime,
) -> dict[str, float]:
    adj_factor = float(state.last_adj_factor or 1.0)
    high = float(quote.get("high") or quote.get("last_price") or math.nan) * adj_factor
    low = float(quote.get("low") or quote.get("last_price") or math.nan) * adj_factor
    close = float(quote.get("last_price") or math.nan) * adj_factor
    volume = float(quote.get("pvolume", quote.get("volume")) or 0.0)
    turnover = estimate_full_day_turnover(volume, state.float_shares, now)
    chip, base_low, n_bins = _update_chip_one_day_py(
        state.chip.copy(),
        float(state.chip_base_low),
        int(state.chip_n_bins),
        high,
        low,
        volume,
        turnover,
        CHOUMA_MIN_D,
        CHOUMA_AC,
        CHOUMA_USE_VOLUME,
    )
    cost_out = np.zeros((len(_COST_PERCENTILES), 1), dtype=np.float64)
    _fill_costs_from_chip_py(
        chip,
        base_low,
        CHOUMA_MIN_D,
        n_bins,
        _COST_PERCENTILES / 100.0,
        cost_out,
        0,
    )
    cost = {int(p): float(cost_out[i, 0]) for i, p in enumerate(_COST_PERCENTILES)}
    cum_high = np.nanmax([state.cum_high, high])
    cum_low = np.nanmin([state.cum_low, low])
    abs_conc = float(_safe_divide(
        np.array([(cost[95] - cost[5]) * 100.0]),
        np.array([cum_high - cum_low]),
    )[0])
    recent = np.append(state.recent_abs_concentration, abs_conc)[-1200:]
    rel_conc = float(_tdx_relative_concentration(recent.reshape(-1, 1))[-1, 0])
    rel_score = float(_score_by_threshold(np.array([rel_conc]))[0])
    abs_score = float(_score_by_threshold(np.array([abs_conc]))[0])
    if rel_score > 0 and abs_score > 0:
        concentration_total = min(rel_score, abs_score)
    else:
        concentration_total = max(rel_score, abs_score)

    single_peak_density = _safe_divide(
        np.array([(cost[85] - cost[15]) * 200.0]),
        np.array([cost[85] + cost[15]]),
    )[0]
    core_ratio = _safe_divide(
        np.array([(cost[85] - cost[15]) * 100.0]),
        np.array([cost[99] - cost[1]]),
    )[0]
    single_peak_state = single_peak_density < 20.0 and core_ratio < 50.0
    above_c33 = close >= cost[33] * 0.98
    center = (cost[85] + cost[15]) / 2.0
    single_peak_best = bool(single_peak_state and above_c33)
    bounds = [
        (1, 10), (10, 20), (20, 30), (30, 40), (40, 50),
        (50, 60), (60, 70), (70, 80), (80, 90), (90, 99),
    ]
    k_list = [
        float(_safe_divide(np.array([10.0]), np.array([cost[hi_p] - cost[lo_p]]))[0])
        for lo_p, hi_p in bounds
    ]
    k_avg = float(_safe_divide(np.array([100.0]), np.array([cost[99] - cost[1]]))[0])
    peaks = []
    if k_avg > 0:
        for i in range(9):
            peaks.append((k_list[i] / k_avg > 1.5) and (k_list[i + 1] / k_avg < 0.67))
        peaks.append((k_list[9] / k_avg > 1.5) and (k_list[8] / k_avg < 0.67))
    peak_count = sum(1 for p in peaks if p)
    double_peak = (not single_peak_state) and peak_count == 2
    multi_peak = (not single_peak_state) and (not double_peak)
    chip_peak_score = 0.0
    if single_peak_best:
        chip_peak_score = 1.0
    elif double_peak and above_c33:
        chip_peak_score = 2.0
    elif multi_peak and above_c33:
        chip_peak_score = 3.0
    return {
        "concentration_total_score": float(concentration_total),
        "chip_peak_score": float(chip_peak_score),
        "turnover_estimate": float(turnover),
    }


def default_chip_provider_factory(states: dict[str, CodeRuntimeState]) -> Callable[[list[str], list[dict[str, Any]], datetime], dict[str, dict[str, float]]]:
    def provider(codes: list[str], quotes: list[dict[str, Any]], now: datetime) -> dict[str, dict[str, float]]:
        quotes_by_code = {str(q.get("htsc_code", "")).upper(): q for q in quotes}
        out: dict[str, dict[str, float]] = {}
        for code in codes:
            state = states.get(code)
            quote = quotes_by_code.get(code)
            if state is None or quote is None:
                continue
            out[code] = _compute_selected_chip_outputs(state, quote, now)
        return out

    return provider


def default_sell_volume_provider_factory(states: dict[str, CodeRuntimeState]) -> Callable[[list[str], list[dict[str, Any]]], dict[str, bool]]:
    def provider(codes: list[str], quotes: list[dict[str, Any]]) -> dict[str, bool]:
        quotes_by_code = {str(q.get("htsc_code", "")).upper(): q for q in quotes}
        out: dict[str, bool] = {}
        for code in codes:
            state = states.get(code)
            quote = quotes_by_code.get(code, {})
            if state is None or len(state.volume_history) < 124:
                out[code] = False
                continue
            current_volume = float(quote.get("pvolume", quote.get("volume")) or 0.0)
            values = np.append(state.volume_history[-124:], current_volume)
            recent_avg = float(np.nanmean(values[-5:]))
            prior_avg = float(np.nanmean(values[-125:-5]))
            out[code] = bool(np.isfinite(prior_avg) and prior_avg > 0 and recent_avg > prior_avg * 1.5)
        return out

    return provider


class RealtimeFactorEngine:
    def __init__(
        self,
        *,
        code_order: list[str],
        fast_signal_provider: Callable[[list[dict[str, Any]]], dict[str, dict[str, bool]]],
        chip_provider: Callable[[list[str], list[dict[str, Any]], datetime], dict[str, dict[str, float]]],
        sell_volume_provider: Callable[[list[str], list[dict[str, Any]]], dict[str, bool]],
        states: dict[str, CodeRuntimeState] | None = None,
    ) -> None:
        self.code_order = code_order
        self.fast_signal_provider = fast_signal_provider
        self.chip_provider = chip_provider
        self.sell_volume_provider = sell_volume_provider
        self.states = states or {}

    @classmethod
    def from_state_db(cls, state_db_path: str | Path) -> "RealtimeFactorEngine":
        states = load_runtime_states(state_db_path)
        codes = sorted(states)
        return cls(
            code_order=codes,
            fast_signal_provider=default_fast_signal_provider_factory(states),
            chip_provider=default_chip_provider_factory(states),
            sell_volume_provider=default_sell_volume_provider_factory(states),
            states=states,
        )

    def evaluate_round(
        self,
        *,
        quotes: list[dict[str, Any]],
        now: datetime,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        start = time.perf_counter()
        quotes_by_code = {str(q.get("htsc_code", "")).upper(): q for q in quotes}
        fast = self.fast_signal_provider(quotes)
        total_buy_candidates = [code for code, flags in fast.items() if flags.get("total_buy_base")]
        tdx_candidates = [code for code, flags in fast.items() if flags.get("tdx_base")]
        sell_candidates = [code for code, flags in fast.items() if flags.get("sell_base")]
        chip_candidates = sorted(set(total_buy_candidates) | set(tdx_candidates))
        chip = self.chip_provider(chip_candidates, quotes, now) if chip_candidates else {}
        sell_volume = self.sell_volume_provider(sell_candidates, quotes) if sell_candidates else {}
        events: list[dict[str, Any]] = []
        snapshot_values: dict[tuple[str, str], float] = {}
        for code in sorted(fast):
            quote = quotes_by_code.get(code, {})
            source_ts = quote.get("ts")
            last_price = quote.get("last_price")
            volume = quote.get("pvolume", quote.get("volume"))
            turnover_estimate = chip.get(code, {}).get("turnover_estimate")
            flags = fast[code]
            chip_values = chip.get(code, {})
            total_buy = False
            if flags.get("total_buy_base"):
                raw = 1.0
                raw += 1.0 if chip_values.get("concentration_total_score", 0.0) > 0.0 else 0.0
                raw += 1.0 if chip_values.get("chip_peak_score", 0.0) > 0.0 else 0.0
                total_buy = raw >= 2.0
            tdx_today = bool(flags.get("tdx_base") and chip_values.get("chip_peak_score", 0.0) > 0.0)
            prior = self.states.get(code).prior_super_strong_no_concentration if code in self.states else []
            tdx_five = bool(tdx_today or np.nanmax(np.append(prior, 0.0)) >= 1.0)
            sell_signal = bool(flags.get("sell_base") and sell_volume.get(code, False))
            for name, value in {
                "total_buy_base": float(bool(flags.get("total_buy_base"))),
                "tdx_base": float(bool(flags.get("tdx_base"))),
                "sell_base": float(bool(flags.get("sell_base"))),
                "concentration_total_score": float(chip_values.get("concentration_total_score", 0.0)),
                "chip_peak_score": float(chip_values.get("chip_peak_score", 0.0)),
                "turnover_estimate": float(turnover_estimate or 0.0),
                "sell_volume_confirm": float(bool(sell_volume.get(code, False))),
                "tdx_five_day_level6_no_concentration": float(tdx_five),
                "total_buy_signal": float(total_buy),
                "sell_factor_1_5_120": float(sell_signal),
            }.items():
                snapshot_values[(code, name)] = value
            for signal_name, signal_value in (
                ("tdx_five_day_level6_no_concentration", tdx_five),
                ("total_buy_signal", total_buy),
                ("sell_factor_1_5_120", sell_signal),
            ):
                if not signal_value:
                    continue
                events.append(
                    {
                        "trading_day": now.strftime("%Y-%m-%d"),
                        "calc_round_id": 0,
                        "signal_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "source_tick_ts": source_ts,
                        "htsc_code": code,
                        "signal_name": signal_name,
                        "signal_value": 1.0,
                        "last_price": float(last_price) if last_price is not None else None,
                        "volume": float(volume) if volume is not None else None,
                        "turnover_estimate": turnover_estimate,
                        "turnover_method": TURNOVER_METHOD_LINEAR,
                        "is_estimated": 1,
                        "calc_elapsed_ms": 0.0,
                    }
                )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        for event in events:
            event["calc_elapsed_ms"] = elapsed_ms
        return events, {
            "quote_count": len(quotes),
            "fast_signal_count": len(fast),
            "total_buy_candidate_count": len(total_buy_candidates),
            "tdx_candidate_count": len(tdx_candidates),
            "sell_candidate_count": len(sell_candidates),
            "chip_candidate_count": len(chip_candidates),
            "signal_count": len(events),
            "snapshot_values": snapshot_values,
            "calc_elapsed_ms": elapsed_ms,
        }
