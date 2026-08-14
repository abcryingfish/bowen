from __future__ import annotations

import math
import os
import threading
import time
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from market_data_service import (
    MarketDataError,
    MarketDataNotFoundError,
    MarketDataValidationError,
)

try:
    from numba import njit, prange

    _NUMBA_AVAILABLE = True
except Exception:  # noqa: BLE001
    _NUMBA_AVAILABLE = False

    def njit(*args, **kwargs):  # type: ignore[override]
        def decorator(func):
            return func

        return decorator

    def prange(*args):  # type: ignore[override]
        return range(*args)


DAILY_BASE_PATH = Path(os.environ.get("MARKET_RESEARCH_DAILY_PATH", r"D:\database\qmt_turnover_data"))
ADJ_SEGMENT_PATH = Path(
    os.environ.get("MARKET_RESEARCH_ADJ_SEGMENT_PATH", r"D:\database\stock_adj_daily\adj_factor_segments.parquet")
)

RSI_PERIOD = 14
RSI_WARMUP_CALENDAR_DAYS = 400
TOP_FRACTION = 0.05
MAX_POINTS = 2000
MARKET_LABELS = {
    "sh": "沪",
    "sz": "深",
    "star": "科创",
    "all-a": "全A",
}

_COMPUTE_LOCK = threading.Lock()


def _parse_timestamp(value: Any, field_name: str, default: datetime) -> datetime:
    if value is None or value == "":
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise MarketDataValidationError(f"{field_name} 必须是 Unix 秒时间戳") from exc
    if not math.isfinite(numeric) or numeric <= 0:
        raise MarketDataValidationError(f"{field_name} 必须是有效的 Unix 秒时间戳")
    try:
        return datetime.fromtimestamp(numeric)
    except (OverflowError, OSError, ValueError) as exc:
        raise MarketDataValidationError(f"{field_name} 超出支持范围") from exc


def _parse_points(value: Any) -> int:
    if value is None or value == "":
        return 60
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise MarketDataValidationError("points 必须是整数") from exc
    if parsed < 1 or parsed > MAX_POINTS:
        raise MarketDataValidationError(f"points 必须在 1 到 {MAX_POINTS} 之间")
    return parsed


def _iter_months(start_day: date, end_day: date):
    cursor = date(start_day.year, start_day.month, 1)
    final = date(end_day.year, end_day.month, 1)
    while cursor <= final:
        yield cursor.year, cursor.month
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)


def _partition_files(base_path: Path, start_day: date, end_day: date) -> list[str]:
    paths: list[str] = []
    for year, month in _iter_months(start_day, end_day):
        path = base_path / f"year={year:04d}" / f"month={month:02d}" / "merged.parquet"
        if path.is_file():
            paths.append(str(path))
    return paths


