from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import market_data_service  # noqa: E402


def epoch(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


class MarketPartitionPathTest(unittest.TestCase):
    def test_minute_base_uses_day_partition_only(self) -> None:
        old_minute_base = market_data_service.MINUTE_BASE_PATH
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            market_data_service.MINUTE_BASE_PATH = str(base)
            month_dir = base / "year=2026" / "month=06"
            day_dir = month_dir / "day=12"
            month_dir.mkdir(parents=True)
            day_dir.mkdir(parents=True)
            (month_dir / "merged.parquet").write_bytes(b"legacy-month")
            (day_dir / "merged.parquet").write_bytes(b"day")

            paths = market_data_service.build_partition_paths(str(base), epoch("2026-06-12"), epoch("2026-06-12"))

            self.assertEqual(paths, [str(day_dir / "merged.parquet").replace("\\", "/")])
        market_data_service.MINUTE_BASE_PATH = old_minute_base

    def test_non_minute_base_keeps_month_partition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            month_dir = base / "year=2026" / "month=06"
            day_dir = month_dir / "day=12"
            month_dir.mkdir(parents=True)
            day_dir.mkdir(parents=True)
            (month_dir / "merged.parquet").write_bytes(b"month")
            (day_dir / "merged.parquet").write_bytes(b"day")

            paths = market_data_service.build_partition_paths(str(base), epoch("2026-06-12"), epoch("2026-06-12"))

            self.assertEqual(paths, [str(month_dir / "merged.parquet").replace("\\", "/")])


if __name__ == "__main__":
    unittest.main()
