from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

PRICE_BASE_PATH = r"D:\database\stock_basic_data_daily"
SIGNAL_BASE_PATH = Path(r"D:\database\signal_daily")
_INVALID_FACTOR_DIR_CHARS = re.compile(r'[\\/:*?"<>|]')

BACKTEST_COMMISSION_RATE = 0.0003


@dataclass(frozen=True)
class FactorRule:
    factor: str
    threshold: float
    column: str
    mode: str = "value"
    operator: str = "gte"
    value_min: float | None = None
    value_max: float | None = None
    direction: str = "top"
    rank_unit: str = "percentile"
    rank: int | None = None
    min_rank: int | None = None
    max_rank: int | None = None
    percentile: float | None = None
    min_percentile: float | None = None
    max_percentile: float | None = None


def _sanitize_factor_dir_name(factor_name: str) -> str:
    safe_name = _INVALID_FACTOR_DIR_CHARS.sub("_", str(factor_name).strip())
    safe_name = safe_name.rstrip(" .")
    return safe_name or "未命名因子"


def _iter_year_month(start_dt: pd.Timestamp, end_dt: pd.Timestamp) -> list[tuple[int, int]]:
    cursor = pd.Timestamp(year=start_dt.year, month=start_dt.month, day=1)
    end_cursor = pd.Timestamp(year=end_dt.year, month=end_dt.month, day=1)
    result: list[tuple[int, int]] = []
    while cursor <= end_cursor:
        result.append((int(cursor.year), int(cursor.month)))
        cursor = cursor + pd.offsets.MonthBegin(1)
    return result


def _existing_factor_partition_paths(
    base_path: Path,
    factor_name: str,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
) -> list[str]:
    factor_dir = _sanitize_factor_dir_name(factor_name)
    paths: list[str] = []
    for year, month in _iter_year_month(start_dt, end_dt):
        month_dir = base_path / f"factor={factor_dir}" / f"year={year}" / f"month={month:02d}"
        if not month_dir.exists():
            continue
        merged_path = month_dir / "merged.parquet"
        if merged_path.exists() and merged_path.is_file():
            paths.append(merged_path.as_posix())
        for part_path in sorted(month_dir.glob("part_*.parquet")):
            if part_path.exists() and part_path.is_file():
                paths.append(part_path.as_posix())
    return paths


def _normalize_operator(value: Any) -> str:
    text = str(value or "and").strip().lower()
    return "or" if text == "or" else "and"


