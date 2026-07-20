import ast
import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


DESKTOP = Path.home() / "Desktop"
SCRIPT_PATHS = [
    DESKTOP / "普通账户_修复版_GBK.txt",
    DESKTOP / "两融账户_修复版_GBK.txt",
]


def read_source(path):
    return path.read_bytes().decode("gbk")


def extract_functions(source, names):
    tree = ast.parse(source)
    selected = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    missing = set(names) - {node.name for node in selected}
    assert not missing, "缺少状态机函数: %s" % sorted(missing)
    module = ast.Module(body=selected, type_ignores=[])
    namespace = {}
    exec(compile(module, "<state_helpers>", "exec"), namespace)
    return namespace


@pytest.mark.parametrize("path", SCRIPT_PATHS)
def test_gbk_source_compiles(path):
    source = read_source(path)
    compile(source, str(path), "exec")
    assert source.encode("gbk") == path.read_bytes()


@pytest.mark.parametrize("path", SCRIPT_PATHS)
def test_cumulative_order_volume_only_records_delta(path):
    helpers = extract_functions(
        read_source(path),
        ["normalize_exact_volume", "calculate_order_traded_delta"],
    )
    calculate_delta = helpers["calculate_order_traded_delta"]

    assert calculate_delta(300, 0) == (300, 300)
    assert calculate_delta(500, 300) == (200, 500)
    assert calculate_delta(500, 500) == (0, 500)
    assert calculate_delta(400, 500) == (0, 500)


@pytest.mark.parametrize("path", SCRIPT_PATHS)
def test_retry_is_forbidden_before_terminal_state(path):
    helpers = extract_functions(
        read_source(path),
        ["can_submit_next_child_order"],
    )
    can_retry = helpers["can_submit_next_child_order"]

    for stage in ["waiting_fill_ticks", "cancel_requested", "waiting_terminal"]:
        assert can_retry(stage, False) is False
        assert can_retry(stage, True) is False
    assert can_retry("ready_to_retry", True) is True
    assert can_retry("ready_to_submit", True) is True


@pytest.mark.parametrize("path", SCRIPT_PATHS)
def test_response_contains_durable_execution_state(path):
    source = read_source(path)
    required_columns = [
        "execution_stage",
        "active_order_id",
        "active_order_recorded_volume",
        "target_volume",
        "target_amount",
        "traded_amount",
        "waited_ticks",
        "execution_round",
        "cancel_requested_at",
        "cancel_count",
        "state_updated_at",
    ]
    for column in required_columns:
        assert repr(column) in source or ('"%s"' % column) in source


@pytest.mark.parametrize("path", SCRIPT_PATHS)
def test_state_advancer_has_no_blocking_wait(path):
    source = read_source(path)
    tree = ast.parse(source)
    functions = {
        node.name: node for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    assert "advance_order_state_machine" in functions
    body = ast.unparse(functions["advance_order_state_machine"])
    assert "sleep(" not in body
    assert "wait_market_ticks(" not in body
    assert body.index("save_tdx_signal_response") < body.index("cancel_order_if_possible")
    assert "tick_key[0] != ''" in body


@pytest.mark.parametrize("path", SCRIPT_PATHS)
def test_two_tick_cancel_rule_is_configured(path):
    source = read_source(path)
    assert "'撤单等待tick数': 2" in source
    assert "g.params.get('撤单等待tick数', 2)" in source


def test_credit_state_keeps_separate_buy_mode_rounds():
    source = read_source(SCRIPT_PATHS[1])
    assert "'collateral_rounds'" in source
    assert "'financing_rounds'" in source
    assert "g.params.get('担保品买入最大轮数', 10)" in source
    assert "g.params.get('融资买入最大轮数', 10)" in source
    assert "强制卖出跳过状态机执行中的股票" in source


@pytest.mark.parametrize("path", SCRIPT_PATHS)
def test_new_fill_delta_updates_round_total(path):
    source = read_source(path)
    tree = ast.parse(source)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "apply_order_fill_to_response"
    )
    assert "g.trade_round_traded_volume += delta" in ast.unparse(function)


