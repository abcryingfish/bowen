from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parent / "\u83b7\u5f97\u6307\u6570\u65e5\u9891\u6570\u636e.py"
SPEC = importlib.util.spec_from_file_location("index_daily_download", MODULE_PATH)
index_daily_download = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(index_daily_download)


def test_normalize_xtquant_index_daily_matches_existing_schema_and_volume_units() -> None:
    raw = pd.DataFrame(
        {
            "time": [1719792000000, 1719878400000],
            "open": [3000.0, 3010.0],
            "high": [3020.0, 3030.0],
            "low": [2990.0, 3005.0],
            "close": [3015.0, 3025.0],
            "volume": [123.0, 456.0],
            "pvolume": [12300.0, None],
            "amount": [1.2e11, 1.3e11],
        }
    )

    out = index_daily_download.normalize_xtquant_index_daily_dataframe(raw, "000001.sh")

    assert list(out.columns) == [
        "htsc_code",
        "time",
        "exchange",
        "security_type",
        "security_id",
        "frequency",
        "open",
        "close",
        "high",
        "low",
        "volume",
        "value",
    ]
    assert out["htsc_code"].tolist() == ["000001.SH", "000001.SH"]
    assert out["exchange"].tolist() == ["DefaultSecurityIDSource", "DefaultSecurityIDSource"]
    assert out["security_type"].tolist() == ["index", "index"]
    assert out["security_id"].tolist() == ["000001", "000001"]
    assert out["frequency"].tolist() == ["daily", "daily"]
    assert out["volume"].tolist() == [12300.0, 45600.0]
    assert out["value"].tolist() == [1.2e11, 1.3e11]
