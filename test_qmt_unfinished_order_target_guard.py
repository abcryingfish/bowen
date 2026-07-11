import importlib.util
import sys
import types
from pathlib import Path


class FakeOrder:
    def __init__(self, order_id, stock_code="601696", exchange="SH", direct=23, total=1500, traded=0):
        self.m_strOrderSysID = order_id
        self.m_strInstrumentID = stock_code
        self.m_strExchangeID = exchange
        self.m_nOffsetFlag = direct
        self.m_nVolumeTotalOriginal = total
        self.m_nVolumeTraded = traded
        self.m_nOrderStatus = 48
        self.m_strRemark = "five-day-six-level"


class FakePosition:
    def __init__(self, stock_code="601696", exchange="SH", value=21000):
        self.m_strInstrumentID = stock_code
        self.m_strExchangeID = exchange
        self.m_dInstrumentValue = value


class FakeAccount:
    m_dBalance = 1000000


def load_trade_module():
    sys.modules.setdefault("talib", types.ModuleType("talib"))

    xtquant = types.ModuleType("xtquant")
    xtquant.xtdata = types.SimpleNamespace()
    sys.modules.setdefault("xtquant", xtquant)
    sys.modules.setdefault("xtquant.xtdata", xtquant.xtdata)

    module_path = Path(__file__).with_name("qmt_tdx_auto_trade.py")
    spec = importlib.util.spec_from_file_location("qmt_tdx_auto_trade_guard", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reached_buy_target_cancels_same_stock_buy_orders_without_retrying(monkeypatch):
    module = load_trade_module()
    module.g.accID = "test-account"
    orders = [FakeOrder("44"), FakeOrder("46")]
    cancelled = []
    retried = []

    def fake_get_trade_detail_data(acc_id, market, data_type):
        if data_type == "ORDER":
            return orders
        if data_type == "POSITION":
            return [FakePosition()]
        if data_type == "ACCOUNT":
            return [FakeAccount()]
        return []

    monkeypatch.setattr(module, "get_trade_detail_data", fake_get_trade_detail_data, raising=False)
    monkeypatch.setattr(module, "cancel_order_if_possible", lambda C, order_id: cancelled.append(order_id))
    monkeypatch.setattr(module, "wait_market_ticks", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "write_trade_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "do_order", lambda C, order: retried.append(order))

    module.check_unfinished_orders(C=None)

    assert cancelled == ["44", "46"]
    assert retried == []
    assert module.g.retried_order_ids == {"44", "46"}


def test_init_cancels_all_existing_orders_before_timer(monkeypatch):
    module = load_trade_module()
    module.g.accID = "test-account"
    orders = [FakeOrder("44"), FakeOrder("46", stock_code="000001", exchange="SZ")]
    cancelled = []
    events = []

    class FakeContext:
        def set_account(self, acc_id):
            events.append(("set_account", acc_id))

        def run_time(self, *args):
            events.append(("run_time", args))

    monkeypatch.setattr(module, "create_xml_if_not_exists", lambda name: 1)
    monkeypatch.setattr(module, "set_param", lambda C: None)
    monkeypatch.setattr(module, "account", "test-account", raising=False)
    monkeypatch.setattr(module, "write_trade_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "get_trade_detail_data", lambda acc_id, market, data_type: orders, raising=False)
    monkeypatch.setattr(module, "cancel_order_if_possible", lambda C, order_id: cancelled.append(order_id), raising=False)

    module.init(FakeContext())

    assert cancelled == ["44", "46"]
    assert events == [
        ("set_account", "test-account"),
        ("run_time", ("on_timer", "3nSecond", "2026-02-10 09:30:00")),
    ]


def test_cancel_order_does_not_check_can_cancel_first(monkeypatch):
    module = load_trade_module()
    module.g.accID = "test-account"
    calls = []
    can_cancel_calls = []

    def fail_if_called(*args, **kwargs):
        can_cancel_calls.append(args)
        return True

    monkeypatch.setattr(module, "can_cancel_order", fail_if_called, raising=False)
    monkeypatch.setattr(module, "cancel", lambda order_id, acc_id, market, C: calls.append((order_id, acc_id, market)) or True, raising=False)
    monkeypatch.setattr(module, "write_trade_log", lambda *args, **kwargs: None)

    module.cancel_order_if_possible(C=None, order_id="44")

    assert calls == [("44", "test-account", "STOCK")]
    assert can_cancel_calls == []


def test_on_timer_does_not_consume_signals_when_account_records_are_empty(monkeypatch):
    module = load_trade_module()
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
        loaded_paths.append(path)
        return __import__("pandas").DataFrame(
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

    monkeypatch.setattr(module, "get_trade_detail_data", fake_get_trade_detail_data, raising=False)
    monkeypatch.setattr(module, "cleanup_cleared_position_costs", lambda: None)
    monkeypatch.setattr(module, "check_unfinished_orders", lambda C: None)
    monkeypatch.setattr(module, "load_tdx_signal", fake_load_tdx_signal)
    monkeypatch.setattr(module, "get_response_file_path", lambda: "buy_response.txt")
    monkeypatch.setattr(module, "save_tdx_signal_response", lambda df, path: saved.append((df, path)))
    monkeypatch.setattr(module, "write_trade_log", lambda *args, **kwargs: None)

    module.on_timer(C=None)

    assert loaded_paths == []
    assert saved == []
