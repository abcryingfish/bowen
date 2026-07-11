import importlib.util
import sys
import types
from pathlib import Path

import pandas as pd
import pytest


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


def test_load_tdx_signal_accepts_space_aligned_tdx_rows(tmp_path):
    module = load_trade_module()
    signal_file = tmp_path / "buy.txt"
    signal_file.write_bytes(
        b"600283   \xc7\xae\xbd\xad\xcb\xae\xc0\xfb 2026-07-09 11:12        8.82        0.68%        33 \xc8\xf5\xc2\xf4\r\n"
    )

    df = module.load_tdx_signal(str(signal_file))
    df = module.add_signal_flags(df)

    row = df.iloc[0]
    assert row["stock_code"] == "600283"
    assert row["datetime"] == "2026-07-09 11:12"
    assert row["price"] == "8.82"
    assert row["volume"] == "33"
    assert row["is_sell"] == 1


def test_convert_order_treats_buy_position_param_as_percent(monkeypatch):
    module = load_trade_module()
    module.g.accID = "test-account"
    module.g.params["单次买入仓位比例"] = 2

    class Position:
        m_strInstrumentID = "301520"
        m_strExchangeID = "SZ"
        m_dInstrumentValue = 5000

    monkeypatch.setattr(module, "get_total_asset", lambda: 1000000)
    monkeypatch.setattr(module, "get_trade_detail_data", lambda *args: [Position()], raising=False)
    monkeypatch.setattr(module, "write_trade_log", lambda *args, **kwargs: None)

    order = module.convert_order(
        {
            "stock_code": "301520",
            "price": "40.93",
            "change_percent": "1.00%",
            "formula": "五日内六级",
            "is_sell": 0,
            "is_buy": 1,
        }
    )

    assert order["trade_amount"] == 15000


def test_get_total_asset_normalizes_cent_like_qmt_balance(monkeypatch):
    module = load_trade_module()
    module.g.accID = "test-account"
    logs = []

    class Account:
        m_dBalance = 10157365033.72

    class Position:
        def __init__(self, value):
            self.m_dInstrumentValue = value

    def fake_get_trade_detail_data(acc_id, account_type, data_type):
        if data_type == "ACCOUNT":
            return [Account()]
        if data_type == "POSITION":
            return [Position(577780), Position(6362537)]
        return []

    monkeypatch.setattr(module, "get_trade_detail_data", fake_get_trade_detail_data, raising=False)
    monkeypatch.setattr(module, "write_trade_log", lambda *args, **kwargs: logs.append(args))

    assert module.get_total_asset() == pytest.approx(101573650.3372)
    assert any(args[0] == "账户总资产疑似按分返回，已除以100" for args in logs)
