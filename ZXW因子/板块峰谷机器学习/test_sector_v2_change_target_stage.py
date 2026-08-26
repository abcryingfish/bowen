"""三周期板块 V2 峰谷变化目标的确定性测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


_MODULE_PATH = Path(__file__).with_name("sector_v2_change_target_stage.py")
_SPEC = importlib.util.spec_from_file_location("sector_v2_change_target_stage", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def _source() -> pd.DataFrame:
    rows = []
    for code, offset in (("881001.THS", 0.0), ("885001.THS", 0.2)):
        for index, time in enumerate(pd.date_range("2020-01-01", periods=25)):
            rows.append(
                {
                    "htsc_code": code,
                    "time": time,
                    "peak_strength_ex_post": offset + index / 100.0,
                    "valley_strength_ex_post": 1.0 - offset - index / 100.0,
                }
            )
    return pd.DataFrame(rows)


def test_change_targets_use_each_codes_own_future_labels() -> None:
    result = _MODULE.build_v2_change_targets(_source())
    first = result[(result["htsc_code"] == "881001.THS")].iloc[0]
    assert np.isclose(first["delta_peak_ultra_short"], 0.017)
    assert np.isclose(first["delta_valley_ultra_short"], -0.017)
    assert np.isclose(first["delta_peak_5d"], 0.05)
    assert np.isclose(first["delta_valley_20d"], -0.20)


def test_target_boundaries_are_marked_incomplete() -> None:
    result = _MODULE.build_v2_change_targets(_source())
    one_code = result[result["htsc_code"] == "881001.THS"].sort_values("time")
    assert one_code["target_complete_ultra_short"].sum() == 22
    assert one_code["target_complete_5d"].sum() == 20
    assert one_code["target_complete_20d"].sum() == 5
    assert one_code.tail(20)["delta_peak_20d"].isna().all()


def test_duplicate_keys_are_rejected() -> None:
    source = _source()
    source = pd.concat([source, source.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="重复主键"):
        _MODULE.build_v2_change_targets(source)


def test_future_horizons_use_global_trading_calendar_when_a_sector_has_missing_day() -> None:
    source = pd.DataFrame(
        [
            {"htsc_code": "881001.THS", "time": "2020-01-01", "peak_strength_ex_post": 0.10, "valley_strength_ex_post": 0.90},
            {"htsc_code": "881001.THS", "time": "2020-01-02", "peak_strength_ex_post": 0.20, "valley_strength_ex_post": 0.80},
            # 881001 缺少全局日历中的 2020-01-03。
            {"htsc_code": "881001.THS", "time": "2020-01-04", "peak_strength_ex_post": 0.40, "valley_strength_ex_post": 0.60},
            {"htsc_code": "885001.THS", "time": "2020-01-01", "peak_strength_ex_post": 0.11, "valley_strength_ex_post": 0.89},
            {"htsc_code": "885001.THS", "time": "2020-01-02", "peak_strength_ex_post": 0.21, "valley_strength_ex_post": 0.79},
            {"htsc_code": "885001.THS", "time": "2020-01-03", "peak_strength_ex_post": 0.31, "valley_strength_ex_post": 0.69},
            {"htsc_code": "885001.THS", "time": "2020-01-04", "peak_strength_ex_post": 0.41, "valley_strength_ex_post": 0.59},
        ]
    )
    source["time"] = pd.to_datetime(source["time"])
    source = source.sort_values(["htsc_code", "time"]).reset_index(drop=True)
    calendar = pd.DatetimeIndex(source["time"].drop_duplicates().sort_values())
    future_two = _MODULE._future_label_by_trading_calendar(
        source, "peak_strength_ex_post", 2, calendar
    )
    first = future_two[(source["htsc_code"] == "881001.THS") & (source["time"] == "2020-01-01")].iloc[0]
    second = future_two[(source["htsc_code"] == "881001.THS") & (source["time"] == "2020-01-02")].iloc[0]
    # Jan-1 + 2 个全局交易日是 Jan-3，但该板块没有该日观测；
    # Jan-2 + 2 个全局交易日是 Jan-4，可准确回查到 0.40。
    assert pd.isna(first)
    assert np.isclose(second, 0.40)


def test_audit_reports_all_six_targets() -> None:
    targets = _MODULE.build_v2_change_targets(_source())
    summary, correlations, report = _MODULE.audit_targets(targets)
    assert len(summary) == 6
    assert correlations.shape == (6, 6)
    assert report["duplicate_keys"] == 0
