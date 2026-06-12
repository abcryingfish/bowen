from __future__ import annotations

import importlib.util
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import polars as pl


SCRIPT_PATH = Path(__file__).resolve().parent / "获得股票分钟级数据.py"


def load_minute_module():
    spec = importlib.util.spec_from_file_location("minute_download_script", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载脚本: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MinuteDailyPartitionTest(unittest.TestCase):
    def test_save_partitioned_parquet_writes_day_partition(self) -> None:
        minute = load_minute_module()
        with tempfile.TemporaryDirectory() as tmp:
            frame = pl.DataFrame(
                {
                    "htsc_code": ["600519.SH", "600519.SH"],
                    "time": [
                        datetime(2026, 6, 11, 9, 30),
                        datetime(2026, 6, 12, 9, 30),
                    ],
                    "open": [1.0, 2.0],
                    "high": [1.0, 2.0],
                    "low": [1.0, 2.0],
                    "close": [1.0, 2.0],
                    "volume": [10.0, 20.0],
                }
            )

            touched = minute.save_partitioned_parquet(frame, tmp, "600519.SH")

            self.assertEqual(touched, [(2026, 6, 11), (2026, 6, 12)])
            self.assertTrue((Path(tmp) / "year=2026" / "month=06" / "day=11").is_dir())
            self.assertTrue((Path(tmp) / "year=2026" / "month=06" / "day=12").is_dir())
            self.assertFalse((Path(tmp) / "year=2026" / "month=06" / "merged.parquet").exists())

    def test_scan_paths_ignore_legacy_month_root_files(self) -> None:
        minute = load_minute_module()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            month_dir = base / "year=2026" / "month=06"
            day_dir = month_dir / "day=12"
            month_dir.mkdir(parents=True)
            day_dir.mkdir(parents=True)

            frame = pl.DataFrame(
                {
                    "htsc_code": ["600519.SH"],
                    "time": [datetime(2026, 6, 12, 9, 30)],
                    "close": [1.0],
                }
            )
            frame.write_parquet(month_dir / "legacy.parquet")
            frame.write_parquet(day_dir / "merged.parquet")

            paths = minute._collect_scan_parquet_paths(tmp, scan_months=12)

            self.assertEqual(paths, [str(day_dir / "merged.parquet").replace("\\", "/")])


if __name__ == "__main__":
    unittest.main()
