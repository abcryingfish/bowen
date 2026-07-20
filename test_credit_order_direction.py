import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

import pandas as pd


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


def test_credit_position_base_uses_net_asset():
    module = load_credit_module()
    asset = types.SimpleNamespace(m_dBalance=3_000_000, m_dAssureAsset=1_000_000)
    module.get_trade_detail_data = lambda account_id, account_type, data_type: [asset]
    module.g.accID = "credit-account"

    assert module.get_total_asset() == 1_000_000


def test_financing_leverage_ratio_parameter_is_within_supported_range():
    module = load_credit_module()

    assert 200 <= module.g.params[module.FINANCING_LEVERAGE_RATIO_PARAM] <= 400


def test_leverage_position_values_use_target_maintenance_ratio():
    module = load_credit_module()

    values = module.calculate_leverage_position_values(1_000_000, 200, 2)

    assert values["max_debt"] == 1_000_000
    assert values["max_total_asset"] == 2_000_000
    assert values["single_target_value"] == 40_000
    assert values["max_stock_count"] == 50


def test_remaining_total_capacity_limits_single_stock_gap():
    module = load_credit_module()

    buy_amount = module.calculate_final_buy_amount(
        single_target_value=40_000,
        current_stock_value=0,
        max_total_asset=2_000_000,
        current_total_position_value=1_990_000,
    )

    assert buy_amount == 10_000


def test_cash_buy_is_used_only_when_cash_covers_a_round_lot():
    module = load_credit_module()

    assert module.select_credit_buy_direct(20_000, 20) == module.CREDIT_COLLATERAL_BUY_DIRECT
    assert module.select_credit_buy_direct(1_999, 20) == module.CREDIT_BUY_DIRECT


def test_buy_order_uses_cash_first_then_financing():
    module = load_credit_module()
    submitted = []
    traded_volumes = iter([700, 1300])
    module.g.params['盘口最大轮数'] = 10
    module.g.params['撤单等待tick数'] = 0
    module.g.params['重新下单等待tick数'] = 0
    module.get_credit_available_cash = lambda: 15_000
    module.get_best_opposite_quote = lambda context, stock_code, direct: (20, 10_000, '卖一')
    module.is_slippage_exceeded = lambda signal_price, quote_price, max_ratio, trade_direct=None: (False, 0)
    module.wait_market_ticks = lambda context, stock_code, ticks: None
    module.update_position_cost_on_buy = lambda stock_code, price, volume: None
    module.cancel_and_get_final_order_result = lambda context, order_id: {
        'confirmed': True,
        'traded_volume': next(traded_volumes),
        'rejected': False,
    }

    def submit_order(context, order, price, volume, title):
        submitted.append((order['trade_direct'], volume))
        return str(len(submitted))

    module.submit_limit_order = submit_order
    result = module.do_order(None, {
        'trade_direct': module.CREDIT_BUY_DIRECT,
        'trade_amount': 40_000,
        'stock_code': '600000.SH',
        'price': 20,
        'remark': 'test',
    })

    assert submitted == [
        (module.CREDIT_COLLATERAL_BUY_DIRECT, 700),
        (module.CREDIT_BUY_DIRECT, 1300),
    ]
    assert result['traded_volume'] == 2000
    assert result['remaining_volume'] == 0
    assert result['order_ids'] == '1,2'


def test_collateral_buy_retry_keeps_collateral_direction():
    module = load_credit_module()
    retry_order = module.build_retry_order(FakeCreditOrder(33), 500)

    assert retry_order['trade_direct'] == module.CREDIT_COLLATERAL_BUY_DIRECT


def test_available_cash_reserves_half_percent_for_fees():
    module = load_credit_module()
    asset = types.SimpleNamespace(m_dAvailable=100_000)
    module.get_trade_detail_data = lambda account_id, account_type, data_type: [asset]
    module.g.accID = 'credit-account'

    assert module.get_credit_available_cash() == 99_500


def test_large_net_asset_is_not_divided_by_one_hundred():
    module = load_credit_module()

    assert module.normalize_total_asset_value(2_000_000_000, object()) == 2_000_000_000


def test_collateral_round_limit_switches_to_financing():
    module = load_credit_module()
    submitted = []
    traded_volumes = iter([100, 1900])
    module.g.params['担保品买入最大轮数'] = 1
    module.g.params['融资买入最大轮数'] = 1
    module.g.params['撤单等待tick数'] = 0
    module.g.params['重新下单等待tick数'] = 0
    module.get_credit_available_cash = lambda: 40_000
    module.get_best_opposite_quote = lambda context, stock_code, direct: (20, 10_000, '卖一')
    module.is_slippage_exceeded = lambda signal_price, quote_price, max_ratio, trade_direct=None: (False, 0)
    module.wait_market_ticks = lambda context, stock_code, ticks: None
    module.update_position_cost_on_buy = lambda stock_code, price, volume: None
    module.cancel_and_get_final_order_result = lambda context, order_id: {
        'confirmed': True,
        'traded_volume': next(traded_volumes),
        'rejected': False,
    }

    def submit_order(context, order, price, volume, title):
        submitted.append((order['trade_direct'], volume))
        return str(len(submitted))

    module.submit_limit_order = submit_order
    result = module.do_order(None, {
        'trade_direct': module.CREDIT_BUY_DIRECT,
        'trade_amount': 40_000,
        'stock_code': '600000.SH',
        'price': 20,
        'remark': 'test',
    })

    assert submitted == [
        (module.CREDIT_COLLATERAL_BUY_DIRECT, 2000),
        (module.CREDIT_BUY_DIRECT, 1900),
    ]
    assert result['traded_volume'] == 2000


