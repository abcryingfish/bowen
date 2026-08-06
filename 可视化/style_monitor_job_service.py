"""Single-worker asynchronous launcher for manual style monitor updates."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKTRADER_DIR = PROJECT_ROOT / "backtrader"
if str(BACKTRADER_DIR) not in sys.path:
    sys.path.append(str(BACKTRADER_DIR))

from models.style_portfolio_monitor.service import run_incremental_update

MAX_STYLE_MONITOR_WORKERS = 1
_executor = ThreadPoolExecutor(max_workers=MAX_STYLE_MONITOR_WORKERS)
_jobs_lock = threading.Lock()
_jobs: dict[str, "StyleMonitorJob"] = {}
_active_job_id: str | None = None


class StyleMonitorJobBusyError(RuntimeError):
    pass


@dataclass
class StyleMonitorJob:
    job_id: str
    status: str = "queued"
    stage: str = "排队中"
    progress: int = 0
    message: str = ""
    result: dict[str, Any] | None = None
    error: str = ""
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))
    log_tail: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "status": self.status, "stage": self.stage, "progress": self.progress, "message": self.message, "result": self.result or {}, "error": self.error, "created_at": self.created_at, "updated_at": self.updated_at, "log_tail": list(self.log_tail[-80:])}


def _set(job: StyleMonitorJob, **values: Any) -> None:
    with _jobs_lock:
        for key, value in values.items():
            setattr(job, key, value)
        job.updated_at = int(time.time())


def _run(job: StyleMonitorJob, payload: dict[str, Any]) -> None:
    global _active_job_id

    def progress(stage: str, percent: int, message: str) -> None:
        _set(job, status="running", stage=stage, progress=max(0, min(100, int(percent))), message=message)

    try:
        _set(job, status="running", stage="启动中", progress=1, message="风格组合更新已启动")
        options: dict[str, Any] = {"progress": progress}
        model_ids = payload.get("model_ids")
        if model_ids:
            options["model_ids"] = [str(item) for item in model_ids]
        if payload.get("through_date"):
            options["through_date"] = date.fromisoformat(str(payload["through_date"]))
        result = run_incremental_update(**options)
        _set(job, status="done", stage="完成", progress=100, message="更新完成", result=result)
    except Exception as exc:  # noqa: BLE001
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        _set(job, status="failed", stage="失败", progress=100, message=detail, error=detail)
    finally:
        with _jobs_lock:
            if _active_job_id == job.job_id:
                _active_job_id = None


def create_style_monitor_job(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    global _active_job_id
    body = payload or {}
    with _jobs_lock:
        if _active_job_id is not None:
            active = _jobs.get(_active_job_id)
            if active and active.status not in {"done", "failed"}:
                raise StyleMonitorJobBusyError("已有风格组合更新任务正在运行")
        job = StyleMonitorJob(uuid.uuid4().hex)
        _jobs[job.job_id] = job
        _active_job_id = job.job_id
    _executor.submit(_run, job, body)
    return job.snapshot()


def get_style_monitor_job(job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(str(job_id or ""))
        if job is None:
            raise KeyError(job_id)
        return job.snapshot()
