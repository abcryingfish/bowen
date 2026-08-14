import json
from pathlib import Path

import api_server
import style_monitor_service


class DummyHandler:
    def __init__(self):
        self.sent = None

    def _send_json(self, status, payload):
        self.sent = (status.value, payload)

    def _first_query_value(self, query, key):
        return query.get(key, [None])[0]


def test_summary_handler_returns_utf8_payload(monkeypatch):
    handler = DummyHandler()
    monkeypatch.setattr(api_server, "query_style_monitor_summary", lambda: {"models": [{"title": "成长原始版"}]})
    api_server.ApiRequestHandler._handle_style_monitor_summary(handler)
    assert handler.sent[0] == 200
    assert handler.sent[1]["models"][0]["title"] == "成长原始版"
    assert json.dumps(handler.sent[1], ensure_ascii=False).encode("utf-8")


def test_positions_handler_rejects_invalid_leg(monkeypatch):
    handler = DummyHandler()
    monkeypatch.setattr(api_server, "query_style_monitor_positions", lambda model_id, leg, trade_date: (_ for _ in ()).throw(ValueError("leg 必须是 high 或 low")))
    api_server.ApiRequestHandler._handle_style_monitor_positions(handler, {"model_id": ["growth_raw"], "leg": ["short"]})
    assert handler.sent[0] == 400
    assert handler.sent[1]["error"]["code"] == "INVALID_ARGUMENT"


def test_style_monitor_schema_is_initialized_without_running_models(monkeypatch):
    calls = []

    class FakeRepository:
        def initialize_schema(self):
            calls.append("initialize_schema")

    monkeypatch.setattr(style_monitor_service, "_repo", lambda: FakeRepository())

    style_monitor_service.initialize_style_monitor_schema()

    assert calls == ["initialize_schema"]


def test_api_exposes_style_monitor_as_read_only() -> None:
    source = Path(api_server.__file__).read_text(encoding="utf-8")

    assert "/api/style-monitor/update" not in source
    assert "create_style_monitor_job" not in source


def test_curves_handler_forwards_custom_benchmark_code(monkeypatch):
    handler = DummyHandler()
    calls = {}

    def fake_query(model_id, range_key, start_date, end_date, benchmark_code=None):
        calls.update(locals())
        return {"benchmark": {"code": benchmark_code}}

    monkeypatch.setattr(api_server, "query_style_monitor_curves", fake_query)
    api_server.ApiRequestHandler._handle_style_monitor_curves(
        handler,
        {
            "model_id": ["growth_raw"],
            "range": ["custom"],
            "start_date": ["2026-01-01"],
            "end_date": ["2026-01-10"],
            "benchmark_code": ["600000.SH"],
        },
    )

    assert handler.sent[0] == 200
    assert calls["benchmark_code"] == "600000.SH"
