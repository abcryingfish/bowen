from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from peak_valley_expost_annotation_v2 import (
    V2_FACTOR_NAME_MAP,
    annotate_peak_valley_ex_post,
    build_peak_valley_expost_v2_label_bundle,
    plan_peak_valley_v2_refresh,
)


def _fixture() -> tuple[pd.Series, pd.Series, pd.Series]:
    index = pd.date_range("2020-01-01", periods=14, freq="D")
    close = pd.Series(
        [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 5.5, 5.0, 4.0, 3.0, 2.0, 1.0, 0.5, 0.0],
        index=index,
    )
    high = close + 0.5
    low = close - 0.5
    return high, low, close


def test_annotation_returns_independent_continuous_peak_and_valley_scores():
    high, low, close = _fixture()
    result = annotate_peak_valley_ex_post(
        high, low, close, windows=(3, 5), horizons=(2, 4), atr_period=3
    )
    expected = {
        "peak_strength_ex_post",
        "valley_strength_ex_post",
        "peak_local_position",
        "valley_local_position",
        "peak_trend_turn",
        "valley_trend_turn",
        "peak_reversal_strength",
        "valley_reversal_strength",
        "peak_persistence",
        "valley_persistence",
        "peak_confirm_delay",
        "valley_confirm_delay",
    }
    assert expected <= set(result.columns)
    bounded = expected - {"peak_confirm_delay", "valley_confirm_delay"}
    for name in bounded:
        assert result[name].between(0.0, 1.0).all()


def test_annotation_does_not_force_peak_valley_alternation():
    high, low, close = _fixture()
    result = annotate_peak_valley_ex_post(
        high, low, close, windows=(3, 5), horizons=(2, 4), atr_period=3
    )
    assert result["peak_strength_ex_post"].iloc[5] > 0
    assert result["peak_strength_ex_post"].iloc[7] > 0


def test_confirm_delay_is_first_directional_barrier_hit():
    high, low, close = _fixture()
    result = annotate_peak_valley_ex_post(
        high, low, close, windows=(3, 5), horizons=(2, 4), atr_period=3
    )
    assert result["peak_confirm_delay"].iloc[5] == 2


def test_v2_label_bundle_has_only_the_twelve_label_factors():
    high, low, close = _fixture()
    wide_high = pd.DataFrame({"300265.SZ": high, "300266.SZ": high + 0.1})
    wide_low = pd.DataFrame({"300265.SZ": low, "300266.SZ": low - 0.1})
    wide_close = pd.DataFrame({"300265.SZ": close, "300266.SZ": close + 0.1})
    bundle = build_peak_valley_expost_v2_label_bundle(wide_high, wide_low, wide_close)
    assert set(bundle["factor_dfs"]) == set(V2_FACTOR_NAME_MAP.values())
    assert len(bundle["factor_name_map"]) == 12
    assert all("label专用，有未来数据" in name for name in bundle["factor_name_map"])


def test_main_generator_uses_v2_label_bundle_without_v1_generator():
    source = (Path(__file__).with_name("ZXW策略技术因子生成.py")).read_text(encoding="utf-8")
    assert "build_peak_valley_expost_v2_label_bundle" in source
    assert "PEAK_VALLEY_V2_LABEL_OUTPUT_BASE_DIR" in source
    assert "drop_null_factor_keys=set(peak_valley_v2_label_factor_dfs)" in source
    assert "from 波峰波谷标签 import" not in source
    assert "build_peak_valley_label_bundle" not in source


def test_main_generator_does_not_restore_v1_factor_outputs():
    source = (Path(__file__).with_name("ZXW策略技术因子生成.py")).read_text(encoding="utf-8")
    v1_factor_names = {
        "波峰波谷HP过滤",
        "波峰波谷HP过滤确认索引",
        "波峰波谷ZigZag枢轴",
        "波峰波谷ZigZag枢轴确认索引",
        "波峰波谷事件索引",
        "波峰波谷候选点",
        "波峰波谷候选点确认索引",
        "波峰波谷去重结果",
        "波峰波谷去重结果确认索引",
        "波峰波谷幅度过滤",
        "波峰波谷幅度过滤确认索引",
        "波峰波谷时间过滤",
        "波峰波谷时间过滤确认索引",
        "波峰波谷极值修正",
        "波峰波谷极值修正确认索引",
        "波峰波谷标签",
        "波峰波谷确认索引",
    }
    assert not [factor_name for factor_name in v1_factor_names if factor_name in source]


def test_v2_refresh_plan_recomputes_tail_with_left_context():
    dates = pd.date_range("2020-01-01", periods=250, freq="B")
    existing_last = dates[-2]
    plan = plan_peak_valley_v2_refresh(
        dates,
        existing_last_dates=[existing_last] * len(V2_FACTOR_NAME_MAP),
        start_date=dates[20],
        end_date=dates[-1],
        recompute_bars=60,
        context_bars=60,
        required_factor_count=len(V2_FACTOR_NAME_MAP),
    )
    assert plan["needs_refresh"] is True
    assert plan["complete_date"] == existing_last
    assert plan["write_start"] == dates[-62]
    assert plan["query_start"] == dates[-122]


def test_v2_refresh_plan_backfills_from_start_when_any_factor_is_missing():
    dates = pd.date_range("2020-01-01", periods=250, freq="B")
    plan = plan_peak_valley_v2_refresh(
        dates,
        existing_last_dates=[dates[-2]] * (len(V2_FACTOR_NAME_MAP) - 1),
        start_date=dates[100],
        end_date=dates[-1],
        recompute_bars=60,
        context_bars=60,
        required_factor_count=len(V2_FACTOR_NAME_MAP),
    )
    assert plan["needs_refresh"] is True
    assert plan["complete_date"] is None
    assert plan["write_start"] == dates[100]
    assert plan["query_start"] == dates[40]


def test_v2_refresh_plan_skips_when_all_factors_cover_source_end():
    dates = pd.date_range("2020-01-01", periods=250, freq="B")
    plan = plan_peak_valley_v2_refresh(
        dates,
        existing_last_dates=[dates[-1]] * len(V2_FACTOR_NAME_MAP),
        start_date=dates[100],
        end_date=dates[-1],
        required_factor_count=len(V2_FACTOR_NAME_MAP),
    )
    assert plan == {
        "needs_refresh": False,
        "complete_date": dates[-1],
        "query_start": None,
        "write_start": None,
    }


def test_main_generator_defines_dependencies_before_v2_runtime_calls():
    source = (Path(__file__).with_name("ZXW策略技术因子生成.py")).read_text(encoding="utf-8")
    assert source.index("def _sanitize_factor_dir_name") < source.index(
        "_peak_valley_v2_existing_map = _load_factor_last_date_map"
    )
    assert source.index("def compact_signal_daily_parts") < source.index(
        "if peak_valley_v2_label_factor_dfs and peak_valley_v2_label_name_map:"
    )
    assert "_PEAK_VALLEY_V2_NEEDS_REFRESH" in source
    assert "and not _PEAK_VALLEY_V2_NEEDS_REFRESH" in source
    assert "_peak_valley_v2_code_windows" in source
