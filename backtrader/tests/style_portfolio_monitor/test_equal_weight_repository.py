from datetime import date

import pytest

from models.style_portfolio_monitor.config import MODEL_DEFINITIONS, build_config_hash
from models.style_portfolio_monitor.repository import (
    IndexLegDayPayload,
    IndexModelDayPayload,
    LegDayPayload,
    ModelDayPayload,
    StyleMonitorRepository,
)


def test_index_schema_and_write_are_weight_only(tmp_path) -> None:
    repo = StyleMonitorRepository(tmp_path / "monitor.duckdb")
    repo.initialize_schema()
    assert {"index_daily", "index_weight_daily"} <= set(repo.list_tables())
    assert repo.primary_key_columns("index_daily") == ["model_version", "leg", "trade_date"]
    conn = repo._connect()
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info('index_daily')").fetchall()}
    finally:
        conn.close()
    assert {"net_index_value", "net_daily_return", "turnover", "transaction_cost"}.isdisjoint(
        columns
    )

    model = MODEL_DEFINITIONS[0]
    version = repo.ensure_model_version(model, build_config_hash(model))
    payload = IndexModelDayPayload(
        model_version=version,
        model_id=model.model_id,
        config_hash=build_config_hash(model),
        trade_date=date(2026, 1, 2),
        last_rebalance_date=date(2026, 1, 1),
        legs={
            "high": IndexLegDayPayload(101.0, 0.01, 0.01, False, 1.0, 2, 1.0, "ok", "", [{"htsc_code": "A.SZ", "score": 90.0, "rank": 1, "target_weight": 1.0, "effective_weight": 1.0}]),
            "low": IndexLegDayPayload(99.0, -0.01, -0.01, False, 1.0, 2, 1.0, "ok", "", [{"htsc_code": "B.SZ", "score": 10.0, "rank": 1, "target_weight": 1.0, "effective_weight": 1.0}]),
        },
    )

    repo.write_index_model_day(payload)
    repo.write_index_model_day(payload)

    assert repo.count_rows("index_daily") == 2
    assert repo.count_rows("index_weight_daily") == 2
    assert repo.count_rows("trade_log") == 0


