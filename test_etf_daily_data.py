from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import polars as pl


ROOT = Path(__file__).resolve().parent
ETF_SCRIPT = ROOT / "工具" / "获得ETF日频数据.py"
VIS_DIR = ROOT / "可视化"


def load_etf_module():
    spec = importlib.util.spec_from_file_location("etf_daily_data_download", ETF_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_etf_universe_rows_deduplicate_codes_and_keep_sector_memberships():
    etf = load_etf_module()

    rows = etf.build_etf_universe_rows(
        {
            "沪深ETF": ["510050.SH", "159915.SZ"],
            "ETF股票型": ["510050.SH", "513100.SH"],
        },
        detail_by_code={
            "510050.SH": {"name": "上证50ETF", "exchange": "SH"},
            "159915.SZ": {"name": "创业板ETF", "exchange": "SZ"},
            "513100.SH": {"name": "纳指ETF", "exchange": "SH"},
        },
    )

    universe = rows["universe"]
    members = rows["members"]

    assert universe["htsc_code"].to_list() == ["159915.SZ", "510050.SH", "513100.SH"]
    assert universe.filter(pl.col("htsc_code") == "510050.SH")["sector_names"][0] == "ETF股票型,沪深ETF"
    assert members.select(["sector_name", "htsc_code"]).rows() == [
        ("ETF股票型", "510050.SH"),
        ("ETF股票型", "513100.SH"),
        ("沪深ETF", "159915.SZ"),
        ("沪深ETF", "510050.SH"),
    ]


def test_global_incremental_start_uses_max_time_across_all_etfs(tmp_path):
    etf = load_etf_module()
    part_dir = tmp_path / "year=2026" / "month=07"
    part_dir.mkdir(parents=True)
    pl.DataFrame(
        [
            {"htsc_code": "510050.SH", "time": datetime(2026, 7, 3)},
            {"htsc_code": "159915.SZ", "time": datetime(2026, 7, 6)},
        ]
    ).write_parquet(part_dir / "merged.parquet")

    start = etf.resolve_download_start_date(
        base_dir=str(tmp_path),
        default_start_date=datetime(2010, 1, 1),
        no_incremental=False,
    )

    assert start == datetime(2026, 7, 7)


def test_chunk_codes_defaults_to_batches_of_30():
    etf = load_etf_module()
    codes = [f"{idx:06d}.SH" for idx in range(65)]

    chunks = list(etf.chunk_codes(codes, 30))

    assert [len(chunk) for chunk in chunks] == [30, 30, 5]


def test_normalize_xtquant_etf_daily_dataframe_uses_etf_security_type():
    etf = load_etf_module()
    raw = pd.DataFrame(
        [
            {
                "time": "20260706",
                "open": 1.0,
                "high": 1.2,
                "low": 0.9,
                "close": 1.1,
                "volume": 100,
                "amount": 1200.0,
            }
        ]
    )

    out = etf.normalize_xtquant_etf_daily_dataframe(raw, "510050.SH")

    assert out.loc[0, "htsc_code"] == "510050.SH"
    assert out.loc[0, "security_type"] == "etf"
    assert out.loc[0, "frequency"] == "daily"
    assert out.loc[0, "value"] == 1200.0


def test_market_service_routes_etf_daily_and_rejects_minute(monkeypatch):
    if str(VIS_DIR) not in sys.path:
        sys.path.append(str(VIS_DIR))
    import market_data_service as svc

    monkeypatch.setattr(svc, "ETF_DAILY_BASE_PATH", r"D:\database\ETF_basic_data_daily")
    monkeypatch.setattr(svc, "_etf_market_code_cache", {"510050.SH"})

    assert svc.get_base_path_by_code_and_interval("510050.SH", "1day") == r"D:\database\ETF_basic_data_daily"
    try:
        svc.get_base_path_by_code_and_interval("510050.SH", "1min")
    except svc.MarketDataValidationError as exc:
        assert "ETF" in str(exc)
    else:
        raise AssertionError("ETF minute route should be rejected")
