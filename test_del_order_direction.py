import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path


def load_del_module():
    sys.modules.setdefault("talib", types.ModuleType("talib"))

    xtquant = types.ModuleType("xtquant")
    xtquant.xtdata = types.SimpleNamespace()
    sys.modules.setdefault("xtquant", xtquant)
    sys.modules.setdefault("xtquant.xtdata", xtquant.xtdata)

    module_path = Path(__file__).with_name("普通账户.txt")
    loader = importlib.machinery.SourceFileLoader("del_order_direction", str(module_path))
    spec = importlib.util.spec_from_loader("del_order_direction", loader)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_directional_slippage_allows_only_favorable_prices_outside_limit():
    module = load_del_module()

    assert module.is_slippage_exceeded(10, 9.5, 0.03, 23)[0] is False
    assert module.is_slippage_exceeded(10, 10.5, 0.03, 24)[0] is False
    assert module.is_slippage_exceeded(10, 10.5, 0.03, 23)[0] is True
    assert module.is_slippage_exceeded(10, 9.5, 0.03, 24)[0] is True


def test_directional_slippage_allows_exact_limit():
    module = load_del_module()

    assert module.is_slippage_exceeded(10, 10.3, 0.03, 23)[0] is False
    assert module.is_slippage_exceeded(10, 9.7, 0.03, 24)[0] is False


def test_change_percent_limits_remain_unchanged():
    module = load_del_module()

    assert module.get_change_percent_limit("600000.SH") == 9.5
    assert module.get_change_percent_limit("000001.SZ") == 9.5
    assert module.get_change_percent_limit("300001.SZ") == 19.5
    assert module.get_change_percent_limit("688001.SH") == 19.5
