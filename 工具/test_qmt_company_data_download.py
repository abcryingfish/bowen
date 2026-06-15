import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT_PATH = Path(__file__).with_name("qmt公司数据获取.py")


def load_script():
    spec = importlib.util.spec_from_file_location("qmt_company_download", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_normalize_qmt_table_adds_common_metadata():
    mod = load_script()
    raw = pd.DataFrame(
        {
            "m_timetag": ["20260331"],
            "m_anntime": ["20260430"],
            "freeFloatCapital": [5583620000.0],
            "total_capital": [9026864000.0],
        }
    )

    out = mod.normalize_qmt_table_frame(raw, "Capital", "601688.SH", "华泰证券", "2026-06-12T10:00:00")

    assert out.loc[0, "htsc_code"] == "601688.SH"
    assert out.loc[0, "name"] == "华泰证券"
    assert out.loc[0, "table_name"] == "Capital"
    assert str(out.loc[0, "report_date"].date()) == "2026-03-31"
    assert str(out.loc[0, "announce_date"].date()) == "2026-04-30"
    assert out.loc[0, "period"] == "Q1"
    assert out.loc[0, "freeFloatCapital"] == 5583620000.0


def test_save_partitioned_parquet_uses_table_year_month_layout(tmp_path):
    mod = load_script()
    df = pd.DataFrame(
        {
            "htsc_code": ["601688.SH"],
            "name": ["华泰证券"],
            "table_name": ["Capital"],
            "report_date": [pd.Timestamp("2026-03-31")],
            "announce_date": [pd.Timestamp("2026-04-30")],
            "period": ["Q1"],
            "freeFloatCapital": [5583620000.0],
            "updated_at": ["2026-06-12T10:00:00"],
        }
    )

    touched = mod.save_partitioned_parquet(df, str(tmp_path), "Capital")
    rebuilt = mod.rebuild_merged_parquets(str(tmp_path), "Capital", set(touched))

    merged_path = tmp_path / "table=Capital" / "year=2026" / "month=03" / "merged.parquet"
    assert merged_path in rebuilt
    assert merged_path.exists()


def test_resolve_codes_prefers_manual_codes(monkeypatch):
    mod = load_script()
    called = {"sector": False}

    def fake_sector(_sector_name):
        called["sector"] = True
        return ["000001.SZ"]

    monkeypatch.setattr(mod, "load_xtquant_sector_universe", fake_sector)

    assert mod.resolve_codes("沪深A股", "601688.SH, 000001.SZ") == ["000001.SZ", "601688.SH"]
    assert called["sector"] is False
