#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""将黄金概念板块的客观 staging 数据导入项目内 Neo4j。

本脚本只导入可由 staging 文件直接证明的事实：板块、成分股、快照归属、
日频行情观察和极值窗口。语义研究尚未完成，因此不会生成 Event、Evidence
或 IMPACTS 关系，避免把未经证实的上涨/下跌原因写入知识图谱。

脚本使用 Python 标准库 + pyarrow + neo4j driver。项目主环境中的 pyarrow
和复制环境中的 neo4j driver 分开存在，因此启动时会显式补充两个环境的
site-packages 路径；这也绕开了旧环境中一个非 UTF-8 的 iFinDPy.pth 文件。
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


SCRIPT_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_ROOT.parent
STAGING_DEFAULT = Path(r"D:\database\sector_information\_staging\gold_885530_20260821")


def _add_dependency_paths() -> None:
    """加载主项目的数据依赖和 Neo4j 专用环境，保持中文路径兼容。"""
    candidates = [
        PROJECT_ROOT / ".venv" / "Lib" / "site-packages",
        SCRIPT_ROOT / ".venv" / "Lib" / "site-packages",
    ]
    for path in reversed(candidates):
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))


_add_dependency_paths()

import pyarrow.parquet as pq  # noqa: E402
from neo4j import GraphDatabase  # noqa: E402


def _configure_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _read_json(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_parquet(path: Path) -> list[dict[str, Any]]:
    return pq.read_table(path).to_pylist()


def _as_temporal(value: Any) -> Any:
    """将 ISO 日期转换为 Neo4j driver 可序列化的 date/datetime。"""
    if value is None or isinstance(value, (date, datetime)):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        if "T" in normalized or " " in normalized:
            return datetime.fromisoformat(normalized)
        return date.fromisoformat(normalized)
    except ValueError:
        return value


def _clean_value(value: Any, *, temporal: bool = False) -> Any:
    if temporal:
        value = _as_temporal(value)
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    # pyarrow usually returns native Python scalars, but this keeps the importer
    # safe if a future file is read through a pandas/numpy-backed adapter.
    item = getattr(value, "item", None)
    if callable(item):
        try:
            value = item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, (list, tuple)):
        return [_clean_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _clean_value(item) for key, item in value.items()}
    return value


def _drop_none(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if value is not None}


def _snapshot_date(snapshot_id: str, analysis_date: str) -> date:
    # snapshot_YYYYMMDD_<hash> is the format produced by the staging pipeline.
    parts = snapshot_id.split("_")
    if len(parts) >= 2 and len(parts[1]) == 8:
        try:
            return datetime.strptime(parts[1], "%Y%m%d").date()
        except ValueError:
            pass
    parsed = _as_temporal(analysis_date)
    return parsed if isinstance(parsed, date) else date.today()


def _flatten_scalar_metrics(prefix: str, values: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, (dict, list, tuple)):
            continue
        cleaned = _clean_value(value)
        if cleaned is not None:
            result[f"{prefix}_{key}"] = cleaned
    return result