def test_confirmed_collateral_submit_failure_switches_to_financing():
    module = load_credit_module()
    submitted = []
    module.g.params['担保品买入最大轮数'] = 1
    module.g.params['融资买入最大轮数'] = 1
    module.g.params['撤单等待tick数'] = 0
    module.g.params['重新下单等待tick数'] = 0
    module.get_credit_available_cash = lambda: 20_000
    module.get_best_opposite_quote = lambda context, stock_code, direct: (20, 10_000, '卖一')
    module.is_slippage_exceeded = lambda signal_price, quote_price, max_ratio, trade_direct=None: (False, 0)
    module.wait_market_ticks = lambda context, stock_code, ticks: None
    module.update_position_cost_on_buy = lambda stock_code, price, volume: None
    module.cancel_and_get_final_order_result = lambda context, order_id: {
        'confirmed': True,
        'traded_volume': 1000,
        'rejected': False,
    }

    def submit_order(context, order, price, volume, title):
        submitted.append(order['trade_direct'])
        if order['trade_direct'] == module.CREDIT_COLLATERAL_BUY_DIRECT:
            module.g.last_submit_failure_confirmed = True
            return ''
        module.g.last_submit_failure_confirmed = False
        return 'financing-order'

    module.submit_limit_order = submit_order
    result = module.do_order(None, {
        'trade_direct': module.CREDIT_BUY_DIRECT,
        'trade_amount': 20_000,
        'stock_code': '600000.SH',
        'price': 20,
        'remark': 'test',
    })

    assert submitted == [module.CREDIT_COLLATERAL_BUY_DIRECT, module.CREDIT_BUY_DIRECT]
    assert result['traded_volume'] == 1000


def test_cancel_confirmation_waits_one_second_before_first_check():
    module = load_credit_module()
    sleeps = []
    order = types.SimpleNamespace(m_nOrderStatus=54, m_nVolumeTraded=300)
    module.g.params['撤单确认等待秒数'] = 1
    module.g.params['撤单确认超时秒数'] = 2
    module.cancel_order_if_possible = lambda context, order_id: None
    module.get_value_by_order_id = lambda order_id, account_id, account_type, data_type: order
    module.time.sleep = lambda seconds: sleeps.append(seconds)
    module.g.accID = 'credit-account'

    result = module.cancel_and_get_final_order_result(None, 'order-1')

    assert sleeps[0] == 1
    assert result['confirmed'] is True
    assert result['traded_volume'] == 300


def test_financing_rejection_stops_after_first_order():
    module = load_credit_module()
    submitted = []
    module.g.params['担保品买入最大轮数'] = 1
    module.g.params['融资买入最大轮数'] = 10
    module.get_credit_available_cash = lambda: 0
    module.get_best_opposite_quote = lambda context, stock_code, direct: (20, 10_000, '卖一')
    module.is_slippage_exceeded = lambda signal_price, quote_price, max_ratio, trade_direct=None: (False, 0)
    module.wait_market_ticks = lambda context, stock_code, ticks: None
    module.update_position_cost_on_buy = lambda stock_code, price, volume: None

    def submit_order(context, order, price, volume, title):
        submitted.append(order['trade_direct'])
        return 'rejected-financing-order'

    module.submit_limit_order = submit_order
    module.cancel_and_get_final_order_result = lambda context, order_id: {
        'confirmed': True,
        'traded_volume': 0,
        'rejected': True,
    }
    result = module.do_order(None, {
        'trade_direct': module.CREDIT_BUY_DIRECT,
        'trade_amount': 20_000,
        'stock_code': '600000.SH',
        'price': 20,
        'remark': 'test',
    })

    assert submitted == [module.CREDIT_BUY_DIRECT]
    assert result['process_status'] == 'failed'


def test_process_result_records_all_order_ids():
    module = load_credit_module()

    result = module.make_process_result(
        'submitted',
        order_id='order-2',
        traded_volume=200,
        order_ids=['order-1', 'order-2'],
    )

    assert result['order_id'] == 'order-2'
    assert result['order_ids'] == 'order-1,order-2'


def test_old_response_without_order_ids_is_loaded_without_column_shift(tmp_path):
    module = load_credit_module()
    response_path = tmp_path / 'old_response.txt'
    response_path.write_text(
        '600000.SH\tA\t2026-07-13 10:00:00\t10\t0\t100\tbuy\tfilled\tok\t123\t100\t0\t2026-07-13 10:01:00\n',
        encoding='gbk',
    )

    response = module.load_tdx_response(str(response_path))
    row = response.iloc[0]

    assert str(row['order_id']) == '123'
    assert str(row['order_ids']) == '123'
    assert int(row['traded_volume']) == 100
    assert int(row['remaining_volume']) == 0
    assert row['processed_at'] == '2026-07-13 10:01:00'


