"""Read-only query DTOs for the style monitor UI."""

from __future__ import annotations

from datetime import date, datetime, time as datetime_time, timedelta, timezone
from functools import lru_cache
from pathlib import Path
import re
import sys
from typing import Any

import pandas as pd

from .config import MODEL_DEFINITIONS


class StyleMonitorValidationError(ValueError):
    pass


BENCHMARK_BASE_DIR = Path(r"D:\database\index_data_daily")
_BENCHMARK_CODES = (("000300.SH", "沪深300"), ("000001.SH", "上证指数"), ("399001.SZ", "深证成指"))
_BENCHMARK_NAME_BY_CODE = dict(_BENCHMARK_CODES)
_BENCHMARK_CODE_PATTERN = r"^\d{6}\.[A-Z]{2,4}$"


def _json_date(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _month_starts(start_date: date, end_date: date) -> list[date]:
    cursor = date(start_date.year, start_date.month, 1)
    finish = date(end_date.year, end_date.month, 1)
    result: list[date] = []
    while cursor <= finish:
        result.append(cursor)
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
    return result


@lru_cache(maxsize=16)
def _load_benchmark_candidates(base_dir: str, start_date: date, end_date: date) -> dict[str, pd.DataFrame]:
    root = Path(base_dir)
    paths = [
        root / f"year={month.year}" / f"month={month.month:02d}" / "merged.parquet"
        for month in _month_starts(start_date, end_date)
        if (root / f"year={month.year}" / f"month={month.month:02d}" / "merged.parquet").is_file()
    ]
    if not paths:
        return {}
    frames = []
    for path in paths:
        try:
            frames.append(pd.read_parquet(path, columns=["htsc_code", "time", "close"]))
        except Exception:
            continue
    if not frames:
        return {}
    frame = pd.concat(frames, ignore_index=True)
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.date
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame[frame["time"].between(start_date, end_date) & frame["close"].gt(0)].dropna(subset=["time", "close"])
    return {
        code: part.drop_duplicates("time", keep="last").sort_values("time")
        for code, part in frame.groupby("htsc_code", sort=False)
    }


def _normalize_benchmark_code(code: str | None) -> str | None:
    normalized = str(code or "").strip().upper()
    if not normalized:
        return None
    if normalized.endswith(".YKRS") or not re.match(_BENCHMARK_CODE_PATTERN, normalized):
        raise StyleMonitorValidationError("基准代码必须是完整市场代码，例如 600000.SH")
    return normalized


def _query_market_bars_for_benchmark(code: str, start_date: date, end_date: date) -> list[dict[str, Any]]:
    project_root = Path(__file__).resolve().parents[3]
    visual_dir = project_root / "可视化"
    if str(visual_dir) not in sys.path:
        sys.path.append(str(visual_dir))
    try:
        from market_data_service import is_index_market_code, query_market_bars
    except ImportError:
        from 可视化.market_data_service import is_index_market_code, query_market_bars

    start_ts = int(datetime.combine(start_date, datetime_time.min, tzinfo=timezone.utc).timestamp())
    end_ts = int(datetime.combine(end_date, datetime_time.max, tzinfo=timezone.utc).timestamp())
    result = query_market_bars(
        code=code,
        interval="1day",
        from_ts=start_ts,
        to_ts=end_ts,
        limit=50000,
        adjust="none" if is_index_market_code(code) else "backward_ratio",
    )
    bars = result.get("bars") if isinstance(result, dict) else None
    return bars if isinstance(bars, list) else []


def _load_custom_benchmark_bars(code: str, start_date: date, end_date: date) -> list[dict[str, Any]]:
    """读取自定义股票/指数基准；股票固定使用等比后复权收盘价。"""
    raw_bars: list[dict[str, Any]] = []
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=3650), end_date)
        raw_bars.extend(_query_market_bars_for_benchmark(code, cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)

    bars_by_day: dict[date, float] = {}
    for bar in raw_bars:
        raw_time = bar.get("time")
        if isinstance(raw_time, datetime):
            day = raw_time.date()
        elif isinstance(raw_time, date):
            day = raw_time
        else:
            try:
                day = datetime.fromtimestamp(float(raw_time), tz=timezone.utc).date()
            except (TypeError, ValueError, OverflowError):
                continue
        try:
            close = float(bar["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if start_date <= day <= end_date and close > 0:
            bars_by_day[day] = close

    return [{"time": day, "close": bars_by_day[day]} for day in sorted(bars_by_day)]


def _benchmark_series(start_date: date, end_date: date, benchmark_code: str | None = None) -> dict[str, Any]:
    requested_code = _normalize_benchmark_code(benchmark_code)
    candidates = _load_benchmark_candidates(str(BENCHMARK_BASE_DIR), start_date, end_date)
    if requested_code:
        frame = candidates.get(requested_code)
        if frame is not None and not frame.empty:
            base = float(frame.iloc[0]["close"])
            return {
                "name": _BENCHMARK_NAME_BY_CODE.get(requested_code, requested_code),
                "code": requested_code,
                "series": [
                    {"time": _json_date(row.time), "value": float(row.close) / base * 100.0}
                    for row in frame.itertuples(index=False)
                ],
            }
        bars = _load_custom_benchmark_bars(requested_code, start_date, end_date)
        if not bars:
            raise StyleMonitorValidationError(f"基准代码无可用数据: {requested_code}")
        base = float(bars[0]["close"])
        if base <= 0:
            raise StyleMonitorValidationError(f"基准代码无可用收盘价: {requested_code}")
        return {
            "name": _BENCHMARK_NAME_BY_CODE.get(requested_code, requested_code),
            "code": requested_code,
            "series": [
                {"time": _json_date(row["time"]), "value": float(row["close"]) / base * 100.0}
                for row in bars
            ],
        }
    for code, name in _BENCHMARK_CODES:
        frame = candidates.get(code)
        if frame is None or frame.empty:
            continue
        base = float(frame.iloc[0]["close"])
        if base <= 0:
            continue
        return {
            "name": name,
            "code": code,
            "series": [
                {"time": _json_date(row.time), "value": float(row.close) / base * 100.0}
                for row in frame.itertuples(index=False)
            ],
        }
    return {"name": None, "code": None, "series": []}


def _version(conn, model_id: str) -> str | None:
    row = conn.execute("SELECT model_version FROM model_definition WHERE model_id=? ORDER BY created_at DESC LIMIT 1", [model_id]).fetchone()
    return str(row[0]) if row else None


def _has_index_data(conn, model_version: str) -> bool:
    try:
        return bool(conn.execute("SELECT count(*) FROM index_daily WHERE model_version=?", [model_version]).fetchone()[0])
    except Exception:
        return False


def query_summary(conn) -> dict[str, Any]:
    models = []
    for definition in MODEL_DEFINITIONS:
        version = _version(conn, definition.model_id)
        if not version:
            models.append({"model_id": definition.model_id, "model_version": None, "title": definition.title, "factor_name": definition.factor_name, "frequency": definition.rebalance_frequency, "latest_date": None, "last_rebalance_date": None, "high_nav": None, "low_nav": None, "relative_nav": None, "holding_count_high": 0, "holding_count_low": 0, "valid_price_coverage_high": None, "valid_price_coverage_low": None, "status": "empty", "status_message": "尚未运行"})
            continue
        if not _has_index_data(conn, version):
            models.append({"model_id": definition.model_id, "model_version": version, "title": definition.title, "factor_name": definition.factor_name, "frequency": definition.rebalance_frequency, "latest_date": None, "last_rebalance_date": None, "high_nav": None, "low_nav": None, "relative_nav": None, "holding_count_high": 0, "holding_count_low": 0, "valid_price_coverage_high": None, "valid_price_coverage_low": None, "status": "empty", "status_message": "理论等权指数账本尚未生成"})
            continue
        rows = conn.execute(
            "SELECT leg,max(trade_date),arg_max(index_value,trade_date),"
            "arg_max(valid_price_coverage,trade_date) "
            "FROM index_daily WHERE model_version=? GROUP BY leg",
            [version],
        ).fetchall()
        by_leg = {str(row[0]): row for row in rows}
        last_rebalance = conn.execute("SELECT last_rebalance_date FROM run_state WHERE model_version=?", [version]).fetchone()
        counts = {
            leg: int(conn.execute(
                "SELECT count(*) FROM index_weight_daily "
                "WHERE model_version=? AND leg=? AND trade_date=(SELECT max(trade_date) FROM index_weight_daily WHERE model_version=? AND leg=?) "
                "AND effective_weight>0",
                [version, leg, version, leg],
            ).fetchone()[0])
            for leg in ("high", "low")
        }
        high = by_leg.get("high")
        low = by_leg.get("low")
        models.append({"model_id": definition.model_id, "model_version": version, "title": definition.title, "factor_name": definition.factor_name, "frequency": definition.rebalance_frequency, "latest_date": _json_date(max([row[1] for row in by_leg.values()] or [None])), "last_rebalance_date": _json_date(last_rebalance[0] if last_rebalance else None), "high_nav": float(high[2]) if high else None, "low_nav": float(low[2]) if low else None, "relative_nav": float(high[2]) / float(low[2]) * 100 if high and low and low[2] else None, "holding_count_high": counts["high"], "holding_count_low": counts["low"], "valid_price_coverage_high": float(high[3]) if high and high[3] is not None else None, "valid_price_coverage_low": float(low[3]) if low and low[3] is not None else None, "status": "ok", "status_message": ""})
    rankings = {}
    for horizon, days in (("1d", 1), ("5d", 5), ("20d", 20)):
        values = []
        for item in models:
            version = item["model_version"]
            if not version or not item["latest_date"]:
                values.append({"model_id": item["model_id"], "value": None})
                continue
            relative_rows = conn.execute("""
                SELECT h.trade_date, h.index_value / l.index_value * 100 AS relative_nav
                FROM index_daily h JOIN index_daily l
                  ON h.model_version=l.model_version AND h.trade_date=l.trade_date
                WHERE h.model_version=? AND h.leg='high' AND l.leg='low'
                ORDER BY h.trade_date DESC LIMIT ?
            """, [version, days + 1]).fetchall()
            latest = relative_rows[0][1] if relative_rows else None
            prior = relative_rows[days][1] if len(relative_rows) > days else None
            values.append({"model_id": item["model_id"], "value": (float(latest) / float(prior) - 1 if latest is not None and prior else None)})
        rankings[horizon] = sorted(values, key=lambda row: (row["value"] is None, -(row["value"] or 0)))
    update_row = conn.execute(
        "SELECT run_id,status,requested_at,started_at,finished_at,through_date,total_steps,completed_steps,message,error "
        "FROM update_run ORDER BY requested_at DESC LIMIT 1"
    ).fetchone()
    latest_update = None
    if update_row:
        latest_update = {
            "run_id": str(update_row[0]),
            "status": str(update_row[1]),
            "requested_at": _json_date(update_row[2]),
            "started_at": _json_date(update_row[3]),
            "finished_at": _json_date(update_row[4]),
            "through_date": _json_date(update_row[5]),
            "total_steps": int(update_row[6]),
            "completed_steps": int(update_row[7]),
            "progress": int(update_row[7] / update_row[6] * 100) if update_row[6] else 0,
            "message": str(update_row[8]),
            "error": str(update_row[9]),
        }
    return {"as_of": max((item["latest_date"] for item in models if item["latest_date"]), default=None), "models": models, "rankings": rankings, "latest_update": latest_update}


def query_curves(conn, model_id: str, range_key: str, start_date: str | None = None, end_date: str | None = None, benchmark_code: str | None = None) -> dict[str, Any]:
    if range_key not in {"20d", "60d", "ytd", "custom", "all"}:
        raise StyleMonitorValidationError(f"不支持的曲线范围: {range_key}")
    normalized_benchmark_code = _normalize_benchmark_code(benchmark_code)
    selected_start = selected_end = None
    if range_key == "custom":
        if not start_date or not end_date:
            raise StyleMonitorValidationError("自定义区间必须同时提供开始日期和结束日期")
        try:
            selected_start = date.fromisoformat(str(start_date))
            selected_end = date.fromisoformat(str(end_date))
        except ValueError as exc:
            raise StyleMonitorValidationError("日期格式必须为 YYYY-MM-DD") from exc
        if selected_start > selected_end:
            raise StyleMonitorValidationError("开始日期不能晚于结束日期")
    version = _version(conn, model_id)
    if not version:
        raise StyleMonitorValidationError(f"未知模型: {model_id}")
    if not _has_index_data(conn, version):
        return {
            "model_id": model_id,
            "range": range_key,
            "series": {"high": [], "low": [], "relative": []},
            "benchmark": {"name": _BENCHMARK_NAME_BY_CODE.get(normalized_benchmark_code, normalized_benchmark_code), "code": normalized_benchmark_code, "series": []},
        }
    rows = conn.execute(
        "SELECT trade_date,leg,index_value FROM index_daily WHERE model_version=? ORDER BY trade_date,leg",
        [version],
    ).fetchall()
    high = [(row[0], float(row[2])) for row in rows if row[1] == "high"]
    low = [(row[0], float(row[2])) for row in rows if row[1] == "low"]
    if range_key == "20d":
        high, low = high[-20:], low[-20:]
    elif range_key == "60d":
        high, low = high[-60:], low[-60:]
    elif range_key == "ytd" and high:
        year = high[-1][0].year
        high = [item for item in high if item[0].year == year]
        low = [item for item in low if item[0].year == year]
    elif range_key == "custom":
        high = [item for item in high if selected_start <= item[0] <= selected_end]
        low = [item for item in low if selected_start <= item[0] <= selected_end]
    if not high or not low:
        return {
            "model_id": model_id,
            "range": range_key,
            "series": {"high": [], "low": [], "relative": []},
            "benchmark": {"name": _BENCHMARK_NAME_BY_CODE.get(normalized_benchmark_code, normalized_benchmark_code), "code": normalized_benchmark_code, "series": []},
        }
    low_by_date = {day: gross for day, gross in low}
    common_high = [(day, gross) for day, gross in high if day in low_by_date]
    if not common_high:
        return {
            "model_id": model_id,
            "range": range_key,
            "series": {"high": [], "low": [], "relative": []},
            "benchmark": {"name": _BENCHMARK_NAME_BY_CODE.get(normalized_benchmark_code, normalized_benchmark_code), "code": normalized_benchmark_code, "series": []},
        }
    high_base = common_high[0][1]
    low_base = low_by_date[common_high[0][0]]
    high_series = [{"time": _json_date(day), "value": gross / high_base * 100} for day, gross in common_high]
    low_series = [{"time": _json_date(day), "value": low_by_date[day] / low_base * 100} for day, _ in common_high]
    relative = [{"time": point["time"], "value": point["value"] / low_series[index]["value"] * 100} for index, point in enumerate(high_series)]
    selected_start = date.fromisoformat(str(high_series[0]["time"])[:10])
    selected_end = date.fromisoformat(str(high_series[-1]["time"])[:10])
    return {
        "model_id": model_id,
        "range": range_key,
        "series": {
            "high": high_series,
            "low": low_series,
            "relative": relative,
        },
        "benchmark": _benchmark_series(selected_start, selected_end, normalized_benchmark_code),
    }


def query_positions(conn, model_id: str, leg: str, trade_date: str | None) -> dict[str, Any]:
    if leg not in {"high", "low"}:
        raise StyleMonitorValidationError("leg 必须是 high 或 low")
    version = _version(conn, model_id)
    if not version:
        raise StyleMonitorValidationError(f"未知模型: {model_id}")
    if trade_date:
        try:
            selected = date.fromisoformat(str(trade_date))
        except ValueError as exc:
            raise StyleMonitorValidationError("日期格式必须为 YYYY-MM-DD") from exc
    else:
        selected = None
    if not _has_index_data(conn, version):
        return {"model_id": model_id, "leg": leg, "date": _json_date(selected), "items": [], "message": "理论等权指数账本尚未生成"}
    if selected is None:
        selected = conn.execute("SELECT max(trade_date) FROM index_weight_daily WHERE model_version=? AND leg=?", [version, leg]).fetchone()[0]
    rows = conn.execute("SELECT htsc_code,score,rank,target_weight,effective_weight FROM index_weight_daily WHERE model_version=? AND leg=? AND trade_date=? ORDER BY effective_weight DESC", [version, leg, selected]).fetchall()
    keys = ["htsc_code", "score", "rank", "target_weight", "effective_weight"]
    return {"model_id": model_id, "leg": leg, "date": _json_date(selected), "items": [dict(zip(keys, row)) for row in rows], "message": ""}


def query_trades(conn, model_id: str, leg: str, limit: int) -> dict[str, Any]:
    if leg not in {"high", "low"}:
        raise StyleMonitorValidationError("leg 必须是 high 或 low")
    if not 1 <= int(limit) <= 1000:
        raise StyleMonitorValidationError("limit 必须在 1 到 1000 之间")
    version = _version(conn, model_id)
    if not version:
        raise StyleMonitorValidationError(f"未知模型: {model_id}")
    return {"model_id": model_id, "leg": leg, "items": [], "message": "等权收益指数不模拟现金交易，无现金交易记录"}