def build_rows(staging: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    manifest = _read_json(staging / "manifest.json")
    metrics = _read_json(staging / "objective_metrics.json")
    market_rows = _read_parquet(staging / "member_market_rows.parquet")
    fundamental_rows = _read_parquet(staging / "member_fundamental_rows.parquet")
    observations = _read_parquet(staging / "market_observations.parquet")
    move_windows = _read_parquet(staging / "move_candidates.parquet")

    sector_code = str(metrics["sector_code"])
    snapshot_id = str(metrics["snapshot_id"])
    snapshot_date = _snapshot_date(snapshot_id, str(metrics["analysis_date"]))

    sector: dict[str, Any] = {
        "entity_id": sector_code,
        "sector_id": sector_code,
        "canonical_name": str(metrics["sector_name"]),
        "sector_name": str(metrics["sector_name"]),
        "sector_type": "theme",
        "level": "theme",
        "source": "同花顺",
        "source_system": "THS",
        "analysis_date": _as_temporal(metrics.get("analysis_date")),
        "latest_complete_trade_date": _as_temporal(metrics.get("latest_complete_trade_date")),
        "history_start": _as_temporal(metrics.get("history_start")),
        "research_window_start": _as_temporal(metrics.get("research_window_start")),
        "snapshot_id": snapshot_id,
        "snapshot_date": snapshot_date,
        "research_status": str(manifest.get("status", "objective_only")),
        "evidence_count": int(manifest.get("evidence_count", 0)),
        "objective_data_completed": bool(manifest.get("objective_data_completed", False)),
        "semantic_research_completed": bool(manifest.get("semantic_research_completed", False)),
        "source_member_count": int(metrics.get("source_member_count", 0)),
        "eligible_member_count": int(metrics.get("eligible_member_count", 0)),
        "excluded_bj_count": int(metrics.get("excluded_bj_count", 0)),
    }
    sector.update(_flatten_scalar_metrics("index", metrics.get("index_metrics", {})))
    sector.update(_flatten_scalar_metrics("benchmark", metrics.get("benchmark_metrics", {})))
    sector.update(_flatten_scalar_metrics("breadth", metrics.get("member_breadth", {})))
    sector.update(_flatten_scalar_metrics("turnover", metrics.get("turnover", {})))
    sector.update(_flatten_scalar_metrics("aggregate", metrics.get("member_aggregates", {})))
    sector = _drop_none(sector)

    market_by_code = {str(row["stock_code"]): row for row in market_rows if row.get("stock_code")}
    fundamental_by_code = {str(row["stock_code"]): row for row in fundamental_rows if row.get("stock_code")}
    eligible_codes = [str(code) for code in metrics.get("eligible_codes", [])]
    codes = sorted(set(eligible_codes) | set(market_by_code) | set(fundamental_by_code))

    stocks: list[dict[str, Any]] = []
    memberships: list[dict[str, Any]] = []
    for code in codes:
        market = market_by_code.get(code, {})
        fundamental = fundamental_by_code.get(code, {})
        name = market.get("name") or fundamental.get("name") or code
        exchange = market.get("exchange") or fundamental.get("exchange")
        stock: dict[str, Any] = {
            "entity_id": f"stock:{code}",
            "stock_id": code,
            "stock_code": code,
            "canonical_name": str(name),
            "stock_name": str(name),
            "exchange": exchange,
            "asset_type": "A_share",
            "source_snapshot_id": snapshot_id,
            "data_cutoff": _as_temporal(market.get("data_cutoff")),
            "latest_close": market.get("latest_close"),
            "return_5d_pct": market.get("return_5d_pct"),
            "return_20d_pct": market.get("return_20d_pct"),
            "return_60d_pct": market.get("return_60d_pct"),
            "return_250d_pct": market.get("return_250d_pct"),
            "return_5y_pct": market.get("return_5y_pct"),
            "annualized_return_5y_pct": market.get("annualized_return_5y_pct"),
            "close_vs_ma20_pct": market.get("close_vs_ma20_pct"),
            "close_vs_ma60_pct": market.get("close_vs_ma60_pct"),
            "volatility_20d_annualized_pct": market.get("volatility_20d_annualized_pct"),
            "max_drawdown_5y_pct": market.get("max_drawdown_5y_pct"),
            "amount_5d_vs_20d_pct": market.get("amount_5d_vs_20d_pct"),
            "fundamental_data_cutoff": _as_temporal(fundamental.get("time")),
            "income_report_date": _as_temporal(fundamental.get("income_report_date")),
            "income_announce_date": _as_temporal(fundamental.get("income_announce_date")),
            "total_market_val": fundamental.get("total_market_val"),
            "pe_ttm": fundamental.get("pe_ttm"),
            "pb": fundamental.get("pb"),
            "roe": fundamental.get("roe"),
            "profitable": fundamental.get("profitable"),
            "revenue_yoy_pct": fundamental.get("revenue_yoy_pct"),
            "profit_yoy_pct": fundamental.get("profit_yoy_pct"),
        }
        stock = _drop_none({key: _clean_value(value) for key, value in stock.items()})
        stocks.append(stock)
        memberships.append(
            {
                "stock_entity_id": stock["entity_id"],
                "sector_entity_id": sector_code,
                "snapshot_id": snapshot_id,
                # This is deliberately a point-in-time snapshot interval, not a
                # claim that the stock entered the sector on this date.
                "valid_from": snapshot_date,
                "valid_to": snapshot_date,
                "as_of_date": snapshot_date,
                "validity_scope": "snapshot_only",
                "rule_version": "ths_snapshot_v1",
                "source": "同花顺",
            }
        )

    observation_rows: list[dict[str, Any]] = []
    for row in observations:
        observed = _as_temporal(row.get("time"))
        observed_key = observed.isoformat() if isinstance(observed, (date, datetime)) else str(row.get("time"))
        observation_rows.append(
            _drop_none(
                {
                    "observation_id": f"{sector_code}|{observed_key}",
                    "sector_entity_id": sector_code,
                    "observed_at": observed,
                    "close": _clean_value(row.get("close")),
                    "value": _clean_value(row.get("value")),
                    "benchmark_close": _clean_value(row.get("benchmark_close")),
                    "sector_normalized_close": _clean_value(row.get("sector_normalized_close")),
                    "benchmark_normalized_close": _clean_value(row.get("benchmark_normalized_close")),
                    "sector_daily_return_pct": _clean_value(row.get("sector_daily_return_pct")),
                    "benchmark_daily_return_pct": _clean_value(row.get("benchmark_daily_return_pct")),
                    "normalized_spread_points": _clean_value(row.get("normalized_spread_points")),
                }
            )
        )

    move_rows: list[dict[str, Any]] = []
    for row in move_windows:
        start = _as_temporal(row.get("start_time"))
        end = _as_temporal(row.get("end_time"))
        direction = str(row.get("direction"))
        window_days = int(row.get("window_days"))
        rank = int(row.get("rank"))
        move_rows.append(
            _drop_none(
                {
                    "move_id": f"{sector_code}|{direction}|{window_days}|{rank}|{start}|{end}",
                    "sector_entity_id": sector_code,
                    "direction": direction,
                    "window_days": window_days,
                    "start_time": start,
                    "end_time": end,
                    "return_pct": _clean_value(row.get("return_pct")),
                    "rank": rank,
                    "fact_status": "objective_only",
                }
            )
        )

    return sector, stocks, memberships, observation_rows, move_rows


CONSTRAINTS = [
    "CREATE CONSTRAINT sector_entity_id_unique IF NOT EXISTS FOR (n:Sector) REQUIRE n.entity_id IS UNIQUE",
    "CREATE CONSTRAINT stock_entity_id_unique IF NOT EXISTS FOR (n:Stock) REQUIRE n.entity_id IS UNIQUE",
    "CREATE CONSTRAINT market_observation_id_unique IF NOT EXISTS FOR (n:MarketObservation) REQUIRE n.observation_id IS UNIQUE",
    "CREATE CONSTRAINT move_window_id_unique IF NOT EXISTS FOR (n:MoveWindow) REQUIRE n.move_id IS UNIQUE",
]

UPSERT_SECTOR = """
UNWIND $rows AS row
MERGE (s:Sector {entity_id: row.entity_id})
SET s += row
"""

UPSERT_STOCKS = """
UNWIND $rows AS row
MERGE (s:Stock {entity_id: row.entity_id})
SET s += row
"""

UPSERT_MEMBERSHIPS = """
UNWIND $rows AS row
MATCH (stock:Stock {entity_id: row.stock_entity_id})
MATCH (sector:Sector {entity_id: row.sector_entity_id})
MERGE (stock)-[r:MEMBER_OF {snapshot_id: row.snapshot_id}]->(sector)
SET r += row
"""

UPSERT_OBSERVATIONS = """
UNWIND $rows AS row
MATCH (sector:Sector {entity_id: row.sector_entity_id})
MERGE (observation:MarketObservation {observation_id: row.observation_id})
SET observation += row
MERGE (sector)-[:HAS_MARKET_OBSERVATION]->(observation)
"""

UPSERT_MOVES = """
UNWIND $rows AS row
MATCH (sector:Sector {entity_id: row.sector_entity_id})
MERGE (move:MoveWindow {move_id: row.move_id})
SET move += row
MERGE (sector)-[:HAS_MOVE_WINDOW]->(move)
"""


def _chunks(values: list[dict[str, Any]], size: int = 500) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _write_rows(driver: Any, database: str, query: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with driver.session(database=database) as session:
        for chunk in _chunks(rows):
            session.execute_write(lambda tx, batch=chunk: tx.run(query, rows=batch).consume())


def import_graph(
    *,
    staging: Path,
    uri: str,
    user: str,
    password: str,
    database: str,
    dry_run: bool,
) -> None:
    sector, stocks, memberships, observations, moves = build_rows(staging)
    print(
        f"准备导入：Sector={1} Stock={len(stocks)} "
        f"MarketObservation={len(observations)} MoveWindow={len(moves)} "
        f"MEMBER_OF={len(memberships)}"
    )
    print(f"研究状态：{sector.get('research_status')}；证据数：{sector.get('evidence_count', 0)}")
    if dry_run:
        print("dry-run：未连接 Neo4j，未写入数据。")
        return

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
        with driver.session(database=database) as session:
            for statement in CONSTRAINTS:
                session.run(statement).consume()
        _write_rows(driver, database, UPSERT_SECTOR, [sector])
        _write_rows(driver, database, UPSERT_STOCKS, stocks)
        _write_rows(driver, database, UPSERT_MEMBERSHIPS, memberships)
        _write_rows(driver, database, UPSERT_OBSERVATIONS, observations)
        _write_rows(driver, database, UPSERT_MOVES, moves)
        with driver.session(database=database) as session:
            counts = {}
            for key, query in {
                "sectors": "MATCH (n:Sector) RETURN count(n) AS value",
                "stocks": "MATCH (n:Stock) RETURN count(n) AS value",
                "observations": "MATCH (n:MarketObservation) RETURN count(n) AS value",
                "moves": "MATCH (n:MoveWindow) RETURN count(n) AS value",
                "memberships": "MATCH ()-[r:MEMBER_OF]->() RETURN count(r) AS value",
            }.items():
                counts[key] = session.run(query).single()["value"]
        print(
            "导入完成："
            f"Sector={counts['sectors']} Stock={counts['stocks']} "
            f"MarketObservation={counts['observations']} MoveWindow={counts['moves']} "
            f"MEMBER_OF={counts['memberships']}"
        )
    finally:
        driver.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入黄金概念板块客观数据到 Neo4j")
    parser.add_argument("--staging", type=Path, default=STAGING_DEFAULT)
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"))
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD", "password123"))
    parser.add_argument("--database", default=os.getenv("NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    _configure_utf8_output()
    args = parse_args()
    if not args.staging.is_dir():
        raise SystemExit(f"找不到 staging 目录：{args.staging}")
    import_graph(
        staging=args.staging,
        uri=args.uri,
        user=args.user,
        password=args.password,
        database=args.database,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
