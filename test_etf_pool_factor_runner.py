from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

import pandas as pd
import polars as pl


ROOT = Path(__file__).resolve().parent
ETF_FACTOR_SCRIPT = ROOT / "ZXW因子-股票池ETF分类" / "run_etf_factors.py"


def load_runner_module():
    spec = importlib.util.spec_from_file_location("etf_pool_factor_runner", ETF_FACTOR_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_pool_codes_detects_etf_code_column_and_filters_existing_etfs(tmp_path):
    runner = load_runner_module()
    pool_file = tmp_path / "ETF行业指数.csv"
    pool_file.write_text(
        "snapshot_date,sector_name,rank_in_return,etf_code,market\n"
        "2026-07-07,ETF行业指数,1,510200.SH,SH\n"
        "2026-07-07,ETF行业指数,2,159996.SZ,SZ\n"
        "2026-07-07,ETF行业指数,3,000001.SZ,SZ\n",
        encoding="utf-8-sig",
    )

    result = runner.load_pool_codes(pool_file, existing_etf_codes={"510200.SH", "159996.SZ"})

    assert result.codes == ["510200.SH", "159996.SZ"]
    assert result.code_column == "etf_code"
    assert result.raw_code_count == 3
    assert result.skipped_codes == [{"code": "000001.SZ", "reason": "not_in_etf_daily_data"}]


def test_build_wide_ohlcv_uses_stock_factor_matrix_shape():
    runner = load_runner_module()
    daily = pl.DataFrame(
        [
            {"htsc_code": "510200.SH", "time": datetime(2026, 7, 1), "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 100.0},
            {"htsc_code": "159996.SZ", "time": datetime(2026, 7, 1), "open": 2.0, "high": 2.2, "low": 1.9, "close": 2.1, "volume": 200.0},
            {"htsc_code": "510200.SH", "time": datetime(2026, 7, 2), "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2, "volume": 110.0},
        ]
    ).to_pandas()

    wide = runner.build_wide_ohlcv(daily, codes=["510200.SH", "159996.SZ"])

    assert list(wide["C"].columns) == ["510200.SH", "159996.SZ"]
    assert list(wide["C"].index) == [pd.Timestamp("2026-07-01"), pd.Timestamp("2026-07-02")]
    assert wide["C"].loc[pd.Timestamp("2026-07-01"), "159996.SZ"] == 2.1
    assert pd.isna(wide["C"].loc[pd.Timestamp("2026-07-02"), "159996.SZ"])
    assert wide["VALID_BAR"].equals(wide["C"].notna())


def test_save_factor_frame_keeps_existing_rows_and_preserves_nan(tmp_path):
    runner = load_runner_module()
    output_root = tmp_path / "signal_daily_etf"
    existing_dir = output_root / "factor=demo_factor" / "year=2026" / "month=07"
    existing_dir.mkdir(parents=True)
    pl.DataFrame(
        [
            {"time": datetime(2026, 7, 1), "htsc_code": "510200.SH", "value": 9.0},
        ]
    ).write_parquet(existing_dir / "merged.parquet")

    frame = pd.DataFrame(
        {
            "510200.SH": [1.0, float("nan")],
            "159996.SZ": [2.0, 3.0],
        },
        index=pd.to_datetime(["2026-07-01", "2026-07-02"]),
    )

    stats = runner.save_factor_frame_no_overwrite(
        frame,
        factor_name="demo_factor",
        output_root=output_root,
        save_after=pd.Timestamp("2026-07-01"),
    )

    saved = pl.read_parquet(existing_dir / "merged.parquet").sort(["time", "htsc_code"])
    assert saved.columns == ["time", "htsc_code", "value"]
    assert saved.filter((pl.col("time") == datetime(2026, 7, 1)) & (pl.col("htsc_code") == "510200.SH"))["value"][0] == 9.0
    assert saved.filter(pl.col("time") == datetime(2026, 7, 2)).height == 2
    assert saved.filter((pl.col("time") == datetime(2026, 7, 2)) & (pl.col("htsc_code") == "510200.SH"))["value"][0] is None
    assert stats["rows_written"] == 2
    assert stats["partitions_written"] == 1
