from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import polars as pl


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "工具" / "形态蜡烛信号生成_合并保存.py"


def load_module():
    spec = importlib.util.spec_from_file_location("morph_candlestick_combined", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_auto_plan_uses_global_latest_event_day_as_incremental_mark_for_missing_stock():
    module = load_module()
    signal_latest = {
        "000001.SZ": pd.Timestamp("2026-07-03"),
        "000002.SZ": pd.Timestamp("2026-07-02"),
    }
    market_max = {
        "000001.SZ": pd.Timestamp("2026-07-06"),
        "000002.SZ": pd.Timestamp("2026-07-06"),
        "001399.SZ": pd.Timestamp("2026-07-06"),
    }

    plan = module.build_stock_fill_plan(
        ["000001.SZ", "000002.SZ", "001399.SZ"],
        signal_latest,
        market_max,
        start_date="2010-01-01",
        end_date="2026-07-07",
        lookback_days=65,
    )

    need = plan[plan["status"].isin(["missing", "stale"])]

    assert need["plan_start"].min() == pd.Timestamp("2026-07-03")
    missing = plan[plan["htsc_code"].eq("001399.SZ")].iloc[0]
    assert missing["status"] == "missing"
    assert missing["plan_start"] == pd.Timestamp("2026-07-03")


def test_auto_plan_backfills_missing_non_stock_code_from_start_date():
    module = load_module()
    signal_latest = {
        "000001.SZ": pd.Timestamp("2026-07-03"),
    }
    market_max = {
        "000001.SZ": pd.Timestamp("2026-07-06"),
        "510300.SH": pd.Timestamp("2026-07-06"),
    }

    plan = module.build_stock_fill_plan(
        ["000001.SZ", "510300.SH"],
        signal_latest,
        market_max,
        start_date="2010-01-01",
        end_date="2026-07-07",
        lookback_days=65,
        full_history_missing_codes={"510300.SH"},
    )

    etf = plan[plan["htsc_code"].eq("510300.SH")].iloc[0]
    assert etf["status"] == "missing"
    assert etf["plan_start"] == pd.Timestamp("2010-01-01")


def _write_daily_partition(root: Path, code: str) -> None:
    month_dir = root / "year=2026" / "month=07"
    month_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "htsc_code": [code],
            "time": ["2026-07-01"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
        }
    ).write_parquet(month_dir / "merged.parquet")


def test_combined_script_reads_stock_and_etf_daily_sources(tmp_path):
    module = load_module()
    stock_root = tmp_path / "stock_basic_data_daily"
    etf_root = tmp_path / "ETF_basic_data_daily"
    _write_daily_partition(stock_root, "000001.SZ")
    _write_daily_partition(etf_root, "510300.SH")

    source_paths = [str(stock_root), str(etf_root)]

    codes = module.fetch_universe_codes_from_market_equity(source_paths)
    assert codes == ["000001.SZ", "510300.SH"]

    _market_min, market_max = module.scan_market_date_range_by_code(source_paths)
    assert set(market_max) == {"000001.SZ", "510300.SH"}

    open_prices, high_prices, low_prices, close_prices, volume = module.load_ohlcv_from_duckdb(
        source_paths,
        query_start_date="2026-07-01",
        query_end_date="2026-07-01",
        target_codes=None,
        adj_wide_base_path=str(tmp_path / "missing_adj"),
    )

    assert open_prices.columns.tolist() == ["000001.SZ", "510300.SH"]
    assert high_prices.columns.tolist() == ["000001.SZ", "510300.SH"]
    assert low_prices.columns.tolist() == ["000001.SZ", "510300.SH"]
    assert close_prices.columns.tolist() == ["000001.SZ", "510300.SH"]
    assert volume.columns.tolist() == ["000001.SZ", "510300.SH"]
