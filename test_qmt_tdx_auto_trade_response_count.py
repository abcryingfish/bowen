import importlib.util
import sys
import types
from pathlib import Path

import pandas as pd


def load_trade_module():
    sys.modules.setdefault("talib", types.ModuleType("talib"))

    xtquant = types.ModuleType("xtquant")
    xtquant.xtdata = types.SimpleNamespace()
    sys.modules.setdefault("xtquant", xtquant)
    sys.modules.setdefault("xtquant.xtdata", xtquant.xtdata)

    module_path = Path(__file__).with_name("qmt_tdx_auto_trade.py")
    spec = importlib.util.spec_from_file_location("qmt_tdx_auto_trade", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_response_buy_stock_count_excludes_sell_and_deduplicates_codes():
    module = load_trade_module()
    df_response = pd.DataFrame(
        [
            {"stock_code": "000001", "formula": "五日内六级"},
            {"stock_code": "000002", "formula": "弱卖"},
            {"stock_code": "000001", "formula": "五日内六级"},
            {"stock_code": "000003", "formula": "五日内六级"},
        ]
    )

    assert module.get_response_buy_stock_count(df_response) == 2


def test_add_process_result_to_signal_keeps_original_signal_and_adds_status():
    module = load_trade_module()
    signal_info = {"stock_code": "000001", "formula": "五日内六级"}
    process_result = {
        "process_status": "submitted",
        "process_reason": "盘口追单结束",
        "order_id": "12345",
    }

    result = module.add_process_result_to_signal(signal_info, process_result)

    assert result["stock_code"] == "000001"
    assert result["formula"] == "五日内六级"
    assert result["process_status"] == "submitted"
    assert result["process_reason"] == "盘口追单结束"
    assert result["order_id"] == "12345"
    assert result["processed_at"]
