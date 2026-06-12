"""强点模型参数遍历：穷举全部非空买入因子子集 × 非空卖出因子子集（固定阈值）。"""

from __future__ import annotations

import inspect
import threading
from itertools import combinations, product
from typing import Any, Callable

from models.configurable_signal_rules.data import FactorRule
from models.zxw_strong_adjusted_only.run_naming import (
    build_full_run_name,
    count_nonempty_buy_subsets,
    strip_run_name_date_prefix,
)
from models.zxw_strong_adjusted_only.runner import run
from models.zxw_strong_adjusted_only.signal_data import (
    sell_template_from_frontend,
    template_from_frontend,
)

_RUN_SIGNATURE = inspect.signature(run)

MAX_EXHAUSTIVE_COMBOS = 4096

ProgressCallback = Callable[[str, int, str], None]
LogAppend = Callable[[str], None]


def _all_nonempty_subsets(template: list[FactorRule]) -> list[list[FactorRule]]:
    out: list[list[FactorRule]] = []
    for size in range(1, len(template) + 1):
        for combo in combinations(template, size):
            out.append(list(combo))
    return out


def _all_nonempty_buy_subsets(template: list[FactorRule]) -> list[list[FactorRule]]:
    return _all_nonempty_subsets(template)


def _count_exhaustive_combos(n_buy: int, n_sell: int) -> int:
    return count_nonempty_buy_subsets(n_buy) * count_nonempty_buy_subsets(n_sell)


def _call_strong_run(**kwargs: Any) -> dict[str, Any]:
    filtered = {k: v for k, v in kwargs.items() if k in _RUN_SIGNATURE.parameters}
    return run(**filtered)


def _resolve_user_base(payload: dict[str, Any], start_date: str, end_date: str) -> str:
    raw = str(
        payload.get("run_name_user_base")
        or payload.get("run_name_base")
        or payload.get("run_name")
        or "ZXW强点"
    ).strip()
    return strip_run_name_date_prefix(raw, start_date, end_date) or "ZXW强点"


def _resolve_sell_template(payload: dict[str, Any]) -> list[FactorRule]:
    return sell_template_from_frontend(payload.get("sell_rules"))


def _objective_value(summary: dict[str, Any], objective_key: str, direction: str) -> float:
    raw = summary.get(objective_key)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float("-inf") if direction == "maximize" else float("inf")
    if value != value:
        return float("-inf") if direction == "maximize" else float("inf")
    return value


def _is_better(score: float, best: float | None, direction: str) -> bool:
    if best is None:
        return True
    if direction == "minimize":
        return score < best
    return score > best