@pytest.mark.parametrize("path", SCRIPT_PATHS)
def test_real_response_fill_application_does_not_double_count(path):
    helpers = extract_functions(
        read_source(path),
        ["normalize_exact_volume", "calculate_order_traded_delta", "apply_order_fill_to_response"],
    )
    helpers.update({
        "to_float_value": lambda value, default=0: float(value or default),
        "add_market_suffix": lambda value: value,
        "update_position_cost_on_buy": lambda *args: None,
        "update_half_sell_progress": lambda *args: None,
        "is_credit_state_buy_direct": lambda direct: int(direct) in [27, 33],
        "datetime": __import__("datetime").datetime,
        "g": SimpleNamespace(trade_round_traded_volume=0),
    })
    apply_fill = helpers["apply_order_fill_to_response"]
    direct = 27 if "两融" in path.name else 23
    frame = pd.DataFrame([{
        "active_order_recorded_volume": 0,
        "traded_volume": 0,
        "target_volume": 1000,
        "target_amount": 0,
        "active_order_price": 10,
        "traded_amount": 0,
        "remaining_volume": 1000,
        "process_status": "submitted",
        "state_updated_at": "",
        "execution_direct": direct,
        "stock_code": "000001.SZ",
        "sell_stage": "",
    }])

    assert apply_fill(frame, 0, 300) is True
    assert apply_fill(frame, 0, 500) is True
    assert apply_fill(frame, 0, 500) is False
    assert int(frame.at[0, "traded_volume"]) == 500
    assert int(frame.at[0, "remaining_volume"]) == 500
    assert int(helpers["g"].trade_round_traded_volume) == 500


@pytest.mark.parametrize("path", SCRIPT_PATHS)
def test_legacy_response_is_migrated_to_state_columns(path, tmp_path):
    helpers = extract_functions(
        read_source(path),
        [
            "get_execution_state_columns", "get_response_columns",
            "normalize_response_columns", "load_tdx_response",
        ],
    )
    helpers.update({"pd": pd, "os": os, "write_trade_log": lambda *args: None})
    response_path = tmp_path / "response.txt"
    legacy_row = [
        "000001", "平安银行", "2026-07-17 10:00", "10.00", "0%", "1", "五日内六级",
        "submitted", "旧记录", "10001", "10001", "0", "1000", "2026-07-17 10:00:01",
    ]
    response_path.write_text("\t".join(legacy_row) + "\n", encoding="gbk")

    frame = helpers["load_tdx_response"](str(response_path))
    assert list(frame.columns) == helpers["get_response_columns"]()
    assert frame.at[0, "order_ids"] == "10001"
    assert frame.at[0, "execution_stage"] == ""


@pytest.mark.parametrize("path", SCRIPT_PATHS)
def test_remaining_buy_target_reprices_from_amount(path):
    helpers = extract_functions(
        read_source(path),
        ["normalize_exact_volume", "round_lot", "calculate_remaining_buy_target"],
    )
    calculate = helpers["calculate_remaining_buy_target"]
    assert calculate(100000, 30000, 10) == (70000.0, 7000)
    assert calculate(100000, 30000, 20) == (70000.0, 3500)
    assert calculate(100000, 99500, 10) == (500.0, 0)


@pytest.mark.parametrize("path", SCRIPT_PATHS)
def test_stopped_execution_is_not_left_retryable(path):
    source = read_source(path)
    tree = ast.parse(source)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "submit_next_response_child"
    )
    body = ast.unparse(function)
    assert "process_status'] = 'stopped'" in body