def _source_signature(paths: list[str]) -> tuple[tuple[str, int, int], ...]:
    signature: list[tuple[str, int, int]] = []
    for raw_path in paths:
        path = Path(raw_path)
        stat = path.stat()
        signature.append((str(path), stat.st_mtime_ns, stat.st_size))
    if ADJ_SEGMENT_PATH.is_file():
        stat = ADJ_SEGMENT_PATH.stat()
        signature.append((str(ADJ_SEGMENT_PATH), stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


@njit(cache=True, parallel=True)
def _wilder_rsi_long_numba(
    close_values: np.ndarray,
    group_starts: np.ndarray,
    group_ends: np.ndarray,
    period: int,
) -> np.ndarray:
    output = np.empty(close_values.shape[0], dtype=np.float64)
    output[:] = np.nan
    for group_index in prange(group_starts.shape[0]):
        start = group_starts[group_index]
        end = group_ends[group_index]
        if end - start <= period:
            continue
        gain_sum = 0.0
        loss_sum = 0.0
        for pos in range(start + 1, start + period + 1):
            delta = close_values[pos] - close_values[pos - 1]
            if delta > 0.0:
                gain_sum += delta
            elif delta < 0.0:
                loss_sum += -delta
        avg_gain = gain_sum / period
        avg_loss = loss_sum / period
        if avg_gain == 0.0 and avg_loss == 0.0:
            output[start + period] = 50.0
        elif avg_loss == 0.0:
            output[start + period] = 100.0
        elif avg_gain == 0.0:
            output[start + period] = 0.0
        else:
            output[start + period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

        for pos in range(start + period + 1, end):
            delta = close_values[pos] - close_values[pos - 1]
            gain = delta if delta > 0.0 else 0.0
            loss = -delta if delta < 0.0 else 0.0
            avg_gain = ((period - 1) * avg_gain + gain) / period
            avg_loss = ((period - 1) * avg_loss + loss) / period
            if avg_gain == 0.0 and avg_loss == 0.0:
                output[pos] = 50.0
            elif avg_loss == 0.0:
                output[pos] = 100.0
            elif avg_gain == 0.0:
                output[pos] = 0.0
            else:
                output[pos] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return output


def _wilder_rsi_long_python(
    close_values: np.ndarray,
    group_starts: np.ndarray,
    group_ends: np.ndarray,
    period: int,
) -> np.ndarray:
    output = np.full(close_values.shape[0], np.nan, dtype=np.float64)
    for start, end in zip(group_starts, group_ends):
        if end - start <= period:
            continue
        deltas = np.diff(close_values[start:end])
        gains = np.where(deltas > 0.0, deltas, 0.0)
        losses = np.where(deltas < 0.0, -deltas, 0.0)
        avg_gain = float(gains[:period].mean())
        avg_loss = float(losses[:period].mean())
        for offset in range(period, len(deltas) + 1):
            if offset > period:
                avg_gain = ((period - 1) * avg_gain + gains[offset - 1]) / period
                avg_loss = ((period - 1) * avg_loss + losses[offset - 1]) / period
            if avg_gain == 0.0 and avg_loss == 0.0:
                value = 50.0
            elif avg_loss == 0.0:
                value = 100.0
            elif avg_gain == 0.0:
                value = 0.0
            else:
                value = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
            output[start + offset] = value
    return output


def _calculate_rsi(frame: pd.DataFrame) -> np.ndarray:
    codes = frame["htsc_code"].to_numpy(dtype=str)
    starts = np.flatnonzero(np.r_[True, codes[1:] != codes[:-1]]).astype(np.int64)
    ends = np.r_[starts[1:], len(codes)].astype(np.int64)
    closes = frame["adjusted_close"].to_numpy(dtype=np.float64)
    if _NUMBA_AVAILABLE and len(frame) >= 50_000:
        return _wilder_rsi_long_numba(closes, starts, ends, RSI_PERIOD)
    return _wilder_rsi_long_python(closes, starts, ends, RSI_PERIOD)


def _load_market_frame(start_day: date, end_day: date) -> tuple[pd.DataFrame, list[str]]:
    daily_paths = _partition_files(DAILY_BASE_PATH, start_day, end_day)
    if not daily_paths:
        raise MarketDataNotFoundError(f"市场研究日线分区不存在: {DAILY_BASE_PATH}")
    conn = duckdb.connect(database=":memory:")
    try:
        if ADJ_SEGMENT_PATH.is_file():
            sql = """
                WITH daily AS (
                    SELECT
                        UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                        CAST(time AS DATE) AS trade_date,
                        TRY_CAST(close AS DOUBLE) AS close,
                        TRY_CAST(value AS DOUBLE) AS trade_value
                    FROM read_parquet(?, union_by_name=true)
                    WHERE CAST(time AS DATE) BETWEEN ? AND ?
                      AND (UPPER(TRIM(CAST(htsc_code AS VARCHAR))) LIKE '%.SH'
                           OR UPPER(TRIM(CAST(htsc_code AS VARCHAR))) LIKE '%.SZ')
                      AND TRY_CAST(close AS DOUBLE) > 0
                ), segment_lag AS (
                    SELECT
                        UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                        CAST(begin_date AS DATE) AS begin_date,
                        TRY_CAST(xdy AS DOUBLE) AS xdy,
                        LAG(TRY_CAST(xdy AS DOUBLE)) OVER (
                            PARTITION BY UPPER(TRIM(CAST(htsc_code AS VARCHAR)))
                            ORDER BY CAST(begin_date AS DATE), CAST(end_date AS DATE)
                        ) AS previous_xdy
                    FROM read_parquet(?)
                    WHERE TRY_CAST(xdy AS DOUBLE) > 0
                ), segment_factors AS (
                    SELECT
                        htsc_code,
                        begin_date,
                        EXP(SUM(LN(
                            CASE WHEN previous_xdy IS NULL OR xdy != previous_xdy THEN xdy ELSE 1.0 END
                        )) OVER (
                            PARTITION BY htsc_code
                            ORDER BY begin_date
                            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                        )) AS adj_factor
                    FROM segment_lag
                )
                SELECT
                    d.htsc_code,
                    d.trade_date,
                    d.close * COALESCE(s.adj_factor, 1.0) AS adjusted_close,
                    d.trade_value
                FROM daily d
                ASOF LEFT JOIN segment_factors s
                  ON d.htsc_code = s.htsc_code
                 AND d.trade_date >= s.begin_date
                ORDER BY d.htsc_code, d.trade_date
            """
            frame = conn.execute(
                sql,
                [daily_paths, start_day, end_day, str(ADJ_SEGMENT_PATH)],
            ).df()
        else:
            sql = """
                SELECT
                    UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                    CAST(time AS DATE) AS trade_date,
                    TRY_CAST(close AS DOUBLE) AS adjusted_close,
                    TRY_CAST(value AS DOUBLE) AS trade_value
                FROM read_parquet(?, union_by_name=true)
                WHERE CAST(time AS DATE) BETWEEN ? AND ?
                  AND (UPPER(TRIM(CAST(htsc_code AS VARCHAR))) LIKE '%.SH'
                       OR UPPER(TRIM(CAST(htsc_code AS VARCHAR))) LIKE '%.SZ')
                  AND TRY_CAST(close AS DOUBLE) > 0
                ORDER BY htsc_code, trade_date
            """
            frame = conn.execute(sql, [daily_paths, start_day, end_day]).df()
    except Exception as exc:  # noqa: BLE001
        raise MarketDataError(f"读取市场研究数据失败: {exc}") from exc
    finally:
        conn.close()

    if frame.empty:
        raise MarketDataNotFoundError("查询区间没有可用的沪深 A 股日线")

    return frame, daily_paths


def _market_mask(codes: pd.Series, market_id: str) -> pd.Series:
    if market_id == "sh":
        return codes.str.endswith(".SH")
    if market_id == "sz":
        return codes.str.endswith(".SZ")
    if market_id == "star":
        return codes.str.match(r"^68[89]\d{3}\.SH$")
    return codes.str.endswith((".SH", ".SZ"))


def _safe_number(value: Any, digits: int = 6) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return round(parsed, digits) if math.isfinite(parsed) else None


def _build_market_points(frame: pd.DataFrame, market_id: str, from_day: date, points: int) -> list[dict[str, Any]]:
    market = frame.loc[_market_mask(frame["htsc_code"], market_id)].copy()
    from_timestamp = pd.Timestamp(from_day)
    market = market.loc[
        (market["trade_date"] >= from_timestamp)
        & np.isfinite(market["trade_value"])
        & (market["trade_value"] > 0)
    ]
    if market.empty:
        return []
    market.sort_values(["trade_date", "trade_value", "htsc_code"], ascending=[True, False, True], inplace=True)
    groups = market.groupby("trade_date", sort=True)
    market["rank"] = groups.cumcount() + 1
    market["stock_count"] = groups["htsc_code"].transform("size")
    market["top_count"] = np.ceil(market["stock_count"] * TOP_FRACTION).astype(np.int64)
    market["is_top"] = market["rank"] <= market["top_count"]
    market["top_trade_value"] = market["trade_value"].where(market["is_top"], 0.0)

    summary = groups.agg(
        stock_count=("stock_count", "first"),
        top_count=("top_count", "first"),
        total_trade_value=("trade_value", "sum"),
        top_trade_value=("top_trade_value", "sum"),
        all_rsi=("rsi14", "mean"),
        rsi_count=("rsi14", "count"),
    )
    top_summary = market.loc[market["is_top"]].groupby("trade_date", sort=True).agg(
        top_rsi=("rsi14", "mean"),
        top_rsi_count=("rsi14", "count"),
    )
    summary = summary.join(top_summary, how="left")
    summary["concentration"] = summary["top_trade_value"] / summary["total_trade_value"]
    summary["rsi_ratio"] = summary["top_rsi"] / summary["all_rsi"]
    summary = summary.tail(points)

    result: list[dict[str, Any]] = []
    for trade_day, row in summary.iterrows():
        timestamp = int(datetime.combine(pd.Timestamp(trade_day).date(), datetime.min.time()).timestamp())
        result.append(
            {
                "time": timestamp,
                "date": pd.Timestamp(trade_day).strftime("%Y-%m-%d"),
                "concentration": _safe_number(row["concentration"] * 100.0),
                "rsi_ratio": _safe_number(row["rsi_ratio"]),
                "stock_count": int(row["stock_count"]),
                "top_count": int(row["top_count"]),
                "rsi_count": int(row["rsi_count"]),
                "top_rsi_count": int(row["top_rsi_count"] if pd.notna(row["top_rsi_count"]) else 0),
                "total_trade_value": _safe_number(row["total_trade_value"], 2),
            }
        )
    return result


@lru_cache(maxsize=12)
def _query_cached(
    from_iso: str,
    to_iso: str,
    points: int,
    signature: tuple[tuple[str, int, int], ...],
) -> dict[str, Any]:
    del signature
    from_day = date.fromisoformat(from_iso)
    to_day = date.fromisoformat(to_iso)
    warmup_day = from_day - timedelta(days=RSI_WARMUP_CALENDAR_DAYS)
    frame, _ = _load_market_frame(warmup_day, to_day)
    frame["rsi14"] = _calculate_rsi(frame)
    markets = {
        market_id: {
            "label": label,
            "points": _build_market_points(frame, market_id, from_day, points),
        }
        for market_id, label in MARKET_LABELS.items()
    }
    return {
        "markets": markets,
        "meta": {
            "from": from_iso,
            "to": to_iso,
            "points": points,
            "top_fraction": TOP_FRACTION,
            "rsi_period": RSI_PERIOD,
            "rsi_warmup_calendar_days": RSI_WARMUP_CALENDAR_DAYS,
            "all_a_includes_bj": False,
            "server_time": int(time.time()),
        },
    }


def clear_market_research_cache() -> None:
    _query_cached.cache_clear()


def query_market_research_concentration(
    from_ts: Any = None,
    to_ts: Any = None,
    points: Any = None,
    refresh: bool = False,
) -> dict[str, Any]:
    now = datetime.now()
    end_dt = _parse_timestamp(to_ts, "to", now)
    start_dt = _parse_timestamp(from_ts, "from", end_dt - timedelta(days=110))
    point_limit = _parse_points(points)
    from_day = start_dt.date()
    to_day = end_dt.date()
    if from_day > to_day:
        raise MarketDataValidationError("from 不能晚于 to")
    if (to_day - from_day).days > 3650:
        raise MarketDataValidationError("查询区间不能超过 10 年")
    warmup_day = from_day - timedelta(days=RSI_WARMUP_CALENDAR_DAYS)
    source_paths = _partition_files(DAILY_BASE_PATH, warmup_day, to_day)
    if not source_paths:
        raise MarketDataNotFoundError(f"市场研究日线分区不存在: {DAILY_BASE_PATH}")
    if refresh:
        clear_market_research_cache()
    signature = _source_signature(source_paths)
    with _COMPUTE_LOCK:
        return _query_cached(from_day.isoformat(), to_day.isoformat(), point_limit, signature)
