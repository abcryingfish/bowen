import pytest
from http import HTTPStatus

import api_server
from market_data_service import (
    MarketDataValidationError,
    list_sector_constituents,
    list_stock_sector_memberships,
    normalize_a_share_code,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("600000", "600000.SH"),
        ("000001", "000001.SZ"),
        ("300750", "300750.SZ"),
        ("688981", "688981.SH"),
        ("830799", "830799.BJ"),
        ("600000.sh", "600000.SH"),
    ],
)
def test_normalize_a_share_code(raw, expected):
    assert normalize_a_share_code(raw) == expected


def test_normalize_a_share_code_rejects_invalid_value():
    with pytest.raises(MarketDataValidationError, match="6 位数字"):
        normalize_a_share_code("浦发银行")


def test_memberships_use_latest_eligible_snapshot():
    payload = list_stock_sector_memberships("600000")
    codes = {item["code"] for item in payload["items"]}

    assert payload["stock_code"] == "600000.SH"
    assert payload["meta"]["snapshot_date"]
    assert {"881155.THS", "882027.THS", "886072.THS"}.issubset(codes)


def test_sector_constituents_use_latest_eligible_snapshot():
    payload = list_sector_constituents("881101.THS")
    codes = {item["code"] for item in payload["items"]}

    assert payload["sector_code"] == "881101.THS"
    assert payload["sector_name"]
    assert payload["meta"]["count"] == len(payload["items"])
    assert "000592.SZ" in codes
    sample = next(item for item in payload["items"] if item["code"] == "000592.SZ")
    assert sample["name"]
    assert 2 <= len(sample["closes_20d"]) <= 20
    assert all(isinstance(value, float) for value in sample["closes_20d"])


class _DummyHandler:
    def __init__(self):
        self.sent = None

    def _first_query_value(self, query, key):
        return query.get(key, [None])[0]

    def _send_json(self, status, payload):
        self.sent = (status, payload)


def test_sector_membership_handler_forwards_stock_code(monkeypatch):
    calls = {}

    def fake_list(stock_code, force_refresh=False):
        calls.update({"stock_code": stock_code, "force_refresh": force_refresh})
        return {"stock_code": "000001.SZ", "items": []}

    monkeypatch.setattr(api_server, "list_stock_sector_memberships", fake_list)
    handler = _DummyHandler()
    api_server.ApiRequestHandler._handle_sector_memberships(
        handler,
        {"stock_code": ["000001"], "refresh": ["1"]},
    )

    assert handler.sent[0] == HTTPStatus.OK
    assert handler.sent[1]["stock_code"] == "000001.SZ"
    assert calls == {"stock_code": "000001", "force_refresh": True}


def test_sector_constituents_handler_forwards_sector_code(monkeypatch):
    calls = {}

    def fake_list(sector_code):
        calls["sector_code"] = sector_code
        return {"sector_code": sector_code, "items": []}

    monkeypatch.setattr(api_server, "list_sector_constituents", fake_list)
    handler = _DummyHandler()
    api_server.ApiRequestHandler._handle_sector_constituents(
        handler,
        {"sector_code": ["881101.THS"]},
    )

    assert handler.sent[0] == HTTPStatus.OK
    assert calls == {"sector_code": "881101.THS"}