def test_weak_sell_uses_qmt_official_position_cost_only():
    module = load_credit_module()
    position = types.SimpleNamespace(
        m_strInstrumentID='600000',
        m_strExchangeID='SH',
        m_nCanUseVolume=1000,
        m_nVolume=1000,
        m_dOpenPrice=10,
    )
    module.g.accID = 'credit-account'
    module.get_trade_detail_data = lambda account_id, account_type, data_type: [position]
    module.get_self_position_cost = lambda stock_code: (0, {})
    module.get_best_opposite_quote = lambda context, stock_code, direct: (16, 1000, 'bid1')
    module.get_history_position_cost_price = lambda stock_code: (_ for _ in ()).throw(
        AssertionError('weak sell must not use realized-profit-adjusted history cost')
    )

    order = module.convert_order({
        'stock_code': '600000',
        'price': 16,
        'change_percent': 0,
        'formula': 'weak-sell',
        'is_sell': 1,
        'is_buy': 0,
    })

    assert order['trade_amount'] == 500
    assert order['sell_stage'] == 'half_150'


def test_partial_half_sell_does_not_mark_stage_complete():
    module = load_credit_module()
    marked = []
    submitted = []
    module.get_best_opposite_quote = lambda context, stock_code, direct: (10, 10_000, 'bid1')
    module.is_slippage_exceeded = lambda signal_price, quote_price, max_ratio, trade_direct=None: (False, 0)
    module.wait_market_ticks = lambda context, stock_code, ticks: None
    module.submit_limit_order = lambda context, order, price, volume, title: submitted.append(volume) or str(len(submitted))
    module.cancel_and_get_final_order_result = lambda context, order_id: {
        'confirmed': True,
        'traded_volume': 10,
        'rejected': False,
    }
    module.mark_half_sell_done = lambda stock_code: marked.append(stock_code)

    result = module.do_order(None, {
        'trade_direct': module.CREDIT_SELL_DIRECT,
        'trade_amount': 500,
        'stock_code': '600000.SH',
        'price': 10,
        'remark': 'weak-sell',
        'sell_stage': 'half_150',
    })

    assert result['traded_volume'] == 100
    assert result['remaining_volume'] == 400
    assert marked == []


def test_fully_filled_half_sell_marks_stage_complete():
    module = load_credit_module()
    marked = []
    module.get_best_opposite_quote = lambda context, stock_code, direct: (10, 10_000, 'bid1')
    module.is_slippage_exceeded = lambda signal_price, quote_price, max_ratio, trade_direct=None: (False, 0)
    module.wait_market_ticks = lambda context, stock_code, ticks: None
    module.submit_limit_order = lambda context, order, price, volume, title: 'order-1'
    module.cancel_and_get_final_order_result = lambda context, order_id: {
        'confirmed': True,
        'traded_volume': 500,
        'rejected': False,
    }
    module.mark_half_sell_done = lambda stock_code: marked.append(stock_code)

    result = module.do_order(None, {
        'trade_direct': module.CREDIT_SELL_DIRECT,
        'trade_amount': 500,
        'stock_code': '600000.SH',
        'price': 10,
        'remark': 'weak-sell',
        'sell_stage': 'half_150',
    })

    assert result['remaining_volume'] == 0
    assert marked == ['600000.SH']


def test_process_signal_rows_persists_each_result_before_next_order():
    module = load_credit_module()
    saved_lengths = []
    ordered_codes = []
    rows = pd.DataFrame([
        {'stock_code': '600000', 'formula': 'buy', 'is_buy': 1, 'is_sell': 0},
        {'stock_code': '000001', 'formula': 'buy', 'is_buy': 1, 'is_sell': 0},
    ])
    module.convert_order = lambda signal, context=None: {'stock_code': signal['stock_code'], 'trade_amount': 100}

    def do_order(context, order):
        ordered_codes.append(order['stock_code'])
        return module.make_process_result('submitted', order_id=order['stock_code'], traded_volume=100)

    module.do_order = do_order
    module.save_tdx_signal_response = lambda response, path: saved_lengths.append(len(response)) or True

    result = module.process_signal_rows(
        None,
        rows,
        pd.DataFrame(),
        0,
        response_file_path='response.txt',
    )

    assert ordered_codes == ['600000', '000001']
    assert saved_lengths == [1, 2]
    assert result['persistence_failed'] is False


def test_process_signal_rows_stops_when_response_persistence_fails():
    module = load_credit_module()
    ordered_codes = []
    rows = pd.DataFrame([
        {'stock_code': '600000', 'formula': 'buy', 'is_buy': 1, 'is_sell': 0},
        {'stock_code': '000001', 'formula': 'buy', 'is_buy': 1, 'is_sell': 0},
    ])
    module.convert_order = lambda signal, context=None: {'stock_code': signal['stock_code'], 'trade_amount': 100}
    module.do_order = lambda context, order: ordered_codes.append(order['stock_code']) or module.make_process_result(
        'submitted', order_id=order['stock_code'], traded_volume=100
    )
    module.save_tdx_signal_response = lambda response, path: False

    result = module.process_signal_rows(
        None,
        rows,
        pd.DataFrame(),
        0,
        response_file_path='response.txt',
    )

    assert ordered_codes == ['600000']
    assert result['persistence_failed'] is True


