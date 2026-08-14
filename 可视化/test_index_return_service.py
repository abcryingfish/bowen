# -*- coding: utf-8 -*-

from http import HTTPStatus
import time

import pytest

import api_server
from market_data_service import (
    MarketDataValidationError,
    query_index_market_bars,
    query_index_market_returns,
)


def test_batch_returns_match_single_sector_bars():
    to_ts = int(time.time())
    from_ts = to_ts - 110 * 86400
    payload = query_index_market_returns("881", from_ts, to_ts, points=60, codes="881101.THS")
    bars_payload = query_index_market_bars("881101.THS", from_ts, to_ts, limit=400)
    bars = [bar for bar in bars_payload["bars"] if float(bar["close"]) > 0][-60:]

    assert payload["meta"]["count"] == 1
    assert payload["items"][0]["point_count"] == len(bars)
    expected = (float(bars[-1]["close"]) / float(bars[0]["close"]) - 1) * 100
    assert payload["items"][0]["return_pct"] == pytest.approx(expected)


@pytest.mark.parametrize("prefix", ["", "880", "8811"])
def test_batch_returns_reject_invalid_prefix(prefix):
    with pytest.raises(MarketDataValidationError, match="prefix"):
        query_index_market_returns(prefix, 1, 2, points=20)


class _DummyHandler:
    def __init__(self):
        self.sent = None

    def _first_query_value(self, query, key):
        return query.get(key, [None])[0]

    def _send_json(self, status, payload):
        self.sent = (status, payload)


def test_index_returns_handler_forwards_query(monkeypatch):
    calls = {}

    def fake_query(prefix, from_ts, to_ts, points=None, codes=None):
        calls.update({"prefix": prefix, "from": from_ts, "to": to_ts, "points": points, "codes": codes})
        return {"items": [], "meta": {"count": 0}}

    monkeypatch.setattr(api_server, "query_index_market_returns", fake_query)
    handler = _DummyHandler()
    api_server.ApiRequestHandler._handle_market_index_returns(
        handler,
        {
            "prefix": ["885"],
            "from": ["100"],
            "to": ["200"],
            "points": ["60"],
            "codes": ["885001.THS,885002.THS"],
        },
    )

    assert handler.sent[0] == HTTPStatus.OK
    assert calls == {
        "prefix": "885",
        "from": "100",
        "to": "200",
        "points": "60",
        "codes": "885001.THS,885002.THS",
    }
