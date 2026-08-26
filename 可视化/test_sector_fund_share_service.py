from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pytest

import sector_concentration_service as service
from market_data_service import MarketDataValidationError


def _write_fixture_data(tmp_path: Path) -> tuple[Path, Path]:
    snapshot_root = tmp_path / "snapshots"
    snapshot_dir = snapshot_root / "analysis_date=2026-01-05"
    snapshot_dir.mkdir(parents=True)
    daily_root = tmp_path / "daily"
    daily_dir = daily_root / "year=2026" / "month=01"
    daily_dir.mkdir(parents=True)

    conn = duckdb.connect(database=":memory:")
    try:
        conn.execute(
            """
            COPY (
                SELECT * FROM (VALUES
                    ('881001.THS', '000001.SZ', TRUE),
                    ('881002.THS', '000002.SZ', TRUE),
                    ('885001.THS', '000001.SZ', TRUE),
                    ('885002.THS', '000001.SZ', TRUE),
                    ('885002.THS', '000002.SZ', TRUE)
                ) AS t(sector_code, stock_code, eligible)
            ) TO ? (FORMAT PARQUET)
            """,
            [str(snapshot_dir / "part-000.parquet")],
        )
        conn.execute(
            """
            COPY (
                SELECT * FROM (VALUES
                    ('000001.SZ', TIMESTAMP '2026-01-04 00:00:00', 30.0),
                    ('000002.SZ', TIMESTAMP '2026-01-04 00:00:00', 70.0),
                    ('000001.SZ', TIMESTAMP '2026-01-05 00:00:00', 60.0),
                    ('000002.SZ', TIMESTAMP '2026-01-05 00:00:00', 40.0),
                    ('000003.SZ', TIMESTAMP '2026-01-05 00:00:00', 0.0)
                ) AS t(htsc_code, time, value)
            ) TO ? (FORMAT PARQUET)
            """,
            [str(daily_dir / "merged.parquet")],
        )
    finally:
        conn.close()
    return snapshot_root, daily_root


def test_sector_fund_share_uses_all_a_denominator_without_concept_normalization(tmp_path, monkeypatch):
    snapshot_root, daily_root = _write_fixture_data(tmp_path)
    monkeypatch.setattr(service, "SNAPSHOT_BASE_PATH", snapshot_root)
    monkeypatch.setattr(service, "DAILY_BASE_PATH", daily_root)
    service.clear_sector_fund_share_cache()
    from_ts = datetime(2026, 1, 1).timestamp()
    to_ts = datetime(2026, 1, 6).timestamp()

    industries = service.query_sector_fund_shares("881", from_ts, to_ts)
    industry_shares = {
        (point["sector_code"], point["date"]): point["fund_share_pct"]
        for point in industries["points"]
    }
    assert industry_shares == {
        ("881001.THS", "2026-01-04"): 30.0,
        ("881001.THS", "2026-01-05"): 60.0,
        ("881002.THS", "2026-01-04"): 70.0,
        ("881002.THS", "2026-01-05"): 40.0,
    }
    assert industries["meta"]["metric_type"] == "market_share"
    assert industries["meta"]["component_mode"] == "latest_snapshot_full_history"
    assert industries["meta"]["snapshot_date"] == "2026-01-05"
    first_point = industries["points"][0]
    assert datetime.fromtimestamp(first_point["time"], tz=timezone.utc).date().isoformat() == first_point["date"]

    concepts = service.query_sector_fund_shares("885", from_ts, to_ts)
    latest_concept_shares = {
        point["sector_code"]: point["fund_share_pct"]
        for point in concepts["points"]
        if point["date"] == "2026-01-05"
    }
    assert latest_concept_shares == {"885001.THS": 60.0, "885002.THS": 100.0}
    assert sum(latest_concept_shares.values()) == 160.0
    assert concepts["meta"]["metric_type"] == "market_coverage"
    assert concepts["meta"]["overlapping_memberships"] is True


def test_sector_fund_share_rejects_unknown_prefix():
    with pytest.raises(MarketDataValidationError, match="prefix"):
        service.query_sector_fund_shares("883")
