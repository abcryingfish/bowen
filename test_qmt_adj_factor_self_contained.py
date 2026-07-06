from __future__ import annotations

import importlib.util
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import polars as pl


ROOT = Path(__file__).resolve().parent
QMT_SCRIPT = ROOT / "工具" / "qmt获得股票日频复权因子.py"


def load_qmt_module():
    spec = importlib.util.spec_from_file_location("qmt_adj_factor", QMT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_qmt_adj_factor_script_does_not_load_legacy_adj_script():
    source = QMT_SCRIPT.read_text(encoding="utf-8")

    assert "获得股票日频复权因子.py" not in source
    assert "_LEGACY_ADJ" not in source


def test_qmt_incremental_start_uses_global_latest_raw_event_date():
    qmt = load_qmt_module()

    _, start_date = qmt.build_codes_to_fetch(
        ["000001.SZ", "000002.SZ", "600000.SH"],
        {
            "000001.SZ": datetime(2006, 1, 1),
            "000002.SZ": datetime(2026, 7, 2),
        },
        datetime(2010, 1, 1),
        overlap_days=10,
    )

    assert start_date.date() == date(2026, 6, 22)


def test_qmt_adj_factor_writes_final_outputs_without_legacy_module(tmp_path):
    qmt = load_qmt_module()
    raw_base = tmp_path / "raw"
    final_base = tmp_path / "final"

    raw = pd.DataFrame(
        {
            "htsc_code": ["000001.SZ", "000001.SZ", "600000.SH"],
            "event_date": pd.to_datetime(["2024-01-02", "2024-02-05", "2024-01-10"]),
            "time": [20240102, 20240205, 20240110],
            "interest": [0.0, 0.0, 0.0],
            "stockBonus": [0.0, 0.0, 0.0],
            "stockGift": [0.0, 0.0, 0.0],
            "allotNum": [0.0, 0.0, 0.0],
            "allotPrice": [0.0, 0.0, 0.0],
            "gugai": [0.0, 0.0, 0.0],
            "dr": [1.2, 1.5, 0.8],
            "updated_at": ["2026-07-02T00:00:00"] * 3,
        }
    )
    touched = set(qmt.save_raw_partitioned_parquet(raw, str(raw_base)))
    qmt.rebuild_raw_merged_parquets(str(raw_base), touched)

    qmt.write_final_outputs_from_raw(str(raw_base), str(final_base), date(2024, 2, 29), {"000001.SZ"})

    segments = pl.read_parquet(str(final_base / "adj_factor_segments.parquet"))
    assert segments.select("htsc_code").unique().to_series().to_list() == ["000001.SZ"]
    assert segments.select("begin_date", "end_date", "xdy").to_dicts() == [
        {"begin_date": date(2024, 1, 3), "end_date": date(2024, 2, 5), "xdy": 1.2},
        {"begin_date": date(2024, 2, 6), "end_date": date(2024, 2, 29), "xdy": 1.5},
    ]

    wide_jan = pl.read_parquet(str(final_base / "wide_xdy" / "year=2024" / "month=01" / "merged.parquet"))
    assert wide_jan.select("htsc_code").to_series().to_list() == ["000001.SZ"]
    assert wide_jan["2024/1/3"].to_list() == [1.2]
