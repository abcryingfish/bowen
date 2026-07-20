# -*- coding: utf-8 -*-
"""盘中信号独立存储、模块化因子注册与事件比较。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SNAPSHOT_ROOT = Path(r"D:\database\intraday_signal_snapshot")
EVENT_ROOT = Path(r"D:\database\intraday_signal_event")
ALGORITHM_VERSION = "intraday_zxw_v1"
FACTOR_CONFIG_VERSION = "realtime_three_signals_v1"


@dataclass(frozen=True)
class FactorSpec:
    key: str
    name: str
    module_name: str
    builder_name: str
    dependencies: tuple[str, ...] = ()
    is_final_signal: bool = False


def load_factor_builder(spec: FactorSpec, *, root_dir: str | Path | None = None):
    """按注册表动态加载 ZXW/实盘因子文件中的 builder。"""
    root = Path(root_dir or Path(__file__).resolve().parents[2])
    module_path = root / Path(spec.module_name.replace("/", "\\"))
    if module_path.suffix != ".py":
        module_path = module_path.with_suffix(".py")
    if not module_path.is_file():
        raise FileNotFoundError(f"因子模块不存在: {module_path}")
    module_key = f"intraday_factor_{spec.key}"
    module_spec = importlib.util.spec_from_file_location(module_key, module_path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"无法加载因子模块: {module_path}")
    module = importlib.util.module_from_spec(module_spec)
    module_dir = str(module_path.parent)
    added = module_dir not in sys.path
    if added:
        sys.path.insert(0, module_dir)
    try:
        module_spec.loader.exec_module(module)
    finally:
        if added:
            try:
                sys.path.remove(module_dir)
            except ValueError:
                pass
    builder = getattr(module, spec.builder_name, None)
    if not callable(builder):
        raise AttributeError(f"因子模块未提供 builder: {spec.builder_name}")
    return builder


def build_default_factor_registry() -> list[FactorSpec]:
    return [
        FactorSpec("tdx_five_day_level6_no_concentration", "通达信强底信号", "实盘环境/实盘因子/通达信强底信号.py", "build_tdx_bottom_alert_bundle", ("macd", "kdj", "bottom_fishing", "moving_average", "chip_structure"), True),
        FactorSpec("total_buy_signal", "总买入信号", "实盘环境/实盘因子/总买入信号_独立全量.py", "build_total_buy_signal_bundle", ("macd", "kdj", "bottom_fishing", "chip_structure"), True),
        FactorSpec("sell_factor_1_5_120", "量能卖出信号", "实盘环境/实盘因子/卖出因子_量能.py", "build_sell_factor_volume_bundle", ("macd", "kdj", "bottom_fishing", "volume_drop"), True),
    ]


def module_signature(registry: Iterable[FactorSpec]) -> str:
    payload = "|".join(f"{x.key}:{x.module_name}:{x.builder_name}" for x in registry)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _connect(path: str | Path, read_only: bool = False) -> sqlite3.Connection:
    db = Path(path)
    if read_only:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=30.0)
    else:
        db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    if not read_only:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def ensure_snapshot_schema(path: str | Path) -> None:
    conn = _connect(path)
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS snapshot_meta (
            id INTEGER PRIMARY KEY CHECK (id = 1), trading_day TEXT NOT NULL,
            round_id INTEGER NOT NULL, quote_cutoff_time TEXT NOT NULL,
            calc_started_at TEXT, calc_finished_at TEXT, calc_elapsed_ms REAL,
            algorithm_version TEXT NOT NULL, factor_config_version TEXT NOT NULL,
            module_signature TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS snapshot_values (
            htsc_code TEXT NOT NULL, factor_name TEXT NOT NULL, value REAL,
            is_final_signal INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (htsc_code, factor_name)
        );
        CREATE TABLE IF NOT EXISTS snapshot_bars (
            htsc_code TEXT PRIMARY KEY, quote_cutoff_time TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL, last_close REAL,
            amount REAL, volume REAL, pvolume REAL
        );
        CREATE TABLE IF NOT EXISTS run_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, round_id INTEGER NOT NULL,
            status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL
        );
        """)
        conn.commit()
    finally:
        conn.close()


