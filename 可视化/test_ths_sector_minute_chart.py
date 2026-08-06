from __future__ import annotations

from datetime import datetime, timezone

import polars as pl

import market_data_service as service


def _unix_seconds(value: datetime) -> int:
    return int(value.replace(tzinfo=timezone.utc).timestamp())


def test_ths_code_routes_to_index_minute_data(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "INDEX_MINUTE_BASE_PATH", str(tmp_path))
    monkeypatch.setattr(service, "is_index_market_code", lambda code: code.upper().endswith(".THS"))

    assert service.get_base_path_by_code_and_interval("881121.THS", "1min") == str(tmp_path)
    assert service.get_base_path_by_code_and_interval("881121.THS", "1day") == service.INDEX_DAILY_BASE_PATH


def test_ths_minute_query_reads_daily_partition(monkeypatch, tmp_path):
    minute_time = datetime(2026, 7, 31, 9, 30)
    partition = tmp_path / "year=2026" / "month=07" / "day=31"
    partition.mkdir(parents=True)
    pl.DataFrame(
        {
            "htsc_code": ["881121.THS"],
            "time": [minute_time],
            "open": [1000.0],
            "high": [1002.0],
            "low": [999.0],
            "close": [1001.0],
            "volume": [123.0],
        }
    ).write_parquet(partition / "merged.parquet")
    monkeypatch.setattr(service, "INDEX_MINUTE_BASE_PATH", str(tmp_path))
    monkeypatch.setattr(service, "is_index_market_code", lambda code: code.upper().endswith(".THS"))

    result = service.query_market_bars(
        code="881121.THS",
        interval="1min",
        from_ts=_unix_seconds(datetime(2026, 7, 31, 9, 30)),
        to_ts=_unix_seconds(datetime(2026, 7, 31, 9, 31)),
        limit=100,
    )

    assert result["meta"]["base_path"] == str(tmp_path)
    assert result["bars"] == [
        {
            "time": _unix_seconds(minute_time),
            "open": 1000.0,
            "high": 1002.0,
            "low": 999.0,
            "close": 1001.0,
            "volume": 123.0,
        }
    ]