def run_optuna_strong_adjusted_study(
    payload: dict[str, Any],
    *,
    job_id: str = "",
    cancel_event: threading.Event | None = None,
    progress_callback: ProgressCallback | None = None,
    log_append: LogAppend | None = None,
) -> dict[str, Any]:
    buy_template = template_from_frontend(payload.get("buy_rules"))
    if not buy_template:
        raise ValueError("参数遍历需要至少一个买入因子模板")

    sell_template = _resolve_sell_template(payload)
    if not sell_template:
        raise ValueError("参数遍历需要至少一个卖出因子模板")

    buy_combos = _all_nonempty_subsets(buy_template)
    sell_combos = _all_nonempty_subsets(sell_template)
    n_buy = len(buy_combos)
    n_sell = len(sell_combos)
    n_total = n_buy * n_sell

    if n_total > MAX_EXHAUSTIVE_COMBOS:
        raise ValueError(
            f"买入因子 {len(buy_template)} 个 → {n_buy} 组子集，"
            f"卖出因子 {len(sell_template)} 个 → {n_sell} 组子集，"
            f"合计 {n_total} 组组合，超过上限 {MAX_EXHAUSTIVE_COMBOS}。"
            "请减少买入或卖出因子数量后再穷举。"
        )

    codes = payload.get("codes")
    start_date = str(payload.get("start_date") or "").strip()
    end_date = str(payload.get("end_date") or "").strip()
    user_base = _resolve_user_base(payload, start_date, end_date)
    buy_operator = str(payload.get("buy_operator") or "and").strip().lower()
    sell_operator = str(payload.get("sell_operator") or "or").strip().lower()
    objective_key = str(payload.get("objective_key") or "夏普比率").strip() or "夏普比率"
    direction = str(payload.get("objective_direction") or "maximize").strip().lower()
    if direction not in ("minimize", "maximize"):
        direction = "maximize"

    if log_append:
        log_append(
            f"强点穷举：{len(buy_template)} 买 → {n_buy} 组 × "
            f"{len(sell_template)} 卖 → {n_sell} 组 = {n_total} 次回测；"
            "卖出子集仅改变止盈触发(strong_sell_signal)，止损用宽表 total_sell_signal"
        )

    trial_records: list[dict[str, Any]] = []
    best_run_tag = ""
    best_score: float | None = None
    best_trial_idx: int | None = None
    failed_count = 0
    completed_count = 0

    for trial_idx, (active_buy, active_sell) in enumerate(product(buy_combos, sell_combos)):
        if cancel_event is not None and cancel_event.is_set():
            break

        full_run_name = build_full_run_name(
            start_date=start_date,
            end_date=end_date,
            user_base=user_base,
            buy_rules=active_buy,
            sell_rules=active_sell,
        )
        if log_append:
            buy_note = ",".join(r.factor for r in active_buy)
            sell_note = ",".join(r.factor for r in active_sell)
            log_append(f"trial {trial_idx}: 买=[{buy_note}] 卖=[{sell_note}] -> {full_run_name}")

        buy_rules_payload = [{"factor": r.factor, "threshold": r.threshold} for r in active_buy]
        sell_rules_payload = [{"factor": r.factor, "threshold": r.threshold} for r in active_sell]

        def progress(stage: str, value: int, message: str) -> None:
            if progress_callback:
                pct = int(100 * (trial_idx / max(n_total, 1)))
                progress_callback(
                    stage,
                    min(99, pct),
                    f"组合 {trial_idx + 1}/{n_total}: {message}",
                )

        try:
            result = _call_strong_run(
                codes=codes,
                start_date=start_date,
                end_date=end_date,
                run_name=full_run_name,
                frontend_buy_rules=buy_rules_payload,
                frontend_sell_rules=sell_rules_payload,
                frontend_buy_operator=buy_operator,
                frontend_sell_operator=sell_operator,
                progress=progress,
                run_name_user_base=user_base,
            )
            summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
            score = _objective_value(summary, objective_key, direction)
            run_tag = str(result.get("run_tag") or "")
            completed_count += 1
            trial_records.append(
                {
                    "trial": trial_idx,
                    "run_tag": run_tag,
                    "run_name": full_run_name,
                    "buy_factors": [r.factor for r in active_buy],
                    "sell_factors": [r.factor for r in active_sell],
                    "objective_key": objective_key,
                    "score": score,
                }
            )
            if _is_better(score, best_score, direction):
                best_score = score
                best_run_tag = run_tag
                best_trial_idx = trial_idx
        except Exception as exc:  # noqa: BLE001
            failed_count += 1
            if log_append:
                log_append(f"trial {trial_idx} 失败: {exc}")

        if progress_callback:
            progress_callback(
                "穷举",
                min(99, int(100 * (trial_idx + 1) / n_total)),
                f"已完成 {trial_idx + 1}/{n_total} 组买卖组合",
            )

    cancelled = cancel_event is not None and cancel_event.is_set()
    if not cancelled and completed_count == 0 and n_total > 0:
        raise RuntimeError(
            f"强点穷举：{n_total} 组组合均未成功（失败 {failed_count} 次）。请查看任务日志。"
        )

    return {
        "run_tag": best_run_tag,
        "study": {
            "cancelled": cancelled,
            "mode": "exhaustive_buy_sell_subsets",
            "n_trials": n_total,
            "buy_subset_count": n_buy,
            "sell_subset_count": n_sell,
            "completed_trials": completed_count,
            "failed_trials": failed_count,
            "best_trial": best_trial_idx,
            "best_value": best_score,
            "objective_key": objective_key,
            "direction": direction,
            "trials": trial_records,
        },
        "config": {
            "template_buy_factors": [r.factor for r in buy_template],
            "template_sell_factors": [r.factor for r in sell_template],
            "run_name_user_base": user_base,
            "exhaustive_subset_count": n_total,
        },
    }
