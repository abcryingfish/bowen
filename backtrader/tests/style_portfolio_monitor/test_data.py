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


def test_first_usable_date_skips_empty_earlier_factor_partition(tmp_path):
    market_root, signal_root = write_fixture_partitions(tmp_path)
    empty_dir = signal_root / "factor=成长风格评分" / "year=2025" / "month=07"
    empty_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=["time", "htsc_code", "value"]).to_parquet(empty_dir / "merged.parquet", index=False)
    source = StyleDataSource(market_root=market_root, signal_root=signal_root)

    assert source.first_usable_date("成长风格评分", date(2015, 1, 1)) == date(2026, 1, 15)


def test_latest_common_date_uses_all_files_in_latest_partition(tmp_path):
    market_root, signal_root = write_fixture_partitions(tmp_path)
    latest = pd.Timestamp("2026-01-15")
    correction = pd.DataFrame([{"time": latest - pd.Timedelta(days=1), "htsc_code": "600000.SH", "value": 75.0}])
    directory = signal_root / "factor=成长风格评分" / "year=2026" / "month=01"
    correction.to_parquet(directory / "part_z_old_correction.parquet", index=False)
    source = StyleDataSource(market_root=market_root, signal_root=signal_root)

    assert source.latest_common_date("成长风格评分") == latest.date()


def test_first_usable_date_uses_earliest_date_across_first_nonempty_partition(tmp_path):
    signal_root = tmp_path / "signal"
    directory = signal_root / "factor=成长风格评分" / "year=2025" / "month=07"
    directory.mkdir(parents=True)
    pd.DataFrame(columns=["time", "htsc_code", "value"]).to_parquet(directory / "merged.parquet", index=False)
    for filename, day in (("part_a.parquet", "2025-07-31"), ("part_z.parquet", "2025-07-01")):
        pd.DataFrame([{"time": pd.Timestamp(day), "htsc_code": "600000.SH", "value": 50.0}]).to_parquet(directory / filename, index=False)
    source = StyleDataSource(market_root=tmp_path / "market", signal_root=signal_root)
    requested_starts = []
    source.available_market_dates = lambda start, end=None: requested_starts.append(start) or []

    assert source.first_usable_date("成长风格评分", date(2015, 1, 1)) is None
    assert requested_starts == [date(2025, 7, 1)]
