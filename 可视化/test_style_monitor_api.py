import json

import api_server


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


def test_update_handler_returns_202_and_job_status_is_looked_up(monkeypatch):
    handler = DummyHandler()
    handler._read_json_body = lambda: {}
    monkeypatch.setattr(api_server, "create_style_monitor_job", lambda payload: {"job_id": "job-1", "status": "queued"})
    api_server.ApiRequestHandler._handle_style_monitor_update(handler)
    assert handler.sent[0] == 202
    monkeypatch.setattr(api_server, "get_style_monitor_job", lambda job_id: {"job_id": job_id, "status": "done"})
    api_server.ApiRequestHandler._handle_style_monitor_job_status(handler, "job-1")
    assert handler.sent[1]["status"] == "done"