def test_schema_migration_removes_legacy_fee_columns_and_keeps_gross_index(tmp_path) -> None:
    repo = StyleMonitorRepository(tmp_path / "monitor.duckdb")
    repo.initialize_schema()
    conn = repo._connect()
    try:
        conn.execute("ALTER TABLE index_daily ADD COLUMN net_index_value DOUBLE")
        conn.execute("ALTER TABLE index_daily ADD COLUMN net_daily_return DOUBLE")
        conn.execute("ALTER TABLE index_daily ADD COLUMN turnover DOUBLE DEFAULT 0")
        conn.execute("ALTER TABLE index_daily ADD COLUMN transaction_cost DOUBLE DEFAULT 0")
        conn.execute(
            """
            INSERT INTO index_daily (
                model_version,leg,trade_date,index_value,daily_return,cumulative_return,
                rebalanced,factor_coverage,valid_count,valid_price_coverage,status,status_message,
                signal_date,net_index_value,net_daily_return,turnover,transaction_cost
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            ["large_cap_raw-v1", "high", date(2026, 1, 2), 110.0, 0.1, 0.1, True, 1.0, 1, 1.0, "ok", "", date(2026, 1, 1), 109.9, 0.099, 1.0, 0.0003],
        )
    finally:
        conn.close()

    repo.initialize_schema()

    conn = repo._connect()
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info('index_daily')").fetchall()}
        gross_row = conn.execute("SELECT index_value,daily_return,cumulative_return,signal_date FROM index_daily").fetchone()
    finally:
        conn.close()
    assert {"net_index_value", "net_daily_return", "turnover", "transaction_cost"}.isdisjoint(columns)
    assert gross_row == (110.0, 0.1, 0.1, date(2026, 1, 1))


def test_rebuild_clears_legacy_cash_rows_for_model(tmp_path) -> None:
    repo = StyleMonitorRepository(tmp_path / "monitor.duckdb")
    repo.initialize_schema()
    model = MODEL_DEFINITIONS[0]
    version = repo.ensure_model_version(model, build_config_hash(model))
    leg = LegDayPayload(
        0.0,
        10_000_000.0,
        10_000_000.0,
        100.0,
        None,
        0.0,
        1.0,
        3_000.0,
        True,
        1.0,
        0,
        "ok",
        "",
        [],
        [],
    )
    repo.write_model_day(ModelDayPayload(version, model.model_id, build_config_hash(model), date(2026, 1, 2), date(2026, 1, 2), {"high": leg, "low": leg}))

    repo.clear_index_model(version)

    assert repo.count_rows("nav_daily") == 0
    assert repo.count_rows("position_daily") == 0
    assert repo.count_rows("trade_log") == 0


def test_index_write_rejects_non_unit_weight_sum(tmp_path) -> None:
    repo = StyleMonitorRepository(tmp_path / "monitor.duckdb")
    repo.initialize_schema()
    model = MODEL_DEFINITIONS[0]
    version = repo.ensure_model_version(model, build_config_hash(model))
    leg = IndexLegDayPayload(100.0, None, 0.0, True, 1.0, 1, 1.0, "ok", "", [{"htsc_code": "A.SZ", "score": 90.0, "rank": 1, "target_weight": 0.5, "effective_weight": 0.5}])
    payload = IndexModelDayPayload(version, model.model_id, build_config_hash(model), date(2026, 1, 2), date(2026, 1, 1), {"high": leg, "low": leg})

    try:
        repo.write_index_model_day(payload)
    except ValueError as exc:
        assert "权重" in str(exc)
    else:
        raise AssertionError("非单位权重应被拒绝")


def test_index_batch_write_rejects_duplicate_model_leg_days(tmp_path) -> None:
    repo = StyleMonitorRepository(tmp_path / "monitor.duckdb")
    repo.initialize_schema()
    model = MODEL_DEFINITIONS[0]
    version = repo.ensure_model_version(model, build_config_hash(model))
    leg = IndexLegDayPayload(100.0, None, 0.0, True, 1.0, 1, 1.0, "ok", "", [{"htsc_code": "A.SZ", "score": 90.0, "rank": 1, "target_weight": 1.0, "effective_weight": 0.0}])
    payload = IndexModelDayPayload(version, model.model_id, build_config_hash(model), date(2026, 1, 2), date(2026, 1, 2), {"high": leg, "low": leg})

    with pytest.raises(ValueError, match="重复"):
        repo.write_index_model_days([payload, payload])


def test_index_batch_write_uses_latest_date_for_run_state_even_when_payloads_are_unsorted(tmp_path) -> None:
    repo = StyleMonitorRepository(tmp_path / "monitor.duckdb")
    repo.initialize_schema()
    model = MODEL_DEFINITIONS[0]
    version = repo.ensure_model_version(model, build_config_hash(model))
    def payload(day: date) -> IndexModelDayPayload:
        leg = IndexLegDayPayload(100.0, None, 0.0, True, 1.0, 1, 1.0, "ok", "", [{"htsc_code": "A.SZ", "score": 90.0, "rank": 1, "target_weight": 1.0, "effective_weight": 1.0}], signal_date=day)
        return IndexModelDayPayload(version, model.model_id, build_config_hash(model), day, day, {"high": leg, "low": leg})

    repo.write_index_model_days([payload(date(2026, 1, 3)), payload(date(2026, 1, 2))])

    assert repo.get_run_state(version).last_success_date == date(2026, 1, 3)


def test_index_queries_use_index_tables_and_expose_no_money_fields(tmp_path) -> None:
    repo = StyleMonitorRepository(tmp_path / "monitor.duckdb")
    repo.initialize_schema()
    model = MODEL_DEFINITIONS[0]
    version = repo.ensure_model_version(model, build_config_hash(model))
    leg = IndexLegDayPayload(100.0, None, 0.0, True, 1.0, 1, 1.0, "ok", "", [{"htsc_code": "A.SZ", "score": 90.0, "rank": 1, "target_weight": 1.0, "effective_weight": 0.0}])
    repo.write_index_model_day(IndexModelDayPayload(version, model.model_id, build_config_hash(model), date(2026, 1, 1), date(2026, 1, 1), {"high": leg, "low": leg}))
    high_day_two = IndexLegDayPayload(
        110.0, 0.1, 0.1, True, 1.0, 1, 1.0, "ok", "",
        [{"htsc_code": "A.SZ", "score": 90.0, "rank": 1, "target_weight": 1.0, "effective_weight": 1.0}],
        signal_date=date(2026, 1, 1),
    )
    low_day_two = IndexLegDayPayload(
        90.0, -0.1, -0.1, True, 1.0, 1, 1.0, "ok", "",
        [{"htsc_code": "B.SZ", "score": 10.0, "rank": 1, "target_weight": 1.0, "effective_weight": 1.0}],
        signal_date=date(2026, 1, 1),
    )
    repo.write_index_model_day(IndexModelDayPayload(version, model.model_id, build_config_hash(model), date(2026, 1, 2), date(2026, 1, 1), {"high": high_day_two, "low": low_day_two}))

    summary = repo.query_summary()
    assert summary["models"][0]["high_nav"] == 110.0
    assert summary["models"][0]["valid_price_coverage_high"] == 1.0
    assert summary["models"][0]["valid_price_coverage_low"] == 1.0
    curve = repo.query_curves("large_cap_raw", "all")
    assert curve["series"]["high"][0]["value"] == 100.0
    assert curve["series"]["high"][1]["value"] == pytest.approx(110.0)
    assert curve["series"]["low"][1]["value"] == pytest.approx(90.0)
    assert set(curve["series"]) == {"high", "low", "relative"}
    positions = repo.query_positions("large_cap_raw", "high", None)["items"][0]
    assert positions["target_weight"] == 1.0
    assert "shares" not in positions
    assert "price" not in positions
    trades = repo.query_trades("large_cap_raw", "high", 10)
    assert trades["items"] == []
    assert "无现金交易" in trades["message"]


def test_index_summary_holding_count_uses_effective_weights(tmp_path) -> None:
    repo = StyleMonitorRepository(tmp_path / "monitor.duckdb")
    repo.initialize_schema()
    model = MODEL_DEFINITIONS[0]
    version = repo.ensure_model_version(model, build_config_hash(model))
    high = IndexLegDayPayload(
        100.0, None, 0.0, True, 1.0, 1, 1.0, "ok", "",
        [
            {"htsc_code": "A.SZ", "score": 90.0, "rank": 1, "target_weight": 1.0, "effective_weight": 0.0},
            {"htsc_code": "B.SZ", "score": 80.0, "rank": 2, "target_weight": 0.0, "effective_weight": 1.0},
        ],
    )
    repo.write_index_model_day(IndexModelDayPayload(version, model.model_id, build_config_hash(model), date(2026, 1, 2), date(2026, 1, 1), {"high": high, "low": high}))

    assert repo.query_summary()["models"][0]["holding_count_high"] == 1