def test_response_save_uses_atomic_replace_and_round_trips_gbk(tmp_path):
    module = load_credit_module()
    response_path = tmp_path / 'response.txt'
    module.log_all_trade_records = lambda force=False: None
    module.log_current_positions = lambda: None
    module.export_official_position_costs = lambda: None
    response = pd.DataFrame([{
        'stock_code': '600000.SH',
        'name': 'A',
        'datetime': '2026-07-14 10:00:00',
        'price': 10,
        'change_percent': 0,
        'volume': 100,
        'formula': 'buy',
        'process_status': 'filled',
        'process_reason': '',
        'order_id': '1',
        'order_ids': '1',
        'traded_volume': 100,
        'remaining_volume': 0,
        'processed_at': '2026-07-14 10:00:01',
    }])

    assert module.save_tdx_signal_response(response, str(response_path)) is True
    assert not (tmp_path / 'response.txt.tmp').exists()
    loaded = module.load_tdx_response(str(response_path))
    assert loaded.iloc[0]['order_ids'] == '1'
    assert loaded.iloc[0]['processed_at'] == '2026-07-14 10:00:01'


def test_response_save_does_not_query_account_snapshots(tmp_path):
    module = load_credit_module()
    response_path = tmp_path / 'response.txt'

    def unexpected_snapshot_call(*args, **kwargs):
        raise AssertionError('逐笔保存response时不应查询全账户快照')

    module.log_all_trade_records = unexpected_snapshot_call
    module.log_current_positions = unexpected_snapshot_call
    module.export_official_position_costs = unexpected_snapshot_call

    assert module.save_tdx_signal_response(
        pd.DataFrame([{'stock_code': '600000.SH'}]),
        str(response_path),
    ) is True


def test_periodic_account_diagnostics_skips_when_busy_and_throttles(monkeypatch):
    module = load_credit_module()
    calls = []
    now = [1000.0]
    monkeypatch.setattr(module.time, 'time', lambda: now[0])
    module.log_all_trade_records = lambda force=False: calls.append(('records', force))
    module.log_current_positions = lambda: calls.append(('positions', None))

    module.g.trade_loop_running = True
    assert module.run_periodic_account_diagnostics() is False
    assert calls == []

    module.g.trade_loop_running = False
    assert module.run_periodic_account_diagnostics() is True
    assert calls == [('records', True)]

    now[0] += 30
    assert module.run_periodic_account_diagnostics() is False
    assert len(calls) == 1

    now[0] += 31
    assert module.run_periodic_account_diagnostics() is True
    assert calls == [('records', True), ('records', True)]


def test_refresh_after_trades_runs_once_only_when_filled():
    module = load_credit_module()
    calls = []
    module.log_current_positions = lambda: calls.append('positions')
    module.export_official_position_costs = lambda: calls.append('costs')

    assert module.refresh_after_trades(0) is False
    assert calls == []

    assert module.refresh_after_trades(300) is True
    assert calls == ['positions', 'costs']


def test_trade_timer_wrapper_refreshes_once_and_releases_busy_flag():
    module = load_credit_module()
    refreshed = []

    def run_trade_timer(context):
        module.g.trade_round_traded_volume += 100
        module.g.trade_round_traded_volume += 200

    module.run_trade_timer = run_trade_timer
    module.refresh_after_trades = lambda volume: refreshed.append(volume)

    module.on_timer(None)

    assert refreshed == [300]
    assert module.g.trade_loop_running is False


def test_response_save_failure_keeps_previous_file(tmp_path):
    module = load_credit_module()
    response_path = tmp_path / 'response.txt'
    response_path.write_text('stable-old-response', encoding='gbk')
    module.os.replace = lambda source, target: (_ for _ in ()).throw(OSError('replace failed'))
    response = pd.DataFrame([{'stock_code': '600000.SH'}])

    assert module.save_tdx_signal_response(response, str(response_path)) is False
    assert response_path.read_text(encoding='gbk') == 'stable-old-response'
    assert not (tmp_path / 'response.txt.tmp').exists()


def test_forced_deleveraging_persists_each_stock_immediately():
    module = load_credit_module()
    saved_lengths = []
    positions = [
        types.SimpleNamespace(m_nCanUseVolume=1000, m_strInstrumentID='600000', m_strExchangeID='SH', m_strInstrumentName='A'),
        types.SimpleNamespace(m_nCanUseVolume=1000, m_strInstrumentID='000001', m_strExchangeID='SZ', m_strInstrumentName='B'),
    ]
    module.g.accID = 'credit-account'
    module.get_trade_detail_data = lambda account_id, account_type, data_type: positions
    module.get_best_opposite_quote = lambda context, stock_code, direct: (10, 1000, 'bid1')
    module.do_order = lambda context, order: module.make_process_result(
        'submitted', order_id=order['stock_code'], traded_volume=order['trade_amount']
    )
    module.wait_credit_assure_snapshot_change = lambda snapshot: {
        'refreshed': True,
        'snapshot': {'valid': True, 'total_asset': 1_400_000, 'total_debt': 400_000, 'assure_ratio': 350},
    }
    module.save_tdx_signal_response = lambda response, path: saved_lengths.append(len(response)) or True

    result = module.execute_forced_deleveraging(
        None,
        300,
        {'valid': True, 'total_asset': 1_500_000, 'total_debt': 600_000, 'assure_ratio': 250},
        df_response=pd.DataFrame(),
        response_file_path='response.txt',
    )

    assert saved_lengths == [1, 2]
    assert result['persistence_failed'] is False


