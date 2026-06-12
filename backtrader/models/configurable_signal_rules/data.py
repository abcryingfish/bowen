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
        try:
            threshold = float(item.get("threshold", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{factor} 阈值必须是数字") from exc
        if not math.isfinite(threshold):
            raise ValueError(f"{factor} 阈值必须是有限数字")
        rules.append(FactorRule(factor=factor, threshold=threshold, column=f"{prefix}_factor_{len(rules)}"))
    return rules


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
        value = pd.to_numeric(df.get(rule.column, 0.0), errors="coerce").fillna(0.0)
        hits.append(value >= rule.threshold)
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
            df[r.column] = 0.0
        df[r.column] = pd.to_numeric(df[r.column], errors="coerce").fillna(0.0)

    buy_hit = _combine_rule_columns(df, buy_u, buy_operator)
    sell_hit = _combine_rule_columns(df, sell_u, sell_operator)
    df["buy_signal"] = buy_hit.astype(float).to_numpy()
    df["sell_signal"] = sell_hit.astype(float).to_numpy()
    return df
