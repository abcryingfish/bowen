import importlib.machinery
import importlib.util
from pathlib import Path


def load_history_module():
    module_path = Path(__file__).with_name("\u5386\u53f2\u6210\u672c\u83b7\u53d6.txt")
    loader = importlib.machinery.SourceFileLoader("history_cost_export_script", str(module_path))
    spec = importlib.util.spec_from_loader("history_cost_export_script", loader)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_export_history_trade_rows_writes_csv(tmp_path, monkeypatch):
    module = load_history_module()
    out_file = tmp_path / "history.csv"

    class Deal:
        m_strInstrumentID = "601318"
        m_strExchangeID = "SH"
        m_strInstrumentName = "\u56fd\u529b\u7535\u5b50"
        m_nDirection = 24
        m_dPrice = 49.75
        m_nVolume = 100
        m_dTradeAmount = 4975.0

    monkeypatch.setattr(module, "OUTPUT_CSV_FILE", str(out_file), raising=False)
    count = module.export_history_trade_rows(
        [("20260710100100", Deal())],
        "1000310",
        "stock",
        "deal",
        "20260701",
        "20260710",
    )

    text = out_file.read_text(encoding="utf-8-sig")
    assert count == 1
    assert "account_id,account_type,data_type,start_date,end_date,timetag,stock_code" in text
    assert "1000310,stock,deal,20260701,20260710,20260710100100,601318.SH" in text
    assert "\u56fd\u529b\u7535\u5b50" in text
    assert ",24,49.750000,100,4975.00," in text


def test_find_history_trade_func_can_use_context_method():
    module = load_history_module()

    def fake_history(*args):
        return []

    class FakeContext:
        get_history_trade_detail_data = staticmethod(fake_history)

    func, source, available = module.find_history_trade_func(FakeContext())

    assert func is fake_history
    assert source == "context.get_history_trade_detail_data"
    assert "get_history_trade_detail_data" in available