def test_unfinished_order_check_confirms_cancel_without_direct_retry():
    module = load_credit_module()
    order = types.SimpleNamespace(
        m_nOrderStatus=50,
        m_nVolume=500,
        m_nVolumeTraded=0,
        m_nOpType=module.CREDIT_BUY_DIRECT,
        m_strOrderID='order-1',
        m_strInstrumentID='600000',
        m_strExchangeID='SH',
    )
    confirmed = []
    module.g.accID = 'credit-account'
    module.get_trade_detail_data = lambda account_id, account_type, data_type: [order]
    module.cancel_and_get_final_order_result = lambda context, order_id, order_obj=None: confirmed.append(order_id) or {
        'confirmed': True,
        'traded_volume': 0,
        'rejected': False,
    }
    module.do_order = lambda *args: (_ for _ in ()).throw(AssertionError('unfinished checker must not submit retry orders'))

    module.check_unfinished_orders(None)

    assert confirmed == ['order-1']


def test_unconfirmed_cancel_blocks_same_stock_for_current_cycle():
    module = load_credit_module()
    order = types.SimpleNamespace(
        m_nOrderStatus=51,
        m_nVolume=500,
        m_nVolumeTraded=0,
        m_nOpType=module.CREDIT_BUY_DIRECT,
        m_strOrderID='order-1',
        m_strInstrumentID='600000',
        m_strExchangeID='SH',
    )
    module.g.accID = 'credit-account'
    module.get_trade_detail_data = lambda account_id, account_type, data_type: [order]
    module.cancel_and_get_final_order_result = lambda context, order_id, order_obj=None: {
        'confirmed': False,
        'traded_volume': None,
        'rejected': False,
    }

    blocked_codes = module.check_unfinished_orders(None)

    assert blocked_codes == {'600000'}


def test_cancel_pending_statuses_are_unfinished_but_not_terminal():
    module = load_credit_module()

    for status in [51, 52]:
        order = types.SimpleNamespace(m_nOrderStatus=status, m_nVolume=500, m_nVolumeTraded=0)
        assert module.is_unfinished_order(order) is True
        assert module.is_order_terminal(order) is False


def test_order_direction_falls_back_after_invalid_qmt_sentinel():
    module = load_credit_module()
    order = types.SimpleNamespace(m_nOpType=2147483647, m_nDirection=48)

    assert module.get_order_direct(order) == module.CREDIT_BUY_DIRECT


def test_collateral_order_matching_accepts_valid_fallback_direction():
    module = load_credit_module()
    order = types.SimpleNamespace(
        m_strOrderID='order-1',
        m_strInstrumentID='600000',
        m_strExchangeID='SH',
        m_nOpType=2147483647,
        m_nDirection=48,
        m_nVolume=500,
    )

    assert module.is_matching_submitted_order(order, {
        'stock_code': '600000.SH',
        'trade_direct': module.CREDIT_COLLATERAL_BUY_DIRECT,
        'trade_amount': 500,
    }) is True


def test_weak_sell_threshold_uses_current_bid_price():
    module = load_credit_module()
    position = types.SimpleNamespace(
        m_strInstrumentID='600000',
        m_strExchangeID='SH',
        m_nCanUseVolume=1000,
        m_nVolume=1000,
        m_dOpenPrice=10,
    )
    module.g.accID = 'credit-account'
    module.get_trade_detail_data = lambda account_id, account_type, data_type: [position]
    module.get_self_position_cost = lambda stock_code: (0, {})
    module.get_best_opposite_quote = lambda context, stock_code, direct: (14.8, 1000, 'bid1')

    order = module.convert_order({
        'stock_code': '600000',
        'price': 15.2,
        'change_percent': 0,
        'formula': 'weak-sell',
        'is_sell': 1,
        'is_buy': 0,
    }, None)

    assert order['price'] == 14.8
    assert order['trade_amount'] == 0


def test_directional_slippage_allows_favorable_prices_only():
    module = load_credit_module()

    assert module.is_slippage_exceeded(10, 9.5, 0.03, module.CREDIT_BUY_DIRECT)[0] is False
    assert module.is_slippage_exceeded(10, 10.5, 0.03, module.CREDIT_SELL_DIRECT)[0] is False
    assert module.is_slippage_exceeded(10, 10.5, 0.03, module.CREDIT_BUY_DIRECT)[0] is True
    assert module.is_slippage_exceeded(10, 9.5, 0.03, module.CREDIT_SELL_DIRECT)[0] is True


def test_timer_cancels_unfinished_orders_after_end_time():
    module = load_credit_module()
    cancelled = []
    module.g.params['\u5f00\u59cb\u65f6\u95f4'] = '00:00:00'
    module.g.params['\u7ed3\u675f\u65f6\u95f4'] = '00:00:00'
    module.cleanup_cleared_position_costs = lambda: None
    module.is_trade_account_ready = lambda: True
    module.cancel_unfinished_orders_after_close = lambda context: cancelled.append(True)

    module.on_timer(None)

    assert cancelled == [True]


