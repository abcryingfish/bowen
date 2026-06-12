from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import pandas as pd


TOOLS_DIR = Path(__file__).resolve().parent
DAILY_SCRIPT_PATH = TOOLS_DIR / "获得股票日频数据.py"
MINUTE_SCRIPT_PATH = TOOLS_DIR / "获得股票分钟级数据.py"


def load_module(script_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载脚本: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class XtquantVolumeUnitsTest(unittest.TestCase):
    def test_daily_normalize_prefers_pvolume_share_units(self) -> None:
        daily = load_module(DAILY_SCRIPT_PATH, "daily_download_script_volume_test")
        raw = pd.DataFrame(
            {
                "time": ["20260601"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.0],
                "close": [10.5],
                "volume": [10.0],
                "pvolume": [1000.0],
                "amount": [10500.0],
            }
        )

        normalized = daily._normalize_xtquant_daily_dataframe(raw, "000001.SZ")

        self.assertEqual(float(normalized.loc[0, "volume"]), 1000.0)

    def test_daily_normalize_converts_volume_lots_when_pvolume_missing(self) -> None:
        daily = load_module(DAILY_SCRIPT_PATH, "daily_download_script_volume_fallback_test")
        raw = pd.DataFrame(
            {
                "time": ["20260601"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.0],
                "close": [10.5],
                "volume": [10.0],
                "amount": [10500.0],
            }
        )

        normalized = daily._normalize_xtquant_daily_dataframe(raw, "000001.SZ")

        self.assertEqual(float(normalized.loc[0, "volume"]), 1000.0)

    def test_minute_normalize_prefers_pvolume_share_units(self) -> None:
        minute = load_module(MINUTE_SCRIPT_PATH, "minute_download_script_volume_test")
        raw = pd.DataFrame(
            {
                "time": ["20260601093000"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.0],
                "close": [10.5],
                "volume": [10.0],
                "pvolume": [1000.0],
                "amount": [10500.0],
            }
        )

        normalized = minute._normalize_xtquant_dataframe(raw, "000001.SZ")

        self.assertEqual(float(normalized["volume"][0]), 1000.0)

    def test_minute_normalize_converts_volume_lots_when_pvolume_missing(self) -> None:
        minute = load_module(MINUTE_SCRIPT_PATH, "minute_download_script_volume_fallback_test")
        raw = pd.DataFrame(
            {
                "time": ["20260601093000"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.0],
                "close": [10.5],
                "volume": [10.0],
                "amount": [10500.0],
            }
        )

        normalized = minute._normalize_xtquant_dataframe(raw, "000001.SZ")

        self.assertEqual(float(normalized["volume"][0]), 1000.0)


if __name__ == "__main__":
    unittest.main()
