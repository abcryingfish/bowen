import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

import pytest


def load_del_module():
    sys.modules.setdefault("talib", types.ModuleType("talib"))

    xtquant = types.ModuleType("xtquant")
    xtquant.xtdata = types.SimpleNamespace()
    sys.modules.setdefault("xtquant", xtquant)
    sys.modules.setdefault("xtquant.xtdata", xtquant.xtdata)

    module_path = Path(__file__).with_name("普通账户.txt")
    loader = importlib.machinery.SourceFileLoader("del_tdx_signal_parser", str(module_path))
    spec = importlib.util.spec_from_loader("del_tdx_signal_parser", loader)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_load_tdx_signal_accepts_space_aligned_tdx_rows(tmp_path):
    module = load_del_module()
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


def test_convert_order_uses_self_cost_info_for_half_sell_state(monkeypatch):
    module = load_del_module()
    module.g.accID = "test-account"
    module.g.params["涨跌幅限制"] = {}

    class Position:
        m_strInstrumentID = "600283"
        m_strExchangeID = "SH"
        m_nCanUseVolume = 1200
        m_nVolume = 1200
        m_dOpenPrice = 10
        m_dInstrumentValue = 19200
        m_dLastPrice = 16
        m_dPositionProfit = 7200

    monkeypatch.setattr(module, "get_trade_detail_data", lambda *args: [Position()], raising=False)
    monkeypatch.setattr(module, "get_history_position_cost_price", lambda stock_code: (10, {"net_cost_price": 10}))
    monkeypatch.setattr(module, "get_official_position_cost_price", lambda position: 10)
    monkeypatch.setattr(module, "get_self_position_cost", lambda stock_code: (0, {}))
    monkeypatch.setattr(module, "write_trade_log", lambda *args, **kwargs: None)

    order = module.convert_order(
        {
            "stock_code": "600283",
            "price": "16.00",
            "change_percent": "0.68%",
            "formula": "弱卖",
            "is_sell": 1,
            "is_buy": 0,
        }
    )

    assert order["trade_amount"] == 600
    assert order["sell_stage"] == "half_150"


def test_get_total_asset_normalizes_cent_like_qmt_balance(monkeypatch):
    module = load_del_module()
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


def test_get_total_asset_keeps_normal_balance(monkeypatch):
    module = load_del_module()
    module.g.accID = "test-account"

    class Account:
        m_dBalance = 1000000

    class Position:
        m_dInstrumentValue = 300000

    def fake_get_trade_detail_data(acc_id, account_type, data_type):
        if data_type == "ACCOUNT":
            return [Account()]
        if data_type == "POSITION":
            return [Position()]
        return []

    monkeypatch.setattr(module, "get_trade_detail_data", fake_get_trade_detail_data, raising=False)
    monkeypatch.setattr(module, "write_trade_log", lambda *args, **kwargs: None)

    assert module.get_total_asset() == 1000000


def test_convert_order_treats_buy_position_param_as_percent(monkeypatch):
    module = load_del_module()
    module.g.accID = "test-account"
    module.g.params["单次买入仓位比例"] = 2
    module.g.params["涨跌幅限制"] = {}

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
    assert order["trade_amount_unit"] == "amount"


def test_export_history_trade_detail_rows_writes_raw_tsv(tmp_path, monkeypatch):
    module = load_del_module()
    out_file = tmp_path / "history_raw.txt"

    class Deal:
        m_strInstrumentID = "601318"
        m_strExchangeID = "SH"
        m_nDirection = 24
        m_dPrice = 49.75
        m_nVolume = 100
        m_dTradeAmount = 4975.0
        m_strInstrumentName = "国力电子"

    monkeypatch.setattr(module, "HISTORY_TRADE_DETAIL_FILE", str(out_file), raising=False)
    monkeypatch.setattr(module, "write_trade_log", lambda *args, **kwargs: None)

    module.export_history_trade_detail_rows(
        [("20260710100100", Deal())],
        "stock",
        "deal",
        "20260701",
        "20260710",
        "history",
    )

    text = out_file.read_text(encoding="utf-8-sig")
    assert "查询来源\t统计开始\t统计结束" in text
    assert "history\t20260701\t20260710\tstock\tdeal\t20260710100100\t601318.SH" in text
    assert "\t24\t49.750000\t100\t4975.00\t" in text
    assert "国力电子" in text