def test_hard_assure_ratio_defaults_to_disabled():
    module = load_credit_module()

    assert module.g.params[module.HARD_ASSURE_RATIO_PARAM] == 0
    assert module.get_hard_assure_ratio() == 0


def test_hard_assure_ratio_accepts_supported_range_only():
    module = load_credit_module()
    module.g.params[module.HARD_ASSURE_RATIO_PARAM] = 300
    assert module.get_hard_assure_ratio() == 300

    module.g.params[module.HARD_ASSURE_RATIO_PARAM] = 199
    assert module.get_hard_assure_ratio() == 0


def test_credit_assure_snapshot_uses_total_debit_then_fin_debt_fallback():
    module = load_credit_module()
    module.g.accID = 'credit-account'
    assets = [types.SimpleNamespace(m_dBalance=1_500_000, m_dTotalDebit=500_000, m_dFinDebt=400_000)]
    module.get_trade_detail_data = lambda account_id, account_type, data_type: assets

    snapshot = module.get_credit_assure_snapshot()
    assert snapshot['valid'] is True
    assert snapshot['debt_field'] == 'm_dTotalDebit'
    assert snapshot['assure_ratio'] == 300

    assets[0] = types.SimpleNamespace(m_dBalance=1_500_000, m_dFinDebt=500_000)
    snapshot = module.get_credit_assure_snapshot()
    assert snapshot['debt_field'] == 'm_dFinDebt'
    assert snapshot['assure_ratio'] == 300


def test_credit_assure_snapshot_marks_missing_debt_field_invalid():
    module = load_credit_module()
    module.g.accID = 'credit-account'
    module.get_trade_detail_data = lambda account_id, account_type, data_type: [
        types.SimpleNamespace(m_dBalance=1_500_000)
    ]

    assert module.get_credit_assure_snapshot()['valid'] is False


def test_required_repayment_reaches_target_assure_ratio():
    module = load_credit_module()

    repayment = module.calculate_required_repayment(1_500_000, 500_000, 350)

    assert repayment == 100_000
    assert (1_500_000 - repayment) / (500_000 - repayment) * 100 == 350


def test_equal_sell_plan_uses_same_position_ratio_and_rounds_down():
    module = load_credit_module()
    candidates = [
        {'stock_code': '600000.SH', 'can_use_volume': 1000, 'bid_price': 20},
        {'stock_code': '000001.SZ', 'can_use_volume': 1000, 'bid_price': 30},
    ]

    plan = module.calculate_equal_sell_plan(candidates, 10_000)

    assert [item['sell_volume'] for item in plan] == [200, 200]
    assert sum(item['planned_amount'] for item in plan) == 10_000


def test_forced_deleveraging_sells_equal_ratios_and_builds_response_records():
    module = load_credit_module()
    module.g.accID = 'credit-account'
    positions = [
        types.SimpleNamespace(
            m_strInstrumentID='600000', m_strExchangeID='SH',
            m_strInstrumentName='浦发银行', m_nCanUseVolume=10_000,
        ),
        types.SimpleNamespace(
            m_strInstrumentID='000001', m_strExchangeID='SZ',
            m_strInstrumentName='平安银行', m_nCanUseVolume=10_000,
        ),
    ]
    module.get_trade_detail_data = lambda account_id, account_type, data_type: positions
    module.get_best_opposite_quote = lambda context, code, direct: (
        (20, 10_000, '买一') if code == '600000.SH' else (10, 10_000, '买一')
    )
    submitted = []

    def do_order(context, order):
        submitted.append(order)
        return module.make_process_result(
            'submitted', order_id=str(len(submitted)),
            traded_volume=order['trade_amount'], remaining_volume=0,
        )

    module.do_order = do_order
    module.get_credit_assure_snapshot = lambda: {
        'valid': True, 'total_asset': 1_350_000,
        'total_debt': 450_000, 'assure_ratio': 300,
    }
    initial_snapshot = {
        'valid': True, 'total_asset': 1_500_000,
        'total_debt': 600_000, 'assure_ratio': 250,
    }

    result = module.execute_forced_deleveraging(None, 300, initial_snapshot)

    assert [order['trade_amount'] for order in submitted] == [5000, 5000]
    assert all(order['trade_direct'] == module.CREDIT_SELL_DIRECT for order in submitted)
    assert all(record['formula'] == '担保比例强制卖出' for record in result['records'])
    assert result['reached'] is True