def normalize_rules(raw_rules: Any, prefix: str) -> list[FactorRule]:
    if raw_rules is None:
        return []
    if not isinstance(raw_rules, list):
        raise ValueError(f"{prefix} rules 必须是数组")
    rules: list[FactorRule] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw_rules):
        if not isinstance(item, dict):
            raise ValueError(f"{prefix} rules 第 {idx + 1} 项格式无效")
        factor = str(item.get("factor", "")).strip()
        if not factor:
            raise ValueError(f"{prefix} rules 第 {idx + 1} 项缺少 factor")
        if factor in seen:
            continue
        seen.add(factor)
        mode = str(item.get("mode") or "value").strip().lower()
        if mode not in {"value", "cross_section_percentile"}:
            raise ValueError(f"{factor} 筛选类型无效")

        if mode == "value":
            operator = str(item.get("operator") or "gte").strip().lower()
            operator_aliases = {
                ">": "gt",
                ">=": "gte",
                "<": "lt",
                "<=": "lte",
                "=": "eq",
                "==": "eq",
                "!=": "ne",
            }
            operator = operator_aliases.get(operator, operator)
            if operator not in {"gt", "gte", "lt", "lte", "eq", "ne", "between"}:
                raise ValueError(f"{factor} 比较方式无效")
            if operator == "between":
                try:
                    value_min = float(item.get("min"))
                    value_max = float(item.get("max"))
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{factor} 区间上下限必须是数字") from exc
                if not math.isfinite(value_min) or not math.isfinite(value_max) or value_min > value_max:
                    raise ValueError(f"{factor} 区间必须满足下限 <= 上限")
                threshold = value_min
                rules.append(
                    FactorRule(
                        factor=factor,
                        threshold=threshold,
                        column=f"{prefix}_factor_{len(rules)}",
                        mode=mode,
                        operator=operator,
                        value_min=value_min,
                        value_max=value_max,
                    )
                )
                continue
            try:
                threshold = float(item.get("value", item.get("threshold", 1)))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{factor} 筛选值必须是数字") from exc
            if not math.isfinite(threshold):
                raise ValueError(f"{factor} 筛选值必须是有限数字")
            rules.append(
                FactorRule(
                    factor=factor,
                    threshold=threshold,
                    column=f"{prefix}_factor_{len(rules)}",
                    mode=mode,
                    operator=operator,
                )
            )
            continue

        direction = str(item.get("direction") or "top").strip().lower()
        if direction not in {"top", "bottom", "range"}:
            raise ValueError(f"{factor} 横截面排名方向无效")
        rank_unit = str(item.get("rank_unit") or "percentile").strip().lower()
        if rank_unit not in {"percentile", "rank"}:
            raise ValueError(f"{factor} 横截面排名单位无效")
        if rank_unit == "rank":
            if direction == "range":
                try:
                    min_rank_value = float(item.get("min_rank"))
                    max_rank_value = float(item.get("max_rank"))
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{factor} 名次区间必须是整数") from exc
                if (
                    not math.isfinite(min_rank_value)
                    or not math.isfinite(max_rank_value)
                    or not min_rank_value.is_integer()
                    or not max_rank_value.is_integer()
                ):
                    raise ValueError(f"{factor} 名次区间必须是整数")
                min_rank = int(min_rank_value)
                max_rank = int(max_rank_value)
                if not 1 <= min_rank <= max_rank:
                    raise ValueError(f"{factor} 名次区间必须满足 1 <= 起始名次 <= 结束名次")
                rules.append(
                    FactorRule(
                        factor=factor,
                        threshold=float(min_rank),
                        column=f"{prefix}_factor_{len(rules)}",
                        mode=mode,
                        direction=direction,
                        rank_unit=rank_unit,
                        min_rank=min_rank,
                        max_rank=max_rank,
                    )
                )
                continue
            try:
                rank_value = float(item.get("rank"))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{factor} 排名名次必须是整数") from exc
            if not math.isfinite(rank_value) or not rank_value.is_integer() or rank_value <= 0:
                raise ValueError(f"{factor} 排名名次必须是大于 0 的整数")
            rank = int(rank_value)
            rules.append(
                FactorRule(
                    factor=factor,
                    threshold=float(rank),
                    column=f"{prefix}_factor_{len(rules)}",
                    mode=mode,
                    direction=direction,
                    rank_unit=rank_unit,
                    rank=rank,
                )
            )
            continue
        if direction == "range":
            try:
                min_percentile = float(item.get("min_percentile"))
                max_percentile = float(item.get("max_percentile"))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{factor} 分位区间必须是数字") from exc
            if not 0 <= min_percentile < max_percentile <= 1:
                raise ValueError(f"{factor} 分位区间必须满足 0% <= 下限 < 上限 <= 100%")
            rules.append(
                FactorRule(
                    factor=factor,
                    threshold=min_percentile,
                    column=f"{prefix}_factor_{len(rules)}",
                    mode=mode,
                    direction=direction,
                    min_percentile=min_percentile,
                    max_percentile=max_percentile,
                )
            )
            continue
        try:
            percentile = float(item.get("percentile"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{factor} 排名比例必须是数字") from exc
        if not 0 < percentile <= 1:
            raise ValueError(f"{factor} 排名比例必须大于 0% 且不超过 100%")
        rules.append(
            FactorRule(
                factor=factor,
                threshold=percentile,
                column=f"{prefix}_factor_{len(rules)}",
                mode=mode,
                direction=direction,
                percentile=percentile,
            )
        )
    return rules


def factor_rule_to_payload(rule: FactorRule) -> dict[str, Any]:
    if rule.mode == "cross_section_percentile":
        payload: dict[str, Any] = {
            "factor": rule.factor,
            "mode": "cross_section_percentile",
            "direction": rule.direction,
            "scope": "selected_stock_pool",
            "frequency": "daily",
        }
        if rule.rank_unit == "rank":
            payload["rank_unit"] = "rank"
            if rule.direction == "range":
                payload["min_rank"] = rule.min_rank
                payload["max_rank"] = rule.max_rank
            else:
                payload["rank"] = rule.rank
            return payload
        if rule.direction == "range":
            payload["min_percentile"] = rule.min_percentile
            payload["max_percentile"] = rule.max_percentile
        else:
            payload["percentile"] = rule.percentile
        return payload
    if rule.operator == "between":
        return {
            "factor": rule.factor,
            "mode": "value",
            "operator": "between",
            "min": rule.value_min,
            "max": rule.value_max,
        }
    return {
        "factor": rule.factor,
        "mode": "value",
        "operator": rule.operator,
        "value": rule.threshold,
        "threshold": rule.threshold,
    }


def _load_price_frame(codes: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    con = duckdb.connect(database=":memory:")
    try:
        sql = """
            SELECT *
            FROM read_parquet(?, hive_partitioning=1, union_by_name=true)
            WHERE CAST(htsc_code AS VARCHAR) IN (
                SELECT UNNEST(?)
            )
              AND CAST(time AS DATE) >= CAST(? AS DATE)
              AND CAST(time AS DATE) < CAST(? AS DATE)
            ORDER BY htsc_code, time
        """
        df = con.execute(
            sql,
            [f"{PRICE_BASE_PATH}/year=*/month=*/merged.parquet", codes, start_date, end_date],
        ).df()
    finally:
        con.close()
    if df.empty:
        raise ValueError("目标标的和日期范围内没有价格数据")
    df["time"] = pd.to_datetime(df["time"]).dt.normalize()
    df["htsc_code"] = df["htsc_code"].astype(str).str.upper()
    return df


def _load_factor_frame(
    rules: list[FactorRule],
    codes: list[str],
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    start_dt = pd.Timestamp(start_date).floor("D")
    end_dt = pd.Timestamp(end_date).floor("D")
    frames: list[pd.DataFrame] = []
    con = duckdb.connect(database=":memory:")
    try:
        for rule in rules:
            paths = _existing_factor_partition_paths(SIGNAL_BASE_PATH, rule.factor, start_dt, end_dt)
            if not paths:
                frame = pd.DataFrame(columns=["time", "htsc_code", rule.column])
                frames.append(frame)
                continue
            sql = """
                SELECT
                    CAST(time AS TIMESTAMP) AS time,
                    UPPER(CAST(htsc_code AS VARCHAR)) AS htsc_code,
                    TRY_CAST(value AS DOUBLE) AS value
                FROM read_parquet(?, union_by_name=true)
                WHERE UPPER(CAST(htsc_code AS VARCHAR)) IN (
                    SELECT UNNEST(?)
                )
                  AND CAST(time AS DATE) >= CAST(? AS DATE)
                  AND CAST(time AS DATE) < CAST(? AS DATE)
                ORDER BY htsc_code, time
            """
            frame = con.execute(sql, [paths, codes, start_date, end_date]).df()
            if frame.empty:
                frame = pd.DataFrame(columns=["time", "htsc_code", rule.column])
            else:
                frame["time"] = pd.to_datetime(frame["time"]).dt.normalize()
                frame["htsc_code"] = frame["htsc_code"].astype(str).str.upper()
                frame = frame.drop_duplicates(["time", "htsc_code"], keep="last")
                frame = frame.rename(columns={"value": rule.column})
                frame = frame[["time", "htsc_code", rule.column]]
            frames.append(frame)
    finally:
        con.close()

    if not frames:
        return pd.DataFrame(columns=["time", "htsc_code"])
    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on=["time", "htsc_code"], how="outer")
    return merged.sort_values(["htsc_code", "time"]).reset_index(drop=True)


def _combine_rule_columns(df: pd.DataFrame, rules: list[FactorRule], operator: str) -> pd.Series:
    if not rules:
        return pd.Series(False, index=df.index)
    hits = []
    for rule in rules:
        value = pd.to_numeric(df.get(rule.column, pd.Series(index=df.index, dtype=float)), errors="coerce")
        valid = value.notna() & np.isfinite(value)
        if rule.mode == "cross_section_percentile":
            if "time" not in df.columns:
                raise ValueError(f"{rule.factor} 横截面排名缺少 time 列")
            hit = pd.Series(False, index=df.index)
            for _, indexes in df.groupby("time", sort=False, dropna=False).groups.items():
                group_value = value.loc[indexes]
                group_valid = valid.loc[indexes]
                valid_value = group_value[group_valid]
                if valid_value.empty:
                    continue
                if rule.rank_unit == "rank":
                    ordered = valid_value.sort_values(
                        ascending=rule.direction == "bottom",
                        kind="stable",
                    )
                    if rule.direction == "range":
                        selected_indexes = ordered.index[
                            int(rule.min_rank or 1) - 1:int(rule.max_rank or 0)
                        ]
                    else:
                        selected_indexes = ordered.index[:int(rule.rank or 0)]
                    hit.loc[selected_indexes] = True
                    continue
                if rule.direction in {"top", "bottom"}:
                    keep_count = max(1, int(math.ceil(len(valid_value) * float(rule.percentile or 0))))
                    ordered = valid_value.sort_values(ascending=rule.direction == "bottom")
                    boundary = ordered.iloc[keep_count - 1]
                    selected = valid_value >= boundary if rule.direction == "top" else valid_value <= boundary
                else:
                    rank_position = (valid_value.rank(method="min", ascending=False) - 1.0) / len(valid_value)
                    selected = (
                        (rank_position >= float(rule.min_percentile or 0.0))
                        & (rank_position <= float(rule.max_percentile or 0.0))
                    )
                hit.loc[selected.index] = selected
            hits.append(hit)
            continue
        if rule.operator == "gt":
            hit = value > rule.threshold
        elif rule.operator == "lt":
            hit = value < rule.threshold
        elif rule.operator == "lte":
            hit = value <= rule.threshold
        elif rule.operator == "eq":
            hit = value == rule.threshold
        elif rule.operator == "ne":
            hit = value != rule.threshold
        elif rule.operator == "between":
            hit = value.between(float(rule.value_min), float(rule.value_max), inclusive="both")
        else:
            hit = value >= rule.threshold
        hits.append(valid & hit)
    hit_df = pd.concat(hits, axis=1)
    if operator == "or":
        return hit_df.any(axis=1)
    return hit_df.all(axis=1)


def _dedupe_rules_by_factor(rules: list[FactorRule]) -> list[FactorRule]:
    seen: set[str] = set()
    out: list[FactorRule] = []
    for r in rules:
        if r.factor in seen:
            continue
        seen.add(r.factor)
        out.append(r)
    return out


def build_configurable_bt_dataframe(
    codes: list[str],
    start_date: str,
    end_date: str,
    buy_rules: list[FactorRule],
    sell_rules: list[FactorRule],
    buy_operator: str,
    sell_operator: str,
) -> pd.DataFrame:
    aux = [
        FactorRule("MAC总", 1.0, "mac_total"),
        FactorRule("KDJ信号", 1.0, "kdj_signal"),
        FactorRule("OBV多头排列", 1.0, "obv_bullish"),
    ]
    buy_u = _dedupe_rules_by_factor(buy_rules)
    sell_u = _dedupe_rules_by_factor(sell_rules)
    load_rules = _dedupe_rules_by_factor(aux + buy_u + sell_u)

    price_df = _load_price_frame(codes, start_date, end_date)
    factor_df = _load_factor_frame(load_rules, codes, start_date, end_date)
    df = price_df.merge(factor_df, on=["time", "htsc_code"], how="left")
    for r in load_rules:
        if r.column not in df.columns:
            df[r.column] = np.nan
        df[r.column] = pd.to_numeric(df[r.column], errors="coerce")

    buy_hit = _combine_rule_columns(df, buy_u, buy_operator)
    sell_hit = _combine_rule_columns(df, sell_u, sell_operator)
    df["buy_signal"] = buy_hit.astype(float).to_numpy()
    df["sell_signal"] = sell_hit.astype(float).to_numpy()
    for r in load_rules:
        df[r.column] = df[r.column].fillna(0.0)
    return df
