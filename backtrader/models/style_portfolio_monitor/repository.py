"""DuckDB persistence for the incremental style portfolio ledger."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

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
class IndexLegDayPayload:
    index_value: float
    daily_return: float | None
    cumulative_return: float
    rebalanced: bool
    factor_coverage: float | None
    valid_count: int
    valid_price_coverage: float
    status: str
    status_message: str
    weights: list[dict[str, Any]]
    signal_date: date | None = None


@dataclass(frozen=True, slots=True)
class IndexModelDayPayload:
    model_version: str
    model_id: str
    config_hash: str
    trade_date: date
    last_rebalance_date: date | None
    legs: dict[str, IndexLegDayPayload]


@dataclass(frozen=True, slots=True)
class ModelDayPayload:
    model_version: str
    model_id: str
    config_hash: str
    trade_date: date
    last_rebalance_date: date | None
    legs: dict[str, LegDayPayload]


class StyleMonitorRepository:
    _LEGACY_INDEX_COST_COLUMNS = (
        "net_index_value",
        "net_daily_return",
        "turnover",
        "transaction_cost",
    )

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def _connect(self):
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(str(self.database_path))

    @classmethod
    def _drop_legacy_index_cost_columns(cls, conn) -> None:
        """Remove fields used by the retired fee-adjusted index curves."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info('index_daily')").fetchall()}
        for column in cls._LEGACY_INDEX_COST_COLUMNS:
            if column in existing:
                conn.execute(f'ALTER TABLE index_daily DROP COLUMN "{column}"')

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
                CREATE TABLE IF NOT EXISTS index_daily (
                  model_version VARCHAR NOT NULL, leg VARCHAR NOT NULL, trade_date DATE NOT NULL,
                  index_value DOUBLE NOT NULL, daily_return DOUBLE, cumulative_return DOUBLE NOT NULL,
                  rebalanced BOOLEAN NOT NULL, factor_coverage DOUBLE, valid_count INTEGER NOT NULL,
                  valid_price_coverage DOUBLE NOT NULL, status VARCHAR NOT NULL, status_message VARCHAR NOT NULL,
                  signal_date DATE,
                  PRIMARY KEY(model_version, leg, trade_date)
                );
                CREATE TABLE IF NOT EXISTS index_weight_daily (
                  model_version VARCHAR NOT NULL, leg VARCHAR NOT NULL, trade_date DATE NOT NULL,
                  htsc_code VARCHAR NOT NULL, score DOUBLE, rank INTEGER, target_weight DOUBLE NOT NULL,
                  effective_weight DOUBLE NOT NULL,
                  PRIMARY KEY(model_version, leg, trade_date, htsc_code)
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
            conn.execute("ALTER TABLE index_daily ADD COLUMN IF NOT EXISTS signal_date DATE")
            self._drop_legacy_index_cost_columns(conn)
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
            existing_versions = [
                str(item[0])
                for item in conn.execute(
                    "SELECT model_version FROM model_definition WHERE model_id=?",
                    [model.model_id],
                ).fetchall()
            ]
            version_numbers = []
            for item in existing_versions:
                suffix = item.rsplit("-v", 1)[-1]
                if suffix.isdigit():
                    version_numbers.append(int(suffix))
            next_number = max(version_numbers, default=0) + 1
            version = f"{model.model_id}-v{next_number}"
            while conn.execute(
                "SELECT 1 FROM model_definition WHERE model_version=?",
                [version],
            ).fetchone():
                next_number += 1
                version = f"{model.model_id}-v{next_number}"
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

    def index_date_bounds(self, model_version: str) -> tuple[date | None, date | None]:
        """返回理论指数账本的最早和最晚日期。"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT min(trade_date),max(trade_date) FROM index_daily WHERE model_version=?",
                [model_version],
            ).fetchone()
            return (row[0], row[1]) if row else (None, None)
        finally:
            conn.close()

    def load_index_state(self, model_version: str) -> tuple[date | None, dict[str, float], dict[str, dict[str, float]]]:
        """读取最近指数值和生效权重，供增量续算使用。"""
        conn = self._connect()
        try:
            latest = conn.execute("SELECT max(trade_date) FROM index_daily WHERE model_version=?", [model_version]).fetchone()[0]
            if latest is None:
                return None, {}, {"high": {}, "low": {}}
            values = {str(row[0]): float(row[1]) for row in conn.execute("SELECT leg,index_value FROM index_daily WHERE model_version=? AND trade_date=?", [model_version, latest]).fetchall()}
            weights = {"high": {}, "low": {}}
            for leg, code, weight in conn.execute("SELECT leg,htsc_code,effective_weight FROM index_weight_daily WHERE model_version=? AND trade_date=? AND effective_weight>0", [model_version, latest]).fetchall():
                weights.setdefault(str(leg), {})[str(code)] = float(weight)
            return latest, values, weights
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

    def load_position_metadata(self, model_version: str, leg: str) -> dict[str, dict[str, Any]]:
        conn = self._connect()
        try:
            latest = conn.execute(
                "SELECT max(trade_date) FROM position_daily WHERE model_version=? AND leg=?",
                [model_version, leg],
            ).fetchone()[0]
            if latest is None:
                return {}
            rows = conn.execute(
                "SELECT htsc_code,score,rank,target_weight FROM position_daily "
                "WHERE model_version=? AND leg=? AND trade_date=?",
                [model_version, leg, latest],
            ).fetchall()
            return {
                str(row[0]): {"score": row[1], "rank": row[2], "target_weight": row[3]}
                for row in rows
            }
        finally:
            conn.close()

    def count_rows(self, table: str) -> int:
        conn = self._connect()
        try:
            return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        finally:
            conn.close()

    def create_update_run(self, run_id: str, through_date: date | None = None) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO update_run VALUES (?, 'queued', current_timestamp, NULL, NULL, ?, 100, 0, NULL, NULL, NULL, NULL, '', '')",
                [run_id, through_date],
            )
        finally:
            conn.close()

    def update_update_run(
        self,
        run_id: str,
        *,
        status: str,
        progress: int,
        message: str,
        error: str = "",
        current_model_id: str | None = None,
        current_date: date | None = None,
    ) -> None:
        conn = self._connect()
        try:
            terminal = status in {"done", "failed"}
            conn.execute(
                """
                UPDATE update_run
                SET status=?,
                    started_at=CASE WHEN ?='running' THEN coalesce(started_at,current_timestamp) ELSE started_at END,
                    finished_at=CASE WHEN ? THEN current_timestamp ELSE finished_at END,
                    completed_steps=?,current_model_id=?,current_date=?,message=?,error=?
                WHERE run_id=?
                """,
                [status, status, terminal, max(0, min(100, int(progress))), current_model_id, current_date, message, error, run_id],
            )
        finally:
            conn.close()

    def query_summary(self):
        conn = self._connect()
        try:
            return query_summary(conn)
        finally:
            conn.close()

    def query_curves(self, model_id: str, range_key: str, start_date: str | None = None, end_date: str | None = None, benchmark_code: str | None = None):
        conn = self._connect()
        try:
            return query_curves(conn, model_id, range_key, start_date, end_date, benchmark_code)
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

    @staticmethod
    def _validate_index_leg(leg_payload: IndexLegDayPayload) -> None:
        target_sum = sum(float(item.get("target_weight", 0.0) or 0.0) for item in leg_payload.weights)
        effective_sum = sum(float(item.get("effective_weight", 0.0) or 0.0) for item in leg_payload.weights)
        expected_target = 1.0 if leg_payload.rebalanced else (1.0 if target_sum else 0.0)
        if abs(target_sum - expected_target) > 1e-9:
            raise ValueError(f"目标权重和必须为 {expected_target:.12f}: {target_sum:.12f}")
        if effective_sum and abs(effective_sum - 1.0) > 1e-9:
            raise ValueError(f"生效权重和必须为 1.000000000000: {effective_sum:.12f}")
        if any("cash" in item or "shares" in item or "commission" in item for item in leg_payload.weights):
            raise ValueError("等权指数权重快照不能包含现金、股数或手续费字段")

    def write_index_model_day(self, payload: IndexModelDayPayload) -> None:
        self.write_index_model_days([payload])

    def write_index_model_days(self, payloads: list[IndexModelDayPayload]) -> None:
        if not payloads:
            return
        seen_days: set[tuple[str, str, date]] = set()
        for payload in payloads:
            if set(payload.legs) != {"high", "low"}:
                raise ValueError("单日指数账本必须同时包含 high 和 low 两条腿")
            for leg, leg_payload in payload.legs.items():
                day_key = (payload.model_version, leg, payload.trade_date)
                if day_key in seen_days:
                    raise ValueError(f"指数账本批次包含重复日期: {day_key}")
                seen_days.add(day_key)
                codes: set[str] = set()
                for item in leg_payload.weights:
                    code = str(item.get("htsc_code") or "").strip().upper()
                    if not code or code in codes:
                        raise ValueError(f"指数账本权重包含重复股票: {payload.trade_date} {leg} {code}")
                    codes.add(code)
                self._validate_index_leg(leg_payload)
        latest_payload = max(payloads, key=lambda item: item.trade_date)
        model_version = latest_payload.model_version
        config_hash = latest_payload.config_hash
        last_success_date = latest_payload.trade_date
        last_rebalance_date = latest_payload.last_rebalance_date
        conn = self._connect()
        try:
            conn.execute("BEGIN TRANSACTION")
            delete_weight_keys: list[tuple[str, str, date]] = []
            delete_daily_keys: list[tuple[str, str, date]] = []
            daily_rows: list[list[Any]] = []
            weight_rows: list[list[Any]] = []
            for payload in payloads:
                if payload.model_version != model_version:
                    raise ValueError("批量指数账本不能混合多个模型版本")
                if payload.config_hash != config_hash:
                    raise ValueError("批量指数账本不能混合多个配置哈希")
                if payload.model_id != latest_payload.model_id:
                    raise ValueError("批量指数账本不能混合多个模型")
                for leg, leg_payload in payload.legs.items():
                    delete_weight_keys.append((payload.model_version, leg, payload.trade_date))
                    delete_daily_keys.append((payload.model_version, leg, payload.trade_date))
                    daily_rows.append([
                        payload.model_version,
                        leg,
                        payload.trade_date,
                        leg_payload.index_value,
                        leg_payload.daily_return,
                        leg_payload.cumulative_return,
                        leg_payload.rebalanced,
                        leg_payload.factor_coverage,
                        leg_payload.valid_count,
                        leg_payload.valid_price_coverage,
                        leg_payload.status,
                        leg_payload.status_message,
                        leg_payload.signal_date,
                    ])
                    for item in leg_payload.weights:
                        weight_rows.append([
                            payload.model_version,
                            leg,
                            payload.trade_date,
                            item.get("htsc_code"),
                            item.get("score"),
                            item.get("rank"),
                            float(item.get("target_weight", 0.0) or 0.0),
                            float(item.get("effective_weight", 0.0) or 0.0),
                        ])
            conn.executemany(
                "DELETE FROM index_weight_daily WHERE model_version=? AND leg=? AND trade_date=?",
                delete_weight_keys,
            )
            conn.executemany(
                "DELETE FROM index_daily WHERE model_version=? AND leg=? AND trade_date=?",
                delete_daily_keys,
            )
            daily_frame = pd.DataFrame(daily_rows, columns=["model_version", "leg", "trade_date", "index_value", "daily_return", "cumulative_return", "rebalanced", "factor_coverage", "valid_count", "valid_price_coverage", "status", "status_message", "signal_date"])
            weight_frame = pd.DataFrame(weight_rows, columns=["model_version", "leg", "trade_date", "htsc_code", "score", "rank", "target_weight", "effective_weight"])
            conn.register("_index_daily_batch", daily_frame)
            conn.execute("""
                INSERT INTO index_daily (
                    model_version,leg,trade_date,index_value,daily_return,cumulative_return,
                    rebalanced,factor_coverage,valid_count,valid_price_coverage,status,status_message,
                    signal_date
                ) SELECT
                    model_version,leg,trade_date,index_value,daily_return,cumulative_return,
                    rebalanced,factor_coverage,valid_count,valid_price_coverage,status,status_message,
                    signal_date
                FROM _index_daily_batch
            """)
            conn.unregister("_index_daily_batch")
            if not weight_frame.empty:
                conn.register("_index_weight_batch", weight_frame)
                conn.execute("INSERT INTO index_weight_daily SELECT * FROM _index_weight_batch")
                conn.unregister("_index_weight_batch")
            conn.execute(
                "UPDATE run_state SET last_success_date=?,last_rebalance_date=?,config_hash=?,updated_at=current_timestamp WHERE model_version=?",
                [last_success_date, last_rebalance_date, config_hash, model_version],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def clear_index_model(self, model_version: str) -> None:
        """删除指定模型的理论指数数据及遗留现金账本记录。"""
        conn = self._connect()
        try:
            conn.execute("BEGIN TRANSACTION")
            conn.execute("DELETE FROM index_weight_daily WHERE model_version=?", [model_version])
            conn.execute("DELETE FROM index_daily WHERE model_version=?", [model_version])
            conn.execute("DELETE FROM trade_log WHERE model_version=?", [model_version])
            conn.execute("DELETE FROM position_daily WHERE model_version=?", [model_version])
            conn.execute("DELETE FROM nav_daily WHERE model_version=?", [model_version])
            conn.execute("UPDATE run_state SET last_success_date=NULL,last_rebalance_date=NULL WHERE model_version=?", [model_version])
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def clear_legacy_cash_ledger(self) -> None:
        """清空已停用的现金净账本表，避免旧数据再次落盘或被误用。"""
        conn = self._connect()
        try:
            conn.execute("BEGIN TRANSACTION")
            conn.execute("DELETE FROM trade_log")
            conn.execute("DELETE FROM position_daily")
            conn.execute("DELETE FROM nav_daily")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
