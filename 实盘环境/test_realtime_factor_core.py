from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


REALTIME_DIR = Path(__file__).resolve().parent / "实时因子"
sys.path.insert(0, str(REALTIME_DIR))

from realtime_factor_core import (  # noqa: E402
    RealtimeFactorEngine,
    append_signal_events,
    elapsed_trading_ratio,
    ensure_signal_schema,
)


class RealtimeFactorCoreTest(unittest.TestCase):
    def test_elapsed_trading_ratio_skips_lunch_break(self) -> None:
        self.assertAlmostEqual(elapsed_trading_ratio(datetime(2026, 6, 15, 9, 30)), 1 / 240)
        self.assertAlmostEqual(elapsed_trading_ratio(datetime(2026, 6, 15, 10, 30)), 60 / 240)
        self.assertAlmostEqual(elapsed_trading_ratio(datetime(2026, 6, 15, 12, 0)), 120 / 240)
        self.assertAlmostEqual(elapsed_trading_ratio(datetime(2026, 6, 15, 14, 0)), 180 / 240)
        self.assertAlmostEqual(elapsed_trading_ratio(datetime(2026, 6, 15, 15, 30)), 1.0)

    def test_signal_events_append_repeated_hits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "signals.sqlite"
            ensure_signal_schema(db_path)
            event = {
                "trading_day": "2026-06-15",
                "calc_round_id": 1,
                "signal_time": "2026-06-15 10:00:00",
                "source_tick_ts": "2026-06-15 10:00:00",
                "htsc_code": "000001.SZ",
                "signal_name": "total_buy_signal",
                "signal_value": 1.0,
                "last_price": 10.0,
                "volume": 1000.0,
                "turnover_estimate": 0.02,
                "turnover_method": "linear_time_scaled",
                "is_estimated": 1,
                "calc_elapsed_ms": 12.5,
            }
            append_signal_events(db_path, [event, dict(event, calc_round_id=2)])

            conn = sqlite3.connect(db_path)
            try:
                count = conn.execute("SELECT COUNT(*) FROM signal_events").fetchone()[0]
                rounds = [
                    row[0]
                    for row in conn.execute(
                        "SELECT calc_round_id FROM signal_events ORDER BY id"
                    ).fetchall()
                ]
            finally:
                conn.close()

            self.assertEqual(count, 2)
            self.assertEqual(rounds, [1, 2])

    def test_expensive_chip_step_is_skipped_when_fast_conditions_fail(self) -> None:
        engine = RealtimeFactorEngine(
            code_order=["000001.SZ", "000002.SZ"],
            fast_signal_provider=lambda quotes: {
                "000001.SZ": {
                    "total_buy_base": False,
                    "tdx_base": False,
                    "sell_base": False,
                },
                "000002.SZ": {
                    "total_buy_base": False,
                    "tdx_base": False,
                    "sell_base": False,
                },
            },
            chip_provider=lambda codes, quotes, now: (_ for _ in ()).throw(
                AssertionError("chip provider should not be called")
            ),
            sell_volume_provider=lambda codes, quotes: {},
        )

        signals, stats = engine.evaluate_round(
            quotes=[
                {
                    "htsc_code": "000001.SZ",
                    "ts": "2026-06-15 10:00:00",
                    "last_price": 10.0,
                    "open": 9.8,
                    "high": 10.2,
                    "low": 9.7,
                    "volume": 1000.0,
                },
                {
                    "htsc_code": "000002.SZ",
                    "ts": "2026-06-15 10:00:00",
                    "last_price": 8.0,
                    "open": 8.1,
                    "high": 8.2,
                    "low": 7.9,
                    "volume": 900.0,
                },
            ],
            now=datetime(2026, 6, 15, 10, 0),
        )

        self.assertEqual(signals, [])
        self.assertEqual(stats["chip_candidate_count"], 0)


if __name__ == "__main__":
    unittest.main()