def test_on_timer_forces_deleveraging_without_signal_file_rows():
    module = load_credit_module()
    module.g.params['开始时间'] = '00:00:00'
    module.g.params['结束时间'] = '23:59:59'
    module.cleanup_cleared_position_costs = lambda: None
    module.is_trade_account_ready = lambda: True
    module.check_unfinished_orders = lambda context: None
    module.get_response_file_path = lambda: 'response.txt'
    module.load_tdx_response = lambda path: pd.DataFrame()
    module.load_tdx_signal = lambda path: pd.DataFrame()
    module.get_hard_assure_ratio = lambda: 300
    module.get_credit_assure_snapshot = lambda: {
        'valid': True, 'total_asset': 1_500_000,
        'total_debt': 600_000, 'assure_ratio': 250,
    }
    forced_calls = []
    forced_record = {
        'stock_code': '600000.SH', 'name': '浦发银行',
        'datetime': '2026-07-13 10:00:00', 'price': 10,
        'change_percent': '', 'volume': 100,
        'formula': '担保比例强制卖出', 'process_status': 'filled',
        'process_reason': '', 'order_id': '1', 'order_ids': '1',
        'traded_volume': 100, 'remaining_volume': 0, 'processed_at': '',
    }

    def force(context, ratio, snapshot, **kwargs):
        forced_calls.append((ratio, snapshot['assure_ratio']))
        return {
            'records': [forced_record],
            'final_snapshot': {'valid': True, 'assure_ratio': 300},
            'reached': True,
        }

    module.execute_forced_deleveraging = force

    module.on_timer(None)

    assert forced_calls == [(300, 250)]


def test_on_timer_orders_normal_sell_then_forced_sell_then_buy():
    module = load_credit_module()
    module.g.params['开始时间'] = '00:00:00'
    module.g.params['结束时间'] = '23:59:59'
    module.cleanup_cleared_position_costs = lambda: None
    module.is_trade_account_ready = lambda: True
    module.check_unfinished_orders = lambda context: None
    module.get_response_file_path = lambda: 'response.txt'
    module.load_tdx_response = lambda path: pd.DataFrame()
    module.load_tdx_signal = lambda path: pd.DataFrame([
        {'stock_code': '600000', 'name': 'A', 'datetime': '1', 'price': 10, 'change_percent': 0, 'volume': 0, 'formula': '弱卖'},
        {'stock_code': '000001', 'name': 'B', 'datetime': '2', 'price': 10, 'change_percent': 0, 'volume': 0, 'formula': '五日内六级'},
    ])
    module.get_hard_assure_ratio = lambda: 300
    snapshots = iter([
        {'valid': True, 'assure_ratio': 250},
        {'valid': True, 'assure_ratio': 260},
    ])
    module.get_credit_assure_snapshot = lambda: next(snapshots)
    events = []

    def process(context, rows, response, count, hard_ratio=0, check_after_buy=False, response_file_path=''):
        events.append(rows.iloc[0]['formula'])
        return {
            'df_response': response,
            'response_buy_stock_count': count,
            'changed': False,
            'stopped_by_hard_ratio': False,
        }

    module.process_signal_rows = process

    def force(context, ratio, snapshot, **kwargs):
        events.append('担保比例强制卖出')
        return {'records': [], 'final_snapshot': {'valid': True, 'assure_ratio': 300}, 'reached': True}

    module.execute_forced_deleveraging = force

    module.on_timer(None)

    assert events == ['弱卖', '担保比例强制卖出', '五日内六级']


def test_buy_breach_forces_sell_and_stops_remaining_buys():
    module = load_credit_module()
    rows = pd.DataFrame([
        {'stock_code': '600000', 'name': 'A', 'datetime': '1', 'price': 10, 'change_percent': 0, 'volume': 0, 'formula': '五日内六级', 'is_buy': 1, 'is_sell': 0},
        {'stock_code': '000001', 'name': 'B', 'datetime': '2', 'price': 10, 'change_percent': 0, 'volume': 0, 'formula': '五日内六级', 'is_buy': 1, 'is_sell': 0},
    ])
    module.convert_order = lambda signal, context=None: {'trade_amount': 1000, 'stock_code': signal['stock_code']}
    submitted = []

    def do_order(context, order):
        submitted.append(order['stock_code'])
        return module.make_process_result('submitted', traded_volume=100, remaining_volume=0)

    module.do_order = do_order
    module.get_credit_assure_snapshot = lambda: {'valid': True, 'assure_ratio': 250}
    forced = []
    module.execute_forced_deleveraging = lambda context, ratio, snapshot, **kwargs: (
        forced.append(ratio) or {'records': [], 'final_snapshot': {'valid': True, 'assure_ratio': 300}}
    )

    result = module.process_signal_rows(
        None, rows, pd.DataFrame(), 0,
        hard_ratio=300, check_after_buy=True,
    )

    assert submitted == ['600000']
    assert forced == [300]
    assert result['stopped_by_hard_ratio'] is True


def test_invalid_assure_fields_process_sell_but_block_buy():
    module = load_credit_module()
    module.g.params['开始时间'] = '00:00:00'
    module.g.params['结束时间'] = '23:59:59'
    module.cleanup_cleared_position_costs = lambda: None
    module.is_trade_account_ready = lambda: True
    module.check_unfinished_orders = lambda context: None
    module.get_response_file_path = lambda: 'response.txt'
    module.load_tdx_response = lambda path: pd.DataFrame()
    module.load_tdx_signal = lambda path: pd.DataFrame([
        {'stock_code': '600000', 'name': 'A', 'datetime': '1', 'price': 10, 'change_percent': 0, 'volume': 0, 'formula': '弱卖'},
        {'stock_code': '000001', 'name': 'B', 'datetime': '2', 'price': 10, 'change_percent': 0, 'volume': 0, 'formula': '五日内六级'},
    ])
    module.get_hard_assure_ratio = lambda: 300
    module.get_credit_assure_snapshot = lambda: {'valid': False, 'reason': '缺少负债字段'}
    processed = []

    def process(context, rows, response, count, hard_ratio=0, check_after_buy=False, response_file_path=''):
        processed.extend(rows['formula'].tolist())
        return {
            'df_response': response,
            'response_buy_stock_count': count,
            'changed': False,
            'stopped_by_hard_ratio': False,
        }

    module.process_signal_rows = process

    module.on_timer(None)

    assert processed == ['弱卖']


