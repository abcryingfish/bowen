from __future__ import annotations

import csv
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

TEMP_TODAY_DATA_DIR = Path(r"D:\database\temp_today_data")
DEFAULT_TIMEZONE = timezone.utc
SQLITE_TIMEOUT_SECONDS = 30.0
SQLITE_BUSY_TIMEOUT_MS = 30000


def today_cache_path(trading_day: str | None = None) -> Path:
    day = trading_day or datetime.now().strftime("%Y-%m-%d")
    return TEMP_TODAY_DATA_DIR / f"market_cache_{day}.sqlite"


def _connect(db_path: str | Path, *, read_only: bool = False) -> sqlite3.Connection:
    path = Path(db_path)
    if read_only:
        uri = f"file:{path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=SQLITE_TIMEOUT_SECONDS)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=SQLITE_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    if not read_only:
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA wal_autocheckpoint = 10000")
    return conn


def ensure_schema(db_path: str | Path) -> None:
    conn = _connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tick_snapshot (
                htsc_code TEXT NOT NULL,
                ts TEXT NOT NULL,
                last_price REAL,
                open REAL,
                high REAL,
                low REAL,
                last_close REAL,
                amount REAL,
                volume REAL,
                pvolume REAL,
                PRIMARY KEY (htsc_code, ts)
            );

            CREATE TABLE IF NOT EXISTS latest_quote (
                htsc_code TEXT PRIMARY KEY,
                ts TEXT NOT NULL,
                last_price REAL,
                open REAL,
                high REAL,
                low REAL,
                last_close REAL,
                amount REAL,
                volume REAL,
                pvolume REAL,
                ask_price TEXT,
                bid_price TEXT,
                ask_vol TEXT,
                bid_vol TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS today_daily_bar (
                htsc_code TEXT PRIMARY KEY,
                trading_day TEXT NOT NULL,
                time INTEGER NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                last_close REAL,
                amount REAL,
                volume REAL,
                pvolume REAL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cache_meta (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            );

            DROP INDEX IF EXISTS idx_tick_snapshot_code_ts;
            DROP INDEX IF EXISTS idx_tick_snapshot_ts;
            DROP INDEX IF EXISTS idx_today_daily_day;
            """
        )
        conn.commit()
    finally:
        conn.close()


def _connect_existing_cache(db_path: str | Path) -> sqlite3.Connection | None:
    if not Path(db_path).exists():
        return None
    try:
        return _connect(db_path, read_only=True)
    except sqlite3.OperationalError:
        return None


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric:
        return None
    return numeric


def _normalize_code(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalize_ts(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("ts is required")
    if len(text) == 14 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    return text


def _ts_to_epoch(ts_text: str) -> int:
    parsed = datetime.strptime(ts_text, "%Y-%m-%d %H:%M:%S")
    return int(parsed.replace(tzinfo=DEFAULT_TIMEZONE).timestamp())


def _day_start_epoch(day_text: str) -> int:
    parsed = datetime.strptime(day_text, "%Y-%m-%d")
    return int(parsed.replace(tzinfo=DEFAULT_TIMEZONE).timestamp())


def _json_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _prepare_tick_payload(row: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
    code = _normalize_code(row.get("htsc_code") or row.get("code"))
    ts_text = _normalize_ts(row.get("ts") or row.get("time") or row.get("timetag"))
    if not code:
        raise ValueError("htsc_code is required")
    payload = {
        "htsc_code": code,
        "ts": ts_text,
        "last_price": _safe_float(row.get("last_price", row.get("lastPrice"))),
        "open": _safe_float(row.get("open")),
        "high": _safe_float(row.get("high")),
        "low": _safe_float(row.get("low")),
        "last_close": _safe_float(row.get("last_close", row.get("lastClose"))),
        "amount": _safe_float(row.get("amount")),
        "volume": _safe_float(row.get("volume")),
        "pvolume": _safe_float(row.get("pvolume")),
    }
    trading_day = ts_text[:10]
    return code, ts_text, trading_day, payload


def _upsert_tick_snapshot_conn(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    updated_at: str,
) -> None:
    code, ts_text, trading_day, payload = _prepare_tick_payload(row)
    conn.execute(
        """
        INSERT INTO tick_snapshot (
            htsc_code, ts, last_price, open, high, low, last_close,
            amount, volume, pvolume
        )
        VALUES (
            :htsc_code, :ts, :last_price, :open, :high, :low, :last_close,
            :amount, :volume, :pvolume
        )
        ON CONFLICT(htsc_code, ts) DO UPDATE SET
            last_price = excluded.last_price,
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            last_close = excluded.last_close,
            amount = excluded.amount,
            volume = excluded.volume,
            pvolume = excluded.pvolume
        """,
        payload,
    )
    conn.execute(
        """
        INSERT INTO latest_quote (
            htsc_code, ts, last_price, open, high, low, last_close,
            amount, volume, pvolume, ask_price, bid_price, ask_vol,
            bid_vol, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(htsc_code) DO UPDATE SET
            ts = excluded.ts,
            last_price = excluded.last_price,
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            last_close = excluded.last_close,
            amount = excluded.amount,
            volume = excluded.volume,
            pvolume = excluded.pvolume,
            ask_price = excluded.ask_price,
            bid_price = excluded.bid_price,
            ask_vol = excluded.ask_vol,
            bid_vol = excluded.bid_vol,
            updated_at = excluded.updated_at
        WHERE excluded.ts >= latest_quote.ts
          AND excluded.last_price IS NOT NULL
          AND excluded.last_price > 0
        """,
        (
            code,
            ts_text,
            payload["last_price"],
            payload["open"],
            payload["high"],
            payload["low"],
            payload["last_close"],
            payload["amount"],
            payload["volume"],
            payload["pvolume"],
            _json_text(row.get("ask_price", row.get("askPrice"))),
            _json_text(row.get("bid_price", row.get("bidPrice"))),
            _json_text(row.get("ask_vol", row.get("askVol"))),
            _json_text(row.get("bid_vol", row.get("bidVol"))),
            updated_at,
        ),
    )


def upsert_tick_snapshot(db_path: str | Path, row: dict[str, Any]) -> None:
    ensure_schema(db_path)
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _connect(db_path)
    try:
        _upsert_tick_snapshot_conn(conn, row, updated_at)
        conn.commit()
    finally:
        conn.close()


def upsert_tick_snapshots(
    db_path: str | Path,
    rows: Iterable[dict[str, Any]],
    *,
    ensure: bool = True,
    update_existing_snapshots: bool = True,
    write_snapshots: bool = True,
    write_latest: bool = True,
    collect_stats: bool = False,
) -> int | tuple[int, dict[str, float]]:
    if ensure:
        ensure_schema(db_path)
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tick_payloads: list[dict[str, Any]] = []
    latest_quote_params: list[tuple[Any, ...]] = []
    for row in rows:
        code, ts_text, _trading_day, payload = _prepare_tick_payload(row)
        tick_payloads.append(payload)
        latest_quote_params.append(
            (
                code,
                ts_text,
                payload["last_price"],
                payload["open"],
                payload["high"],
                payload["low"],
                payload["last_close"],
                payload["amount"],
                payload["volume"],
                payload["pvolume"],
                _json_text(row.get("ask_price", row.get("askPrice"))),
                _json_text(row.get("bid_price", row.get("bidPrice"))),
                _json_text(row.get("ask_vol", row.get("askVol"))),
                _json_text(row.get("bid_vol", row.get("bidVol"))),
                updated_at,
            )
        )
    if not tick_payloads:
        empty_stats = {"snapshot_sec": 0.0, "latest_sec": 0.0, "commit_sec": 0.0}
        return (0, empty_stats) if collect_stats else 0
    conn = _connect(db_path)
    stats = {"snapshot_sec": 0.0, "latest_sec": 0.0, "commit_sec": 0.0}
    try:
        conn.execute("BEGIN")
        if write_snapshots:
            snapshot_start = datetime.now()
            snapshot_conflict_clause = (
                """
                ON CONFLICT(htsc_code, ts) DO UPDATE SET
                    last_price = excluded.last_price,
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    last_close = excluded.last_close,
                    amount = excluded.amount,
                    volume = excluded.volume,
                    pvolume = excluded.pvolume
                """
                if update_existing_snapshots
                else "ON CONFLICT(htsc_code, ts) DO NOTHING"
            )
            conn.executemany(
                f"""
                INSERT INTO tick_snapshot (
                    htsc_code, ts, last_price, open, high, low, last_close,
                    amount, volume, pvolume
                )
                VALUES (
                    :htsc_code, :ts, :last_price, :open, :high, :low, :last_close,
                    :amount, :volume, :pvolume
                )
                {snapshot_conflict_clause}
                """,
                tick_payloads,
            )
            stats["snapshot_sec"] = (datetime.now() - snapshot_start).total_seconds()
        if write_latest:
            latest_start = datetime.now()
            conn.executemany(
                """
                INSERT INTO latest_quote (
                    htsc_code, ts, last_price, open, high, low, last_close,
                    amount, volume, pvolume, ask_price, bid_price, ask_vol,
                    bid_vol, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(htsc_code) DO UPDATE SET
                    ts = excluded.ts,
                    last_price = excluded.last_price,
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    last_close = excluded.last_close,
                    amount = excluded.amount,
                    volume = excluded.volume,
                    pvolume = excluded.pvolume,
                    ask_price = excluded.ask_price,
                    bid_price = excluded.bid_price,
                    ask_vol = excluded.ask_vol,
                    bid_vol = excluded.bid_vol,
                    updated_at = excluded.updated_at
                WHERE excluded.ts >= latest_quote.ts
                  AND excluded.last_price IS NOT NULL
                  AND excluded.last_price > 0
                """,
                latest_quote_params,
            )
            stats["latest_sec"] = (datetime.now() - latest_start).total_seconds()
        commit_start = datetime.now()
        conn.commit()
        stats["commit_sec"] = (datetime.now() - commit_start).total_seconds()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return (len(tick_payloads), stats) if collect_stats else len(tick_payloads)


def import_tick_csv(db_path: str | Path, csv_path: str | Path) -> int:
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return upsert_tick_snapshots(db_path, reader)


def query_today_minute_bars(
    db_path: str | Path,
    code: str,
    from_ts: int,
    to_ts: int,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if not Path(db_path).exists():
        return []
    code_u = _normalize_code(code)
    conn = _connect_existing_cache(db_path)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            SELECT ts, last_price, amount, volume, pvolume
            FROM tick_snapshot
            WHERE htsc_code = ?
            ORDER BY ts ASC
            """,
            (code_u,),
        ).fetchall()
        latest_row = conn.execute(
            """
            SELECT ts, last_price, amount, volume, pvolume
            FROM latest_quote
            WHERE htsc_code = ?
              AND last_price IS NOT NULL
              AND last_price > 0
            """,
            (code_u,),
        ).fetchone()
    finally:
        conn.close()

    latest_ts_sec: int | None = None
    if latest_row is not None:
        try:
            latest_ts_sec = _ts_to_epoch(str(latest_row["ts"]))
        except ValueError:
            latest_ts_sec = None

    if latest_row is not None and latest_ts_sec is not None and from_ts <= latest_ts_sec <= to_ts:
        snapshot_latest_ts = max((_ts_to_epoch(str(row["ts"])) for row in rows), default=None)
        if snapshot_latest_ts is None or latest_ts_sec >= snapshot_latest_ts:
            rows = [*rows, latest_row]

    grouped: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        ts_sec = _ts_to_epoch(str(row["ts"]))
        minute_sec = ts_sec - (ts_sec % 60)
        if minute_sec < from_ts or minute_sec > to_ts:
            continue
        grouped.setdefault(minute_sec, []).append(row)

    bars: list[dict[str, Any]] = []
    for minute_sec in sorted(grouped):
        bucket = sorted(
            [
                row
                for row in grouped[minute_sec]
                if (price := _safe_float(row["last_price"])) is not None and price > 0
            ],
            key=lambda row: str(row["ts"]),
        )
        prices = [
            price
            for row in bucket
            if (price := _safe_float(row["last_price"])) is not None and price > 0
        ]
        if not prices:
            continue
        amounts = [_safe_float(row["amount"]) for row in bucket]
        volumes = [_safe_float(row["volume"]) for row in bucket]
        pvolumes = [_safe_float(row["pvolume"]) for row in bucket]
        amount_values = [value for value in amounts if value is not None]
        volume_values = [value for value in volumes if value is not None]
        pvolume_values = [value for value in pvolumes if value is not None]
        cumulative_volume_values = pvolume_values or volume_values
        bars.append(
            {
                "time": minute_sec,
                "open": float(prices[0]),
                "high": float(max(prices)),
                "low": float(min(prices)),
                "close": float(prices[-1]),
                "volume": float(volume_values[-1] - volume_values[0]) if volume_values else 0.0,
                "cumulative_volume": float(cumulative_volume_values[-1]) if cumulative_volume_values else 0.0,
                "amount": float(amount_values[-1] - amount_values[0]) if amount_values else 0.0,
            }
        )
    return bars[-limit:] if limit and len(bars) > limit else bars


def query_today_daily_bar(
    db_path: str | Path,
    code: str,
    from_ts: int,
    to_ts: int,
) -> list[dict[str, Any]]:
    if not Path(db_path).exists():
        return []
    conn = _connect_existing_cache(db_path)
    if conn is None:
        return []
    try:
        row = conn.execute(
            """
            SELECT ts, open, high, low, last_price, volume, pvolume
            FROM latest_quote
            WHERE htsc_code = ?
              AND last_price IS NOT NULL
              AND last_price > 0
            """,
            (_normalize_code(code),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return []
    day_start = _day_start_epoch(str(row["ts"])[:10])
    if day_start < int(from_ts) or day_start > int(to_ts):
        return []
    return [
        {
            "time": int(day_start),
            "open": float(row["open"]) if row["open"] is not None else 0.0,
            "high": float(row["high"]) if row["high"] is not None else 0.0,
            "low": float(row["low"]) if row["low"] is not None else 0.0,
            "close": float(row["last_price"]) if row["last_price"] is not None else 0.0,
            "volume": float(row["pvolume"] if row["pvolume"] is not None else row["volume"])
            if row["pvolume"] is not None or row["volume"] is not None
            else 0.0,
        }
    ]


def query_latest_quote(db_path: str | Path, code: str) -> dict[str, Any] | None:
    if not Path(db_path).exists():
        return None
    conn = _connect_existing_cache(db_path)
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT * FROM latest_quote WHERE htsc_code = ?",
            (_normalize_code(code),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    result = dict(row)
    for key in ("ask_price", "bid_price", "ask_vol", "bid_vol"):
        value = result.get(key)
        if isinstance(value, str) and value:
            try:
                result[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return result


def should_supplement_minute(existing_bars: list[dict[str, Any]], target_latest_time: int) -> bool:
    if not existing_bars:
        return True
    latest = max(int(bar["time"]) for bar in existing_bars if bar.get("time") is not None)
    return latest < int(target_latest_time)


def should_supplement_daily(existing_bars: list[dict[str, Any]], today_day_start_ts: int) -> bool:
    if not existing_bars:
        return True
    latest = max(int(bar["time"]) for bar in existing_bars if bar.get("time") is not None)
    return latest < int(today_day_start_ts)


def merge_bars_with_parquet_priority(
    parquet_bars: list[dict[str, Any]],
    sqlite_bars: list[dict[str, Any]],
    limit: int | None = None,
) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for bar in parquet_bars:
        merged[int(bar["time"])] = dict(bar)
    for bar in sqlite_bars:
        merged.setdefault(int(bar["time"]), dict(bar))
    bars = [merged[t] for t in sorted(merged)]
    return bars[-limit:] if limit and len(bars) > limit else bars


def has_cache(db_path: str | Path) -> bool:
    return Path(db_path).exists() and os.path.getsize(db_path) > 0
