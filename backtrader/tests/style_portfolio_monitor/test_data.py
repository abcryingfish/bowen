from datetime import date
from pathlib import Path

import pandas as pd

from models.style_portfolio_monitor.data import StyleDataSource


def _write_partitioned(frame: pd.DataFrame, root: Path, *, factor_name: str | None = None) -> None:
    base = root / (f"factor={factor_name}" if factor_name else "")
    for (year, month), part in frame.groupby([frame["time"].dt.year, frame["time"].dt.month]):
        directory = base / f"year={year}" / f"month={month:02d}"
        directory.mkdir(parents=True, exist_ok=True)
        part.to_parquet(directory / "merged.parquet", index=False)


def write_fixture_partitions(tmp_path: Path, *, merged_score: float = 40.0, part_score: float | None = None, missing_score_code: str | None = None):
    market_root = tmp_path / "market"
    signal_root = tmp_path / "signal"
    dates = pd.bdate_range("2025-08-01", periods=120)
    rows = []
    for day in dates:
        for code, value in [("600000.SH", 25_000_000.0), ("000001.SZ", 25_000_000.0), ("000002.BJ", 25_000_000.0), ("881001.THS", 25_000_000.0), ("300001.SZ", 1_000_000.0)]:
            rows.append({"time": day, "htsc_code": code, "close": 10.0, "volume": 100_000.0, "value": value})
    market = pd.DataFrame(rows)
    _write_partitioned(market, market_root)
    scores = pd.DataFrame(
        [{"time": day, "htsc_code": code, "value": (None if code == missing_score_code else merged_score)} for day in dates for code in ["600000.SH", "000001.SZ"]]
    )
    _write_partitioned(scores, signal_root, factor_name="成长风格评分")
    if part_score is not None:
        part = scores[(scores["time"] == dates[-1]) & (scores["htsc_code"] == "600000.SH")].copy()
        part["value"] = part_score
        directory = signal_root / "factor=成长风格评分" / f"year={dates[-1].year}" / f"month={dates[-1].month:02d}"
        part.to_parquet(directory / "part_override.parquet", index=False)
    return market_root, signal_root


def test_build_eligible_snapshot_filters_market_history_liquidity_and_missing_values(tmp_path):
    market_root, signal_root = write_fixture_partitions(tmp_path)
    source = StyleDataSource(market_root=market_root, signal_root=signal_root)
    snapshot = source.build_eligible_snapshot(date(2026, 1, 15), "成长风格评分")
    assert set(snapshot["htsc_code"]) == {"600000.SH", "000001.SZ"}
    assert snapshot.iloc[0]["average_turnover_20d"] >= 20_000_000
    assert snapshot.iloc[0]["history_days"] >= 120


def test_factor_part_file_overrides_merged_for_same_date_and_code(tmp_path):
    market_root, signal_root = write_fixture_partitions(tmp_path, merged_score=40.0, part_score=80.0)
    source = StyleDataSource(market_root=market_root, signal_root=signal_root)
    snapshot = source.build_eligible_snapshot(date(2026, 1, 15), "成长风格评分")
    assert snapshot.set_index("htsc_code").loc["600000.SH", "score"] == 80.0


def test_factor_coverage_uses_tradable_universe_before_score_filter(tmp_path):
    market_root, signal_root = write_fixture_partitions(tmp_path, missing_score_code="000001.SZ")
    source = StyleDataSource(market_root=market_root, signal_root=signal_root)
    snapshot = source.build_eligible_snapshot(date(2026, 1, 15), "成长风格评分")
    assert snapshot.attrs["tradable_count"] == 2
    assert snapshot.attrs["factor_valid_count"] == 1
    assert snapshot.attrs["factor_coverage"] == 0.5


def test_close_prices_does_not_hide_missing_current_day_with_old_price(tmp_path):
    market_root, signal_root = write_fixture_partitions(tmp_path)
    source = StyleDataSource(market_root=market_root, signal_root=signal_root)
    assert source.close_prices(date(2026, 1, 16), ["600000.SH"]) == {}
