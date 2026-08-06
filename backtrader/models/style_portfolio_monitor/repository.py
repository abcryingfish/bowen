"""DuckDB persistence for the incremental style portfolio ledger."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

from .config import StyleModelDefinition
from .portfolio import PortfolioState
from .query import StyleMonitorValidationError, query_curves, query_positions, query_summary, query_trades


@dataclass(frozen=True, slots=True)
class RunState:
    model_version: str
    last_success_date: date | None
    last_rebalance_date: date | None
    config_hash: str


@dataclass(frozen=True, slots=True)
class LegDayPayload:
    cash: float
    market_value: float
    total_asset: float
    nav: float
    daily_return: float | None
    cumulative_return: float
    turnover: float
    commission: float
    rebalanced: bool
    factor_coverage: float | None
    stale_price_count: int
    status: str
    status_message: str
    positions: list[dict[str, Any]]
    trades: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ModelDayPayload:
    model_version: str
    model_id: str
    config_hash: str
    trade_date: date
    last_rebalance_date: date | None
    legs: dict[str, LegDayPayload]


class StyleMonitorRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def _connect(self):
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(str(self.database_path))

    def initialize_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS model_definition (
                  model_version VARCHAR PRIMARY KEY, model_id VARCHAR NOT NULL, title VARCHAR NOT NULL,
                  factor_name VARCHAR NOT NULL, factor_key VARCHAR NOT NULL, rebalance_frequency VARCHAR NOT NULL,
                  config_hash VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
                  UNIQUE(model_id, config_hash)
                );
                CREATE TABLE IF NOT EXISTS nav_daily (
                  model_version VARCHAR NOT NULL, leg VARCHAR NOT NULL, trade_date DATE NOT NULL,
                  cash DOUBLE NOT NULL, market_value DOUBLE NOT NULL, total_asset DOUBLE NOT NULL,
                  nav DOUBLE NOT NULL, daily_return DOUBLE, cumulative_return DOUBLE NOT NULL,
                  turnover DOUBLE NOT NULL, commission DOUBLE NOT NULL, rebalanced BOOLEAN NOT NULL,
                  factor_coverage DOUBLE, stale_price_count INTEGER NOT NULL, status VARCHAR NOT NULL,
                  status_message VARCHAR NOT NULL, PRIMARY KEY(model_version, leg, trade_date)
                );
                CREATE TABLE IF NOT EXISTS position_daily (
                  model_version VARCHAR NOT NULL, leg VARCHAR NOT NULL, trade_date DATE NOT NULL,
                  htsc_code VARCHAR NOT NULL, score DOUBLE, rank INTEGER, target_weight DOUBLE,
                  actual_weight DOUBLE NOT NULL, shares BIGINT NOT NULL, price DOUBLE NOT NULL,
                  market_value DOUBLE NOT NULL, stale_price BOOLEAN NOT NULL,
                  PRIMARY KEY(model_version, leg, trade_date, htsc_code)
                );
                CREATE TABLE IF NOT EXISTS trade_log (
                  trade_id VARCHAR PRIMARY KEY, model_version VARCHAR NOT NULL, leg VARCHAR NOT NULL,
                  trade_date DATE NOT NULL, htsc_code VARCHAR NOT NULL, side VARCHAR NOT NULL,
                  shares BIGINT NOT NULL, price DOUBLE NOT NULL, trade_value DOUBLE NOT NULL,
                  commission DOUBLE NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_state (
                  model_version VARCHAR PRIMARY KEY, last_success_date DATE, last_rebalance_date DATE,
                  config_hash VARCHAR NOT NULL, updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp
                );
                CREATE TABLE IF NOT EXISTS update_run (
                  run_id VARCHAR PRIMARY KEY, status VARCHAR NOT NULL, requested_at TIMESTAMP NOT NULL,
                  started_at TIMESTAMP, finished_at TIMESTAMP, through_date DATE,
                  total_steps INTEGER NOT NULL, completed_steps INTEGER NOT NULL,
                  current_model_id VARCHAR, current_date DATE, failed_model_id VARCHAR,
                  failed_date DATE, message VARCHAR NOT NULL, error VARCHAR NOT NULL
                );
            """)
        finally:
            conn.close()

    def list_tables(self) -> list[str]:
        conn = self._connect()
        try:
            return [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
        finally:
            conn.close()

    def primary_key_columns(self, table: str) -> list[str]:
        conn = self._connect()
        try:
            info = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
            return [row[1] for row in info if row[5]]
        finally:
            conn.close()

    def ensure_model_version(self, model: StyleModelDefinition, config_hash: str) -> str:
        conn = self._connect()
        try:
            row = conn.execute("SELECT model_version FROM model_definition WHERE model_id=? AND config_hash=?", [model.model_id, config_hash]).fetchone()
            if row:
                return str(row[0])
            count = conn.execute("SELECT count(*) FROM model_definition WHERE model_id=?", [model.model_id]).fetchone()[0]
            version = f"{model.model_id}-v{int(count) + 1}"
            conn.execute("INSERT INTO model_definition(model_version,model_id,title,factor_name,factor_key,rebalance_frequency,config_hash) VALUES (?,?,?,?,?,?,?)", [version, model.model_id, model.title, model.factor_name, model.factor_key, model.rebalance_frequency, config_hash])
            conn.execute("INSERT INTO run_state(model_version,last_success_date,last_rebalance_date,config_hash) VALUES (?,?,?,?)", [version, None, None, config_hash])
            return version
        finally:
            conn.close()

    def get_run_state(self, model_version: str) -> RunState:
        conn = self._connect()
        try:
            row = conn.execute("SELECT model_version,last_success_date,last_rebalance_date,config_hash FROM run_state WHERE model_version=?", [model_version]).fetchone()
            if not row:
                return RunState(model_version, None, None, "")
            return RunState(str(row[0]), row[1], row[2], str(row[3]))
        finally:
            conn.close()

    def load_portfolio_state(self, model_version: str, leg: str) -> tuple[PortfolioState, float | None]:
        conn = self._connect()
        try:
            nav_row = conn.execute("SELECT trade_date,cash,nav FROM nav_daily WHERE model_version=? AND leg=? ORDER BY trade_date DESC LIMIT 1", [model_version, leg]).fetchone()
            if not nav_row:
                from .config import INITIAL_CASH
                return PortfolioState(INITIAL_CASH, {}, {}), None
            rows = conn.execute("SELECT htsc_code,shares,price FROM position_daily WHERE model_version=? AND leg=? AND trade_date=?", [model_version, leg, nav_row[0]]).fetchall()
            positions = {str(row[0]): int(row[1]) for row in rows if int(row[1]) > 0}
            prices = {str(row[0]): float(row[2]) for row in rows if float(row[2]) > 0}
            return PortfolioState(float(nav_row[1]), positions, prices), float(nav_row[2])
        finally:
            conn.close()

    def count_rows(self, table: str) -> int:
        conn = self._connect()
        try:
            return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        finally:
            conn.close()

    def query_summary(self):
        conn = self._connect()
        try:
            return query_summary(conn)
        finally:
            conn.close()

    def query_curves(self, model_id: str, range_key: str):
        conn = self._connect()
        try:
            return query_curves(conn, model_id, range_key)
        finally:
            conn.close()

    def query_positions(self, model_id: str, leg: str, trade_date: str | None):
        conn = self._connect()
        try:
            return query_positions(conn, model_id, leg, trade_date)
        finally:
            conn.close()

    def query_trades(self, model_id: str, leg: str, limit: int):
        conn = self._connect()
        try:
            return query_trades(conn, model_id, leg, limit)
        finally:
            conn.close()

    def _insert_positions(self, conn, payload: ModelDayPayload, leg: str, leg_payload: LegDayPayload) -> None:
        for position in leg_payload.positions:
            conn.execute("INSERT INTO position_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [payload.model_version, leg, payload.trade_date, position.get("htsc_code"), position.get("score"), position.get("rank"), position.get("target_weight", 0.0), position.get("actual_weight", 0.0), position.get("shares", 0), position.get("price", 0.0), position.get("market_value", 0.0), bool(position.get("stale_price", False))])

    def write_model_day(self, payload: ModelDayPayload) -> None:
        if set(payload.legs) != {"high", "low"}:
            raise ValueError("单日账本必须同时包含 high 和 low 两条腿")
        conn = self._connect()
        try:
            conn.execute("BEGIN TRANSACTION")
            for leg, leg_payload in payload.legs.items():
                conn.execute("DELETE FROM position_daily WHERE model_version=? AND leg=? AND trade_date=?", [payload.model_version, leg, payload.trade_date])
                conn.execute("DELETE FROM trade_log WHERE model_version=? AND leg=? AND trade_date=?", [payload.model_version, leg, payload.trade_date])
                conn.execute("DELETE FROM nav_daily WHERE model_version=? AND leg=? AND trade_date=?", [payload.model_version, leg, payload.trade_date])
                conn.execute("INSERT INTO nav_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [payload.model_version, leg, payload.trade_date, leg_payload.cash, leg_payload.market_value, leg_payload.total_asset, leg_payload.nav, leg_payload.daily_return, leg_payload.cumulative_return, leg_payload.turnover, leg_payload.commission, leg_payload.rebalanced, leg_payload.factor_coverage, leg_payload.stale_price_count, leg_payload.status, leg_payload.status_message])
                self._insert_positions(conn, payload, leg, leg_payload)
                for trade in leg_payload.trades:
                    trade_id = hashlib.sha256("|".join([payload.model_version, leg, payload.trade_date.isoformat(), str(trade.get("htsc_code")), str(trade.get("side")), str(trade.get("shares"))]).encode("utf-8")).hexdigest()
                    conn.execute("INSERT INTO trade_log VALUES (?,?,?,?,?,?,?,?,?,?)", [trade_id, payload.model_version, leg, payload.trade_date, trade.get("htsc_code"), trade.get("side"), trade.get("shares", 0), trade.get("price", 0.0), trade.get("trade_value", 0.0), trade.get("commission", 0.0)])
            conn.execute("UPDATE run_state SET last_success_date=?,last_rebalance_date=?,config_hash=?,updated_at=current_timestamp WHERE model_version=?", [payload.trade_date, payload.last_rebalance_date, payload.config_hash, payload.model_version])
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
