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