@pytest.mark.parametrize("path", SCRIPT_PATHS)
def test_state_submission_does_not_poll_or_sleep_for_order_id(path):
    source = read_source(path)
    tree = ast.parse(source)
    functions = {
        node.name: node for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    assert "submit_limit_order_nonblocking" in functions
    submit_body = ast.unparse(functions["submit_limit_order_nonblocking"])
    assert "sleep(" not in submit_body
    assert "fetch_submitted_order_id(" not in submit_body
    assert "fetch_last_order_id(" not in submit_body
    assert "resolving_order_id" in source


@pytest.mark.parametrize("path", SCRIPT_PATHS)
def test_unresolved_state_orders_are_protected_from_orphan_cancel(path):
    source = read_source(path)
    assert "is_order_protected_by_pending_response" in source
    assert "check_unfinished_orders_nonblocking(C, active_order_ids, df_response)" in source


@pytest.mark.parametrize("path", SCRIPT_PATHS)
def test_previous_state_response_column_count_is_migrated(path, tmp_path):
    helpers = extract_functions(
        read_source(path),
        [
            "get_execution_state_columns", "get_response_columns",
            "normalize_response_columns", "load_tdx_response",
        ],
    )
    helpers.update({"pd": pd, "os": os, "write_trade_log": lambda *args: None})
    current_columns = helpers["get_response_columns"]()
    previous_columns = current_columns[:-5]
    values = ["" for _ in previous_columns]
    values[0] = "000001"
    values[6] = "五日内六级"
    response_path = tmp_path / "previous_state_response.txt"
    response_path.write_text("\t".join(values) + "\n", encoding="gbk")

    frame = helpers["load_tdx_response"](str(response_path))
    assert list(frame.columns) == current_columns
    assert frame.at[0, "stock_code"] == "000001"
    assert frame.at[0, "pending_submit_started_at"] == ""


def test_credit_only_one_active_buy_stock_from_response():
    source = read_source(SCRIPT_PATHS[1])
    helpers = extract_functions(source, ["get_active_credit_buy_codes_from_response"])
    helpers.update({
        "normalize_stock_code_for_count": lambda value: str(value).split(".")[0],
        "is_credit_state_buy_direct": lambda value: int(float(value or 0)) in [27, 33],
    })
    frame = pd.DataFrame([
        {"stock_code": "000001", "execution_stage": "waiting_fill_ticks", "execution_direct": 27},
        {"stock_code": "000002", "execution_stage": "resolving_order_id", "execution_direct": 33},
        {"stock_code": "000003", "execution_stage": "ready_to_retry", "execution_direct": 27},
        {"stock_code": "000004", "execution_stage": "completed", "execution_direct": 27},
        {"stock_code": "000005", "execution_stage": "waiting_terminal", "execution_direct": 31},
    ])
    assert helpers["get_active_credit_buy_codes_from_response"](frame) == {"000001", "000002", "000003"}


def test_credit_signal_scheduler_defers_additional_buy_without_response():
    source = read_source(SCRIPT_PATHS[1])
    assert "g.active_credit_buy_stock_codes" in source
    assert "两融买入串行等待：已有活动买入股票，本条延后" in source
    assert "get_live_credit_buy_stock_codes" in source
    assert "ORDER_QUERY_FAILED" in source


def test_ordinary_only_one_active_buy_stock_from_response():
    source = read_source(SCRIPT_PATHS[0])
    helpers = extract_functions(source, ["get_active_ordinary_buy_codes_from_response"])
    helpers.update({"normalize_stock_code_for_count": lambda value: str(value).split(".")[0]})
    frame = pd.DataFrame([
        {"stock_code": "000001", "execution_stage": "waiting_fill_ticks", "execution_direct": 23},
        {"stock_code": "000002", "execution_stage": "resolving_order_id", "execution_direct": 23},
        {"stock_code": "000003", "execution_stage": "ready_to_retry", "execution_direct": 23},
        {"stock_code": "000004", "execution_stage": "completed", "execution_direct": 23},
        {"stock_code": "000005", "execution_stage": "waiting_terminal", "execution_direct": 24},
    ])
    assert helpers["get_active_ordinary_buy_codes_from_response"](frame) == {"000001", "000002", "000003"}


def test_ordinary_signal_scheduler_defers_additional_buy_without_response():
    source = read_source(SCRIPT_PATHS[0])
    assert "g.active_ordinary_buy_stock_codes" in source
    assert "普通买入串行等待：已有活动买入股票，本条延后" in source
    assert "get_live_ordinary_buy_stock_codes" in source
    assert "ORDER_QUERY_FAILED" in source


@pytest.mark.parametrize("path", SCRIPT_PATHS)
def test_new_position_lifecycle_resets_half_sell_state(path):
    helpers = extract_functions(
        read_source(path), ["reset_half_sell_state_for_new_position"]
    )
    reset = helpers["reset_half_sell_state_for_new_position"]
    stale = {
        "buy_amount": 1000,
        "buy_volume": 100,
        "cost_price": 10,
        "half_sell_target_volume": 50,
        "half_sell_traded_volume": 50,
        "half_sell_remaining_volume": 0,
        "half_sell_done": True,
        "half_sell_done_at": "2026-07-17 10:00:00",
    }

    reset_item, was_reset = reset(dict(stale), 100, 100)
    assert was_reset is True
    assert "half_sell_done" not in reset_item
    assert "half_sell_target_volume" not in reset_item

    preserved_item, was_reset = reset(dict(stale), 200, 100)
    assert was_reset is False
    assert preserved_item["half_sell_done"] is True


@pytest.mark.parametrize("path", SCRIPT_PATHS)
def test_cost_save_uses_atomic_replace(path):
    source = read_source(path)
    assert "os.replace(temp_path, POSITION_COST_FILE)" in source
    assert "os.fsync" in source
