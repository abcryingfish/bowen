import threading
import time

import pytest

import style_monitor_job_service as service


def wait_for_terminal(job_id):
    for _ in range(100):
        snapshot = service.get_style_monitor_job(job_id)
        if snapshot["status"] in {"done", "failed"}:
            return snapshot
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_create_job_runs_update_and_reports_progress(monkeypatch):
    monkeypatch.setattr(service, "run_incremental_update", lambda **kwargs: {"completed_models": ["growth_raw"]})
    final = wait_for_terminal(service.create_style_monitor_job({})["job_id"])
    assert final["status"] == "done"
    assert final["progress"] == 100
    assert final["result"]["completed_models"]


def test_second_job_is_rejected_while_first_is_running(monkeypatch):
    release = threading.Event()

    def blocking(**kwargs):
        release.wait(2)
        return {}

    monkeypatch.setattr(service, "run_incremental_update", blocking)
    first = service.create_style_monitor_job({})
    with pytest.raises(service.StyleMonitorJobBusyError, match="已有风格组合更新任务"):
        service.create_style_monitor_job({})
    release.set()
    wait_for_terminal(first["job_id"])


def test_failed_update_exposes_short_error_without_trace_log_spam(monkeypatch):
    monkeypatch.setattr(service, "run_incremental_update", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("测试失败")))
    final = wait_for_terminal(service.create_style_monitor_job({})["job_id"])
    assert final["status"] == "failed"
    assert final["error"] == "RuntimeError: 测试失败"
    assert len(final["log_tail"]) <= 80
