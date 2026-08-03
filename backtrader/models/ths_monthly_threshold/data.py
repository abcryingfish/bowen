from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .rules import build_monthly_rebalance_frame


INDEX_PRICE_BASE_PATH = Path(r"D:\database\index_data_daily")
SIGNAL_BASE_PATH = Path(r"D:\database\signal_daily")
_INVALID_FACTOR_DIR_CHARS = re.compile(r'[\\/:*?"<>|]')


def normalize_codes(raw_codes: Any) -> list[str]:
    if not isinstance(raw_codes, list):
        raise ValueError("codes 必须是数组")
    codes = list(dict.fromkeys(str(item or "").strip().upper() for item in raw_codes if str(item or "").strip()))
    if not codes:
        raise ValueError("至少需要输入一个THS板块代码")
    invalid = [code for code in codes if not code.endswith(".THS")]
    if invalid:
        raise ValueError(f"THS板块月度模型仅支持 .THS 代码: {', '.join(invalid)}")
    return codes


def normalize_rules(raw_rules: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ValueError("THS板块月度模型至少需要一个买入因子")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            raise ValueError(f"买入因子第 {index + 1} 项格式无效")
        factor = str(raw.get("factor") or "").strip()
        if not factor:
            raise ValueError(f"买入因子第 {index + 1} 项缺少 factor")
        if factor in seen:
            continue
        seen.add(factor)
        mode = str(raw.get("mode") or "value").strip().lower()
        if mode == "value":
            operator = str(raw.get("operator") or "gte").strip().lower()
            operator = {">": "gt", ">=": "gte", "<": "lt", "<=": "lte", "=": "eq", "==": "eq", "!=": "ne"}.get(operator, operator)
            if operator not in {"gt", "gte", "lt", "lte", "eq", "ne", "between"}:
                raise ValueError(f"{factor} 比较方式无效")
            rule: dict[str, Any] = {"factor": factor, "mode": "value", "operator": operator}
            if operator == "between":
                value_min = float(raw.get("min"))
                value_max = float(raw.get("max"))
                if not math.isfinite(value_min) or not math.isfinite(value_max) or value_min > value_max:
                    raise ValueError(f"{factor} 区间必须满足下限 <= 上限")
                rule.update({"min": value_min, "max": value_max})
            else:
                value = float(raw.get("value", raw.get("threshold", 1.0)))
                if not math.isfinite(value):
                    raise ValueError(f"{factor} 筛选值必须是有限数字")
                rule["value"] = value
            normalized.append(rule)
            continue
        if mode != "cross_section_percentile":
            raise ValueError(f"{factor} 筛选类型无效")
        direction = str(raw.get("direction") or "top").strip().lower()
        if direction not in {"top", "bottom", "range"}:
            raise ValueError(f"{factor} 横截面排名方向无效")
        rank_unit = str(raw.get("rank_unit") or "percentile").strip().lower()
        if rank_unit not in {"percentile", "rank"}:
            raise ValueError(f"{factor} 横截面排名单位无效")
        rule = {
            "factor": factor,
            "mode": "cross_section_percentile",
            "direction": direction,
            "rank_unit": rank_unit,
        }
        if rank_unit == "rank":
            if direction == "range":
                min_rank = int(raw.get("min_rank"))
                max_rank = int(raw.get("max_rank"))
                if min_rank < 1 or max_rank < min_rank:
                    raise ValueError(f"{factor} 名次区间无效")
                rule.update({"min_rank": min_rank, "max_rank": max_rank})
            else:
                rank = int(raw.get("rank"))
                if rank < 1:
                    raise ValueError(f"{factor} 排名名次必须大于0")
                rule["rank"] = rank
        elif direction == "range":
            min_percentile = float(raw.get("min_percentile"))
            max_percentile = float(raw.get("max_percentile"))
            if not 0 <= min_percentile < max_percentile <= 1:
                raise ValueError(f"{factor} 分位区间无效")
            rule.update({"min_percentile": min_percentile, "max_percentile": max_percentile})
        else:
            percentile = float(raw.get("percentile"))
            if not 0 < percentile <= 1:
                raise ValueError(f"{factor} 排名比例必须大于0且不超过100%")
            rule["percentile"] = percentile
        normalized.append(rule)
    return normalized


def _factor_partition_paths(factor: str, start_date: str, end_date: str) -> list[str]:
    safe_factor = _INVALID_FACTOR_DIR_CHARS.sub("_", factor).rstrip(" .") or "未命名因子"
    start = pd.Timestamp(start_date).to_period("M")
    end = pd.Timestamp(end_date).to_period("M")
    paths: list[str] = []
    for period in pd.period_range(start, end, freq="M"):
        directory = SIGNAL_BASE_PATH / f"factor={safe_factor}" / f"year={period.year}" / f"month={period.month:02d}"
        merged = directory / "merged.parquet"
        if merged.is_file():
            paths.append(merged.as_posix())
        paths.extend(path.as_posix() for path in sorted(directory.glob("part_*.parquet")) if path.is_file())
    return paths


def _load_price_frame(codes: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    pattern = (INDEX_PRICE_BASE_PATH / "year=*" / "month=*" / "merged.parquet").as_posix()
    with duckdb.connect(database=":memory:") as connection:
        frame = connection.execute(
            """
            SELECT * FROM read_parquet(?, hive_partitioning=1, union_by_name=true)
            WHERE UPPER(CAST(htsc_code AS VARCHAR)) IN (SELECT UNNEST(?))
              AND CAST(time AS DATE) >= CAST(? AS DATE)
              AND CAST(time AS DATE) < CAST(? AS DATE)
            ORDER BY time, htsc_code
            """,
            [pattern, codes, start_date, end_date],
        ).df()
    if frame.empty:
        raise ValueError("THS板块代码和日期范围内没有指数行情数据")
    frame["time"] = pd.to_datetime(frame["time"]).dt.normalize()
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.upper()
    return frame


def _load_factor_frame(rules: list[dict[str, Any]], codes: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    base = pd.DataFrame(columns=["time", "htsc_code"])
    with duckdb.connect(database=":memory:") as connection:
        for rule in rules:
            factor = str(rule["factor"])
            paths = _factor_partition_paths(factor, start_date, end_date)
            if not paths:
                continue
            frame = connection.execute(
                """
                SELECT CAST(time AS TIMESTAMP) AS time,
                       UPPER(CAST(htsc_code AS VARCHAR)) AS htsc_code,
                       TRY_CAST(value AS DOUBLE) AS factor_value
                FROM read_parquet(?, union_by_name=true)
                WHERE UPPER(CAST(htsc_code AS VARCHAR)) IN (SELECT UNNEST(?))
                  AND CAST(time AS DATE) >= CAST(? AS DATE)
                  AND CAST(time AS DATE) < CAST(? AS DATE)
                ORDER BY time, htsc_code
                """,
                [paths, codes, start_date, end_date],
            ).df()
            frame["time"] = pd.to_datetime(frame["time"]).dt.normalize()
            frame = frame.drop_duplicates(["time", "htsc_code"], keep="last").rename(columns={"factor_value": factor})
            columns = ["time", "htsc_code", factor]
            base = frame[columns] if base.empty else base.merge(frame[columns], on=["time", "htsc_code"], how="outer")
    return base


def build_ths_bt_dataframe(
    codes: list[str],
    start_date: str,
    end_date: str,
    rules: list[dict[str, Any]],
    operator: str,
) -> pd.DataFrame:
    price = _load_price_frame(codes, start_date, end_date)
    factors = _load_factor_frame(rules, codes, start_date, end_date)
    frame = price.merge(factors, on=["time", "htsc_code"], how="left") if not factors.empty else price
    frame = build_monthly_rebalance_frame(frame, rules, operator)
    frame["buy_signal"] = frame["condition_met"].astype(float)
    frame["sell_signal"] = frame["rebalance_due"].astype(float)
    frame["mac_total"] = 0.0
    frame["kdj_signal"] = 0.0
    frame["obv_bullish"] = 0.0
    return frame
