from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "工具" / "形态蜡烛信号生成_合并保存.py"


def load_module():
    spec = importlib.util.spec_from_file_location("morph_candlestick_signal_generation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_filter_signals_by_stock_plan_accepts_yyyymmdd_int_dates():
    module = load_module()
    signals = pd.DataFrame(
        [
            {"Contract": "000001.SZ", "Date": 20260705, "signal_name": "sig_a"},
            {"Contract": "000001.SZ", "Date": 20260706, "signal_name": "sig_b"},
        ]
    )
    plan = pd.DataFrame(
        [
            {
                "htsc_code": "000001.SZ",
                "status": "missing",
                "plan_start": pd.Timestamp("2026-07-01"),
                "plan_end": pd.Timestamp("2026-07-05"),
            }
        ]
    )

    filtered = module._filter_signals_by_stock_plan(signals, plan)

    assert filtered["signal_name"].tolist() == ["sig_a"]


def test_filter_signals_to_missing_pairs_accepts_yyyymmdd_int_dates():
    module = load_module()
    signals = pd.DataFrame(
        [
            {"Contract": "000001.SZ", "Date": 20260705, "signal_name": "sig_a"},
            {"Contract": "000001.SZ", "Date": 20260706, "signal_name": "sig_b"},
        ]
    )
    existing = {("000001.SZ", pd.Timestamp("2026-07-05"), "sig_a")}

    filtered = module._filter_signals_to_missing_pairs(signals, existing)

    assert filtered["signal_name"].tolist() == ["sig_b"]
