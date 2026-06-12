import importlib.util
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("获得股票日频数据.py")
SPEC = importlib.util.spec_from_file_location("daily_stock_data", MODULE_PATH)
daily_stock_data = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(daily_stock_data)


def test_build_universe_df_fills_name_and_pinyin_from_xtquant_detail():
    detail_by_code = {
        "300750.SZ": {"InstrumentName": "宁德时代", "ExchangeID": "SZ"},
        "600519.SH": {"InstrumentName": "贵州茅台", "ExchangeID": "SH"},
    }

    with mock.patch.object(
        daily_stock_data.xtdata,
        "get_instrument_detail",
        side_effect=lambda code: detail_by_code.get(code, {}),
    ):
        frame = daily_stock_data.build_universe_df(["300750.SZ", "600519.SH"])

    rows = frame.set_index("htsc_code").to_dict(orient="index")
    assert rows["300750.SZ"]["name"] == "宁德时代"
    assert rows["300750.SZ"]["pinyin_initials"] == "NDSD"
    assert rows["600519.SH"]["name"] == "贵州茅台"
    assert rows["600519.SH"]["pinyin_initials"] == "GZMT"
