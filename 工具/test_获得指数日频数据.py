from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

import polars as pl


MODULE_PATH = Path(__file__).with_name("获得指数日频数据.py")
SPEC = importlib.util.spec_from_file_location("index_daily_download", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_scan_latest_downloaded_times_ignores_meta_parquet(tmp_path: Path) -> None:
    partition_dir = tmp_path / "year=2026" / "month=08"
    partition_dir.mkdir(parents=True)
    pl.DataFrame(
        {
            "htsc_code": ["000001.SH", "000001.SH", "399001.SZ"],
            "time": [
                datetime(2026, 8, 14),
                datetime(2026, 8, 17),
                datetime(2026, 8, 15),
            ],
        }
    ).write_parquet(partition_dir / "merged.parquet")

    meta_dir = tmp_path / "_meta"
    meta_dir.mkdir()
    pl.DataFrame({"sector_code": ["881001.THS"]}).write_parquet(
        meta_dir / "ths_level1_universe.parquet"
    )

    latest = MODULE.scan_latest_downloaded_times(str(tmp_path))

    assert latest == {
        "000001.SH": datetime(2026, 8, 17),
        "399001.SZ": datetime(2026, 8, 15),
    }
