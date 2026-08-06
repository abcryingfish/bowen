"""HTTP-facing read-only facade for the style monitor ledger."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKTRADER_DIR = PROJECT_ROOT / "backtrader"
if str(BACKTRADER_DIR) not in sys.path:
    sys.path.append(str(BACKTRADER_DIR))

from models.style_portfolio_monitor.config import MODEL_DEFINITIONS, STYLE_MONITOR_DB_PATH  # noqa: E402
from models.style_portfolio_monitor.repository import StyleMonitorRepository  # noqa: E402


def _repo() -> StyleMonitorRepository:
    return StyleMonitorRepository(STYLE_MONITOR_DB_PATH)


def query_style_monitor_summary():
    if not STYLE_MONITOR_DB_PATH.is_file():
        models = [{"model_id": model.model_id, "model_version": None, "title": model.title, "factor_name": model.factor_name, "frequency": model.rebalance_frequency, "latest_date": None, "last_rebalance_date": None, "high_nav": None, "low_nav": None, "relative_nav": None, "holding_count_high": 0, "holding_count_low": 0, "status": "empty", "status_message": "尚未运行"} for model in MODEL_DEFINITIONS]
        empty_rankings = {horizon: [{"model_id": model.model_id, "value": None} for model in MODEL_DEFINITIONS] for horizon in ("1d", "5d", "20d")}
        return {"as_of": None, "models": models, "rankings": empty_rankings, "latest_update": None}
    return _repo().query_summary()


def query_style_monitor_curves(model_id: str, range_key: str):
    return _repo().query_curves(model_id, range_key)


def query_style_monitor_positions(model_id: str, leg: str, trade_date: str | None):
    return _repo().query_positions(model_id, leg, trade_date)


def query_style_monitor_trades(model_id: str, leg: str, limit: int):
    return _repo().query_trades(model_id, leg, limit)
