# -*- coding: utf-8 -*-

from datetime import datetime
from http import HTTPStatus

import pandas as pd
import pytest

import api_server
import market_research_service as service
from market_data_service import MarketDataValidationError


def _timestamp(value: pd.Timestamp) -> int:
    return int(value.to_pydatetime().timestamp())


@pytest.fixture
def synthetic_market_data(tmp_path, monkeypatch):
    dates = pd.bdate_range("2026-01-02", periods=20)
    rows = []
    for index, day in enumerate(dates):
        rows.append({"htsc_code": "600000.SH", "time": day, "close": 10.0 + index, "value": 200.0})
        rows.append({"htsc_code": "000001.SZ", "time": day, "close": 30.0 - index, "value": 100.0})
    rows.append({"htsc_code": "688001.SH", "time": dates[-1], "close": 20.0, "value": 1000.0})

    daily_base = tmp_path / "daily"
    month_dir = daily_base / "year=2026" / "month=01"
    month_dir.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(month_dir / "merged.parquet", index=False)

    monkeypatch.setattr(service, "DAILY_BASE_PATH", daily_base)
    monkeypatch.setattr(service, "ADJ_SEGMENT_PATH", tmp_path / "segments.parquet")
    service.clear_market_research_cache()
    yield dates
    service.clear_market_research_cache()


def test_concentration_uses_dynamic_daily_pool_and_keeps_rsi_separate(synthetic_market_data):
    dates = synthetic_market_data
    payload = service.query_market_research_concentration(
        _timestamp(dates[0]),
        _timestamp(dates[-1] + pd.Timedelta(hours=23)),
        points=30,
    )
    all_a = payload["markets"]["all-a"]["points"]

    previous = all_a[-2]
    latest = all_a[-1]
    assert previous["stock_count"] == 2
    assert previous["concentration"] == pytest.approx(200.0 / 300.0 * 100.0)
    assert previous["rsi_ratio"] == pytest.approx(2.0)

    assert latest["stock_count"] == 3
    assert latest["top_count"] == 1
    assert latest["concentration"] == pytest.approx(1000.0 / 1300.0 * 100.0)
    assert latest["rsi_count"] == 2
    assert latest["top_rsi_count"] == 0
    assert latest["rsi_ratio"] is None


def test_star_market_is_independent_subset(synthetic_market_data):
    dates = synthetic_market_data
    payload = service.query_market_research_concentration(
        _timestamp(dates[0]),
        _timestamp(dates[-1] + pd.Timedelta(hours=23)),
        points=30,
    )
    star = payload["markets"]["star"]["points"]
    assert len(star) == 1
    assert star[0]["stock_count"] == 1
    assert star[0]["concentration"] == 100.0


def test_segment_adjustment_uses_cumulative_backward_factor(tmp_path, monkeypatch):
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    daily_base = tmp_path / "daily"
    month_dir = daily_base / "year=2026" / "month=01"
    month_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "htsc_code": ["600000.SH"] * 3,
            "time": dates,
            "close": [10.0, 5.0, 10.0 / 3.0],
            "value": [100.0] * 3,
        }
    ).to_parquet(month_dir / "merged.parquet", index=False)
    segment_path = tmp_path / "segments.parquet"
    pd.DataFrame(
        {
            "htsc_code": ["600000.SH", "600000.SH"],
            "begin_date": dates[1:],
            "end_date": dates[1:],
            "xdy": [2.0, 1.5],
        }
    ).to_parquet(segment_path, index=False)
    monkeypatch.setattr(service, "DAILY_BASE_PATH", daily_base)
    monkeypatch.setattr(service, "ADJ_SEGMENT_PATH", segment_path)

    frame, _ = service._load_market_frame(dates[0].date(), dates[-1].date())
    assert frame["adjusted_close"].tolist() == pytest.approx([10.0, 10.0, 10.0])


@pytest.mark.parametrize("points", [0, 2001, "bad"])
def test_rejects_invalid_points(points, synthetic_market_data):
    with pytest.raises(MarketDataValidationError, match="points"):
        service.query_market_research_concentration(points=points)


class _DummyHandler:
    def __init__(self):
        self.sent = None

    def _first_query_value(self, query, key):
        return query.get(key, [None])[0]

    def _send_json(self, status, payload):
        self.sent = (status, payload)


def test_api_handler_forwards_market_research_query(monkeypatch):
    calls = {}

    def fake_query(from_ts, to_ts, points, refresh=False):
        calls.update({"from": from_ts, "to": to_ts, "points": points, "refresh": refresh})
        return {"markets": {}, "meta": {}}

    monkeypatch.setattr(api_server, "query_market_research_concentration", fake_query)
    handler = _DummyHandler()
    api_server.ApiRequestHandler._handle_market_research_concentration(
        handler,
        {"from": ["100"], "to": ["200"], "points": ["60"], "refresh": ["1"]},
    )

    assert handler.sent[0] == HTTPStatus.OK
    assert calls == {"from": "100", "to": "200", "points": "60", "refresh": True}
