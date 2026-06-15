import importlib
import sys
from pathlib import Path

import pandas as pd
import polars as pl
import pytest


VIS_DIR = Path(__file__).parent
if str(VIS_DIR) not in sys.path:
    sys.path.insert(0, str(VIS_DIR))


def reload_service(monkeypatch, base_dir: Path):
    monkeypatch.setenv("QMT_COMPANY_DATA_DIR", str(base_dir))
    sys.modules.pop("qmt_company_data_service", None)
    return importlib.import_module("qmt_company_data_service")


def write_table(base_dir: Path, table: str, rows: list[dict]):
    df = pl.from_pandas(pd.DataFrame(rows))
    out_dir = base_dir / f"table={table}" / "year=2026" / "month=03"
    out_dir.mkdir(parents=True)
    df.write_parquet(str(out_dir / "merged.parquet"))


def test_query_qmt_company_tables_lists_available_tables(tmp_path, monkeypatch):
    write_table(
        tmp_path,
        "Capital",
        [
            {
                "htsc_code": "601688.SH",
                "name": "华泰证券",
                "table_name": "Capital",
                "report_date": pd.Timestamp("2026-03-31"),
                "announce_date": pd.Timestamp("2026-04-30"),
                "period": "Q1",
                "freeFloatCapital": 5583620000.0,
            }
        ],
    )
    service = reload_service(monkeypatch, tmp_path)

    payload = service.query_qmt_company_tables()

    assert payload["tables"][0]["key"] == "Capital"
    assert payload["tables"][0]["label"] == "股本结构"


def test_query_qmt_company_table_returns_dynamic_columns_and_rows(tmp_path, monkeypatch):
    write_table(
        tmp_path,
        "Capital",
        [
            {
                "htsc_code": "601688.SH",
                "name": "华泰证券",
                "table_name": "Capital",
                "report_date": pd.Timestamp("2026-03-31"),
                "announce_date": pd.Timestamp("2026-04-30"),
                "period": "Q1",
                "freeFloatCapital": 5583620000.0,
            }
        ],
    )
    service = reload_service(monkeypatch, tmp_path)

    payload = service.query_qmt_company_table("601688.SH", "Capital")

    assert payload["meta"]["code"] == "601688.SH"
    assert payload["meta"]["table"] == "Capital"
    column_keys = [col["key"] for col in payload["columns"]]
    labels = {col["key"]: col["label"] for col in payload["columns"]}
    assert "freeFloatCapital" in column_keys
    assert "table" not in column_keys
    assert "year" not in column_keys
    assert "month" not in column_keys
    assert labels["report_date"] == "报告期"
    assert labels["announce_date"] == "公告日期"
    assert labels["freeFloatCapital"] == "自由流通股本"
    assert payload["rows"][0]["freeFloatCapital"] == 5583620000.0


def test_query_qmt_company_summary_includes_latest_capital(tmp_path, monkeypatch):
    write_table(
        tmp_path,
        "Capital",
        [
            {
                "htsc_code": "601688.SH",
                "name": "华泰证券",
                "table_name": "Capital",
                "report_date": pd.Timestamp("2026-03-31"),
                "announce_date": pd.Timestamp("2026-04-30"),
                "period": "Q1",
                "freeFloatCapital": 5583620000.0,
                "total_capital": 9026864000.0,
            }
        ],
    )
    service = reload_service(monkeypatch, tmp_path)

    payload = service.query_qmt_company_summary("601688.SH")

    assert payload["meta"]["code"] == "601688.SH"
    assert payload["meta"]["name"] == "华泰证券"
    assert payload["latest_by_table"]["Capital"]["freeFloatCapital"] == 5583620000.0


def test_query_qmt_company_table_rejects_unknown_table(tmp_path, monkeypatch):
    service = reload_service(monkeypatch, tmp_path)

    with pytest.raises(service.MarketDataValidationError):
        service.query_qmt_company_table("601688.SH", "Missing")
