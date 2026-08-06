from datetime import date

import pytest

from models.style_portfolio_monitor.config import MODEL_DEFINITIONS
from models.style_portfolio_monitor.repository import StyleMonitorRepository
from models.style_portfolio_monitor.service import StyleMonitorPaused, run_incremental_update


class FakeSource:
    def __init__(self, market_dates=None, factor_first_usable_date=None, factor_coverage=1.0, close_prices=None):
        self.market_dates = market_dates or [date(2026, 1, 29), date(2026, 1, 30)]
        self.factor_first_usable_date = factor_first_usable_date or self.market_dates[0]
        self.factor_coverage = factor_coverage
        self.close_prices_map = close_prices or {"600000.SH": 10.0}
        self.requested_dates = {}
        self.snapshot_calls = 0

    def available_market_dates(self, start, end=None):
        return [item for item in self.market_dates if item >= start and (end is None or item <= end)]

    def latest_common_date(self, factor_name):
        return self.market_dates[-1]

    def first_usable_date(self, factor_name, start, minimum_coverage):
        return self.factor_first_usable_date

    def build_eligible_snapshot(self, trade_date, factor_name):
        import pandas as pd
        self.snapshot_calls += 1
        self.requested_dates.setdefault(factor_name, []).append(trade_date)
        frame = pd.DataFrame([{"htsc_code": "600000.SH", "score": 90.0, "close": 10.0, "average_turnover_20d": 30_000_000.0, "history_days": 200}])
        frame.attrs.update(tradable_count=1, factor_valid_count=1 if self.factor_coverage >= 1 else 0, factor_coverage=self.factor_coverage)
        return frame

    def close_prices(self, trade_date, codes):
        return {code: self.close_prices_map[code] for code in codes if code in self.close_prices_map}


def ready_repository(tmp_path, last_success_date=None):
    repo = StyleMonitorRepository(tmp_path / "monitor.duckdb")
    repo.initialize_schema()
    if last_success_date is not None:
        from models.style_portfolio_monitor.config import build_config_hash
        version = repo.ensure_model_version(MODEL_DEFINITIONS[4], build_config_hash(MODEL_DEFINITIONS[4]))
        conn = repo._connect()
        conn.execute("UPDATE run_state SET last_success_date=?, last_rebalance_date=? WHERE model_version=?", [last_success_date, last_success_date, version])
        conn.close()
    return repo


def test_first_run_starts_at_2015_or_factor_first_usable_date(tmp_path):
    source = FakeSource(market_dates=[date(2015, 1, 5), date(2015, 1, 6)], factor_first_usable_date=date(2015, 1, 6))
    result = run_incremental_update(model_ids=["growth_raw"], data_source=source, repository=ready_repository(tmp_path), through_date=date(2015, 1, 6))
    assert source.requested_dates["成长风格评分"][0] == date(2015, 1, 6)
    assert result["completed_models"] == ["growth_raw"]


def test_incremental_run_processes_every_missing_market_date_after_watermark(tmp_path):
    repo = ready_repository(tmp_path, last_success_date=date(2026, 1, 28))
    source = FakeSource()
    result = run_incremental_update(model_ids=["growth_raw"], data_source=source, repository=repo)
    assert result["processed_days"]["growth_raw"] == 2


def test_low_factor_coverage_pauses_on_rebalance_day_without_advancing_watermark(tmp_path):
    repo = ready_repository(tmp_path)
    source = FakeSource(factor_coverage=0.79)
    with pytest.raises(StyleMonitorPaused, match="79.00%"):
        run_incremental_update(model_ids=["growth_raw"], data_source=source, repository=repo, through_date=date(2026, 1, 30))
    assert repo.get_run_state("growth_raw-v1").last_success_date is None


def test_non_rebalance_day_values_existing_positions_without_reselecting(tmp_path):
    repo = ready_repository(tmp_path, last_success_date=date(2026, 1, 28))
    source = FakeSource(market_dates=[date(2026, 1, 29)])
    run_incremental_update(model_ids=["growth_raw"], data_source=source, repository=repo)
    assert source.snapshot_calls == 0


def test_repeated_update_produces_no_duplicate_nav_or_trades(tmp_path):
    repo = ready_repository(tmp_path)
    source = FakeSource()
    run_incremental_update(model_ids=["growth_raw"], data_source=source, repository=repo)
    counts = (repo.count_rows("nav_daily"), repo.count_rows("trade_log"))
    run_incremental_update(model_ids=["growth_raw"], data_source=source, repository=repo)
    assert (repo.count_rows("nav_daily"), repo.count_rows("trade_log")) == counts


def test_restart_restores_previous_cash_and_positions_before_incrementing(tmp_path):
    repo = ready_repository(tmp_path)
    source = FakeSource(market_dates=[date(2026, 1, 29)])
    run_incremental_update(model_ids=["growth_raw"], data_source=source, repository=repo)
    first_asset = repo._connect().execute("SELECT total_asset FROM nav_daily WHERE model_version='growth_raw-v1' AND leg='high' ORDER BY trade_date DESC LIMIT 1").fetchone()[0]
    source.market_dates = [date(2026, 1, 30)]
    run_incremental_update(model_ids=["growth_raw"], data_source=source, repository=repo)
    second_cash = repo._connect().execute("SELECT cash FROM nav_daily WHERE model_version='growth_raw-v1' AND leg='high' ORDER BY trade_date DESC LIMIT 1").fetchone()[0]
    assert second_cash <= first_asset
