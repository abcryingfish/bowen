from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MINUTE_SCRIPT = ROOT / "工具" / "获得股票分钟级数据.py"


def load_minute_module():
    spec = importlib.util.spec_from_file_location("minute_data_download", MINUTE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_end_time_cuts_after_close_to_1500():
    mins = load_minute_module()

    end_time = mins.resolve_default_end_datetime(datetime(2026, 7, 6, 16, 12))

    assert end_time == datetime(2026, 7, 6, 15, 0)


def test_default_end_time_keeps_intraday_current_minute():
    mins = load_minute_module()

    end_time = mins.resolve_default_end_datetime(datetime(2026, 7, 6, 14, 37, 42, 123456))

    assert end_time == datetime(2026, 7, 6, 14, 37)
