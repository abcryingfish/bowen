import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

import pandas as pd


def load_del_module():
    sys.modules.setdefault("talib", types.ModuleType("talib"))

    xtquant = types.ModuleType("xtquant")
    xtquant.xtdata = types.SimpleNamespace()
    sys.modules.setdefault("xtquant", xtquant)
    sys.modules.setdefault("xtquant.xtdata", xtquant.xtdata)

    module_path = Path(__file__).with_name("普通账户.txt")
    loader = importlib.machinery.SourceFileLoader("del_account_ready_guard", str(module_path))
    spec = importlib.util.spec_from_loader("del_account_ready_guard", loader)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_on_timer_does_not_consume_signals_when_account_records_are_empty(monkeypatch):
    module = load_del_module()
    module.g.accID = "wrong-account"
    module.g.params.update(
        {
            "开始时间": "00:00:00",
            "结束时间": "23:59:59",
            "预警文件": "buy.txt",
            "防重规则": "按股票代码",
            "最大买入标的数": 1000,
        }
    )
    loaded_paths = []
    saved = []

    def fake_get_trade_detail_data(acc_id, market, data_type):
        return []

    def fake_load_tdx_signal(path):
        loaded_paths.append(("signal", path))
        return pd.DataFrame(
            [
                {
                    "stock_code": "301259",
                    "name": "艾布鲁",
                    "datetime": "2026-07-02 13:46",
                    "price": 28.16,
                    "change_percent": "4.53%",
                    "volume": 58,
                    "formula": "五日内六级",
                }
            ]
        )

    def fake_load_tdx_response(path):
        loaded_paths.append(("response", path))
        return pd.DataFrame()

    monkeypatch.setattr(module, "get_trade_detail_data", fake_get_trade_detail_data, raising=False)
    monkeypatch.setattr(module, "cleanup_cleared_position_costs", lambda: None)
    monkeypatch.setattr(module, "check_unfinished_orders", lambda C: None)
    monkeypatch.setattr(module, "load_tdx_signal", fake_load_tdx_signal)
    monkeypatch.setattr(module, "load_tdx_response", fake_load_tdx_response)
    monkeypatch.setattr(module, "get_response_file_path", lambda: "buy_response.txt")
    monkeypatch.setattr(module, "save_tdx_signal_response", lambda df, path: saved.append((df, path)))
    monkeypatch.setattr(module, "write_trade_log", lambda *args, **kwargs: None)

    module.on_timer(C=None)

    assert loaded_paths == []
    assert saved == []
