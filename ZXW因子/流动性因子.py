"""基于成交额、换手率的股票流动性因子。"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import glob

import duckdb
import numpy as np
import pandas as pd


BUNDLE_ID = "liquidity"
DEFAULT_TURNOVER_GLOB = r"D:\database\qmt_turnover_data\year=*\month=*\merged.parquet"
FACTOR_LOOKBACK_DAYS = {
    "avg_trading_value_20d": 20,
    "avg_trading_value_60d": 60,
    "avg_turnover_20d": 20,
    "avg_turnover_60d": 60,
    "amihud_20d": 21,
    "trading_value_volatility_20d": 21,
    "zero_trading_value_ratio_20d": 20,
}
FACTOR_NAME_MAP = {
    "20日平均成交额": "avg_trading_value_20d",
    "60日平均成交额": "avg_trading_value_60d",
    "20日平均换手率": "avg_turnover_20d",
    "60日平均换手率": "avg_turnover_60d",
    "20日Amihud非流动性": "amihud_20d",
    "20日成交额波动率": "trading_value_volatility_20d",
    "20日零成交额占比": "zero_trading_value_ratio_20d",
}


def get_factor_catalog() -> dict[str, dict[str, str]]:
    return {"factor_name_map": dict(FACTOR_NAME_MAP)}


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(FACTOR_LOOKBACK_DAYS.values()),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }


def _normalize_code(value: object) -> str:
    return str(value or "").strip().upper()


def _resolve_source(source_glob: str) -> str | list[str]:
    path = Path(source_glob)
    if path.is_file():
        return str(path)
    normalized = str(source_glob).replace("\\", "/")
    if "*" not in normalized:
        return str(source_glob)
    paths = sorted(glob.glob(normalized))
    return paths if len(paths) > 1 else (paths[0] if paths else str(source_glob))


def _read_source(
    source_glob: str,
    target_codes: list[str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    source = _resolve_source(source_glob)
    placeholders = ", ".join("?" for _ in target_codes)
    query = f"""
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            CAST(time AS DATE) AS time,
            TRY_CAST(value AS DOUBLE) AS trading_value,
            TRY_CAST(turnover_rate AS DOUBLE) AS turnover_rate
        FROM read_parquet(?, union_by_name=true)
        WHERE CAST(time AS DATE) BETWEEN ? AND ?
          AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN ({placeholders})
        ORDER BY time, htsc_code
    """
    with duckdb.connect(database=":memory:") as con:
        available = {
            str(row[0])
            for row in con.execute(
                "DESCRIBE SELECT * FROM read_parquet(?, union_by_name=true)",
                [source],
            ).fetchall()
        }
        required = {"htsc_code", "time", "value", "turnover_rate"}
        missing = sorted(required - available)
        if missing:
            raise ValueError(f"qmt_turnover_data 缺少字段: {', '.join(missing)}")
        return con.execute(
            query,
            [source, start_date.date(), end_date.date(), *target_codes],
        ).df()


def build_liquidity_factor_bundle(
    C: pd.DataFrame,
    *,
    stock_codes: set[str] | list[str] | tuple[str, ...],
    source_glob: str = DEFAULT_TURNOVER_GLOB,
) -> dict[str, Any]:
    index = pd.DatetimeIndex(pd.to_datetime(C.index)).floor("D")
    target_codes = sorted(
        {_normalize_code(code) for code in C.columns}
        & {_normalize_code(code) for code in stock_codes if _normalize_code(code)}
    )
    factor_dfs = {
        key: pd.DataFrame(index=index, columns=target_codes, dtype=float)
        for key in FACTOR_NAME_MAP.values()
    }
    if index.empty or not target_codes:
        return {"bundle_id": BUNDLE_ID, "factor_dfs": factor_dfs, "factor_name_map": dict(FACTOR_NAME_MAP)}

    source = _read_source(source_glob, target_codes, index.min(), index.max())
    if source.empty or pd.Timestamp(source["time"].max()).floor("D") < index.max():
        latest = source["time"].max() if not source.empty else None
        raise ValueError(
            "qmt_turnover_data 流动性源数据未更新到请求结束日："
            f"要求 {index.max().date()}，最新 {latest}"
        )
    source["time"] = pd.to_datetime(source["time"], errors="coerce").dt.floor("D")
    source["htsc_code"] = source["htsc_code"].map(_normalize_code)
    source = source.dropna(subset=["time"]).drop_duplicates(["time", "htsc_code"], keep="last")
    source = source.set_index(["time", "htsc_code"]).sort_index()
    value = source["trading_value"].unstack("htsc_code").reindex(index=index, columns=target_codes).astype(float)
    turnover = source["turnover_rate"].unstack("htsc_code").reindex(index=index, columns=target_codes).astype(float)
    returns = C.reindex(index=index, columns=target_codes).astype(float).pct_change(fill_method=None)
    safe_value = value.where(value > 0.0)

    factor_dfs["avg_trading_value_20d"] = value.rolling(20, min_periods=20).mean()
    factor_dfs["avg_trading_value_60d"] = value.rolling(60, min_periods=60).mean()
    factor_dfs["avg_turnover_20d"] = turnover.rolling(20, min_periods=20).mean()
    factor_dfs["avg_turnover_60d"] = turnover.rolling(60, min_periods=60).mean()
    factor_dfs["amihud_20d"] = (returns.abs() / safe_value).rolling(20, min_periods=20).mean()
    factor_dfs["trading_value_volatility_20d"] = safe_value.pct_change(fill_method=None).rolling(20, min_periods=20).std()
    zero_value_flag = value.le(0.0).where(value.notna()).astype(float)
    factor_dfs["zero_trading_value_ratio_20d"] = zero_value_flag.rolling(20, min_periods=20).mean()
    return {"bundle_id": BUNDLE_ID, "factor_dfs": factor_dfs, "factor_name_map": dict(FACTOR_NAME_MAP)}
