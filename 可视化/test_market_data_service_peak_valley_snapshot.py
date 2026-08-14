from __future__ import annotations

import pandas as pd

import market_data_service as service


def _write_factor(root, factor_name: str, value: float) -> None:
    factor_dir = root / f"factor={factor_name}" / "year=2026" / "month=08"
    factor_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "htsc_code": ["000001.SZ"],
            "time": pd.to_datetime(["2026-08-03"]),
            "value": [value],
        }
    ).to_parquet(factor_dir / "merged.parquet", index=False)


def test_factor_snapshot_reads_peak_valley_group_from_label_storage(
    monkeypatch,
    tmp_path,
) -> None:
    signal_root = tmp_path / "signal_daily"
    label_root = tmp_path / "signal_daily_label"
    signal_root.mkdir()

    factor_name = "波峰事后连续强度（label专用，有未来数据）"
    _write_factor(label_root, factor_name, 1.0)

    monkeypatch.setattr(service, "SIGNAL_DAILY_BASE_PATH", str(signal_root))
    monkeypatch.setattr(service, "SIGNAL_DAILY_LABEL_BASE_PATH", str(label_root))

    result = service.query_market_factor_snapshot(
        code="000001.SZ",
        interval="1day",
        time_ts=int(pd.Timestamp("2026-08-03", tz="UTC").timestamp()),
        mode="group",
        group_id="peak_valley_lookback_class",
    )

    assert result["factors"] == {factor_name: 1.0}


def test_core_snapshot_includes_peak_valley_group_summary(
    monkeypatch,
    tmp_path,
) -> None:
    signal_root = tmp_path / "signal_daily"
    label_root = tmp_path / "signal_daily_label"
    _write_factor(signal_root, "KDJ信号", 2.0)
    factor_name = "波峰事后连续强度（label专用，有未来数据）"
    _write_factor(label_root, factor_name, -1.0)

    monkeypatch.setattr(service, "SIGNAL_DAILY_BASE_PATH", str(signal_root))
    monkeypatch.setattr(service, "SIGNAL_DAILY_LABEL_BASE_PATH", str(label_root))

    result = service.query_market_factor_snapshot(
        code="000001.SZ",
        interval="1day",
        time_ts=int(pd.Timestamp("2026-08-03", tz="UTC").timestamp()),
        mode="core",
    )

    assert result["factors"][factor_name] == -1.0


def test_signal_reads_label_storage_when_normal_signal_root_is_missing(
    monkeypatch,
    tmp_path,
) -> None:
    label_root = tmp_path / "signal_daily_label"
    factor_name = "波峰事后连续强度（label专用，有未来数据）"
    _write_factor(label_root, factor_name, 0.75)

    monkeypatch.setattr(service, "SIGNAL_DAILY_BASE_PATH", str(tmp_path / "missing_signal_daily"))
    monkeypatch.setattr(service, "SIGNAL_DAILY_LABEL_BASE_PATH", str(label_root))

    result = service.query_market_signal(
        code="000001.SZ",
        interval="1day",
        factor=factor_name,
        from_ts=int(pd.Timestamp("2026-08-01", tz="UTC").timestamp()),
        to_ts=int(pd.Timestamp("2026-08-10", tz="UTC").timestamp()),
    )

    assert result["signals"] == [
        {"time": int(pd.Timestamp("2026-08-03", tz="UTC").timestamp()), "value": 0.75}
    ]
