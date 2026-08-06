"""Read-only query DTOs for the style monitor UI."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .config import MODEL_DEFINITIONS


class StyleMonitorValidationError(ValueError):
    pass


def _json_date(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _version(conn, model_id: str) -> str | None:
    row = conn.execute("SELECT model_version FROM model_definition WHERE model_id=? ORDER BY created_at DESC LIMIT 1", [model_id]).fetchone()
    return str(row[0]) if row else None


def query_summary(conn) -> dict[str, Any]:
    models = []
    for definition in MODEL_DEFINITIONS:
        version = _version(conn, definition.model_id)
        if not version:
            models.append({"model_id": definition.model_id, "model_version": None, "title": definition.title, "factor_name": definition.factor_name, "frequency": definition.rebalance_frequency, "latest_date": None, "last_rebalance_date": None, "high_nav": None, "low_nav": None, "relative_nav": None, "holding_count_high": 0, "holding_count_low": 0, "status": "empty", "status_message": "尚未运行"})
            continue
        rows = conn.execute("SELECT leg,max(trade_date),arg_max(nav,trade_date) FROM nav_daily WHERE model_version=? GROUP BY leg", [version]).fetchall()
        by_leg = {str(row[0]): row for row in rows}
        last_rebalance = conn.execute("SELECT last_rebalance_date FROM run_state WHERE model_version=?", [version]).fetchone()
        counts = {leg: int(conn.execute("SELECT count(*) FROM position_daily WHERE model_version=? AND leg=? AND trade_date=(SELECT max(trade_date) FROM position_daily WHERE model_version=? AND leg=?)", [version, leg, version, leg]).fetchone()[0]) for leg in ("high", "low")}
        high = by_leg.get("high")
        low = by_leg.get("low")
        models.append({"model_id": definition.model_id, "model_version": version, "title": definition.title, "factor_name": definition.factor_name, "frequency": definition.rebalance_frequency, "latest_date": _json_date(max([row[1] for row in by_leg.values()] or [None])), "last_rebalance_date": _json_date(last_rebalance[0] if last_rebalance else None), "high_nav": float(high[2]) if high else None, "low_nav": float(low[2]) if low else None, "relative_nav": float(high[2]) / float(low[2]) * 100 if high and low and low[2] else None, "holding_count_high": counts["high"], "holding_count_low": counts["low"], "status": "ok", "status_message": ""})
    rankings = {}
    for horizon, days in (("1d", 1), ("5d", 5), ("20d", 20)):
        values = []
        for item in models:
            version = item["model_version"]
            if not version or not item["latest_date"]:
                values.append({"model_id": item["model_id"], "value": None})
                continue
            relative_rows = conn.execute("""
                SELECT h.trade_date, h.nav / l.nav * 100 AS relative_nav
                FROM nav_daily h JOIN nav_daily l
                  ON h.model_version=l.model_version AND h.trade_date=l.trade_date
                WHERE h.model_version=? AND h.leg='high' AND l.leg='low'
                ORDER BY h.trade_date DESC LIMIT ?
            """, [version, days + 1]).fetchall()
            latest = relative_rows[0][1] if relative_rows else None
            prior = relative_rows[days][1] if len(relative_rows) > days else None
            values.append({"model_id": item["model_id"], "value": (float(latest) / float(prior) - 1 if latest is not None and prior else None)})
        rankings[horizon] = sorted(values, key=lambda row: (row["value"] is None, -(row["value"] or 0)))
    return {"as_of": max((item["latest_date"] for item in models if item["latest_date"]), default=None), "models": models, "rankings": rankings, "latest_update": None}


def query_curves(conn, model_id: str, range_key: str) -> dict[str, Any]:
    if range_key not in {"20d", "60d", "ytd", "all"}:
        raise StyleMonitorValidationError(f"不支持的曲线范围: {range_key}")
    version = _version(conn, model_id)
    if not version:
        raise StyleMonitorValidationError(f"未知模型: {model_id}")
    rows = conn.execute("SELECT trade_date,leg,nav FROM nav_daily WHERE model_version=? ORDER BY trade_date,leg", [version]).fetchall()
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
    if not high or not low:
        return {"model_id": model_id, "range": range_key, "series": {"high": [], "low": [], "relative": []}}
    high_base, low_base = high[0][1], low[0][1]
    low_by_date = dict(low)
    high_series = [{"time": _json_date(day), "value": value / high_base * 100} for day, value in high if day in low_by_date]
    low_series = [{"time": _json_date(day), "value": low_by_date[day] / low_base * 100} for day, _ in high if day in low_by_date]
    relative = [{"time": point["time"], "value": point["value"] / low_series[index]["value"] * 100} for index, point in enumerate(high_series)]
    return {"model_id": model_id, "range": range_key, "series": {"high": high_series, "low": low_series, "relative": relative}}


def query_positions(conn, model_id: str, leg: str, trade_date: str | None) -> dict[str, Any]:
    if leg not in {"high", "low"}:
        raise StyleMonitorValidationError("leg 必须是 high 或 low")
    version = _version(conn, model_id)
    if not version:
        raise StyleMonitorValidationError(f"未知模型: {model_id}")
    selected = trade_date or conn.execute("SELECT max(trade_date) FROM position_daily WHERE model_version=? AND leg=?", [version, leg]).fetchone()[0]
    rows = conn.execute("SELECT htsc_code,score,rank,target_weight,actual_weight,shares,price,market_value,stale_price FROM position_daily WHERE model_version=? AND leg=? AND trade_date=? ORDER BY actual_weight DESC", [version, leg, selected]).fetchall()
    keys = ["htsc_code", "score", "rank", "target_weight", "actual_weight", "shares", "price", "market_value", "stale_price"]
    return {"model_id": model_id, "leg": leg, "date": _json_date(selected), "items": [dict(zip(keys, row)) for row in rows]}


def query_trades(conn, model_id: str, leg: str, limit: int) -> dict[str, Any]:
    if leg not in {"high", "low"}:
        raise StyleMonitorValidationError("leg 必须是 high 或 low")
    if not 1 <= int(limit) <= 1000:
        raise StyleMonitorValidationError("limit 必须在 1 到 1000 之间")
    version = _version(conn, model_id)
    if not version:
        raise StyleMonitorValidationError(f"未知模型: {model_id}")
    rows = conn.execute("SELECT trade_date,htsc_code,side,shares,price,trade_value,commission FROM trade_log WHERE model_version=? AND leg=? ORDER BY trade_date DESC LIMIT ?", [version, leg, int(limit)]).fetchall()
    keys = ["trade_date", "htsc_code", "side", "shares", "price", "trade_value", "commission"]
    return {"model_id": model_id, "leg": leg, "items": [{**dict(zip(keys, row)), "trade_date": _json_date(row[0])} for row in rows]}
