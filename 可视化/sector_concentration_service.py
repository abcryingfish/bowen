from __future__ import annotations

import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import duckdb

from market_data_service import MarketDataError, MarketDataNotFoundError, MarketDataValidationError


DAILY_BASE_PATH = Path(os.environ.get("SECTOR_CONCENTRATION_DAILY_PATH", r"D:\database\qmt_turnover_data"))
SNAPSHOT_BASE_PATH = Path(
    os.environ.get(
        "SECTOR_CONCENTRATION_SNAPSHOT_PATH",
        r"D:\database\sector_information\constituent_snapshots_eligible",
    )
)
MAX_POINTS = 2000


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


def _parse_limit(value: Any) -> int:
    if value in (None, ""):
        return 400
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise MarketDataValidationError("limit 必须是整数") from exc
    if parsed < 1 or parsed > MAX_POINTS:
        raise MarketDataValidationError(f"limit 必须在 1 到 {MAX_POINTS} 之间")
    return parsed


def _iter_months(start_day: date, end_day: date):
    cursor = date(start_day.year, start_day.month, 1)
    final = date(end_day.year, end_day.month, 1)
    while cursor <= final:
        yield cursor.year, cursor.month
        cursor = date(
            cursor.year + (cursor.month == 12),
            1 if cursor.month == 12 else cursor.month + 1,
            1,
        )


def _daily_paths(start_day: date, end_day: date) -> list[str]:
    paths = []
    for year, month in _iter_months(start_day, end_day):
        path = DAILY_BASE_PATH / f"year={year:04d}" / f"month={month:02d}" / "merged.parquet"
        if path.is_file():
            paths.append(str(path))
    return paths


def _latest_snapshot_paths() -> tuple[date | None, list[str]]:
    dated_paths: list[tuple[date, str]] = []
    for path in sorted(SNAPSHOT_BASE_PATH.glob("analysis_date=*/part-*.parquet")):
        try:
            snapshot_day = date.fromisoformat(path.parent.name.split("=", 1)[1])
        except (IndexError, ValueError):
            continue
        dated_paths.append((snapshot_day, str(path)))
    if not dated_paths:
        return None, []
    latest_day = max(item[0] for item in dated_paths)
    return latest_day, [path for snapshot_day, path in dated_paths if snapshot_day == latest_day]


def _safe_number(value: Any, digits: int = 6) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return round(parsed, digits) if math.isfinite(parsed) else None


