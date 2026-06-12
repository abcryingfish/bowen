from __future__ import annotations

import unittest
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

TOOLS_DIR = Path(__file__).resolve().parent
ROOT_DIR = TOOLS_DIR.parent
VIS_DIR = ROOT_DIR / "可视化"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
if str(VIS_DIR) not in sys.path:
    sys.path.insert(0, str(VIS_DIR))

import 实时行情写入SQLite as realtime_cache  # noqa: E402
from 实时行情写入SQLite import normalize_code, tick_payload_to_cache_row  # noqa: E402


class RealtimeTickCacheTest(unittest.TestCase):
    def test_tick_payload_to_cache_row_maps_xtquant_fields(self) -> None:
        row = tick_payload_to_cache_row(
            "600000.SH",
            {
                "timetag": "20260612 09:30:03",
                "lastPrice": 9.57,
                "open": 9.59,
                "high": 9.61,
                "low": 9.48,
                "lastClose": 9.59,
                "amount": 642197700,
                "volume": 671089,
                "pvolume": 67108917,
                "askPrice": [9.58, 9.59],
                "bidPrice": [9.57, 9.56],
                "askVol": [100, 200],
                "bidVol": [300, 400],
            },
        )

        self.assertEqual(row["htsc_code"], "600000.SH")
        self.assertEqual(row["ts"], "2026-06-12 09:30:03")
        self.assertEqual(row["last_price"], 9.57)
        self.assertEqual(row["last_close"], 9.59)
        self.assertEqual(row["ask_price"], [9.58, 9.59])

    def test_normalize_code(self) -> None:
        self.assertEqual(normalize_code(" 000001.sz "), "000001.SZ")

    def test_write_tick_batch_skips_schema_initialization_inside_hot_loop(self) -> None:
        tick_data = {
            "600000.SH": {
                "timetag": "20260612 09:30:03",
                "lastPrice": 9.57,
            }
        }
        with patch.object(
            realtime_cache,
            "upsert_tick_snapshots",
            return_value=(1, {"snapshot_sec": 0.1, "latest_sec": 0.2, "commit_sec": 0.3}),
        ) as upsert:
            written, skipped, stats = realtime_cache.write_tick_batch(
                Path("dummy.sqlite"),
                tick_data,
                {"600000.SH"},
            )

        self.assertEqual(written, 1)
        self.assertEqual(skipped, 0)
        self.assertGreaterEqual(stats["build_sec"], 0.0)
        upsert.assert_called_once()
        self.assertEqual(upsert.call_args.kwargs["ensure"], False)
        self.assertEqual(upsert.call_args.kwargs["update_existing_snapshots"], False)
        self.assertEqual(upsert.call_args.kwargs["write_snapshots"], True)
        self.assertEqual(upsert.call_args.kwargs["write_latest"], True)
        self.assertEqual(upsert.call_args.kwargs["collect_stats"], True)
        self.assertEqual(stats["snapshot_sec"], 0.1)
        self.assertEqual(stats["latest_sec"], 0.2)

    def test_write_tick_batch_can_skip_snapshot_writes(self) -> None:
        tick_data = {
            "600000.SH": {
                "timetag": "20260612 09:30:03",
                "lastPrice": 9.57,
            }
        }
        with patch.object(
            realtime_cache,
            "upsert_tick_snapshots",
            return_value=(1, {"snapshot_sec": 0.0, "latest_sec": 0.2, "commit_sec": 0.3}),
        ) as upsert:
            written, skipped, stats = realtime_cache.write_tick_batch(
                Path("dummy.sqlite"),
                tick_data,
                {"600000.SH"},
                write_snapshots=False,
            )

        self.assertEqual(written, 1)
        self.assertEqual(skipped, 0)
        self.assertEqual(upsert.call_args.kwargs["write_snapshots"], False)
        self.assertEqual(stats["snapshot_sec"], 0.0)

    def test_snapshot_flush_worker_writes_pending_rows_in_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "cache.sqlite"
            worker = realtime_cache.SnapshotFlushWorker(
                db_path,
                flush_interval_seconds=0.01,
            )
            with patch.object(
                realtime_cache,
                "upsert_tick_snapshots",
                return_value=(1, {"snapshot_sec": 0.1, "latest_sec": 0.0, "commit_sec": 0.2}),
            ) as upsert:
                worker.start()
                try:
                    worker.enqueue(
                        [
                            {
                                "htsc_code": "600000.SH",
                                "ts": "2026-06-12 09:30:03",
                                "last_price": 9.57,
                            }
                        ]
                    )
                    deadline = time.time() + 1.0
                    while upsert.call_count == 0 and time.time() < deadline:
                        time.sleep(0.01)
                finally:
                    worker.stop()

        upsert.assert_called_once()
        self.assertEqual(upsert.call_args.kwargs["ensure"], False)
        self.assertEqual(upsert.call_args.kwargs["write_snapshots"], True)
        self.assertEqual(upsert.call_args.kwargs["write_latest"], False)

    def test_snapshot_flush_worker_keeps_only_latest_row_per_stock(self) -> None:
        worker = realtime_cache.SnapshotFlushWorker(
            Path("dummy.sqlite"),
            flush_interval_seconds=60.0,
        )

        worker.enqueue(
            [
                {
                    "htsc_code": "600000.SH",
                    "ts": "2026-06-12 09:30:03",
                    "last_price": 9.57,
                },
                {
                    "htsc_code": "600001.SH",
                    "ts": "2026-06-12 09:30:03",
                    "last_price": 8.01,
                },
            ]
        )
        worker.enqueue(
            [
                {
                    "htsc_code": "600000.SH",
                    "ts": "2026-06-12 09:30:06",
                    "last_price": 9.59,
                }
            ]
        )

        self.assertEqual(worker.pending_count(), 2)
        with patch.object(
            realtime_cache,
            "upsert_tick_snapshots",
            return_value=(2, {"snapshot_sec": 0.1, "latest_sec": 0.0, "commit_sec": 0.2}),
        ) as upsert:
            worker.flush_once()

        rows = list(upsert.call_args.args[1])
        self.assertEqual(len(rows), 2)
        latest_600000 = [row for row in rows if row["htsc_code"] == "600000.SH"][0]
        self.assertEqual(latest_600000["ts"], "2026-06-12 09:30:06")
        self.assertEqual(latest_600000["last_price"], 9.59)

    def test_write_tick_batch_can_enqueue_snapshots_without_waiting_for_flush(self) -> None:
        tick_data = {
            "600000.SH": {
                "timetag": "20260612 09:30:03",
                "lastPrice": 9.57,
            }
        }
        worker = realtime_cache.SnapshotFlushWorker(
            Path("dummy.sqlite"),
            flush_interval_seconds=60.0,
        )
        with patch.object(worker, "enqueue") as enqueue, patch.object(
            realtime_cache,
            "upsert_tick_snapshots",
            return_value=(1, {"snapshot_sec": 0.0, "latest_sec": 0.2, "commit_sec": 0.3}),
        ) as upsert:
            written, skipped, stats = realtime_cache.write_tick_batch(
                Path("dummy.sqlite"),
                tick_data,
                {"600000.SH"},
                snapshot_worker=worker,
            )

        self.assertEqual(written, 1)
        self.assertEqual(skipped, 0)
        enqueue.assert_called_once()
        self.assertEqual(upsert.call_args.kwargs["write_snapshots"], False)
        self.assertEqual(upsert.call_args.kwargs["write_latest"], True)
        self.assertEqual(stats["queued_snapshot_rows"], 1)


if __name__ == "__main__":
    unittest.main()