def replace_snapshot(path: str | Path, *, trading_day: str, round_id: int,
                     quote_cutoff_time: str, values: list[dict[str, Any]],
                     bars: list[dict[str, Any]] | None = None,
                     calc_started_at: str | None = None, calc_finished_at: str | None = None,
                     calc_elapsed_ms: float | None = None,
                     registry: Iterable[FactorSpec] | None = None) -> None:
    registry = list(registry or build_default_factor_registry())
    ensure_snapshot_schema(path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM snapshot_values")
        conn.execute("DELETE FROM snapshot_bars")
        conn.executemany("INSERT INTO snapshot_values(htsc_code,factor_name,value,is_final_signal) VALUES(?,?,?,?)", [
            (str(row["htsc_code"]), str(row["factor_name"]), row.get("value"), int(row.get("is_final_signal", 0))) for row in values
        ])
        if bars:
            conn.executemany("INSERT INTO snapshot_bars(htsc_code,quote_cutoff_time,open,high,low,close,last_close,amount,volume,pvolume) VALUES(?,?,?,?,?,?,?,?,?,?)", [
                (row["htsc_code"], quote_cutoff_time, row.get("open"), row.get("high"), row.get("low"), row.get("close"), row.get("last_close"), row.get("amount"), row.get("volume"), row.get("pvolume")) for row in bars
            ])
        conn.execute("INSERT OR REPLACE INTO snapshot_meta(id,trading_day,round_id,quote_cutoff_time,calc_started_at,calc_finished_at,calc_elapsed_ms,algorithm_version,factor_config_version,module_signature,updated_at) VALUES(1,?,?,?,?,?,?,?,?,?,?)", (trading_day, round_id, quote_cutoff_time, calc_started_at, calc_finished_at, calc_elapsed_ms, ALGORITHM_VERSION, FACTOR_CONFIG_VERSION, module_signature(registry), now))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_event_schema(path: str | Path) -> None:
    conn = _connect(path)
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS signal_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, trading_day TEXT NOT NULL,
            calc_round_id INTEGER NOT NULL, event_time TEXT NOT NULL,
            source_tick_ts TEXT, htsc_code TEXT NOT NULL, signal_name TEXT NOT NULL,
            event_type TEXT NOT NULL, signal_value REAL NOT NULL, last_price REAL,
            volume REAL, algorithm_version TEXT NOT NULL,
            UNIQUE(trading_day, htsc_code, signal_name, event_type, calc_round_id)
        );
        CREATE INDEX IF NOT EXISTS idx_signal_events_day_code ON signal_events(trading_day, htsc_code);
        """)
        conn.commit()
    finally:
        conn.close()


def append_run_log(path: str | Path, round_id: int, status: str, error: str | None = None) -> None:
    ensure_snapshot_schema(path)
    conn = _connect(path)
    try:
        conn.execute("INSERT INTO run_log(round_id,status,error,created_at) VALUES(?,?,?,?)", (round_id, status, error, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    finally:
        conn.close()


def append_signal_transitions(path: str | Path, trading_day: str, round_id: int,
                              previous: dict[tuple[str, str], float],
                              current: dict[tuple[str, str], float], *,
                              event_time: str | None = None,
                              quote_by_code: dict[str, dict[str, Any]] | None = None) -> int:
    ensure_event_schema(path)
    event_time = event_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    quote_by_code = quote_by_code or {}
    rows = []
    for key in sorted(set(previous) | set(current)):
        before = float(previous.get(key, 0.0) or 0.0) > 0.0
        after = float(current.get(key, 0.0) or 0.0) > 0.0
        if before == after:
            continue
        code, signal_name = key
        quote = quote_by_code.get(code, {})
        rows.append((trading_day, round_id, event_time, quote.get("ts"), code, signal_name, "triggered" if after else "cleared", 1.0 if after else 0.0, quote.get("last_price"), quote.get("pvolume", quote.get("volume")), ALGORITHM_VERSION))
    if not rows:
        return 0
    conn = _connect(path)
    try:
        conn.executemany("INSERT OR IGNORE INTO signal_events(trading_day,calc_round_id,event_time,source_tick_ts,htsc_code,signal_name,event_type,signal_value,last_price,volume,algorithm_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        return conn.total_changes
    finally:
        conn.close()


def read_final_signal_state(path: str | Path) -> dict[tuple[str, str], float]:
    if not Path(path).exists():
        return {}
    conn = _connect(path, read_only=True)
    try:
        rows = conn.execute("SELECT htsc_code, factor_name, value FROM snapshot_values WHERE is_final_signal=1").fetchall()
        return {(str(row["htsc_code"]), str(row["factor_name"])): float(row["value"] or 0.0) for row in rows}
    finally:
        conn.close()


def read_last_round_id(path: str | Path) -> int:
    if not Path(path).exists():
        return 0
    conn = _connect(path, read_only=True)
    try:
        row = conn.execute("SELECT round_id FROM snapshot_meta WHERE id=1").fetchone()
        return int(row["round_id"]) if row is not None else 0
    finally:
        conn.close()


def read_event_signal_state(path: str | Path) -> dict[tuple[str, str], float] | None:
    """读取事件库中每个信号的最后状态，用于事件写入失败后的补偿重试。"""
    if not Path(path).exists():
        return None
    conn = _connect(path, read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT htsc_code, signal_name, event_type, id
            FROM signal_events
            ORDER BY id
            """
        ).fetchall()
    finally:
        conn.close()
    state: dict[tuple[str, str], float] = {}
    for row in rows:
        state[(str(row["htsc_code"]), str(row["signal_name"]))] = 1.0 if row["event_type"] == "triggered" else 0.0
    return state


def daily_snapshot_path(trading_day: str) -> Path:
    return SNAPSHOT_ROOT / f"intraday_signal_snapshot_{trading_day}.sqlite"


def daily_event_path(trading_day: str) -> Path:
    return EVENT_ROOT / f"intraday_signal_event_{trading_day}.sqlite"
