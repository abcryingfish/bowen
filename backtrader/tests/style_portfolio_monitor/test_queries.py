from datetime import date, timedelta

import pandas as pd
import pytest

from models.style_portfolio_monitor.config import MODEL_DEFINITIONS, build_config_hash
from models.style_portfolio_monitor import query as query_module
from models.style_portfolio_monitor.repository import (
    IndexLegDayPayload,
    IndexModelDayPayload,
    LegDayPayload,
    ModelDayPayload,
    StyleMonitorRepository,
    StyleMonitorValidationError,
)


def seed_repo(tmp_path):
    repo = StyleMonitorRepository(tmp_path / "monitor.duckdb")
    repo.initialize_schema()
    model = MODEL_DEFINITIONS[4]
    version = repo.ensure_model_version(model, build_config_hash(model))
    for index in range(25):
        day = date(2026, 1, 1) + timedelta(days=index)
        leg = {}
        for side, multiplier in [("high", 1.02), ("low", 1.01)]:
            index_value = 100.0 * multiplier ** index
            leg[side] = IndexLegDayPayload(
                index_value,
                None if index == 0 else multiplier - 1.0,
                index_value / 100.0 - 1.0,
                True,
                1.0,
                1,
                1.0,
                "ok",
                "",
                [{"htsc_code": "600000.SH", "score": 90, "rank": 1, "target_weight": 1.0, "effective_weight": 1.0}],
                signal_date=day,
            )
        repo.write_index_model_day(IndexModelDayPayload(version, model.model_id, build_config_hash(model), day, day, leg))
    return repo


def test_summary_ranks_relative_leg_returns_over_1_5_20_days(tmp_path):
    payload = seed_repo(tmp_path).query_summary()
    assert len(payload["models"]) == 12
    assert payload["models"][4]["latest_date"] is not None
    assert payload["rankings"]["1d"]


def test_curves_rebases_selected_window_and_keeps_ratio_formula(tmp_path):
    payload = seed_repo(tmp_path).query_curves("growth_raw", range_key="20d")
    assert payload["series"]["high"][0]["value"] == pytest.approx(100.0)
    assert payload["series"]["low"][0]["value"] == pytest.approx(100.0)
    for high, low, relative in zip(payload["series"]["high"], payload["series"]["low"], payload["series"]["relative"]):
        assert relative["value"] == pytest.approx(high["value"] / low["value"] * 100)


def test_curves_accept_custom_date_window(tmp_path):
    payload = seed_repo(tmp_path).query_curves("growth_raw", range_key="custom", start_date="2026-01-05", end_date="2026-01-10")
    assert payload["range"] == "custom"
    assert payload["series"]["high"][0]["time"] == "2026-01-05"
    assert payload["series"]["high"][-1]["time"] == "2026-01-10"
    assert payload["series"]["high"][0]["value"] == pytest.approx(100.0)


def test_positions_and_trades_validate_model_leg_date_and_limit(tmp_path):
    repo = seed_repo(tmp_path)
    assert repo.query_positions("growth_raw", "high", None)["items"]
    assert repo.query_trades("growth_raw", "high", limit=1)["items"] == []
    with pytest.raises(StyleMonitorValidationError):
        repo.query_curves("missing", "60d")


def test_theoretical_queries_never_fall_back_to_legacy_cash_ledger(tmp_path):
    repo = StyleMonitorRepository(tmp_path / "monitor.duckdb")
    repo.initialize_schema()
    model = MODEL_DEFINITIONS[4]
    version = repo.ensure_model_version(model, build_config_hash(model))
    legacy_leg = {
        side: LegDayPayload(0.0, 10_000_000.0, 10_000_000.0, 100.0, None, 0.0, 1.0, 3_000.0, True, 1.0, 0, "ok", "", [], [])
        for side in ("high", "low")
    }
    repo.write_model_day(ModelDayPayload(version, model.model_id, build_config_hash(model), date(2026, 1, 2), date(2026, 1, 2), legacy_leg))

    summary = next(item for item in repo.query_summary()["models"] if item["model_id"] == model.model_id)
    assert summary["status"] == "empty"
    assert summary["high_nav"] is None
    assert repo.query_curves(model.model_id, "all")["series"] == {"high": [], "low": [], "relative": []}
    positions = repo.query_positions(model.model_id, "high", None)
    assert positions["items"] == []
    assert "理论等权指数" in positions["message"]
    assert repo.query_trades(model.model_id, "high", 1)["items"] == []


