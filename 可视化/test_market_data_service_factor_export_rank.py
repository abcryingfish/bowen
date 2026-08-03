from __future__ import annotations

import csv

import pandas as pd

import market_data_service as service


def test_factor_rank_export_uses_codes_present_in_selected_factor(monkeypatch, tmp_path):
    factor_name = "板块PB历史分位_5年_整体法"
    month_dir = tmp_path / f"factor={factor_name}" / "year=2026" / "month=07"
    month_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-07-29"] * 4),
            "htsc_code": ["000001.SZ", "510300.SH", "881101.THS", "881102.THS"],
            "value": [1.0, 0.9, 0.8, 0.2],
        }
    ).to_parquet(month_dir / "merged.parquet", index=False)

    export_home = tmp_path / "home"
    (export_home / "Desktop").mkdir(parents=True)
    monkeypatch.setattr(service.Path, "home", lambda: export_home)
    monkeypatch.setattr(service, "_get_cached_factor_names", lambda *_args, **_kwargs: [factor_name])
    monkeypatch.setattr(service, "_get_factor_export_rank_codes", lambda: ["000001.SZ"])
    monkeypatch.setattr(
        service,
        "_load_stock_universe_records",
        lambda: [{"code": "000001.SZ", "name": "平安银行"}],
    )
    monkeypatch.setattr(
        service,
        "_load_etf_universe_records",
        lambda: [{"code": "510300.SH", "name": "沪深300ETF"}],
    )
    monkeypatch.setattr(
        service,
        "_load_index_universe_records",
        lambda: [{"code": "881101.THS", "name": "行业甲"}],
    )

    result = service.export_market_factor_rank_csv(
        time_ts=int(pd.Timestamp("2026-07-29", tz="UTC").timestamp()),
        factor=factor_name,
        base_path=str(tmp_path),
    )

    with open(result["file_path"], newline="", encoding="utf-8-sig") as csv_file:
        rows = list(csv.DictReader(csv_file))

    assert list(rows[0]) == ["时间", "标的代码", "标的名称", "因子值"]
    assert [row["标的代码"] for row in rows] == [
        "000001.SZ",
        "510300.SH",
        "881101.THS",
        "881102.THS",
    ]
    assert [row["标的名称"] for row in rows] == ["平安银行", "沪深300ETF", "行业甲", ""]
    assert [float(row["因子值"]) for row in rows] == [1.0, 0.9, 0.8, 0.2]
    assert result["meta"]["row_count"] == 4
    assert result["meta"]["missing_count"] == 0
