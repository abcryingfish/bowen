from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

BT_DIR = Path(__file__).parent / "backtrader"
if str(BT_DIR) not in sys.path:
    sys.path.append(str(BT_DIR))

from models.zxw_factor_check_base_threshold.fundamental_filter import (  # noqa: E402
    _build_q4_indicator_frame,
    apply_base_threshold_filter,
)


def test_q4_indicator_uses_annual_revenue_yoy_and_roe_priority():
    income = pd.DataFrame(
        [
            {
                "htsc_code": "000001.SZ",
                "end_date": "2024-12-31",
                "announce_date": "2025-03-30",
                "revenue": 100.0,
            },
            {
                "htsc_code": "000001.SZ",
                "end_date": "2025-12-31",
                "announce_date": "2026-04-20",
                "revenue": 125.0,
            },
        ]
    )
    roe = pd.DataFrame(
        [
            {
                "htsc_code": "000001.SZ",
                "end_date": "2025-12-31",
                "announce_date": "2026-04-21",
                "equity_roe": None,
                "net_roe": 12.0,
                "du_return_on_equity": 15.0,
            }
        ]
    )

    indicator = _build_q4_indicator_frame(income, roe)
    row = indicator[indicator["end_date"].eq(pd.Timestamp("2025-12-31"))].iloc[0]

    assert row["announce_date"] == pd.Timestamp("2026-04-20")
    assert row["roe"] == 12.0
    assert row["oper_revenue_yoy"] == 25.0


def test_base_threshold_matches_q4_indicators_after_announce_date_only():
    bt_df = pd.DataFrame(
        [
            {"htsc_code": "000001.SZ", "time": "2026-04-19", "strong_buy_signal": 1.0},
            {"htsc_code": "000001.SZ", "time": "2026-04-20", "strong_buy_signal": 1.0},
        ]
    )
    valuation = pd.DataFrame(
        [
            {"htsc_code": "000001.SZ", "time": "2026-04-19", "pe": None, "pettm": 20.0, "pb": 2.0},
            {"htsc_code": "000001.SZ", "time": "2026-04-20", "pe": None, "pettm": 20.0, "pb": 2.0},
        ]
    )
    indicator = pd.DataFrame(
        [
            {
                "htsc_code": "000001.SZ",
                "end_date": "2025-12-31",
                "announce_date": "2026-04-20",
                "roe": 12.0,
                "weighted_roe": None,
                "cut_roe": None,
                "oper_revenue_yoy": 25.0,
            }
        ]
    )

    filtered, stats = apply_base_threshold_filter(bt_df, valuation, indicator)

    by_date = filtered.set_index(filtered["time"].dt.strftime("%Y-%m-%d"))
    assert by_date.loc["2026-04-19", "strong_buy_signal"] == 0.0
    assert by_date.loc["2026-04-20", "strong_buy_signal"] == 1.0
    assert stats["raw_buy_signals"] == 2
    assert stats["kept_buy_signals"] == 1


def test_base_threshold_rejects_negative_pe():
    bt_df = pd.DataFrame(
        [
            {"htsc_code": "000001.SZ", "time": "2026-04-20", "strong_buy_signal": 1.0},
        ]
    )
    valuation = pd.DataFrame(
        [
            {"htsc_code": "000001.SZ", "time": "2026-04-20", "pe": None, "pettm": -20.0, "pb": 2.0},
        ]
    )
    indicator = pd.DataFrame(
        [
            {
                "htsc_code": "000001.SZ",
                "end_date": "2025-12-31",
                "announce_date": "2026-04-20",
                "roe": 12.0,
                "weighted_roe": None,
                "cut_roe": None,
                "oper_revenue_yoy": 25.0,
            }
        ]
    )

    filtered, stats = apply_base_threshold_filter(bt_df, valuation, indicator)

    assert filtered.loc[0, "strong_buy_signal"] == 0.0
    assert stats["raw_buy_signals"] == 1
    assert stats["kept_buy_signals"] == 0


def test_q4_indicator_exposes_five_year_rolling_average_roe():
    roe = pd.DataFrame(
        [
            {
                "htsc_code": "000001.SZ",
                "end_date": f"{year}-12-31",
                "announce_date": f"{year + 1}-04-20",
                "equity_roe": value,
                "net_roe": None,
                "du_return_on_equity": None,
            }
            for year, value in [
                (2020, 5.0),
                (2021, 10.0),
                (2022, 15.0),
                (2023, 20.0),
                (2024, 25.0),
                (2025, 30.0),
            ]
        ]
    )

    indicator = _build_q4_indicator_frame(pd.DataFrame(), roe)
    rows = indicator.set_index(indicator["end_date"].dt.strftime("%Y-%m-%d"))

    assert pd.isna(rows.loc["2021-12-31", "roe_5y_avg"])
    assert rows.loc["2022-12-31", "roe_5y_avg"] == 10.0
    assert rows.loc["2025-12-31", "roe_5y_avg"] == 20.0


def test_base_threshold_uses_five_year_average_roe_for_filter():
    bt_df = pd.DataFrame(
        [
            {"htsc_code": "000001.SZ", "time": "2026-04-20", "strong_buy_signal": 1.0},
        ]
    )
    valuation = pd.DataFrame(
        [
            {"htsc_code": "000001.SZ", "time": "2026-04-20", "pe": None, "pettm": 20.0, "pb": 2.0},
        ]
    )
    indicator = pd.DataFrame(
        [
            {
                "htsc_code": "000001.SZ",
                "end_date": "2025-12-31",
                "announce_date": "2026-04-20",
                "roe": 30.0,
                "roe_5y_avg": 9.0,
                "weighted_roe": None,
                "cut_roe": None,
                "oper_revenue_yoy": 25.0,
            }
        ]
    )

    filtered, stats = apply_base_threshold_filter(bt_df, valuation, indicator)

    assert filtered.loc[0, "strong_buy_signal"] == 0.0
    assert stats["raw_buy_signals"] == 1
    assert stats["kept_buy_signals"] == 0
