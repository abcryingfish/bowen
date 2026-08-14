import threading
import time

import pytest

import style_monitor_job_service as service


@pytest.fixture(autouse=True)
def isolated_style_monitor_database(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "STYLE_MONITOR_DB_PATH", tmp_path / "monitor.duckdb")


def wait_for_terminal(job_id):
    for _ in range(100):
        snapshot = service.get_style_monitor_job(job_id)
        if snapshot["status"] in {"done", "failed"}:
            return snapshot
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_create_job_runs_update_and_reports_progress(monkeypatch):
    monkeypatch.setattr(service, "run_equal_weight_update", lambda **kwargs: {"completed_models": ["growth_raw"]})
    final = wait_for_terminal(service.create_style_monitor_job({})["job_id"])
    assert final["status"] == "done"
    assert final["progress"] == 100
    assert final["result"]["completed_models"]


def test_second_job_is_rejected_while_first_is_running(monkeypatch):
    release = threading.Event()

    def blocking(**kwargs):
        release.wait(2)
        return {}

    monkeypatch.setattr(service, "run_equal_weight_update", blocking)
    first = service.create_style_monitor_job({})
    with pytest.raises(service.StyleMonitorJobBusyError, match="已有风格组合更新任务"):
        service.create_style_monitor_job({})
    release.set()
    wait_for_terminal(first["job_id"])


def test_failed_update_exposes_short_error_without_trace_log_spam(monkeypatch):
    monkeypatch.setattr(service, "run_equal_weight_update", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("测试失败")))
    final = wait_for_terminal(service.create_style_monitor_job({})["job_id"])
    assert final["status"] == "failed"
    assert final["error"] == "RuntimeError: 测试失败"
    assert len(final["log_tail"]) <= 80


def test_job_lifecycle_is_persisted_without_writing_every_same_percent(tmp_path, monkeypatch):
    database_path = tmp_path / "monitor.duckdb"
    monkeypatch.setattr(service, "STYLE_MONITOR_DB_PATH", database_path)

    def update(progress, **kwargs):
        progress("增量更新", 10, "growth_raw 2026-01-29")
        progress("增量更新", 10, "growth_raw 2026-01-30")
        return {"completed_models": ["growth_raw"]}

    monkeypatch.setattr(service, "run_equal_weight_update", update)
    final = wait_for_terminal(service.create_style_monitor_job({"through_date": "2026-01-30"})["job_id"])

    from models.style_portfolio_monitor.repository import StyleMonitorRepository

    latest = StyleMonitorRepository(database_path).query_summary()["latest_update"]
    assert final["status"] == "done"
    assert latest["run_id"] == final["job_id"]
    assert latest["status"] == "done"
    assert latest["progress"] == 100


def test_partial_model_failure_is_reported_in_terminal_message(monkeypatch):
    monkeypatch.setattr(
        service,
        "run_equal_weight_update",
        lambda **kwargs: {"completed_models": [], "failed_models": [{"model_id": "growth_raw"}], "paused_models": []},
    )

    final = wait_for_terminal(service.create_style_monitor_job({})["job_id"])

    assert final["status"] == "done"
    assert final["message"] == "部分模型更新未完成（1）"


def test_terminal_status_is_not_visible_before_it_is_persisted(monkeypatch):
    terminal_started = threading.Event()
    release_terminal = threading.Event()
    original_update = service.StyleMonitorRepository.update_update_run

    def delayed_update(repo, run_id, **values):
        if values["status"] == "done":
            terminal_started.set()
            release_terminal.wait(2)
        return original_update(repo, run_id, **values)

    monkeypatch.setattr(service.StyleMonitorRepository, "update_update_run", delayed_update)
    monkeypatch.setattr(service, "run_equal_weight_update", lambda **kwargs: {"completed_models": []})
    job_id = service.create_style_monitor_job({})["job_id"]
    assert terminal_started.wait(2)
    try:
        assert service.get_style_monitor_job(job_id)["status"] == "running"
    finally:
        release_terminal.set()
    assert wait_for_terminal(job_id)["status"] == "done"


def test_terminal_persistence_is_retried_before_completion(monkeypatch):
    original_update = service.StyleMonitorRepository.update_update_run
    terminal_attempts = 0

    def fail_first_terminal_write(repo, run_id, **values):
        nonlocal terminal_attempts
        if values["status"] == "done":
            terminal_attempts += 1
            if terminal_attempts == 1:
                raise RuntimeError("temporary lock")
        return original_update(repo, run_id, **values)

    monkeypatch.setattr(service.StyleMonitorRepository, "update_update_run", fail_first_terminal_write)
    monkeypatch.setattr(service, "run_equal_weight_update", lambda **kwargs: {"completed_models": []})
    final = wait_for_terminal(service.create_style_monitor_job({})["job_id"])

    assert final["status"] == "done"
    assert terminal_attempts == 2
