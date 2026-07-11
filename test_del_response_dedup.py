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
    loader = importlib.machinery.SourceFileLoader("del_response_dedup", str(module_path))
    spec = importlib.util.spec_from_loader("del_response_dedup", loader)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_unfinished_buy_response_does_not_block_next_same_stock_buy_signal():
    module = load_del_module()
    df_response = pd.DataFrame(
        [
            {
                "stock_code": "301165",
                "datetime": "2026-07-09 10:22",
                "formula": "五日内六级",
                "process_status": "submitted",
                "traded_volume": 0,
                "remaining_volume": 17800,
            }
        ]
    )

    df_dedup = module.get_response_records_for_dedup(df_response)

    assert df_dedup.empty


def test_completed_buy_response_still_blocks_next_same_stock_buy_signal():
    module = load_del_module()
    df_response = pd.DataFrame(
        [
            {
                "stock_code": "301165",
                "datetime": "2026-07-09 10:22",
                "formula": "五日内六级",
                "process_status": "filled",
                "traded_volume": 1000,
                "remaining_volume": 0,
            }
        ]
    )

    df_dedup = module.get_response_records_for_dedup(df_response)

    assert len(df_dedup) == 1


def test_buy_signal_is_blocked_after_more_than_ten_failed_buy_responses():
    module = load_del_module()
    df_response = pd.DataFrame(
        [
            {
                "stock_code": "301191",
                "formula": "?????",
                "process_status": "failed",
                "process_reason": "???????????",
            }
            for _ in range(11)
        ]
    )
    signal_info = {"stock_code": "301191", "formula": "?????", "is_buy": 1, "is_sell": 0}

    blocked, reason = module.should_skip_by_failed_response_count(signal_info, df_response)

    assert blocked is True
    assert "10" in reason


def test_buy_signal_is_not_blocked_at_ten_failed_buy_responses():
    module = load_del_module()
    df_response = pd.DataFrame(
        [
            {
                "stock_code": "301191",
                "formula": "?????",
                "process_status": "failed",
                "process_reason": "???????????",
            }
            for _ in range(10)
        ]
    )
    signal_info = {"stock_code": "301191", "formula": "?????", "is_buy": 1, "is_sell": 0}

    blocked, reason = module.should_skip_by_failed_response_count(signal_info, df_response)

    assert blocked is False
    assert reason == ""


def test_sell_signal_is_not_blocked_by_failed_buy_response_count():
    module = load_del_module()
    df_response = pd.DataFrame(
        [
            {
                "stock_code": "301191",
                "formula": "?????",
                "process_status": "failed",
                "process_reason": "???????????",
            }
            for _ in range(11)
        ]
    )
    signal_info = {"stock_code": "301191", "formula": "??", "is_buy": 0, "is_sell": 1}

    blocked, reason = module.should_skip_by_failed_response_count(signal_info, df_response)

    assert blocked is False
    assert reason == ""



def test_failed_limit_skipped_response_blocks_next_same_stock_buy_signal():
    module = load_del_module()
    df_response = pd.DataFrame(
        [
            {
                "stock_code": "301191",
                "datetime": "2026-07-09 13:59",
                "formula": "?????",
                "process_status": "skipped",
                "process_reason": "?????????10??????",
                "traded_volume": 0,
                "remaining_volume": 0,
            }
        ]
    )

    df_dedup = module.get_response_records_for_dedup(df_response)

    assert len(df_dedup) == 1
    assert df_dedup.iloc[0]["process_status"] == "skipped"



def test_existing_failed_limit_skipped_response_blocks_without_new_reason():
    module = load_del_module()
    df_response = pd.DataFrame(
        [
            {
                "stock_code": "301191",
                "formula": "?????",
                "process_status": "failed",
                "process_reason": "???????????",
            }
            for _ in range(11)
        ]
        + [
            {
                "stock_code": "301191",
                "formula": "?????",
                "process_status": "skipped",
                "process_reason": "?????????10??????",
            }
        ]
    )
    signal_info = {"stock_code": "301191", "formula": "?????", "is_buy": 1, "is_sell": 0}

    blocked, reason = module.should_skip_by_failed_response_count(signal_info, df_response)

    assert blocked is True
    assert reason == ""
