from datetime import date

import pytest

from models.style_portfolio_monitor.config import MODEL_DEFINITIONS
from models.style_portfolio_monitor.repository import (
    LegDayPayload,
    ModelDayPayload,
    StyleMonitorRepository,
)


def ready_repository(tmp_path):
    repo = StyleMonitorRepository(tmp_path / "monitor.duckdb")
    repo.initialize_schema()
    return repo


def make_model_day_payload(model_version="large_cap_raw-v1"):
    return ModelDayPayload(
        model_version=model_version,
        model_id="large_cap_raw",
        config_hash="hash-a",
        trade_date=date(2026, 1, 30),
        last_rebalance_date=date(2026, 1, 30),
        legs={
            "high": LegDayPayload(cash=900.0, market_value=100.0, total_asset=1000.0, nav=100.0, daily_return=0.0, cumulative_return=0.0, turnover=0.1, commission=0.1, rebalanced=True, factor_coverage=1.0, stale_price_count=0, status="ok", status_message="", positions=[{"htsc_code": "600000.SH", "score": 90.0, "rank": 1, "target_weight": 1.0, "actual_weight": 0.1, "shares": 100, "price": 1.0, "market_value": 100.0, "stale_price": False}], trades=[{"htsc_code": "600000.SH", "side": "BUY", "shares": 100, "price": 1.0, "trade_value": 100.0, "commission": 0.1}]),
            "low": LegDayPayload(cash=900.0, market_value=100.0, total_asset=1000.0, nav=100.0, daily_return=0.0, cumulative_return=0.0, turnover=0.1, commission=0.1, rebalanced=True, factor_coverage=1.0, stale_price_count=0, status="ok", status_message="", positions=[{"htsc_code": "600000.SH", "score": 10.0, "rank": 1, "target_weight": 1.0, "actual_weight": 0.1, "shares": 100, "price": 1.0, "market_value": 100.0, "stale_price": False}], trades=[{"htsc_code": "600000.SH", "side": "BUY", "shares": 100, "price": 1.0, "trade_value": 100.0, "commission": 0.1}]),
        },
    )


def test_schema_contains_required_tables_and_two_leg_primary_keys(tmp_path):
    repo = ready_repository(tmp_path)
    assert {"model_definition", "nav_daily", "position_daily", "trade_log", "run_state", "update_run"} <= set(repo.list_tables())
    assert repo.primary_key_columns("nav_daily") == ["model_version", "leg", "trade_date"]


def test_ensure_model_version_reuses_same_hash_and_creates_new_version_for_changed_hash(tmp_path):
    repo = ready_repository(tmp_path)
    first = repo.ensure_model_version(MODEL_DEFINITIONS[0], "hash-a")
    assert repo.ensure_model_version(MODEL_DEFINITIONS[0], "hash-a") == first
    assert repo.ensure_model_version(MODEL_DEFINITIONS[0], "hash-b") != first


def test_ensure_model_version_skips_existing_version_number_after_cleanup(tmp_path):
    repo = ready_repository(tmp_path)
    first = repo.ensure_model_version(MODEL_DEFINITIONS[0], "hash-a")
    second = repo.ensure_model_version(MODEL_DEFINITIONS[0], "hash-b")
    assert first == "large_cap_raw-v1"
    assert second == "large_cap_raw-v2"
    conn = repo._connect()
    try:
        conn.execute("DELETE FROM model_definition WHERE model_version=?", [first])
        conn.execute("DELETE FROM run_state WHERE model_version=?", [first])
    finally:
        conn.close()
    assert repo.ensure_model_version(MODEL_DEFINITIONS[0], "hash-c") == "large_cap_raw-v3"


def test_write_model_day_is_idempotent(tmp_path):
    repo = ready_repository(tmp_path)
    payload = make_model_day_payload()
    repo.write_model_day(payload)
    repo.write_model_day(payload)
    assert repo.count_rows("nav_daily") == 2
    assert repo.count_rows("trade_log") == 2


def test_failed_day_rolls_back_all_rows_and_does_not_advance_watermark(tmp_path, monkeypatch):
    repo = ready_repository(tmp_path)
    monkeypatch.setattr(repo, "_insert_positions", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        repo.write_model_day(make_model_day_payload())
    assert repo.count_rows("nav_daily") == 0
    assert repo.get_run_state("large_cap_raw-v1").last_success_date is None


def test_update_run_lifecycle_is_persisted_for_summary(tmp_path):
    repo = ready_repository(tmp_path)
    repo.create_update_run("run-1", through_date=date(2026, 1, 30))
    repo.update_update_run("run-1", status="running", progress=25, message="growth_raw 2026-01-10")
    repo.update_update_run("run-1", status="done", progress=100, message="更新完成")

    latest = repo.query_summary()["latest_update"]
    assert latest["run_id"] == "run-1"
    assert latest["status"] == "done"
    assert latest["progress"] == 100
    assert latest["through_date"] == "2026-01-30"
