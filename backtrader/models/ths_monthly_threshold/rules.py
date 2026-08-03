from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def _value_rule_hit(values: pd.Series, rule: dict[str, Any]) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.notna() & np.isfinite(numeric)
    operator = str(rule.get("operator") or "gte").strip().lower()
    if operator == "between":
        hit = numeric.between(float(rule["min"]), float(rule["max"]), inclusive="both")
    else:
        threshold = float(rule.get("value", rule.get("threshold", 1.0)))
        comparisons = {
            "gt": numeric > threshold,
            "gte": numeric >= threshold,
            "lt": numeric < threshold,
            "lte": numeric <= threshold,
            "eq": numeric == threshold,
            "ne": numeric != threshold,
        }
        hit = comparisons.get(operator, comparisons["gte"])
    return valid & hit


def _cross_section_rule_hit(frame: pd.DataFrame, rule: dict[str, Any]) -> pd.Series:
    factor = str(rule["factor"])
    values = pd.to_numeric(frame[factor], errors="coerce")
    result = pd.Series(False, index=frame.index)
    direction = str(rule.get("direction") or "top").lower()
    rank_unit = str(rule.get("rank_unit") or "percentile").lower()
    for _, indexes in frame.groupby("time", sort=False).groups.items():
        valid_values = values.loc[indexes].dropna()
        valid_values = valid_values[np.isfinite(valid_values)]
        if valid_values.empty:
            continue
        ascending = direction == "bottom"
        ordered = valid_values.sort_values(ascending=ascending, kind="stable")
        if rank_unit == "rank":
            if direction == "range":
                selected = ordered.index[int(rule["min_rank"]) - 1:int(rule["max_rank"])]
            else:
                selected = ordered.index[:int(rule["rank"])]
            result.loc[selected] = True
            continue
        if direction == "range":
            positions = (valid_values.rank(method="min", ascending=False) - 1.0) / len(valid_values)
            selected = positions[
                (positions >= float(rule["min_percentile"]))
                & (positions <= float(rule["max_percentile"]))
            ].index
        else:
            keep_count = max(1, int(math.ceil(len(ordered) * float(rule["percentile"]))))
            boundary = ordered.iloc[keep_count - 1]
            selected = valid_values[valid_values >= boundary].index if direction == "top" else valid_values[valid_values <= boundary].index
        result.loc[selected] = True
    return result


def evaluate_rules(frame: pd.DataFrame, rules: list[dict[str, Any]], operator: str) -> pd.Series:
    if not rules:
        return pd.Series(False, index=frame.index)
    hits: list[pd.Series] = []
    for rule in rules:
        factor = str(rule.get("factor") or "").strip()
        if not factor or factor not in frame.columns:
            hits.append(pd.Series(False, index=frame.index))
            continue
        if str(rule.get("mode") or "value") == "cross_section_percentile":
            hits.append(_cross_section_rule_hit(frame, rule))
        else:
            hits.append(_value_rule_hit(frame[factor], rule))
    hit_frame = pd.concat(hits, axis=1)
    return hit_frame.any(axis=1) if str(operator).lower() == "or" else hit_frame.all(axis=1)


def build_monthly_rebalance_frame(
    frame: pd.DataFrame,
    rules: list[dict[str, Any]],
    operator: str,
) -> pd.DataFrame:
    out = frame.copy()
    out["time"] = pd.to_datetime(out["time"]).dt.normalize()
    out["htsc_code"] = out["htsc_code"].astype(str).str.upper()
    out = out.sort_values(["time", "htsc_code"], kind="stable").reset_index(drop=True)
    out["condition_met"] = evaluate_rules(out, rules, operator).astype(bool)
    out["month_key"] = out["time"].dt.to_period("M")
    month_last = out.groupby(["htsc_code", "month_key"])["time"].transform("max")
    out["rebalance_due"] = out["time"].eq(month_last)
    out["eligible"] = False
    for _, indexes in out.groupby("htsc_code", sort=False).groups.items():
        ordered = list(indexes)
        previous_decision = False
        for index in ordered:
            out.at[index, "eligible"] = previous_decision
            if bool(out.at[index, "rebalance_due"]):
                previous_decision = bool(out.at[index, "condition_met"])
    return out.drop(columns=["month_key"])


def select_target_codes(frame: pd.DataFrame, input_codes: list[str], max_codes: int) -> list[str]:
    if frame.empty:
        return []
    ordered_codes = list(dict.fromkeys(str(code).strip().upper() for code in input_codes if str(code).strip()))
    if "rebalance_due" in frame.columns and frame["rebalance_due"].astype(bool).any():
        decisions = frame[frame["rebalance_due"].astype(bool)]
        latest_date = pd.to_datetime(decisions["time"]).max()
        latest = decisions[pd.to_datetime(decisions["time"]).eq(latest_date)]
        selected = set(latest.loc[latest["condition_met"].astype(bool), "htsc_code"].astype(str).str.upper())
    else:
        latest_date = pd.to_datetime(frame["time"]).max()
        latest = frame[pd.to_datetime(frame["time"]).eq(latest_date)]
        selected = set(latest.loc[latest["eligible"].astype(bool), "htsc_code"].astype(str).str.upper())
    return [code for code in ordered_codes if code in selected][:max(0, int(max_codes))]
