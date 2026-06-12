from __future__ import annotations

import contextlib
import io
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VIS_DIR = Path(__file__).resolve().parent
BACKTRADER_DIR = PROJECT_ROOT / "backtrader"
if str(VIS_DIR) not in sys.path:
    sys.path.insert(0, str(VIS_DIR))
if str(BACKTRADER_DIR) not in sys.path:
    sys.path.append(str(BACKTRADER_DIR))

from configurable_backtest import run_configured_backtest  # noqa: E402
from run_name_format import apply_frontend_run_name_format  # noqa: E402


MAX_BACKTEST_WORKERS = 1
LOG_TAIL_LIMIT = 200
_executor = ThreadPoolExecutor(max_workers=MAX_BACKTEST_WORKERS)
_jobs_lock = threading.Lock()
_jobs: dict[str, "BacktestJob"] = {}
# Optuna 寻优：job_id -> cancel Event（仅此类任务可中断）
_study_cancel_events: dict[str, threading.Event] = {}


@dataclass
class BacktestJob:
    job_id: str
    status: str = "queued"
    stage: str = "排队中"
    progress: int = 0
    message: str = ""
    run_tag: str = ""
    run_mode: str = "normal"
    result: dict[str, Any] | None = None
    error: str = ""
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))
    log_tail: list[str] = field(default_factory=list)

    def append_log(self, text: str) -> None:
        for line in str(text or "").splitlines():
            line = line.strip()
            if line:
                self.log_tail.append(line)
        if len(self.log_tail) > LOG_TAIL_LIMIT:
            self.log_tail = self.log_tail[-LOG_TAIL_LIMIT:]
        self.updated_at = int(time.time())

    def snapshot(self) -> dict[str, Any]:
        result = self.result or {}
        saved_paths = result.get("saved_paths", {}) if isinstance(result, dict) else {}
        return {
            "job_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "message": self.message,
            "run_tag": self.run_tag,
            "run_mode": self.run_mode,
            "summary_path": saved_paths.get("summary", ""),
            "saved_paths": saved_paths,
            "curve_info": result.get("curve_info", {}) if isinstance(result, dict) else {},
            "summary": result.get("summary", {}) if isinstance(result, dict) else {},
            "study": result.get("study") if isinstance(result, dict) else {},
            "error": self.error,
            "log_tail": list(self.log_tail[-80:]),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class _JobLogWriter(io.TextIOBase):
    def __init__(self, job: BacktestJob) -> None:
        self.job = job
        self._buffer = ""

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            with _jobs_lock:
                self.job.append_log(line)
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            with _jobs_lock:
                self.job.append_log(self._buffer)
            self._buffer = ""


def _set_job_state(job: BacktestJob, **updates: Any) -> None:
    with _jobs_lock:
        for key, value in updates.items():
            setattr(job, key, value)
        job.updated_at = int(time.time())


def _run_job(job: BacktestJob, payload: dict[str, Any]) -> None:
    def progress_callback(stage: str, progress: int, message: str) -> None:
        _set_job_state(
            job,
            status="running",
            stage=stage,
            progress=max(0, min(100, int(progress))),
            message=message,
        )
        with _jobs_lock:
            job.append_log(f"{stage}: {message}")

    writer = _JobLogWriter(job)
    _set_job_state(job, status="running", stage="启动中", progress=1, message="后台任务已启动")
    try:
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            result = run_configured_backtest(payload, progress_callback=progress_callback)
        writer.flush()
        run_tag = str(result.get("run_tag") or "")
        _set_job_state(
            job,
            status="done",
            stage="完成",
            progress=100,
            message="回测完成",
            run_tag=run_tag,
            result=result,
        )
        with _jobs_lock:
            job.append_log(f"完成: run_tag={run_tag}")
    except Exception as exc:  # noqa: BLE001
        writer.flush()
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        _set_job_state(
            job,
            status="failed",
            stage="失败",
            progress=100,
            message=detail,
            error=detail,
        )
        with _jobs_lock:
            job.append_log("失败:")
            job.append_log(traceback.format_exc())


def _run_optuna_job(job: BacktestJob, payload: dict[str, Any], cancel_event: threading.Event) -> None:
    adopt = str(payload.get("adopt_model") or "").strip()

    def progress_callback(stage: str, progress: int, message: str) -> None:
        _set_job_state(
            job,
            status="running",
            stage=stage,
            progress=max(0, min(100, int(progress))),
            message=message,
        )
        with _jobs_lock:
            job.append_log(f"{stage}: {message}")

    def log_append(text: str) -> None:
        with _jobs_lock:
            job.append_log(text)

    writer = _JobLogWriter(job)
    _set_job_state(job, status="running", stage="Optuna", progress=1, message="参数寻优已启动")
    try:
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            if adopt == "zxw_strong_adjusted_only":
                from optuna_strong_adjusted_study import run_optuna_strong_adjusted_study

                result = run_optuna_strong_adjusted_study(
                    payload,
                    job_id=job.job_id,
                    cancel_event=cancel_event,
                    progress_callback=progress_callback,
                    log_append=log_append,
                )
            else:
                from optuna_signal_study import run_optuna_signal_study

                result = run_optuna_signal_study(
                    payload,
                    job_id=job.job_id,
                    cancel_event=cancel_event,
                    progress_callback=progress_callback,
                    log_append=log_append,
                )
        writer.flush()
        run_tag = str(result.get("run_tag") or "")
        study_meta = result.get("study") if isinstance(result.get("study"), dict) else {}
        cancelled = bool(study_meta.get("cancelled"))
        _set_job_state(
            job,
            status="cancelled" if cancelled else "done",
            stage="已终止" if cancelled else "完成",
            progress=100,
            message="寻优已终止，已完成部分已保存" if cancelled else "参数寻优完成",
            run_tag=run_tag,
            result=result,
        )
        with _jobs_lock:
            job.append_log(f"结束: run_tag={run_tag}, cancelled={cancelled}")
    except Exception as exc:  # noqa: BLE001
        writer.flush()
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        _set_job_state(
            job,
            status="failed",
            stage="失败",
            progress=100,
            message=detail,
            error=detail,
        )
        with _jobs_lock:
            job.append_log("失败:")
            job.append_log(traceback.format_exc())
    finally:
        with _jobs_lock:
            _study_cancel_events.pop(job.job_id, None)


def _prepare_optuna_payload(payload: dict[str, Any], adopt_model: str) -> dict[str, Any]:
    """Optuna 自行拼 run_name 日期前缀；保留用户输入的未加前缀名称。"""
    out = dict(payload)
    raw = str(out.get("run_name_base") or out.get("run_name") or "").strip()
    if not raw:
        raw = "ZXW强点" if adopt_model == "zxw_strong_adjusted_only" else "可配置"
    out["run_name_user_base"] = raw
    out.pop("run_name_base", None)
    out.pop("apply_run_name_date_prefix", None)
    return out


def create_backtest_job(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("请求体必须是 JSON 对象")
    run_mode = str(payload.get("run_mode") or "normal").strip().lower()
    adopt = str(payload.get("adopt_model") or "").strip()
    if run_mode == "optuna":
        if adopt not in ("configurable_signal_rules", "zxw_strong_adjusted_only"):
            raise ValueError(
                "run_mode=optuna 仅支持 adopt_model=configurable_signal_rules 或 zxw_strong_adjusted_only"
            )
        if adopt in (
            "zxw_factor_check_only",
            "zxw_factor_check_no_lookahead",
            "zxw_factor_check_dual_assumption",
        ):
            raise ValueError(f"因子检验模型 {adopt} 不支持 run_mode=optuna")
        payload = _prepare_optuna_payload(payload, adopt)
    else:
        payload = apply_frontend_run_name_format(payload)

    job = BacktestJob(job_id=uuid.uuid4().hex[:12], run_mode=run_mode)
    with _jobs_lock:
        _jobs[job.job_id] = job
        job.append_log("任务已创建，等待执行")
    if run_mode == "optuna":
        ev = threading.Event()
        with _jobs_lock:
            _study_cancel_events[job.job_id] = ev
        _executor.submit(_run_optuna_job, job, payload, ev)
    else:
        _executor.submit(_run_job, job, payload)
    return job.snapshot()


def cancel_backtest_job(job_id: Any) -> dict[str, Any]:
    parsed_id = str(job_id or "").strip()
    if not parsed_id:
        raise ValueError("job id 不能为空")
    ev = _study_cancel_events.get(parsed_id)
    if ev is not None:
        ev.set()
        return {"ok": True, "job_id": parsed_id, "message": "已请求终止寻优（当前 trial 结束后不再启动新 trial）"}
    with _jobs_lock:
        if parsed_id not in _jobs:
            raise KeyError(parsed_id)
    return {"ok": False, "job_id": parsed_id, "message": "该任务不支持终止（仅运行中的 Optuna 寻优可终止）"}


def get_backtest_job(job_id: Any) -> dict[str, Any]:
    parsed_id = str(job_id or "").strip()
    if not parsed_id:
        raise ValueError("job id 不能为空")
    with _jobs_lock:
        job = _jobs.get(parsed_id)
        if job is None:
            raise KeyError(parsed_id)
        return job.snapshot()
