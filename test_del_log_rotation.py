import importlib.machinery
import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path


def load_del_module():
    sys.modules.setdefault("talib", types.ModuleType("talib"))

    xtquant = types.ModuleType("xtquant")
    xtquant.xtdata = types.SimpleNamespace()
    sys.modules.setdefault("xtquant", xtquant)
    sys.modules.setdefault("xtquant.xtdata", xtquant.xtdata)

    module_path = Path(__file__).with_name("普通账户.txt")
    loader = importlib.machinery.SourceFileLoader("del_log_rotation", str(module_path))
    spec = importlib.util.spec_from_loader("del_log_rotation", loader)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_trade_log_path_uses_current_date(tmp_path):
    module = load_del_module()
    module.TRADE_LOG_FILE = str(tmp_path / "trade_record_log.txt")

    log_path = module.get_trade_log_file_path(datetime(2026, 7, 9, 10, 0, 0))

    assert log_path == str(tmp_path / "trade_record_log_20260709.txt")


def test_trade_log_rotates_when_current_file_exceeds_limit(tmp_path):
    module = load_del_module()
    module.TRADE_LOG_FILE = str(tmp_path / "trade_record_log.txt")
    module.TRADE_LOG_MAX_BYTES = 10
    log_path = tmp_path / "trade_record_log_20260709.txt"
    log_path.write_bytes(b"x" * 11)

    active_path = module.prepare_trade_log_file(datetime(2026, 7, 9, 10, 0, 0))

    assert active_path == str(log_path)
    assert (tmp_path / "trade_record_log_20260709_001.txt").exists()
    assert (tmp_path / "trade_record_log_20260709_001.txt").read_bytes() == b"x" * 11
    assert not log_path.exists()
