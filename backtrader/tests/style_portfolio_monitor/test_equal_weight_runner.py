from datetime import date
import warnings

import pandas as pd

from models.style_portfolio_monitor import equal_weight_runner


class _FakeSource:
    market_root = "unused"

    def __init__(self, dates, codes):
        self._dates = list(dates)
        self._codes = list(codes)
        self.requested_factor_keys = []

    def available_market_dates(self, start, end):
        return [day.date() for day in self._dates if start <= day.date() <= end]

    def build_eligible_snapshot(self, trade_date, factor_name):
        self.requested_factor_keys.append(factor_name)
        frame = pd.DataFrame(
            {"htsc_code": self._codes, "score": range(len(self._codes))}
        )
        frame.attrs["factor_coverage"] = 1.0
        return frame


def test_build_model_inputs_does_not_fragment_score_frame(monkeypatch):
    dates = pd.bdate_range("2026-01-01", periods=105)
    codes = [f"{number:06d}.SZ" for number in range(1, 106)]
    source = _FakeSource(dates, codes)
    prices = pd.DataFrame(1.0, index=dates, columns=codes)
    monkeypatch.setattr(equal_weight_runner, "load_adjusted_open_close", lambda **kwargs: (prices, prices))

    with warnings.catch_warnings():
        warnings.simplefilter("error", pd.errors.PerformanceWarning)
        score, _, _, _, _, _ = equal_weight_runner._build_model_inputs(
            definition=type("Definition", (), {"model_id": "test", "factor_name": "展示因子", "factor_key": "stored_factor", "rebalance_frequency": "weekly"})(),
            source=source,
            start=date(2026, 1, 1),
            end=dates[-1].date(),
        )

    assert score.shape == (len(dates), len(codes))
    assert set(source.requested_factor_keys) == {"stored_factor"}


def test_run_skips_model_already_at_target_date(monkeypatch, tmp_path):
    class Source:
        def __init__(self, **kwargs):
            pass

        def latest_common_date(self, factor_key):
            return date(2026, 8, 17)

        def first_usable_date(self, *args, **kwargs):
            raise AssertionError("已完成模型不应重新扫描起始日")

    class Repo:
        def __init__(self, path):
            pass

        def initialize_schema(self):
            pass

        def clear_legacy_cash_ledger(self):
            pass

        def ensure_model_version(self, definition, config_hash):
            return definition.model_id + "-v1"

        def index_date_bounds(self, version):
            return date(2016, 1, 4), date(2026, 8, 17)

    monkeypatch.setattr(equal_weight_runner, "StyleDataSource", Source)
    monkeypatch.setattr(equal_weight_runner, "StyleMonitorRepository", Repo)

    result = equal_weight_runner.run_equal_weight_update(
        model_ids=["large_cap_raw"],
        through_date=date(2026, 8, 17),
        database_path=tmp_path / "monitor.duckdb",
    )

    assert result["completed_models"] == ["large_cap_raw"]
    assert result["skipped_models"] == ["large_cap_raw"]
    assert result["processed_days"]["large_cap_raw"] == 0


def test_run_rebuilds_when_requested_date_is_before_existing_ledger(monkeypatch, tmp_path):
    class Source:
        def __init__(self, **kwargs):
            pass

        def latest_common_date(self, factor_key):
            return date(2026, 8, 25)

        def first_usable_date(self, *args, **kwargs):
            return date(2026, 1, 2)

        def available_market_dates(self, start, end):
            return [date(2026, 1, 2), date(2026, 1, 5)]

    class Repo:
        def __init__(self, path):
            self.cleared = False

        def initialize_schema(self):
            pass

        def clear_legacy_cash_ledger(self):
            pass

        def ensure_model_version(self, definition, config_hash):
            return definition.model_id + "-v1"

        def index_date_bounds(self, version):
            return date(2026, 1, 2), date(2026, 8, 25)

        def get_run_state(self, version):
            return type("State", (), {"last_rebalance_date": date(2026, 8, 24)})()

    monkeypatch.setattr(equal_weight_runner, "StyleDataSource", Source)
    monkeypatch.setattr(equal_weight_runner, "StyleMonitorRepository", Repo)
    monkeypatch.setattr(equal_weight_runner, "_build_model_inputs", lambda **kwargs: (_ for _ in ()).throw(AssertionError("test fixture should reach reset input path")))

    result = equal_weight_runner.run_equal_weight_update(
        model_ids=["large_cap_raw"],
        through_date=date(2026, 8, 20),
        database_path=tmp_path / "monitor.duckdb",
    )

    assert result["failed_models"]
    assert "test fixture should reach reset input path" in result["failed_models"][0]["message"]


def test_build_model_inputs_reuses_adjusted_prices_for_same_date_range(monkeypatch):
    dates = pd.bdate_range("2026-01-01", periods=5)
    codes = ["000001.SZ"]
    source = _FakeSource(dates, codes)
    prices = pd.DataFrame(1.0, index=dates, columns=codes)
    calls = []

    def fake_load(**kwargs):
        calls.append(kwargs)
        return prices, prices

    monkeypatch.setattr(equal_weight_runner, "load_adjusted_open_close", fake_load)
    definition = type(
        "Definition",
        (),
        {
            "model_id": "test",
            "factor_name": "展示因子",
            "factor_key": "stored_factor",
            "rebalance_frequency": "weekly",
        },
    )()
    cache = {}

    for _ in range(2):
        equal_weight_runner._build_model_inputs(
            definition=definition,
            source=source,
            start=dates[0].date(),
            end=dates[-1].date(),
            adjusted_price_cache=cache,
        )

    assert len(calls) == 1