def test_forced_deleveraging_does_not_submit_without_sellable_positions():
    module = load_credit_module()
    module.g.accID = 'credit-account'
    module.get_trade_detail_data = lambda account_id, account_type, data_type: []
    module.get_credit_assure_snapshot = lambda: {
        'valid': True, 'total_asset': 1_500_000,
        'total_debt': 600_000, 'assure_ratio': 250,
    }
    module.do_order = lambda context, order: (_ for _ in ()).throw(AssertionError('不应下单'))

    result = module.execute_forced_deleveraging(None, 300, {
        'valid': True, 'total_asset': 1_500_000,
        'total_debt': 600_000, 'assure_ratio': 250,
    })

    assert result['attempted'] is False
    assert result['reached'] is False
    assert result['records'] == []


def test_forced_sell_response_is_classified_as_sell_for_dedup():
    module = load_credit_module()
    module.g.params['防重规则'] = '按股票代码'
    request = pd.DataFrame([
        {'stock_code': '600000.SH', 'name': 'A', 'datetime': '2', 'price': 10, 'change_percent': 0, 'volume': 0, 'formula': '五日内六级'}
    ])
    response = pd.DataFrame([
        {'stock_code': '600000.SH', 'name': 'A', 'datetime': '1', 'price': 10, 'change_percent': '', 'volume': 100,
         'formula': '担保比例强制卖出', 'process_status': 'filled', 'remaining_volume': 0}
    ])

    flagged = module.add_signal_flags(response.copy())
    remaining = module.prepare_new_signal_requests(request, response)

    assert flagged.iloc[0]['is_sell'] == 1
    assert len(remaining) == 1


def test_wait_assure_snapshot_requires_account_fields_to_change():
    module = load_credit_module()
    module.g.params['账户担保比例刷新等待秒数'] = 1
    module.g.params['账户担保比例刷新超时秒数'] = 1
    sleeps = []
    module.time.sleep = lambda seconds: sleeps.append(seconds)
    previous = {'valid': True, 'total_asset': 1_500_000, 'total_debt': 600_000, 'assure_ratio': 250}
    module.get_credit_assure_snapshot = lambda: dict(previous)

    result = module.wait_credit_assure_snapshot_change(previous)

    assert sleeps[0] == 1
    assert result['refreshed'] is False


def test_pending_account_refresh_blocks_repeated_forced_sell():
    module = load_credit_module()
    snapshot = {'valid': True, 'total_asset': 1_500_000, 'total_debt': 600_000, 'assure_ratio': 250}
    module.g.pending_assure_refresh_snapshot = dict(snapshot)
    module.get_trade_detail_data = lambda *args: (_ for _ in ()).throw(AssertionError('等待刷新时不应查询持仓'))

    result = module.execute_forced_deleveraging(None, 300, snapshot)

    assert result['attempted'] is False
    assert result['reason'] == '等待账户字段刷新'


def test_stale_account_after_normal_sell_blocks_forced_sell_and_buy():
    module = load_credit_module()
    module.g.params['开始时间'] = '00:00:00'
    module.g.params['结束时间'] = '23:59:59'
    module.cleanup_cleared_position_costs = lambda: None
    module.is_trade_account_ready = lambda: True
    module.check_unfinished_orders = lambda context: None
    module.get_response_file_path = lambda: 'response.txt'
    module.load_tdx_response = lambda path: pd.DataFrame()
    module.load_tdx_signal = lambda path: pd.DataFrame([
        {'stock_code': '600000', 'name': 'A', 'datetime': '1', 'price': 10, 'change_percent': 0, 'volume': 0, 'formula': '弱卖'},
        {'stock_code': '000001', 'name': 'B', 'datetime': '2', 'price': 10, 'change_percent': 0, 'volume': 0, 'formula': '五日内六级'},
    ])
    module.get_hard_assure_ratio = lambda: 300
    stale_snapshot = {'valid': True, 'total_asset': 1_500_000, 'total_debt': 600_000, 'assure_ratio': 250}
    module.get_credit_assure_snapshot = lambda: dict(stale_snapshot)
    processed = []

    def process(context, rows, response, count, hard_ratio=0, check_after_buy=False, response_file_path=''):
        processed.extend(rows['formula'].tolist())
        return {
            'df_response': response,
            'response_buy_stock_count': count,
            'changed': False,
            'stopped_by_hard_ratio': False,
            'total_traded_volume': 100,
        }

    module.process_signal_rows = process
    module.wait_credit_assure_snapshot_change = lambda previous: {
        'refreshed': False,
        'snapshot': dict(stale_snapshot),
    }
    module.execute_forced_deleveraging = lambda *args: (_ for _ in ()).throw(
        AssertionError('账户未刷新时不应强卖')
    )

    module.on_timer(None)

    assert processed == ['弱卖']
