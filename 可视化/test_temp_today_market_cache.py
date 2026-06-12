from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import market_data_service  # noqa: E402
import temp_today_market_cache as cache  # noqa: E402
from temp_today_market_cache import (  # noqa: E402
    ensure_schema,
    query_today_daily_bar,
    query_today_minute_bars,
    should_supplement_daily,
    should_supplement_minute,
    upsert_tick_snapshot,
    upsert_tick_snapshots,
)


def epoch(text: str) -> int:
    if len(text) == 10:
        return int(datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    return int(datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())


class TempTodayMarketCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "market_cache_test.sqlite"
        ensure_schema(self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_minute_aggregation_uses_last_price_and_volume_diff(self) -> None:
        rows = [
            {
                "htsc_code": "600519.SH",
                "ts": "2026-06-11 09:30:01",
                "last_price": 10.0,
                "open": 9.8,
                "high": 10.2,
                "low": 9.7,
                "last_close": 9.6,
                "amount": 1000.0,
                "volume": 100.0,
                "pvolume": 10000.0,
            },
            {
                "htsc_code": "600519.SH",
                "ts": "2026-06-11 09:30:31",
                "last_price": 12.0,
                "open": 9.8,
                "high": 12.0,
                "low": 9.7,
                "last_close": 9.6,
                "amount": 1600.0,
                "volume": 160.0,
                "pvolume": 16000.0,
            },
            {
                "htsc_code": "600519.SH",
                "ts": "2026-06-11 09:30:58",
                "last_price": 11.0,
                "open": 9.8,
                "high": 12.0,
                "low": 9.7,
                "last_close": 9.6,
                "amount": 1800.0,
                "volume": 180.0,
                "pvolume": 18000.0,
            },
        ]
        for row in rows:
            upsert_tick_snapshot(self.db_path, row)

        bars = query_today_minute_bars(
            self.db_path,
            "600519.SH",
            from_ts=epoch("2026-06-11 09:30:00"),
            to_ts=epoch("2026-06-11 09:31:00"),
        )

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["time"], epoch("2026-06-11 09:30:00"))
        self.assertEqual(bars[0]["open"], 10.0)
        self.assertEqual(bars[0]["high"], 12.0)
        self.assertEqual(bars[0]["low"], 10.0)
        self.assertEqual(bars[0]["close"], 11.0)
        self.assertEqual(bars[0]["volume"], 80.0)
        self.assertEqual(bars[0]["cumulative_volume"], 18000.0)
        self.assertEqual(bars[0]["amount"], 800.0)

    def test_minute_aggregation_ignores_zero_price_snapshots(self) -> None:
        rows = [
            {
                "htsc_code": "600519.SH",
                "ts": "2026-06-11 09:30:01",
                "last_price": 0.0,
                "amount": 0.0,
                "volume": 0.0,
            },
            {
                "htsc_code": "600519.SH",
                "ts": "2026-06-11 09:30:10",
                "last_price": 10.0,
                "amount": 1000.0,
                "volume": 100.0,
                "pvolume": 10000.0,
            },
            {
                "htsc_code": "600519.SH",
                "ts": "2026-06-11 09:30:40",
                "last_price": 12.0,
                "amount": 1500.0,
                "volume": 150.0,
                "pvolume": 15000.0,
            },
        ]
        for row in rows:
            upsert_tick_snapshot(self.db_path, row)

        bars = query_today_minute_bars(
            self.db_path,
            "600519.SH",
            from_ts=epoch("2026-06-11 09:30:00"),
            to_ts=epoch("2026-06-11 09:31:00"),
        )

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["open"], 10.0)
        self.assertEqual(bars[0]["low"], 10.0)
        self.assertEqual(bars[0]["close"], 12.0)
        self.assertEqual(bars[0]["volume"], 50.0)
        self.assertEqual(bars[0]["cumulative_volume"], 15000.0)
        self.assertEqual(bars[0]["amount"], 500.0)

    def test_minute_bar_updates_current_bucket_from_latest_quote(self) -> None:
        upsert_tick_snapshots(
            self.db_path,
            [
                {
                    "htsc_code": "600519.SH",
                    "ts": "2026-06-11 09:30:01",
                    "last_price": 10.0,
                    "amount": 1000.0,
                    "volume": 100.0,
                    "pvolume": 10000.0,
                },
                {
                    "htsc_code": "600519.SH",
                    "ts": "2026-06-11 09:30:31",
                    "last_price": 11.0,
                    "amount": 1400.0,
                    "volume": 140.0,
                    "pvolume": 14000.0,
                },
            ],
            write_latest=False,
        )
        upsert_tick_snapshots(
            self.db_path,
            [
                {
                    "htsc_code": "600519.SH",
                    "ts": "2026-06-11 09:30:45",
                    "last_price": 12.0,
                    "amount": 1800.0,
                    "volume": 180.0,
                    "pvolume": 18000.0,
                }
            ],
            write_snapshots=False,
            write_latest=True,
        )

        bars = query_today_minute_bars(
            self.db_path,
            "600519.SH",
            from_ts=epoch("2026-06-11 09:30:00"),
            to_ts=epoch("2026-06-11 09:31:00"),
        )

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["open"], 10.0)
        self.assertEqual(bars[0]["high"], 12.0)
        self.assertEqual(bars[0]["low"], 10.0)
        self.assertEqual(bars[0]["close"], 12.0)
        self.assertEqual(bars[0]["volume"], 80.0)
        self.assertEqual(bars[0]["cumulative_volume"], 18000.0)
        self.assertEqual(bars[0]["amount"], 800.0)

    def test_minute_bar_can_use_latest_quote_before_snapshot_flush(self) -> None:
        upsert_tick_snapshots(
            self.db_path,
            [
                {
                    "htsc_code": "600519.SH",
                    "ts": "2026-06-11 09:31:05",
                    "last_price": 12.0,
                    "amount": 1800.0,
                    "volume": 180.0,
                }
            ],
            write_snapshots=False,
            write_latest=True,
        )

        bars = query_today_minute_bars(
            self.db_path,
            "600519.SH",
            from_ts=epoch("2026-06-11 09:31:00"),
            to_ts=epoch("2026-06-11 09:32:00"),
        )

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["time"], epoch("2026-06-11 09:31:00"))
        self.assertEqual(bars[0]["open"], 12.0)
        self.assertEqual(bars[0]["high"], 12.0)
        self.assertEqual(bars[0]["low"], 12.0)
        self.assertEqual(bars[0]["close"], 12.0)
        self.assertEqual(bars[0]["volume"], 0.0)
        self.assertEqual(bars[0]["amount"], 0.0)

    def test_daily_bar_does_not_update_with_zero_last_price(self) -> None:
        upsert_tick_snapshot(
            self.db_path,
            {
                "htsc_code": "600519.SH",
                "ts": "2026-06-11 09:30:10",
                "last_price": 10.0,
                "open": 9.8,
                "high": 10.2,
                "low": 9.7,
                "last_close": 9.6,
                "amount": 1000.0,
                "volume": 100.0,
            },
        )
        upsert_tick_snapshot(
            self.db_path,
            {
                "htsc_code": "600519.SH",
                "ts": "2026-06-11 09:31:10",
                "last_price": 0.0,
                "open": 0.0,
                "high": 0.0,
                "low": 0.0,
                "last_close": 9.6,
                "amount": 0.0,
                "volume": 0.0,
            },
        )

        bars = query_today_daily_bar(
            self.db_path,
            "600519.SH",
            from_ts=epoch("2026-06-11"),
            to_ts=epoch("2026-06-11 23:59:59"),
        )

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["close"], 10.0)
        self.assertEqual(bars[0]["open"], 9.8)

    def test_today_daily_bar_uses_latest_snapshot_fields(self) -> None:
        upsert_tick_snapshot(
            self.db_path,
            {
                "htsc_code": "600519.SH",
                "ts": "2026-06-11 14:56:00",
                "last_price": 11.0,
                "open": 9.8,
                "high": 12.0,
                "low": 9.7,
                "last_close": 9.6,
                "amount": 1800.0,
                "volume": 180.0,
                "pvolume": 18000.0,
            },
        )

        bars = query_today_daily_bar(
            self.db_path,
            "600519.SH",
            from_ts=epoch("2026-06-11"),
            to_ts=epoch("2026-06-11 23:59:59"),
        )

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["time"], epoch("2026-06-11"))
        self.assertEqual(bars[0]["open"], 9.8)
        self.assertEqual(bars[0]["high"], 12.0)
        self.assertEqual(bars[0]["low"], 9.7)
        self.assertEqual(bars[0]["close"], 11.0)
        self.assertEqual(bars[0]["volume"], 18000.0)

    def test_supplement_decision_respects_parquet_priority(self) -> None:
        today_minute = epoch("2026-06-11 09:30:00")
        today_day = epoch("2026-06-11")

        self.assertFalse(should_supplement_minute([{"time": today_minute}], today_minute))
        self.assertTrue(should_supplement_minute([{"time": today_minute - 60}], today_minute))
        self.assertFalse(should_supplement_daily([{"time": today_day}], today_day))
        self.assertTrue(should_supplement_daily([{"time": today_day - 86400}], today_day))

    def test_schema_has_expected_tables(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()
        self.assertIn("tick_snapshot", tables)
        self.assertIn("latest_quote", tables)
        self.assertIn("today_daily_bar", tables)

    def test_queries_do_not_run_schema_writes_after_cache_exists(self) -> None:
        upsert_tick_snapshot(
            self.db_path,
            {
                "htsc_code": "600519.SH",
                "ts": "2026-06-11 09:30:10",
                "last_price": 10.0,
                "amount": 1000.0,
                "volume": 100.0,
            },
        )

        with patch.object(cache, "ensure_schema", side_effect=AssertionError("schema write")):
            minute_bars = query_today_minute_bars(
                self.db_path,
                "600519.SH",
                from_ts=epoch("2026-06-11 09:30:00"),
                to_ts=epoch("2026-06-11 09:31:00"),
            )
            daily_bars = query_today_daily_bar(
                self.db_path,
                "600519.SH",
                from_ts=epoch("2026-06-11"),
                to_ts=epoch("2026-06-11 23:59:59"),
            )
            latest_quote = cache.query_latest_quote(self.db_path, "600519.SH")

        self.assertEqual(len(minute_bars), 1)
        self.assertEqual(len(daily_bars), 1)
        self.assertIsNotNone(latest_quote)

    def test_batch_insert_can_append_snapshots_without_conflict_updates(self) -> None:
        rows = [
            {
                "htsc_code": "600519.SH",
                "ts": "2026-06-11 09:30:10",
                "last_price": 10.0,
                "amount": 1000.0,
                "volume": 100.0,
            },
            {
                "htsc_code": "600519.SH",
                "ts": "2026-06-11 09:30:10",
                "last_price": 11.0,
                "amount": 1100.0,
                "volume": 110.0,
            },
        ]

        written = upsert_tick_snapshots(
            self.db_path,
            rows,
            update_existing_snapshots=False,
        )

        conn = sqlite3.connect(self.db_path)
        try:
            snapshot_rows = conn.execute(
                "SELECT last_price FROM tick_snapshot WHERE htsc_code = ? AND ts = ?",
                ("600519.SH", "2026-06-11 09:30:10"),
            ).fetchall()
            latest_row = conn.execute(
                "SELECT last_price FROM latest_quote WHERE htsc_code = ?",
                ("600519.SH",),
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(written, 2)
        self.assertEqual(snapshot_rows, [(10.0,)])
        self.assertEqual(latest_row[0], 11.0)


class MarketDataServiceTempCacheIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.db_path = self.root / "market_cache_test.sqlite"
        self.minute_base = self.root / "mins"
        self.daily_base = self.root / "daily"
        ensure_schema(self.db_path)
        self.old_cache_path = market_data_service.TEMP_TODAY_MARKET_CACHE_PATH
        self.old_minute_base = market_data_service.MINUTE_BASE_PATH
        self.old_daily_base = market_data_service.DAILY_BASE_PATH
        market_data_service.TEMP_TODAY_MARKET_CACHE_PATH = str(self.db_path)
        market_data_service.MINUTE_BASE_PATH = str(self.minute_base)
        market_data_service.DAILY_BASE_PATH = str(self.daily_base)

    def tearDown(self) -> None:
        market_data_service.TEMP_TODAY_MARKET_CACHE_PATH = self.old_cache_path
        market_data_service.MINUTE_BASE_PATH = self.old_minute_base
        market_data_service.DAILY_BASE_PATH = self.old_daily_base
        self.tmp_dir.cleanup()

    def _write_parquet_partition(self, base: Path, rows: list[dict[str, object]]) -> None:
        is_minute_base = base == self.minute_base
        part_dir = base / "year=2026" / "month=06"
        if is_minute_base:
            part_dir = part_dir / "day=11"
        part_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_parquet(part_dir / "merged.parquet", index=False)

    def test_query_market_bars_adds_sqlite_minutes_only_when_needed(self) -> None:
        self._write_parquet_partition(
            self.minute_base,
            [
                {
                    "htsc_code": "600519.SH",
                    "time": epoch("2026-06-11 09:30:00"),
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "volume": 10.0,
                }
            ],
        )
        for row in [
            {
                "htsc_code": "600519.SH",
                "ts": "2026-06-11 09:30:03",
                "last_price": 2.0,
                "open": 2.0,
                "high": 2.0,
                "low": 2.0,
                "last_close": 1.0,
                "amount": 10.0,
                "volume": 1.0,
                "pvolume": 100.0,
            },
            {
                "htsc_code": "600519.SH",
                "ts": "2026-06-11 09:31:03",
                "last_price": 3.0,
                "open": 2.0,
                "high": 3.0,
                "low": 2.0,
                "last_close": 1.0,
                "amount": 30.0,
                "volume": 3.0,
                "pvolume": 300.0,
            },
        ]:
            upsert_tick_snapshot(self.db_path, row)

        result = market_data_service.query_market_bars(
            "600519.SH",
            "1min",
            from_ts=epoch("2026-06-11 09:30:00"),
            to_ts=epoch("2026-06-11 09:32:00"),
            limit=10,
        )

        self.assertEqual([bar["time"] for bar in result["bars"]], [
            epoch("2026-06-11 09:30:00"),
            epoch("2026-06-11 09:31:00"),
        ])
        self.assertEqual(result["bars"][0]["close"], 1.0)
        self.assertEqual(result["bars"][1]["close"], 3.0)
        self.assertTrue(result["meta"]["temp_today_supplemented"])

    def test_query_market_bars_uses_parquet_only_when_today_exists(self) -> None:
        self._write_parquet_partition(
            self.daily_base,
            [
                {
                    "htsc_code": "600519.SH",
                    "time": epoch("2026-06-11"),
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "volume": 10.0,
                }
            ],
        )
        upsert_tick_snapshot(
            self.db_path,
            {
                "htsc_code": "600519.SH",
                "ts": "2026-06-11 14:56:00",
                "last_price": 9.0,
                "open": 9.0,
                "high": 9.0,
                "low": 9.0,
                "last_close": 8.0,
                "amount": 90.0,
                "volume": 90.0,
                "pvolume": 900.0,
            },
        )

        result = market_data_service.query_market_bars(
            "600519.SH",
            "1day",
            from_ts=epoch("2026-06-11"),
            to_ts=epoch("2026-06-11 23:59:59"),
            limit=10,
            adjust="none",
        )

        self.assertEqual(len(result["bars"]), 1)
        self.assertEqual(result["bars"][0]["close"], 1.0)
        self.assertNotIn("temp_today_supplemented", result["meta"])

    def test_build_partition_paths_prefers_day_partitions(self) -> None:
        month_dir = self.minute_base / "year=2026" / "month=06"
        day10_dir = month_dir / "day=10"
        day11_dir = month_dir / "day=11"
        month_dir.mkdir(parents=True, exist_ok=True)
        day10_dir.mkdir(parents=True, exist_ok=True)
        day11_dir.mkdir(parents=True, exist_ok=True)
        month_file = month_dir / "merged.parquet"
        day10_file = day10_dir / "merged.parquet"
        day11_file = day11_dir / "merged.parquet"
        for path in [month_file, day10_file, day11_file]:
            path.write_bytes(b"placeholder")

        paths = market_data_service.build_partition_paths(
            str(self.minute_base),
            epoch("2026-06-11"),
            epoch("2026-06-11 23:59:59"),
        )

        normalized = {Path(path).as_posix() for path in paths}
        self.assertIn(day11_file.as_posix(), normalized)
        self.assertNotIn(day10_file.as_posix(), normalized)
        self.assertNotIn(month_file.as_posix(), normalized)

    def test_query_market_bars_adjusts_supplemented_daily_bar(self) -> None:
        self._write_parquet_partition(
            self.daily_base,
            [
                {
                    "htsc_code": "600519.SH",
                    "time": epoch("2026-06-10"),
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 10.0,
                }
            ],
        )
        upsert_tick_snapshot(
            self.db_path,
            {
                "htsc_code": "600519.SH",
                "ts": "2026-06-11 14:56:00",
                "last_price": 20.0,
                "open": 20.0,
                "high": 20.0,
                "low": 20.0,
                "last_close": 19.0,
                "amount": 200.0,
                "volume": 20.0,
                "pvolume": 2000.0,
            },
        )

        with patch.object(
            market_data_service,
            "adjust_daily_bars",
            side_effect=lambda code, bars, mode: (
                [
                    {
                        **bar,
                        "open": bar["open"] * 2,
                        "high": bar["high"] * 2,
                        "low": bar["low"] * 2,
                        "close": bar["close"] * 2,
                    }
                    for bar in bars
                ],
                "forward",
            ),
        ):
            result = market_data_service.query_market_bars(
                "600519.SH",
                "1day",
                from_ts=epoch("2026-06-10"),
                to_ts=epoch("2026-06-11 23:59:59"),
                limit=10,
                adjust="forward",
            )

        self.assertEqual([bar["time"] for bar in result["bars"]], [epoch("2026-06-10"), epoch("2026-06-11")])
        self.assertEqual(result["bars"][0]["close"], 20.0)
        self.assertEqual(result["bars"][1]["close"], 40.0)
        self.assertEqual(result["meta"]["adjust"], "forward")


if __name__ == "__main__":
    unittest.main()