@lru_cache(maxsize=256)
def _query_cached(
    prefix: str,
    from_iso: str,
    to_iso: str,
    limit: int,
    snapshot_iso: str,
    snapshot_signature: tuple[tuple[str, int, int], ...],
    daily_signature: tuple[tuple[str, int, int], ...],
) -> dict[str, Any]:
    del daily_signature
    from_day = date.fromisoformat(from_iso)
    to_day = date.fromisoformat(to_iso)
    snapshot_day = date.fromisoformat(snapshot_iso)
    snapshot_paths = [item[0] for item in snapshot_signature]
    daily_paths = _daily_paths(from_day, to_day)
    if not snapshot_paths:
        return {"points": [], "meta": {"prefix": prefix, "sector_count": 0, "point_count": 0, "snapshot_date": None}}
    if not daily_paths:
        raise MarketDataNotFoundError(f"板块资金占比日线分区不存在: {DAILY_BASE_PATH}")

    conn = duckdb.connect(database=":memory:")
    try:
        snapshot_expr = "[" + ",".join("'" + path.replace("'", "''") + "'" for path in snapshot_paths) + "]"
        daily_expr = "[" + ",".join("'" + path.replace("'", "''") + "'" for path in daily_paths) + "]"
        from_literal = from_day.isoformat()
        to_literal = to_day.isoformat()
        sql = f"""
            WITH members AS (
                SELECT DISTINCT
                    UPPER(TRIM(CAST(sector_code AS VARCHAR))) AS sector_code,
                    UPPER(TRIM(CAST(stock_code AS VARCHAR))) AS htsc_code
                FROM read_parquet({snapshot_expr}, hive_partitioning=true, union_by_name=true)
                WHERE LEFT(UPPER(TRIM(CAST(sector_code AS VARCHAR))), 3) = '{prefix}'
                  AND COALESCE(TRY_CAST(eligible AS BOOLEAN), TRUE)
                  AND stock_code IS NOT NULL
            ), daily_raw AS (
                SELECT
                    UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                    CAST(time AS DATE) AS trade_date,
                    TRY_CAST(value AS DOUBLE) AS trade_value
                FROM read_parquet({daily_expr}, union_by_name=true)
                WHERE CAST(time AS DATE) BETWEEN DATE '{from_literal}' AND DATE '{to_literal}'
                  AND REGEXP_MATCHES(UPPER(TRIM(CAST(htsc_code AS VARCHAR))), '^[0-9]{{6}}\\.(SH|SZ|BJ)$')
                  AND TRY_CAST(value AS DOUBLE) > 0
            ), daily AS (
                SELECT htsc_code, trade_date, MAX(trade_value) AS trade_value
                FROM daily_raw
                GROUP BY htsc_code, trade_date
            ), market_totals AS (
                SELECT d.trade_date,
                       COUNT(*) AS market_stock_count,
                       SUM(d.trade_value) AS market_trade_value
                FROM daily d
                GROUP BY d.trade_date
            ), sector_totals AS (
                SELECT d.trade_date, m.sector_code,
                       COUNT(*) AS stock_count,
                       SUM(d.trade_value) AS sector_trade_value
                FROM members m
                INNER JOIN daily d
                  ON d.htsc_code = m.htsc_code
                GROUP BY d.trade_date, m.sector_code
            )
            SELECT s.trade_date, s.sector_code, s.stock_count, m.market_stock_count,
                   s.sector_trade_value, m.market_trade_value
            FROM sector_totals s
            INNER JOIN market_totals m ON m.trade_date = s.trade_date
            WHERE m.market_trade_value > 0
            ORDER BY s.sector_code, s.trade_date
        """
        rows = conn.execute(sql).fetchall()
    except Exception as exc:  # noqa: BLE001
        raise MarketDataError(f"读取板块资金占比失败: {exc}") from exc
    finally:
        conn.close()

    metric_type = "market_share" if prefix in {"881", "882"} else "market_coverage"
    grouped: dict[str, list[dict[str, Any]]] = {}
    points = []
    for trade_day, sector_code, stock_count, market_stock_count, sector_value, market_value in rows:
        fund_share = float(sector_value) / float(market_value) * 100.0 if market_value else None
        timestamp = int(datetime.combine(trade_day, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        grouped.setdefault(sector_code, []).append(
            {
                "time": timestamp,
                "date": trade_day.isoformat(),
                "sector_code": sector_code,
                "fund_share_pct": _safe_number(fund_share),
                "stock_count": int(stock_count),
                "market_stock_count": int(market_stock_count),
                "sector_trade_value": _safe_number(sector_value, 2),
                "market_trade_value": _safe_number(market_value, 2),
                "snapshot_date": snapshot_day.isoformat(),
                "metric_type": metric_type,
            }
        )
    for sector_points in grouped.values():
        points.extend(sector_points[-limit:])
    points.sort(key=lambda item: (item["sector_code"], item["time"]))
    return {
        "points": points,
        "meta": {
            "prefix": prefix,
            "metric_type": metric_type,
            "overlapping_memberships": prefix in {"885", "886"},
            "component_mode": "latest_snapshot_full_history",
            "snapshot_date": snapshot_day.isoformat(),
            "sector_count": len(grouped),
            "point_count": len(points),
            "data_range": [min(item["date"] for item in points), max(item["date"] for item in points)] if points else [],
            "server_time": int(time.time()),
        },
    }


def clear_sector_fund_share_cache() -> None:
    _query_cached.cache_clear()


def query_sector_fund_shares(
    prefix: Any,
    from_ts: Any = None,
    to_ts: Any = None,
    limit: Any = None,
    refresh: bool = False,
) -> dict[str, Any]:
    normalized_prefix = str(prefix or "").strip()
    if normalized_prefix not in {"881", "882", "885", "886"}:
        raise MarketDataValidationError("prefix 必须是 881、882、885 或 886")
    now = datetime.now()
    end_dt = _parse_timestamp(to_ts, "to", now)
    start_dt = _parse_timestamp(from_ts, "from", end_dt - timedelta(days=110))
    if start_dt.date() > end_dt.date():
        raise MarketDataValidationError("from 不能晚于 to")
    if (end_dt.date() - start_dt.date()).days > 3650:
        raise MarketDataValidationError("查询区间不能超过 10 年")
    point_limit = _parse_limit(limit)
    snapshot_day, snapshot_paths = _latest_snapshot_paths()
    if snapshot_day is None or not snapshot_paths:
        return {"points": [], "meta": {"prefix": normalized_prefix, "sector_count": 0, "point_count": 0, "snapshot_date": None}}
    daily_paths = _daily_paths(start_dt.date(), end_dt.date())
    snapshot_signature = tuple((path, Path(path).stat().st_mtime_ns, Path(path).stat().st_size) for path in snapshot_paths)
    daily_signature = tuple((path, Path(path).stat().st_mtime_ns, Path(path).stat().st_size) for path in daily_paths)
    if refresh:
        clear_sector_fund_share_cache()
    return _query_cached(
        normalized_prefix,
        start_dt.date().isoformat(),
        end_dt.date().isoformat(),
        point_limit,
        snapshot_day.isoformat(),
        snapshot_signature,
        daily_signature,
    )
