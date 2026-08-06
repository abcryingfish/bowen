"""HTTP-facing read-only facade for the style monitor ledger."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKTRADER_DIR = PROJECT_ROOT / "backtrader"
if str(BACKTRADER_DIR) not in sys.path:
    sys.path.append(str(BACKTRADER_DIR))

from models.style_portfolio_monitor.config import STYLE_MONITOR_DB_PATH  # noqa: E402
from models.style_portfolio_monitor.repository import StyleMonitorRepository  # noqa: E402


def _repo() -> StyleMonitorRepository:
    return StyleMonitorRepository(STYLE_MONITOR_DB_PATH)


def query_style_monitor_summary():
    return _repo().query_summary()


def query_style_monitor_curves(model_id: str, range_key: str):
    return _repo().query_curves(model_id, range_key)


def query_style_monitor_positions(model_id: str, leg: str, trade_date: str | None):
    return _repo().query_positions(model_id, leg, trade_date)


def query_style_monitor_trades(model_id: str, leg: str, limit: int):
    return _repo().query_trades(model_id, leg, limit)
