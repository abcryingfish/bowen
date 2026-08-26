"""把等权指数结果转换为账本 payload 并批量持久化。"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from .equal_weight_index import build_equal_weight_index
from .repository import IndexLegDayPayload, IndexModelDayPayload, StyleMonitorRepository


def build_index_day_payloads(
    *,
    model_version: str,
    model_id: str,
    config_hash: str,
    result: dict[str, Any],
    score_frame: pd.DataFrame,
    initial_last_rebalance: date | None = None,
    initial_index_values: dict[str, float] | None = None,
) -> list[IndexModelDayPayload]:
    """将纯指数结果转换为每日双腿权重账本。"""
    dates = pd.DatetimeIndex(result["index_dfs"]["high"].index)
    scores = score_frame.copy()
    scores.index = pd.DatetimeIndex(pd.to_datetime(scores.index)).floor("D")
    scores.columns = scores.columns.astype(str).str.strip().str.upper()
    payloads: list[IndexModelDayPayload] = []
    last_rebalance: date | None = initial_last_rebalance
    for position, day in enumerate(dates):
        day_date = day.date()
        signal_date = result.get("signal_dates", {}).get(day_date)
        day_payloads: dict[str, IndexLegDayPayload] = {}
        for leg in ("high", "low"):
            value = float(result["index_dfs"][leg].loc[day])
            previous = float(result["index_dfs"][leg].iloc[position - 1]) if position else (initial_index_values or {}).get(leg)
            daily_return = value / previous - 1.0 if previous not in (None, 0.0) else None
            target = result.get("target_weights", {}).get(leg, {}).get(day_date, {})
            effective = result.get("weights", {}).get(leg, {}).get(day_date, {})
            if target:
                last_rebalance = day_date
            diagnostics = result.get("diagnostics", {}).get(leg, {}).get(day_date, {})
            coverage_day = signal_date or day_date
            factor_coverage = result.get("factor_coverage", {}).get(coverage_day)
            # 排名只表示当日目标组合中的信号排名；换仓过渡期仍需展示旧生效持仓，
            # 但旧持仓不应被重新编号成 201、202 等伪排名。
            rank_by_code = {
                code: rank
                for rank, code in enumerate(target.keys(), start=1)
            }
            codes = sorted(set(target) | set(effective))
            weights: list[dict[str, Any]] = []
            for code in codes:
                score = None
                score_day = pd.Timestamp(signal_date) if signal_date else day
                if score_day in scores.index and code in scores.columns:
                    number = pd.to_numeric(scores.loc[score_day, code], errors="coerce")
                    score = float(number) if pd.notna(number) else None
                weights.append({
                    "htsc_code": code,
                    "score": score,
                    "rank": rank_by_code.get(code),
                    "target_weight": float(target.get(code, 0.0)),
                    "effective_weight": float(effective.get(code, 0.0)),
                })
            day_payloads[leg] = IndexLegDayPayload(
                index_value=value,
                daily_return=daily_return,
                cumulative_return=value / 100.0 - 1.0,
                rebalanced=bool(target),
                factor_coverage=float(factor_coverage) if factor_coverage is not None else None,
                valid_count=int(diagnostics.get("valid_count", 0)),
                valid_price_coverage=float(diagnostics.get("valid_price_coverage", 0.0)),
                status="ok",
                status_message="",
                weights=weights,
                signal_date=signal_date,
            )
        payloads.append(IndexModelDayPayload(model_version, model_id, config_hash, day_date, last_rebalance, day_payloads))
    return payloads


def build_and_persist_equal_weight_index(
    *,
    repo: StyleMonitorRepository,
    model_version: str,
    model_id: str,
    config_hash: str,
    score_frame: pd.DataFrame,
    adjusted_open: pd.DataFrame,
    adjusted_close: pd.DataFrame,
    valid_bar: pd.DataFrame,
    rebalance_dates: set[pd.Timestamp | date],
    factor_coverage: dict[date, float] | None = None,
    persist_start_date: date | None = None,
    ratio: float = 0.20,
    max_count: int = 200,
    initial_last_rebalance: date | None = None,
    initial_index_values: dict[str, float] | None = None,
    initial_weights: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    result = build_equal_weight_index(
        score_frame,
        adjusted_close,
        valid_bar,
        adjusted_open=adjusted_open,
        rebalance_dates=rebalance_dates,
        ratio=ratio,
        max_count=max_count,
        initial_index_values=initial_index_values,
        initial_weights=initial_weights,
    )
    if factor_coverage:
        result["factor_coverage"] = factor_coverage
    payloads = build_index_day_payloads(
        model_version=model_version,
        model_id=model_id,
        config_hash=config_hash,
        result=result,
        score_frame=score_frame,
        initial_last_rebalance=initial_last_rebalance,
        initial_index_values=initial_index_values,
    )
    if persist_start_date is not None:
        payloads = [
            payload
            for payload in payloads
            if payload.trade_date >= persist_start_date
        ]
    repo.write_index_model_days(payloads)
    return {"result": result, "payload_count": len(payloads)}
