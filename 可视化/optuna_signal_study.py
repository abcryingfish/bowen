"""网页 Optuna 任务：可配置因子买卖规则（阈值区间遍历）。"""

from __future__ import annotations

import math
import re
import sys
import threading
from pathlib import Path
from typing import Any, Callable

import optuna
from optuna.trial import TrialState

BACKTRADER_DIR = Path(__file__).resolve().parents[1] / "backtrader"
if str(BACKTRADER_DIR) not in sys.path:
    sys.path.append(str(BACKTRADER_DIR))

from models.configurable_signal_rules.runner import run as run_configurable

ProgressCallback = Callable[[str, int, str], None]
LogAppend = Callable[[str], None]

_TRIAL_SAFE = re.compile(r"[^0-9A-Za-z_\u4e00-\u9fff]+")


def _suggest_threshold(trial: optuna.Trial, prefix: str, rule: dict[str, Any]) -> float:
    factor = str(rule.get("factor") or "").strip()
    key = _TRIAL_SAFE.sub("_", f"{prefix}_{factor}") or f"{prefix}_th"
    lo = float(rule["threshold_lo"])
    hi = float(rule["threshold_hi"])
    step = float(rule["threshold_step"])
    if step <= 0 or hi <= lo:
        return float(rule.get("threshold", 1))
    n_steps = max(1, int(math.floor((hi - lo) / step + 1e-9)))
    idx = trial.suggest_int(key, 0, n_steps)
    return round(lo + idx * step, 10)


def _build_rules(trial: optuna.Trial, template: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rule in template:
        out.append(
            {
                "factor": rule["factor"],
                "threshold": _suggest_threshold(trial, prefix, rule),
            }
        )
    return out


def _objective_value(summary: dict[str, Any], objective_key: str, direction: str) -> float:
    raw = summary.get(objective_key)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float("-inf") if direction == "maximize" else float("inf")
    if value != value:
        return float("-inf") if direction == "maximize" else float("inf")
    return value


def run_optuna_signal_study(
    payload: dict[str, Any],
    *,
    job_id: str = "",
    cancel_event: threading.Event | None = None,
    progress_callback: ProgressCallback | None = None,
    log_append: LogAppend | None = None,
) -> dict[str, Any]:
    buy_template = list(payload.get("buy_rules") or [])
    sell_template = list(payload.get("sell_rules") or [])
    if not buy_template or not sell_template:
        raise ValueError("可配置模型参数遍历需要买入与卖出因子模板")

    n_trials = max(2, min(5000, int(payload.get("n_trials") or 20)))
    objective_key = str(payload.get("objective_key") or "夏普比率").strip() or "夏普比率"
    direction = str(payload.get("objective_direction") or "maximize").strip().lower()
    if direction not in ("maximize", "minimize"):
        direction = "maximize"

    study = optuna.create_study(direction=direction, study_name=f"configurable_{job_id or 'web'}")
    trial_records: list[dict[str, Any]] = []
    user_base = str(payload.get("run_name_user_base") or payload.get("run_name") or "可配置").strip()

    def objective(trial: optuna.Trial) -> float:
        if cancel_event is not None and cancel_event.is_set():
            raise optuna.exceptions.OptunaError("cancelled")
        buy_rules = _build_rules(trial, buy_template, "buy")
        sell_rules = _build_rules(trial, sell_template, "sell")
        if log_append:
            log_append(f"trial {trial.number}: buy={len(buy_rules)} sell={len(sell_rules)}")

        def progress(stage: str, value: int, message: str) -> None:
            if progress_callback:
                pct = int(100 * (trial.number / max(n_trials, 1)))
                progress_callback(stage, min(99, pct), f"trial {trial.number + 1}/{n_trials}: {message}")

        result = run_configurable(
            codes=payload.get("codes"),
            start_date=str(payload.get("start_date") or ""),
            end_date=str(payload.get("end_date") or ""),
            run_name=user_base,
            frontend_buy_rules=buy_rules,
            frontend_sell_rules=sell_rules,
            frontend_buy_operator=str(payload.get("buy_operator") or "and"),
            frontend_sell_operator=str(payload.get("sell_operator") or "or"),
            progress=progress,
        )
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        score = _objective_value(summary, objective_key, direction)
        trial_records.append({"trial": trial.number, "run_tag": result.get("run_tag"), "score": score})
        return score

    for trial_idx in range(n_trials):
        if cancel_event is not None and cancel_event.is_set():
            break
        study.optimize(objective, n_trials=1, catch=(Exception,))

    cancelled = cancel_event is not None and cancel_event.is_set()
    completed_trials = [t for t in study.trials if t.state == TrialState.COMPLETE]
    failed_trials = [t for t in study.trials if t.state == TrialState.FAIL]
    best_trial = None
    if completed_trials and not cancelled:
        best_trial = study.best_trial
    elif not cancelled and study.trials:
        raise RuntimeError(
            f"Optuna 可配置寻优：{len(study.trials)} 次 trial 均未成功（失败 {len(failed_trials)} 次）。"
            "请查看任务日志。"
        )
    return {
        "run_tag": str(best_trial.user_attrs.get("run_tag", "")) if best_trial else "",
        "study": {
            "cancelled": cancelled,
            "n_trials": n_trials,
            "completed_trials": len(study.trials),
            "best_trial": best_trial.number if best_trial else None,
            "best_value": study.best_value if best_trial else None,
            "trials": trial_records,
        },
    }
