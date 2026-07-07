from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

VIS_DIR = Path(__file__).parent / "可视化" / "量化因子有效性检验"
if str(VIS_DIR) not in sys.path:
    sys.path.append(str(VIS_DIR))

from factor_validation_service import (  # noqa: E402
    calculate_factor_validation,
    delete_factor_validation_record,
    list_stock_pool_files,
    list_universe_stocks,
    resolve_universe_codes,
    list_factor_validation_records,
    save_factor_validation_record,
)


def test_calculate_factor_validation_metrics_for_small_panel():
    factor = pd.DataFrame(
        [
            {"time": "2026-01-01", "htsc_code": "000001.SZ", "value": 1.0},
            {"time": "2026-01-01", "htsc_code": "000002.SZ", "value": 2.0},
            {"time": "2026-01-01", "htsc_code": "000003.SZ", "value": 3.0},
            {"time": "2026-01-02", "htsc_code": "000001.SZ", "value": 1.0},
            {"time": "2026-01-02", "htsc_code": "000002.SZ", "value": 2.0},
            {"time": "2026-01-02", "htsc_code": "000003.SZ", "value": 3.0},
        ]
    )
    prices = pd.DataFrame(
        [
            {"time": "2026-01-01", "htsc_code": "000001.SZ", "close": 10.0},
            {"time": "2026-01-01", "htsc_code": "000002.SZ", "close": 10.0},
            {"time": "2026-01-01", "htsc_code": "000003.SZ", "close": 10.0},
            {"time": "2026-01-02", "htsc_code": "000001.SZ", "close": 11.0},
            {"time": "2026-01-02", "htsc_code": "000002.SZ", "close": 12.0},
            {"time": "2026-01-02", "htsc_code": "000003.SZ", "close": 13.0},
            {"time": "2026-01-03", "htsc_code": "000001.SZ", "close": 12.0},
            {"time": "2026-01-03", "htsc_code": "000002.SZ", "close": 14.0},
            {"time": "2026-01-03", "htsc_code": "000003.SZ", "close": 16.0},
        ]
    )

    result = calculate_factor_validation(
        factor_df=factor,
        price_df=prices,
        universe_codes=["000001.SZ", "000002.SZ", "000003.SZ"],
        factor_name="demo_factor",
        start_date="2026-01-01",
        end_date="2026-01-03",
        periods=[1],
        rolling_window=2,
        group_count=5,
    )

    assert result["quality"]["avg_valid_stock_count"] == 3.0
    assert result["quality"]["avg_coverage"] == 1.0
    assert result["ic_summary"][0]["period"] == 1
    assert result["ic_summary"][0]["ic_mean"] > 0.99
    assert result["ic_summary"][0]["rank_ic_mean"] > 0.99
    assert len(result["ic_series"]["1"]) == 2
    assert len(result["group_returns"]["1"]["groups"]) == 5
    assert result["event_study"]["mode"] == "continuous_top_20pct"
    assert result["event_study"]["summary"][0]["event_count"] >= 2


def test_factor_validation_records_roundtrip(tmp_path):
    payload = {
        "factor": "demo_factor",
        "stock_pool": "ALL_A",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "periods": [1, 3],
        "rolling_window": 60,
        "group_count": 5,
        "quality": {"avg_valid_stock_count": 3},
        "ic_summary": [],
        "event_summary": [],
        "chart_payload": {},
    }

    saved = save_factor_validation_record(payload, records_dir=tmp_path)
    records = list_factor_validation_records(records_dir=tmp_path)

    assert saved["id"]
    assert len(records["items"]) == 1
    assert records["items"][0]["factor"] == "demo_factor"

    deleted = delete_factor_validation_record(saved["id"], records_dir=tmp_path)
    assert deleted["deleted"] is True
    assert list_factor_validation_records(records_dir=tmp_path)["items"] == []


def test_list_universe_stocks_accepts_all_a_csv_shape(tmp_path):
    csv_path = tmp_path / "all_a.csv"
    csv_path.write_text(
        "\ufeffindex_code,index_name,stock_code,stock_name,stock_exchange\n"
        "ALL.A,全市场股票,000001.SZ,平安银行,XSHE\n"
        "ALL.A,全市场股票,000002.SZ,万 科Ａ,XSHE\n",
        encoding="utf-8",
    )

    payload = list_universe_stocks(path=csv_path)

    assert payload["count"] == 2
    assert payload["items"][0]["code"] == "000001.SZ"
    assert payload["items"][0]["name"] == "平安银行"


def test_resolve_universe_codes_accepts_selected_codes_from_payload(tmp_path):
    csv_path = tmp_path / "universe.csv"
    csv_path.write_text(
        "htsc_code,name\n"
        "000001.SZ,平安银行\n"
        "000002.SZ,万 科Ａ\n"
        "000003.SZ,国华网安\n",
        encoding="utf-8-sig",
    )

    codes = resolve_universe_codes(
        {"stock_codes": ["000002.SZ", "999999.SH", "000001.SZ", "000001.SZ"]},
        path=csv_path,
    )

    assert codes == ["000002.SZ", "000001.SZ"]


def test_list_stock_pool_files_lists_supported_files(tmp_path):
    (tmp_path / "ALL_A.csv").write_text("stock_code\n000001.SZ\n", encoding="utf-8-sig")
    (tmp_path / "ETF池.xlsx").write_bytes(b"placeholder")
    (tmp_path / "ignore.txt").write_text("stock_code\n000002.SZ\n", encoding="utf-8")

    payload = list_stock_pool_files(pool_dir=tmp_path)

    names = [item["name"] for item in payload["items"]]
    assert names == ["ALL_A.csv", "ETF池.xlsx"]


def test_resolve_universe_codes_uses_selected_stock_pool_file(tmp_path):
    default_path = tmp_path / "ALL_A.csv"
    default_path.write_text(
        "stock_code,stock_name\n"
        "000001.SZ,平安银行\n",
        encoding="utf-8-sig",
    )
    selected_path = tmp_path / "ETF池.xlsx"
    pd.DataFrame(
        [
            {"htsc_code": "510300.SH", "name": "沪深300ETF"},
            {"htsc_code": "159915.SZ", "name": "创业板ETF"},
        ]
    ).to_excel(selected_path, index=False)

    codes = resolve_universe_codes(
        {"stock_pool_file": "ETF池.xlsx"},
        path=default_path,
        pool_dir=tmp_path,
    )

    assert codes == ["159915.SZ", "510300.SH"]


def test_universe_stock_reader_accepts_etf_code_column(tmp_path):
    csv_path = tmp_path / "ETF行业指数.csv"
    csv_path.write_text(
        "snapshot_date,sector_name,rank_in_return,etf_code,market\n"
        "2026-07-07,ETF行业指数,1,510200.SH,SH\n"
        "2026-07-07,ETF行业指数,2,159996.SZ,SZ\n",
        encoding="utf-8-sig",
    )

    payload = list_universe_stocks(path=csv_path)

    assert payload["count"] == 2
    assert [item["code"] for item in payload["items"]] == ["159996.SZ", "510200.SH"]
