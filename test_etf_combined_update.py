# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT_PATH = Path(__file__).resolve().parent / "工具" / "ETF日频数据_合并更新.py"


def load_module():
    spec = importlib.util.spec_from_file_location("etf_combined_update", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_sector_csv_frame_matches_existing_schema():
    module = load_module()

    frame = module.build_sector_csv_frame("沪深ETF", ["510300.SH", "159915.SZ"], snapshot_time="2026-07-07 09:30:00")

    assert list(frame.columns) == [
        "snapshot_date",
        "snapshot_time",
        "sector_name",
        "rank_in_return",
        "etf_code",
        "market",
        "source_api",
    ]
    assert frame.to_dict("records") == [
        {
            "snapshot_date": "2026-07-07",
            "snapshot_time": "2026-07-07 09:30:00",
            "sector_name": "沪深ETF",
            "rank_in_return": 1,
            "etf_code": "510300.SH",
            "market": "SH",
            "source_api": "xtdata.get_stock_list_in_sector",
        },
        {
            "snapshot_date": "2026-07-07",
            "snapshot_time": "2026-07-07 09:30:00",
            "sector_name": "沪深ETF",
            "rank_in_return": 2,
            "etf_code": "159915.SZ",
            "market": "SZ",
            "source_api": "xtdata.get_stock_list_in_sector",
        },
    ]


def test_write_sector_csvs_uses_utf8_sig_and_overwrites(tmp_path):
    module = load_module()

    sector_map = {
        "沪深ETF": ["510300.SH"],
        "深市ETF": ["159915.SZ", "159919.SZ"],
    }
    written = module.write_sector_csvs(sector_map, tmp_path, snapshot_time="2026-07-07 09:30:00")

    assert sorted(path.name for path in written) == sorted(f"{name}.csv" for name in module.DEFAULT_ETF_SECTOR_NAMES)
    raw = (tmp_path / "沪深ETF.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    df = pd.read_csv(tmp_path / "深市ETF.csv", encoding="utf-8-sig")
    assert df["etf_code"].tolist() == ["159915.SZ", "159919.SZ"]


def test_combined_script_is_standalone():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "importlib" not in source
    assert "SOURCE_SCRIPT" not in source
    assert "_load_etf_daily_module" not in source
    assert "获得ETF日频数据.py" not in source
