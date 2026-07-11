import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path


class FakeCreditOrder:
    def __init__(self, op_type):
        self.m_nOpType = op_type
        self.m_nDirection = 48 if op_type == 33 else 49
        self.m_strInstrumentID = "688728"
        self.m_strExchangeID = "SH"


def load_credit_module():
    sys.modules.setdefault("talib", types.ModuleType("talib"))

    xtquant = types.ModuleType("xtquant")
    xtquant.xtdata = types.SimpleNamespace()
    sys.modules.setdefault("xtquant", xtquant)
    sys.modules.setdefault("xtquant.xtdata", xtquant.xtdata)

    module_path = Path(__file__).with_name("\u4e24\u878d.txt")
    loader = importlib.machinery.SourceFileLoader("credit_order_direction", str(module_path))
    spec = importlib.util.spec_from_loader("credit_order_direction", loader)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_credit_collateral_buy_order_direction_is_recognized():
    module = load_credit_module()

    assert module.get_order_direct(FakeCreditOrder(33)) == module.CREDIT_BUY_DIRECT


def test_credit_collateral_sell_order_direction_is_recognized():
    module = load_credit_module()

    assert module.get_order_direct(FakeCreditOrder(34)) == module.CREDIT_SELL_DIRECT
