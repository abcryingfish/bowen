from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "工具" / "形态蜡烛信号生成_合并保存.py"


def load_module():
    spec = importlib.util.spec_from_file_location("morph_candlestick_combined", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_auto_plan_uses_global_latest_event_day_as_incremental_mark_for_missing_stock():
    module = load_module()
    signal_latest = {
        "000001.SZ": pd.Timestamp("2026-07-03"),
        "000002.SZ": pd.Timestamp("2026-07-02"),
    }
    market_max = {
        "000001.SZ": pd.Timestamp("2026-07-06"),
        "000002.SZ": pd.Timestamp("2026-07-06"),
        "001399.SZ": pd.Timestamp("2026-07-06"),
    }

    plan = module.build_stock_fill_plan(
        ["000001.SZ", "000002.SZ", "001399.SZ"],
        signal_latest,
        market_max,
        start_date="2010-01-01",
        end_date="2026-07-07",
        lookback_days=65,
    )

    need = plan[plan["status"].isin(["missing", "stale"])]

    assert need["plan_start"].min() == pd.Timestamp("2026-07-03")
    missing = plan[plan["htsc_code"].eq("001399.SZ")].iloc[0]
    assert missing["status"] == "missing"
    assert missing["plan_start"] == pd.Timestamp("2026-07-03")
