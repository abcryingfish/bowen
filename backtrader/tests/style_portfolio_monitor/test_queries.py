from datetime import date, timedelta

import pytest

from models.style_portfolio_monitor.config import MODEL_DEFINITIONS, build_config_hash
from models.style_portfolio_monitor.repository import LegDayPayload, ModelDayPayload, StyleMonitorRepository, StyleMonitorValidationError


def seed_repo(tmp_path):
    repo = StyleMonitorRepository(tmp_path / "monitor.duckdb")
    repo.initialize_schema()
    model = MODEL_DEFINITIONS[4]
    version = repo.ensure_model_version(model, build_config_hash(model))
    for index in range(25):
        day = date(2026, 1, 1) + timedelta(days=index)
        leg = {}
        for side, multiplier in [("high", 1.02), ("low", 1.01)]:
            nav = 100.0 * multiplier ** index
            leg[side] = LegDayPayload(900_000, 10_000_000 * nav / 100 - 900_000, 10_000_000 * nav / 100, nav, None, nav / 100 - 1, 0, 0, index == 0, 1, 0, "ok", "", [{"htsc_code": "600000.SH", "score": 90, "rank": 1, "target_weight": 1, "actual_weight": 1, "shares": 100, "price": nav, "market_value": nav, "stale_price": False}], [{"htsc_code": "600000.SH", "side": "BUY", "shares": 100, "price": nav, "trade_value": nav, "commission": nav * .0003}] if index == 0 else [])
        repo.write_model_day(ModelDayPayload(version, model.model_id, build_config_hash(model), day, day if index == 0 else date(2026, 1, 1), leg))
    return repo


def test_summary_ranks_relative_leg_returns_over_1_5_20_days(tmp_path):
    payload = seed_repo(tmp_path).query_summary()
    assert len(payload["models"]) == 10
    assert payload["models"][4]["latest_date"] is not None
    assert payload["rankings"]["1d"]


def test_curves_rebases_selected_window_and_keeps_ratio_formula(tmp_path):
    payload = seed_repo(tmp_path).query_curves("growth_raw", range_key="20d")
    assert payload["series"]["high"][0]["value"] == pytest.approx(100.0)
    assert payload["series"]["low"][0]["value"] == pytest.approx(100.0)
    for high, low, relative in zip(payload["series"]["high"], payload["series"]["low"], payload["series"]["relative"]):
        assert relative["value"] == pytest.approx(high["value"] / low["value"] * 100)


def test_positions_and_trades_validate_model_leg_date_and_limit(tmp_path):
    repo = seed_repo(tmp_path)
    assert repo.query_positions("growth_raw", "high", None)["items"]
    assert len(repo.query_trades("growth_raw", "high", limit=1)["items"]) == 1
    with pytest.raises(StyleMonitorValidationError):
        repo.query_curves("missing", "60d")
