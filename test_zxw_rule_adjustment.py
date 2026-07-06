from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

BT_DIR = Path(__file__).parent / "backtrader"
if str(BT_DIR) not in sys.path:
    sys.path.append(str(BT_DIR))

from models.zxw_rule_backtest import zxw_view_results_full as zxw  # noqa: E402


def test_apply_ohlc_adj_to_price_df_uses_backward_ratio_wide_xdy(tmp_path):
    wide_dir = tmp_path / "wide_xdy" / "year=2024" / "month=01"
    wide_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "htsc_code": "000001.SZ",
                "2024/1/1": 1.0,
                "2024/1/2": 1.0,
                "2024/1/3": 2.0,
                "2024/1/4": 2.0,
            }
        ]
    ).to_parquet(wide_dir / "merged.parquet")
    price = pd.DataFrame(
        [
            {"htsc_code": "000001.SZ", "time": "2024-01-01", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100},
            {"htsc_code": "000001.SZ", "time": "2024-01-02", "open": 20.0, "high": 21.0, "low": 19.0, "close": 20.5, "volume": 200},
            {"htsc_code": "000001.SZ", "time": "2024-01-03", "open": 30.0, "high": 31.0, "low": 29.0, "close": 30.5, "volume": 300},
            {"htsc_code": "000001.SZ", "time": "2024-01-04", "open": 40.0, "high": 41.0, "low": 39.0, "close": 40.5, "volume": 400},
        ]
    )

    old_base = zxw.ADJ_BASE_PATH
    try:
        zxw.ADJ_BASE_PATH = str(tmp_path)
        adjusted = zxw.apply_ohlc_adj_to_price_df(
            price,
            target_codes=["000001.SZ"],
            query_start_date="2024-01-01",
            query_end_exclusive="2024-01-05",
            adj_mode="backward_ratio",
        )
    finally:
        zxw.ADJ_BASE_PATH = old_base

    by_day = adjusted.set_index(adjusted["time"].dt.strftime("%Y-%m-%d"))
    assert by_day.loc["2024-01-01", "close"] == 10.5
    assert by_day.loc["2024-01-02", "close"] == 20.5
    assert by_day.loc["2024-01-03", "close"] == 61.0
    assert by_day.loc["2024-01-04", "open"] == 80.0
    assert by_day.loc["2024-01-04", "volume"] == 400


def test_backward_ratio_carries_last_factor_after_wide_xdy_ends(tmp_path):
    wide_dir = tmp_path / "wide_xdy" / "year=2024" / "month=01"
    wide_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "htsc_code": "000001.SZ",
                "2024/1/2": 2.0,
                "2024/1/3": 2.0,
                "2024/1/4": 3.0,
            }
        ]
    ).to_parquet(wide_dir / "merged.parquet")
    price = pd.DataFrame(
        [
            {"htsc_code": "000001.SZ", "time": "2024-01-01", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100},
            {"htsc_code": "000001.SZ", "time": "2024-01-04", "open": 20.0, "high": 21.0, "low": 19.0, "close": 20.5, "volume": 200},
            {"htsc_code": "000001.SZ", "time": "2024-01-05", "open": 30.0, "high": 31.0, "low": 29.0, "close": 30.5, "volume": 300},
        ]
    )

    old_base = zxw.ADJ_BASE_PATH
    try:
        zxw.ADJ_BASE_PATH = str(tmp_path)
        adjusted = zxw.apply_ohlc_adj_to_price_df(
            price,
            target_codes=["000001.SZ"],
            query_start_date="2024-01-01",
            query_end_exclusive="2024-01-06",
            adj_mode="backward_ratio",
        )
    finally:
        zxw.ADJ_BASE_PATH = old_base

    by_day = adjusted.set_index(adjusted["time"].dt.strftime("%Y-%m-%d"))
    assert by_day.loc["2024-01-01", "close"] == 10.5
    assert by_day.loc["2024-01-04", "open"] == 120.0
    assert by_day.loc["2024-01-05", "open"] == 180.0


def test_backward_ratio_combines_same_code_across_wide_xdy_months(tmp_path):
    jan_dir = tmp_path / "wide_xdy" / "year=2024" / "month=01"
    feb_dir = tmp_path / "wide_xdy" / "year=2024" / "month=02"
    jan_dir.mkdir(parents=True)
    feb_dir.mkdir(parents=True)
    pd.DataFrame([{"htsc_code": "000001.SZ", "2024/1/31": 2.0}]).to_parquet(jan_dir / "merged.parquet")
    pd.DataFrame([{"htsc_code": "000001.SZ", "2024/2/1": 3.0}]).to_parquet(feb_dir / "merged.parquet")
    price = pd.DataFrame(
        [
            {"htsc_code": "000001.SZ", "time": "2024-01-31", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100},
            {"htsc_code": "000001.SZ", "time": "2024-02-01", "open": 20.0, "high": 21.0, "low": 19.0, "close": 20.5, "volume": 200},
        ]
    )

    old_base = zxw.ADJ_BASE_PATH
    try:
        zxw.ADJ_BASE_PATH = str(tmp_path)
        adjusted = zxw.apply_ohlc_adj_to_price_df(
            price,
            target_codes=["000001.SZ"],
            query_start_date="2024-01-31",
            query_end_exclusive="2024-02-02",
            adj_mode="backward_ratio",
        )
    finally:
        zxw.ADJ_BASE_PATH = old_base

    by_day = adjusted.set_index(adjusted["time"].dt.strftime("%Y-%m-%d"))
    assert by_day.loc["2024-01-31", "open"] == 20.0
    assert by_day.loc["2024-02-01", "open"] == 120.0


def test_backward_ratio_reads_only_months_overlapping_query_range(tmp_path):
    dec_dir = tmp_path / "wide_xdy" / "year=2023" / "month=12"
    jan_dir = tmp_path / "wide_xdy" / "year=2024" / "month=01"
    dec_dir.mkdir(parents=True)
    jan_dir.mkdir(parents=True)
    pd.DataFrame([{"htsc_code": "000001.SZ", "2023/12/29": 99.0}]).to_parquet(dec_dir / "merged.parquet")
    pd.DataFrame([{"htsc_code": "000001.SZ", "2024/1/2": 2.0}]).to_parquet(jan_dir / "merged.parquet")
    price = pd.DataFrame(
        [
            {"htsc_code": "000001.SZ", "time": "2024-01-02", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100},
        ]
    )

    old_base = zxw.ADJ_BASE_PATH
    try:
        zxw.ADJ_BASE_PATH = str(tmp_path)
        adjusted = zxw.apply_ohlc_adj_to_price_df(
            price,
            target_codes=["000001.SZ"],
            query_start_date="2024-01-01",
            query_end_exclusive="2024-02-01",
            adj_mode="backward_ratio",
        )
    finally:
        zxw.ADJ_BASE_PATH = old_base

    assert adjusted.loc[0, "open"] == 20.0
