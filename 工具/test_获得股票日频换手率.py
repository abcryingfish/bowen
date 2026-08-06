from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import polars as pl


MODULE_PATH = Path(__file__).with_name("获得股票日频换手率.py")
SPEC = importlib.util.spec_from_file_location("stock_daily_turnover", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def _daily_frame(dates: list[str]) -> pd.DataFrame:
    count = len(dates)
    return pd.DataFrame(
        {
            "htsc_code": ["000001.SZ"] * count,
            "time": pd.to_datetime(dates),
            "open": [10.0] * count,
            "high": [10.0] * count,
            "low": [10.0] * count,
            "close": [10.0] * count,
            "volume": [1000.0] * count,
            "value": [10000.0] * count,
        }
    )


def test_capital_becomes_effective_after_report_and_announcement_dates() -> None:
    daily = _daily_frame(
        ["2026-01-09", "2026-01-10", "2026-01-19", "2026-01-20"]
    )
    capital = pd.DataFrame(
        {
            "htsc_code": ["000001.SZ"] * 3,
            "report_date": pd.to_datetime(
                ["2026-01-01", "2026-01-05", "2026-01-20"]
            ),
            "announce_date": pd.to_datetime(
                ["2026-01-01", "2026-01-10", "2026-01-15"]
            ),
            "total_capital": [100.0, 200.0, 300.0],
            "circulating_capital": [80.0, 160.0, 240.0],
            "freeFloatCapital": [60.0, 120.0, 180.0],
        }
    )

    result = module.calculate_turnover_frame(daily, capital)

    assert result["total_capital"].tolist() == [100.0, 200.0, 200.0, 300.0]
    assert result["capital_effective_date"].tolist() == list(
        pd.to_datetime(
            ["2026-01-01", "2026-01-10", "2026-01-10", "2026-01-20"]
        )
    )


def test_market_values_use_their_corresponding_capital_fields() -> None:
    daily = _daily_frame(["2026-01-10"])
    capital = pd.DataFrame(
        {
            "htsc_code": ["000001.SZ"],
            "report_date": pd.to_datetime(["2026-01-01"]),
            "announce_date": pd.to_datetime(["2026-01-01"]),
            "total_capital": [100.0],
            "circulating_capital": [80.0],
            "freeFloatCapital": [60.0],
        }
    )

    result = module.calculate_turnover_frame(daily, capital)

    assert result.loc[0, "total_market_val"] == 1000.0
    assert result.loc[0, "floating_market_val"] == 800.0
    assert result.loc[0, "free_float_market_val"] == 600.0


def test_missing_free_float_capital_only_blanks_free_float_market_value() -> None:
    daily = _daily_frame(["2026-01-10"])
    capital = pd.DataFrame(
        {
            "htsc_code": ["000001.SZ"],
            "report_date": pd.to_datetime(["2026-01-01"]),
            "announce_date": pd.to_datetime(["2026-01-01"]),
            "total_capital": [100.0],
            "circulating_capital": [80.0],
            "freeFloatCapital": [float("nan")],
        }
    )

    result = module.calculate_turnover_frame(daily, capital)

    assert result.loc[0, "total_market_val"] == 1000.0
    assert result.loc[0, "floating_market_val"] == 800.0
    assert pd.isna(result.loc[0, "free_float_market_val"])


def test_invalid_free_float_capital_uses_previous_valid_value() -> None:
    daily = _daily_frame(
        [
            "2026-01-01",
            "2026-01-02",
            "2026-01-03",
            "2026-01-04",
            "2026-01-05",
        ]
    )
    capital = pd.DataFrame(
        {
            "htsc_code": ["000001.SZ"] * 5,
            "report_date": pd.to_datetime(
                [
                    "2025-12-01",
                    "2026-01-02",
                    "2026-01-03",
                    "2026-01-04",
                    "2026-01-05",
                ]
            ),
            "announce_date": pd.to_datetime(
                [
                    "2025-12-01",
                    "2026-01-02",
                    "2026-01-03",
                    "2026-01-04",
                    "2026-01-05",
                ]
            ),
            "total_capital": [100.0, 110.0, 120.0, 130.0, 140.0],
            "circulating_capital": [80.0, 90.0, 100.0, 110.0, 120.0],
            "freeFloatCapital": [60.0, -1.0, 0.0, 200.0, 50.0],
        }
    )

    result = module.calculate_turnover_frame(daily, capital)

    assert result["freeFloatCapital"].tolist() == [60.0, 60.0, 60.0, 60.0, 50.0]
    assert result["free_float_market_val"].tolist() == [600.0, 600.0, 600.0, 600.0, 500.0]


def test_rebuild_can_replace_existing_partition_instead_of_preserving_old_rows(
    tmp_path,
) -> None:
    partition = tmp_path / "year=2026" / "month=01"
    partition.mkdir(parents=True)
    merged = partition / "merged.parquet"
    stale_raw = partition / "old.parquet"
    raw = partition / "new.parquet"
    pl.DataFrame(
        {
            "htsc_code": ["OLD.SZ"],
            "time": [pd.Timestamp("2026-01-05")],
            "turnover_rate": [1.0],
        }
    ).write_parquet(merged)
    pl.DataFrame(
        {
            "htsc_code": ["STALE.SZ"],
            "time": [pd.Timestamp("2026-01-04")],
            "turnover_rate": [0.5],
        }
    ).write_parquet(stale_raw)
    pl.DataFrame(
        {
            "htsc_code": ["NEW.SZ"],
            "time": [pd.Timestamp("2026-01-06")],
            "turnover_rate": [2.0],
            "capital_effective_date": [pd.Timestamp("2026-01-06")],
        }
    ).write_parquet(raw)

    module.rebuild_merged_parquets(
        str(tmp_path),
        {(2026, 1)},
        replace_existing=True,
    )

    result = pl.read_parquet(merged)
    assert result["htsc_code"].to_list() == ["NEW.SZ"]