def test_positions_rejects_invalid_iso_date_as_validation_error(tmp_path):
    repo = seed_repo(tmp_path)

    with pytest.raises(StyleMonitorValidationError, match="日期格式"):
        repo.query_positions("growth_raw", "high", "not-a-date")


def test_curves_include_same_range_local_index_benchmark(tmp_path, monkeypatch):
    benchmark_root = tmp_path / "index_data_daily"
    month_dir = benchmark_root / "year=2026" / "month=01"
    month_dir.mkdir(parents=True)
    days = pd.date_range("2026-01-01", periods=25, freq="D")
    pd.DataFrame(
        {
            "htsc_code": ["000001.SH"] * len(days),
            "time": days,
            "close": [100.0 + index for index in range(len(days))],
        }
    ).to_parquet(month_dir / "merged.parquet", index=False)
    monkeypatch.setattr(query_module, "BENCHMARK_BASE_DIR", benchmark_root)

    payload = seed_repo(tmp_path).query_curves("growth_raw", range_key="20d")

    assert payload["benchmark"]["name"] == "上证指数"
    assert payload["benchmark"]["series"][0]["time"] == "2026-01-06"
    assert payload["benchmark"]["series"][0]["value"] == pytest.approx(100.0)


def test_curves_accept_custom_index_benchmark_code(tmp_path, monkeypatch):
    benchmark_root = tmp_path / "index_data_daily"
    month_dir = benchmark_root / "year=2026" / "month=01"
    month_dir.mkdir(parents=True)
    days = pd.date_range("2026-01-01", periods=25, freq="D")
    pd.DataFrame(
        {
            "htsc_code": ["399001.SZ"] * len(days),
            "time": days,
            "close": [200.0 + index * 2 for index in range(len(days))],
        }
    ).to_parquet(month_dir / "merged.parquet", index=False)
    monkeypatch.setattr(query_module, "BENCHMARK_BASE_DIR", benchmark_root)

    payload = seed_repo(tmp_path).query_curves("growth_raw", range_key="20d", benchmark_code="399001.SZ")

    assert payload["benchmark"]["name"] == "深证成指"
    assert payload["benchmark"]["code"] == "399001.SZ"
    assert payload["benchmark"]["series"][0]["value"] == pytest.approx(100.0)


def test_curves_accept_custom_stock_benchmark_and_normalize_from_first_close(tmp_path, monkeypatch):
    monkeypatch.setattr(
        query_module,
        "_load_custom_benchmark_bars",
        lambda code, start_date, end_date: [
            {"time": date(2026, 1, 6), "close": 50.0},
            {"time": date(2026, 1, 7), "close": 55.0},
        ],
    )

    payload = seed_repo(tmp_path).query_curves("growth_raw", range_key="20d", benchmark_code="600000.SH")

    assert payload["benchmark"]["code"] == "600000.SH"
    assert payload["benchmark"]["name"] == "600000.SH"
    assert payload["benchmark"]["series"] == [
        {"time": "2026-01-06", "value": pytest.approx(100.0)},
        {"time": "2026-01-07", "value": pytest.approx(110.0)},
    ]


def test_custom_benchmark_code_must_be_complete_market_code(tmp_path):
    with pytest.raises(StyleMonitorValidationError, match="基准代码"):
        seed_repo(tmp_path).query_curves("growth_raw", range_key="20d", benchmark_code="600000")


def test_invalid_custom_benchmark_is_rejected_even_when_curve_range_is_empty(tmp_path):
    with pytest.raises(StyleMonitorValidationError, match="基准代码"):
        seed_repo(tmp_path).query_curves(
            "growth_raw",
            range_key="custom",
            start_date="2050-01-01",
            end_date="2050-01-31",
            benchmark_code="600000",
        )


def test_custom_benchmark_loader_chunks_ranges_longer_than_market_bar_limit(monkeypatch):
    calls = []

    def fake_query(code, start_date, end_date):
        calls.append((code, start_date, end_date))
        return [{"time": start_date, "close": 10.0}]

    monkeypatch.setattr(query_module, "_query_market_bars_for_benchmark", fake_query)

    rows = query_module._load_custom_benchmark_bars("600000.SH", date(2010, 1, 1), date(2026, 1, 1))

    assert len(calls) > 1
    assert rows[0]["time"] == date(2010, 1, 1)
