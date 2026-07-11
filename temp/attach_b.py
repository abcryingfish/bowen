# -*- coding: gbk -*-
import pandas as pd
import numpy as np
import talib
import time
from datetime import datetime
import math
import os
import json
import logging
from xtquant import xtdata
# 全局参数
class a():
    pass

g = a()
g.retried_order_ids = set()
g.cost_recorded_order_ids = set()
g.params = {
    '策略名称': '通达信预警交易策�?,
    '开始时�?: '09:30:00',
    '结束时间': '15:57:00',
    '最大买入标的数': 1000,
    '单次买入仓位比例': 0.002,
    '兜底买入金额': 10000,
    '盘口补单等待秒数': 5,
    '盘口最大轮�?: 10,
    '撤单等待tick�?: 1,
    '重新下单等待tick�?: 2,
    'tick等待超时秒数': 6,
    '最大滑点比�?: 0.03,
    '检查未完成委托': True,
    '价格类型': '对手�?,
    '预警文件': r'C:\Users\Administrator\Desktop\python_venv\buy.txt',
    '防重规则': '按股票代�?,
    '公式配置': r'C:\new_tdx_ok\T0002\signals\预警公式配置.xlsx',
    '历史成交开始日�?: datetime.now().strftime('%Y%m%d'),
}

TRADE_LOG_FILE = r'C:\Users\Administrator\Desktop\python_venv\trade_record_log.txt'
POSITION_COST_FILE = r'C:\Users\Administrator\Desktop\python_venv\position_cost.json'
g.last_trade_log_time = 0
g.last_cost_cleanup_date = ''

def safe_log_value(value, depth=0):
    if depth >= 3:
        return '<max_depth>'

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:80]:
            try:
                safe_key = key if isinstance(key, str) else object.__repr__(key)
            except:
                safe_key = '<bad_key>'
            result[safe_key] = safe_log_value(item, depth + 1)
        return result

    if isinstance(value, (list, tuple, set)):
        return [safe_log_value(item, depth + 1) for item in list(value)[:120]]

    result = {'__class__': value.__class__.__name__}
    try:
        attrs = getattr(value, '__dict__', None)
        if isinstance(attrs, dict):
            for key, item in list(attrs.items())[:80]:
                result[key] = safe_log_value(item, depth + 1)
            return result
    except:
        pass

    for name in dir(value):
        if name.startswith('_'):
            continue
        try:
            item = getattr(value, name)
            if callable(item):
                continue
            result[name] = safe_log_value(item, depth + 1)
        except Exception as e:
            result[name] = '<read_error:%s>' % e.__class__.__name__

    return result


def safe_log_text(value):
    try:
        return json.dumps(safe_log_value(value), ensure_ascii=False, default=lambda item: object.__repr__(item))
    except Exception as e:
        try:
            return '<log_serialize_error:%s>' % e.__class__.__name__
        except:
            return '<log_serialize_error>'

def write_trade_log(title, data=None):
    try:
        log_dir = os.path.dirname(TRADE_LOG_FILE)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        log_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(TRADE_LOG_FILE, 'a', encoding='utf-8-sig') as f:
            f.write('\n' + '=' * 80 + '\n')
            f.write(f'[{log_time}] {title}\n')
            if data is not None:
                f.write(safe_log_text(data) + '\n')

        print('日志已写�?', TRADE_LOG_FILE, flush=True)
    except Exception as e:
        print('写入交易日志异常', e, flush=True)


def load_position_costs():
    try:
        if not os.path.exists(POSITION_COST_FILE):
            return {}

        with open(POSITION_COST_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return data if isinstance(data, dict) else {}
    except Exception as e:
        write_trade_log('读取持有成本JSON异常', {'file': POSITION_COST_FILE, 'error': str(e)})
        return {}


def save_position_costs(data):
    try:
        cost_dir = os.path.dirname(POSITION_COST_FILE)
        if cost_dir and not os.path.exists(cost_dir):
            os.makedirs(cost_dir)

        with open(POSITION_COST_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        write_trade_log('保存持有成本JSON成功', {'file': POSITION_COST_FILE, 'count': len(data)})
    except Exception as e:
        write_trade_log('保存持有成本JSON异常', {'file': POSITION_COST_FILE, 'error': str(e), 'data': data})


def update_position_cost_on_buy(stock_code, price, volume):
    try:
        price = float(price)
        volume = int(volume)
    except:
        write_trade_log('买入持有成本更新跳过：价格或数量异常', {
            'stock_code': stock_code,
            'price': price,
            'volume': volume,
        })
        return

    if price <= 0 or volume <= 0:
        write_trade_log('买入持有成本更新跳过：价格或数量�?', {
            'stock_code': stock_code,
            'price': price,
            'volume': volume,
        })
        return

    costs = load_position_costs()
    item = costs.get(stock_code, {})

    old_buy_amount = float(item.get('buy_amount', 0) or 0)
    old_buy_volume = int(item.get('buy_volume', 0) or 0)
    buy_amount = old_buy_amount + price * volume
    buy_volume = old_buy_volume + volume
    cost_price = buy_amount / buy_volume if buy_volume > 0 else 0

    costs[stock_code] = {
        'buy_amount': buy_amount,
        'buy_volume': buy_volume,
        'cost_price': cost_price,
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    save_position_costs(costs)
    write_trade_log('买入后更新自维护持有成本', {
        'stock_code': stock_code,
        'price': price,
        'volume': volume,
        'old_buy_amount': old_buy_amount,
        'old_buy_volume': old_buy_volume,
        'buy_amount': buy_amount,
        'buy_volume': buy_volume,
        'cost_price': cost_price,
    })


def get_self_position_cost(stock_code):
    costs = load_position_costs()
    item = costs.get(stock_code, {})
    try:
        cost_price = float(item.get('cost_price', 0) or 0)
    except:
        cost_price = 0

    return cost_price, item


def mark_half_sell_done(stock_code):
    costs = load_position_costs()
    item = costs.get(stock_code, {})
    item['half_sell_done'] = True
    item['half_sell_done_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    costs[stock_code] = item
    save_position_costs(costs)
    write_trade_log('记录150%卖出已执�?, {
        'stock_code': stock_code,
        'cost_info': item,
    })


def cleanup_cleared_position_costs():
    curr_time = datetime.now().strftime('%H%M%S')
    curr_date = datetime.now().strftime('%Y%m%d')
    if curr_time < '153500' or g.last_cost_cleanup_date == curr_date:
        return

    g.last_cost_cleanup_date = curr_date

    costs = load_position_costs()
    if not costs:
        return

    try:
        positions = get_trade_detail_data(g.accID, 'STOCK', 'POSITION')
    except Exception as e:
        write_trade_log('清理持有成本异常：查询持仓失�?, str(e))
        return

    holding_codes = set()
    for position in positions:
        code = getattr(position, 'm_strInstrumentID', '') + '.' + getattr(position, 'm_strExchangeID', '')
        volume = getattr(position, 'm_nVolume', 0)
        if code.strip('.') and volume > 0:
            holding_codes.add(code.upper())

    removed = {}
    for stock_code in list(costs.keys()):
        if stock_code.upper() not in holding_codes:
            removed[stock_code] = costs.pop(stock_code)

    if removed:
        save_position_costs(costs)

    write_trade_log('下午1535清理已清仓持有成本完�?, {
        'holding_count': len(holding_codes),
        'removed_count': len(removed),
        'removed': removed,
    })


def obj_to_dict(obj):
    try:
        return obj.__dict__
    except:
        result = {}
        for name in dir(obj):
            if name.startswith('_'):
                continue
            try:
                value = getattr(obj, name)
                if not callable(value):
                    result[name] = value
            except:
                pass
        return result


def obj_to_debug_dict(obj):
    result = obj_to_dict(obj)
    if result:
        return result

    debug = {}
    for name in dir(obj):
        if name.startswith('_'):
            continue
        try:
            value = getattr(obj, name)
            if not callable(value):
                debug[name] = value
        except:
            pass
    return debug


def log_all_trade_records(force=False):
    try:
        now_ts = time.time()
        if not force and now_ts - g.last_trade_log_time < 5:
            return

        g.last_trade_log_time = now_ts

        write_trade_log('当前账户', getattr(g, 'accID', ''))

        for data_type in ['ACCOUNT', 'POSITION', 'ORDER', 'DEAL']:
            try:
                records = get_trade_detail_data(g.accID, 'STOCK', data_type)
                write_trade_log(f'{data_type} 记录数量', len(records))

                for i, item in enumerate(records):
                    write_trade_log(f'{data_type} #{i + 1}', obj_to_dict(item))

            except Exception as e:
                write_trade_log(f'{data_type} 查询异常', str(e))

        print('已写入交易记录日�?, TRADE_LOG_FILE, flush=True)

    except Exception as e:
        print('记录交易日志异常', e, flush=True)


# 生成xml文件，方便后续读�?
def create_xml_if_not_exists(xml_name):
    xml_content = '''<?xml version="1.0" encoding="utf-8"?>
                <TCStageLayout>
                    <control note="控件">
                        <variable note="控件">
                            <item position="" bind="start_time" value="09:30:00" note="开始时�? name="开始时�? type="intput"/>
                            <item position="" bind="end_time" value="15:05:00" note="结束时间" name="结束时间" type="intput"/>
                            <item position="" bind="max_buy_count" value="10" note="最大买入标的数" name="最大买入标的数" type="intput"/>
                            <item position="" bind="price_type_combo" value="对手�? note="价格类型" name="价格类型" type="combo" comboType="custom" list="预警�?对手�?市价�? />
                            <item position="" bind="request_file" value="C:/Users/Administrator/Desktop/python_venv/buy.txt" note="预警文件" name="预警文件" type="intput"/>
                            <item position="" bind="avoid_repeat_type" value="按股票代�? note="防重规则" name="防重规则" type="combo" comboType="custom" list="按股票代�?按代�?时间/条件" />
                            <item position="" bind="formula_param" value="C:/new_tdx_ok/T0002/signals/预警公式配置.xlsx" note="公式配置" name="公式配置" type="intput"/>
                      </variable>
                    </control>
                </TCStageLayout>'''

    current_directory = os.getcwd()
    parent_directory = os.path.dirname(current_directory)
    file_path = parent_directory + "\\python\\formulaLayout\\" + xml_name + '.xml'

    print("当前工作目录:", os.getcwd(), flush=True)
    print("XML目标路径:", file_path, flush=True)

    if not os.path.exists(file_path):
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        print("初始化配置！", flush=True)
        return 0
    else:
        print("file already exists, skipping�?, flush=True)
        return 1


# 策略初始�?
def init(C):
    write_trade_log('策略启动测试日志', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    is_exists = create_xml_if_not_exists(g.params['策略名称'])
    if is_exists != 1:
        clear_buy_file_if_response_missing(g.params['预警文件'], get_response_file_path())
        return

    set_param(C)
    set_account(C)
    clear_buy_file_if_response_missing(g.params['预警文件'], get_response_file_path())
    cancel_all_orders_on_startup(C)
    export_official_position_costs()
    C.run_time("on_timer", "3nSecond", "2026-02-10 09:30:00")


def cancel_all_orders_on_startup(C):
    try:
        orders = get_trade_detail_data(g.accID, 'STOCK', 'ORDER')
    except Exception as e:
        write_trade_log('startup cancel all orders failed: query ORDER failed', str(e))
        return

    if not orders:
        write_trade_log('startup cancel all orders skipped: no orders')
        return

    cancelled_order_ids = []
    for order_obj in orders:
        order_id = get_order_id_from_obj(order_obj)
        cancel_order_if_possible(C, order_id, order_obj)
        if order_id:
            g.retried_order_ids.add(order_id)
            cancelled_order_ids.append(order_id)

    write_trade_log('startup cancel all orders submitted', {
        'order_count': len(orders),
        'cancelled_order_ids': cancelled_order_ids,
    })

# 设置全局参数和变�?
def set_param(C):
    try:
        g.params['开始时�?] = start_time
        g.params['结束时间'] = end_time
        g.params['最大买入标的数'] = max_buy_count
        g.params['价格类型'] = price_type_combo
        g.params['预警文件'] = request_file
        g.params['防重规则'] = avoid_repeat_type
        g.params['公式配置'] = formula_param
    except Exception as e:
        print('参数设置异常', e, flush=True)
        write_trade_log('参数设置异常', str(e))

    print(json.dumps(g.params, ensure_ascii=False, indent=2), flush=True)
    write_trade_log('当前参数', g.params)

    g.df_formula = pd.DataFrame()


# 设置资金账户
def set_account(C):
    try:
        g.accID = '1000310'
    except Exception as err:
        g.accID = ''
        print('获取account失败', err, flush=True)
        write_trade_log('获取account失败', str(err))

    C.set_account(g.accID)
    print('当前账户:', g.accID, flush=True)
    write_trade_log('设置账户', g.accID)


def on_timer(C):
    curr_dt = datetime.now().strftime('%Y%m%d%H%M%S')

    cleanup_cleared_position_costs()

    if curr_dt[-6:] < g.params['开始时�?].replace(':', '') or curr_dt[-6:] >= g.params['结束时间'].replace(':', ''):
        return

    check_unfinished_orders(C)

    df_request = load_tdx_signal(g.params['预警文件'])
    if df_request.empty:
        print('预警为空', flush=True)
        return

    df_request = add_signal_flags(df_request)
    df_request = df_request[(df_request['is_sell'] == 1) | (df_request['is_buy'] == 1)]

    response_file_path = get_response_file_path()
    df_response = load_tdx_response(response_file_path)
    response_buy_stock_count = get_response_buy_stock_count(df_response)

    if not df_response.empty:
        df_response = add_signal_flags(df_response)
        index_cols = ['stock_code', 'is_sell'] if g.params['防重规则'] == '按股票代�? else ['stock_code', 'datetime', 'formula']
        unique_indexes = df_response[index_cols].drop_duplicates()
        mask = df_request[index_cols].apply(tuple, axis=1).isin(unique_indexes.apply(tuple, axis=1))
        df_request = df_request[~mask]

    if df_request.empty:
        print('没有新增预警', flush=True)
        return

    print('新增预警', len(df_request), df_request, flush=True)
    write_trade_log('新增预警', df_request.to_dict('records'))

    response_columns = df_request.columns
    for _, row in df_request.iterrows():
        if int(row.get('is_buy', 0)) == 1 and response_buy_stock_count >= g.params['最大买入标的数']:
            signal_info = row.to_dict()
            print('已达当日最大买入标的数', flush=True)
            write_trade_log('已达当日最大买入标的数，跳过本条买入信�?, {
                'response_buy_stock_count': response_buy_stock_count,
                'signal': signal_info,
            })
            process_result = make_process_result('skipped', '已达当日最大买入标的数')
            response_signal_info = add_process_result_to_signal(signal_info, process_result)
            df_response_item = pd.DataFrame([response_signal_info])
            df_response = pd.concat([df_response, df_response_item])
            continue

        signal_info = row.to_dict()
        write_trade_log('收到预警信号', signal_info)

        order = convert_order(signal_info)
        write_trade_log('生成委托信息', order)

        process_result = do_order(C, order)

        response_signal_info = add_process_result_to_signal(signal_info, process_result)
        df_response_item = pd.DataFrame([response_signal_info])
        df_response = pd.concat([df_response, df_response_item])
        response_buy_stock_count = get_response_buy_stock_count(df_response)

    df_response.drop(['is_sell', 'is_buy'], axis=1, inplace=True, errors='ignore')
    save_tdx_signal_response(df_response, response_file_path)


# 直接根据预警信号名称标记买入/卖出
def add_signal_flags(df_request):
    df_request['is_sell'] = df_request['formula'].apply(
        lambda x: 1 if str(x).strip() == '弱卖' else 0
    )
    df_request['is_buy'] = df_request['formula'].apply(
        lambda x: 1 if str(x).strip() == '五日内六�? else 0
    )
    return df_request



def get_response_buy_stock_count(df_response):
    if df_response is None or df_response.empty or 'stock_code' not in df_response.columns:
        return 0

    df = add_signal_flags(df_response.copy())
    df_buy = df[df['is_buy'] == 1]
    if df_buy.empty:
        return 0

    traded_volume = pd.to_numeric(df_buy.get('traded_volume', 0), errors='coerce').fillna(0)
    df_buy = df_buy[traded_volume > 0]
    if df_buy.empty:
        return 0

    stock_codes = df_buy['stock_code'].astype(str).str.strip()
    stock_codes = stock_codes[stock_codes != '']
    return len(stock_codes.drop_duplicates())

# 获取响应文件路径
def get_response_file_path():
    file_path = g.params['预警文件']
    dir_path = os.path.dirname(file_path)
    file_name_without_ext = os.path.splitext(os.path.basename(file_path))[0]
    curr_date = datetime.now().strftime('%Y%m%d')
    file_name = file_name_without_ext + "_response_" + curr_date + ".txt"
    response_file_path = os.path.join(dir_path, file_name)
    return response_file_path


def clear_buy_file_if_response_missing(buy_file_path, response_file_path):
    try:
        if os.path.exists(response_file_path):
            print('当天response文件已存在，不清空预警文�?, response_file_path, flush=True)
            write_trade_log('启动检查：当天response文件已存在，不清空预警文�?, {
                'buy_file_path': buy_file_path,
                'response_file_path': response_file_path,
            })
            return False

        dir_path = os.path.dirname(buy_file_path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path)

        with open(buy_file_path, 'w', encoding='gbk') as f:
            f.write('')

        print('当天response文件不存在，已清空预警文�?, buy_file_path, flush=True)
        write_trade_log('启动检查：当天response文件不存在，已清空预警文�?, {
            'buy_file_path': buy_file_path,
            'response_file_path': response_file_path,
        })
        return True
    except Exception as e:
        print('启动清空预警文件异常', e, buy_file_path, flush=True)
        write_trade_log('启动清空预警文件异常', {
            'buy_file_path': buy_file_path,
            'response_file_path': response_file_path,
            'error': str(e),
        })
        return False



def round_lot(volume):
    return int(volume) // 100 * 100

def get_tick_data(C, stock_code):
    try:
        if C is not None and hasattr(C, 'get_full_tick'):
            tick_data = C.get_full_tick([stock_code])
        else:
            tick_data = xtdata.get_full_tick([stock_code])
        return tick_data.get(stock_code, {}) if isinstance(tick_data, dict) else {}
    except Exception as e:
        print('获取tick异常', stock_code, e, flush=True)
        write_trade_log('获取tick异常', {'stock_code': stock_code, 'error': str(e)})
        return {}


def get_tick_key(C, stock_code):
    tick = get_tick_data(C, stock_code)
    return (
        tick.get('timetag') or tick.get('time') or '',
        tick.get('lastPrice') or tick.get('last_price') or 0,
        str(tick.get('askPrice') or ''),
        str(tick.get('bidPrice') or ''),
    )


def wait_market_ticks(C, stock_code, tick_count):
    tick_count = max(int(tick_count), 0)
    if tick_count <= 0:
        return

    timeout_seconds = g.params.get('tick等待超时秒数', 6)
    last_key = get_tick_key(C, stock_code)
    changed_count = 0
    start_ts = time.time()

    while changed_count < tick_count:
        time.sleep(0.2)
        curr_key = get_tick_key(C, stock_code)
        if curr_key != last_key and curr_key[0] != '':
            changed_count += 1
            last_key = curr_key
            start_ts = time.time()
            continue

        if time.time() - start_ts >= timeout_seconds:
            write_trade_log('等待tick超时，按时间兜底继续', {
                'stock_code': stock_code,
                'target_tick_count': tick_count,
                'changed_count': changed_count,
                'timeout_seconds': timeout_seconds,
            })
            break


def get_best_opposite_quote(C, stock_code, trade_direct):
    try:
        tick = get_tick_data(C, stock_code)

        if trade_direct == 23:
            prices = tick.get('askPrice', [])
            vols = tick.get('askVol', [])
            side_name = '卖一'
        else:
            prices = tick.get('bidPrice', [])
            vols = tick.get('bidVol', [])
            side_name = '买一'

        if not prices or not vols:
            return 0, 0, side_name

        price = float(prices[0])
        raw_volume = int(vols[0])
        volume = raw_volume * 100

        if price <= 0 or volume <= 0:
            return 0, 0, side_name

        write_trade_log('获取盘口对手�?, {
            'stock_code': stock_code,
            'side': side_name,
            'price': price,
            'raw_volume': raw_volume,
            'volume': volume,
            'volume_unit': '�?,
            'raw_volume_unit': '�?,
        })
        return price, volume, side_name

    except Exception as e:
        print('获取盘口异常', stock_code, e, flush=True)
        write_trade_log('获取盘口异常', {'stock_code': stock_code, 'error': str(e)})
        return 0, 0, ''



def get_price_slippage_ratio(signal_price, quote_price):
    try:
        signal_price = float(signal_price)
        quote_price = float(quote_price)
    except Exception:
        return None

    if signal_price <= 0 or quote_price <= 0:
        return None

    return abs(quote_price / signal_price - 1)


def is_slippage_exceeded(signal_price, quote_price, max_slippage_ratio):
    slippage_ratio = get_price_slippage_ratio(signal_price, quote_price)
    if slippage_ratio is None:
        return False, None

    return slippage_ratio > max_slippage_ratio, slippage_ratio


def fetch_last_order_id(strategy_name, poll_seconds=2):
    end_ts = time.time() + poll_seconds
    last_order_id = ''
    while time.time() <= end_ts:
        try:
            last_order_id = get_last_order_id(g.accID, 'STOCK', strategy_name)
        except Exception as e:
            write_trade_log('获取最新委托号异常', str(e))
            return ''

        if last_order_id:
            return last_order_id

        time.sleep(0.1)

    return last_order_id


def get_current_order_id_set():
    try:
        orders = get_trade_detail_data(g.accID, 'STOCK', 'ORDER')
    except Exception as e:
        write_trade_log('获取当前委托列表异常', str(e))
        return set()

    order_ids = set()
    for order_obj in orders or []:
        order_id = get_order_id_from_obj(order_obj)
        if order_id:
            order_ids.add(order_id)

    return order_ids


def is_matching_submitted_order(order_obj, order_to_send):
    order_id = get_order_id_from_obj(order_obj)
    stock_code = get_order_stock_code(order_obj)
    trade_direct = infer_order_direct(order_obj, stock_code, '新增委托方向字段未识�?)
    total_volume = get_order_total_volume(order_obj)

    if not order_id:
        return False

    if stock_code != str(order_to_send.get('stock_code', '')).upper():
        return False

    if trade_direct != order_to_send.get('trade_direct'):
        return False

    if round_lot(total_volume) != round_lot(order_to_send.get('trade_amount', 0)):
        return False

    return True


def fetch_submitted_order_id(before_order_ids, order_to_send, poll_seconds=2):
    end_ts = time.time() + poll_seconds
    while time.time() <= end_ts:
        try:
            orders = get_trade_detail_data(g.accID, 'STOCK', 'ORDER')
        except Exception as e:
            write_trade_log('查询新委托异�?, str(e))
            return ''

        for order_obj in orders or []:
            order_id = get_order_id_from_obj(order_obj)
            if not order_id or order_id in before_order_ids:
                continue

            if is_matching_submitted_order(order_obj, order_to_send):
                return order_id

        time.sleep(0.1)

    return ''


def get_order_field(order_obj, field_names, default=0):
    for field_name in field_names:
        try:
            value = getattr(order_obj, field_name)
            if value is not None:
                return value
        except:
            pass
    return default


def get_order_id_from_obj(order_obj):
    return str(get_order_field(
        order_obj,
        ['order_id', 'm_strOrderID', 'm_nOrderID', 'm_strOrderRef'],
        ''
    ) or '').strip()


def get_order_sysid_from_obj(order_obj):
    return str(get_order_field(
        order_obj,
        ['order_sysid', 'm_strOrderSysID', 'm_strOrderSysId', 'm_strEntrustNo', 'm_strContractNo'],
        ''
    ) or '').strip()


def get_order_market_from_obj(order_obj):
    stock_code = get_order_stock_code(order_obj)
    exchange_id = str(get_order_field(order_obj, ['m_strExchangeID', 'm_strMarket', 'exchange_id', 'market'], '') or '').upper()

    if stock_code.endswith('.SH') or exchange_id in ['SH', 'SSE', '上海', '上交所']:
        return getattr(globals().get('xtconstant', None), 'SH_MARKET', 0)
    if stock_code.endswith('.SZ') or exchange_id in ['SZ', 'SZSE', '深圳', '深交所']:
        return getattr(globals().get('xtconstant', None), 'SZ_MARKET', 1)
    return exchange_id or ''


def get_order_stock_code(order_obj):
    instrument_id = str(get_order_field(order_obj, ['stock_code', 'stock_code1', 'm_strInstrumentID', 'm_strStockCode'], '') or '').strip()
    exchange_id = str(get_order_field(order_obj, ['m_strExchangeID', 'm_strMarket', 'exchange_id'], '') or '').strip()

    if '.' in instrument_id:
        return instrument_id.upper()

    if instrument_id and exchange_id:
        return (instrument_id + '.' + exchange_id).upper()

    return instrument_id.upper()


def get_order_direct(order_obj):
    value = get_order_field(order_obj, [
        'offset_flag',
        'm_nOffsetFlag',
        'm_nEntrustDirection',
        'm_nTradeDirect',
        'order_type',
        'm_nOrderType',
        'm_nDirection',
        'm_nSide',
        'order_remark',
        'm_strEntrustDirection',
        'm_strTradeDirect',
        'm_strDirection',
        'm_strSide',
        'entrust_direction',
        'trade_direct',
        'direction',
        'side',
    ], None)
    text = str(value or '')

    if value in [23, '23', 48, '48'] or '�? in text or '五日内六�? in text:
        return 23

    if value in [24, '24', 49, '49'] or '�? in text or '弱卖' in text:
        return 24

    return None


def get_order_total_volume(order_obj):
    return round_lot(get_order_field(
        order_obj,
        ['order_volume', 'm_nVolumeTotalOriginal', 'm_nOrderVolume', 'm_nVolume', 'm_nEntrustAmount', 'm_nEntrustVolume'],
        0
    ))


def get_order_price(order_obj):
    try:
        return float(get_order_field(
            order_obj,
            ['price', 'order_price', 'm_dLimitPrice', 'm_dPrice', 'm_dEntrustPrice'],
            0
        ) or 0)
    except:
        return 0


def get_order_traded_volume_from_obj(order_obj):
    traded_volume = get_order_field(
        order_obj,
        ['traded_volume', 'm_nVolumeTraded', 'm_nTradedVolume', 'm_nDealVolume', 'm_nFilledVolume', 'm_n成交数量'],
        None
    )
    if traded_volume is None:
        return None
    return round_lot(traded_volume)


def is_unfinished_order(order_obj):
    status_value = get_order_field(
        order_obj,
        ['order_status', 'm_nOrderStatus', 'm_nStatus', 'm_strOrderStatus', 'm_strStatus'],
        ''
    )
    status_text = str(status_value)

    if status_value in [48, 49, 50, 55, '48', '49', '50', '55']:
        return True

    if status_value in [51, 52, 53, 54, 56, 57, '51', '52', '53', '54', '56', '57']:
        return False

    if '已报' in status_text or '部成' in status_text:
        return True

    if '已成' in status_text or '已撤' in status_text or '废单' in status_text:
        return False

    total_volume = get_order_total_volume(order_obj)
    traded_volume = get_order_traded_volume_from_obj(order_obj)
    if traded_volume is None:
        return False

    return total_volume > traded_volume


def infer_order_direct(order_obj, stock_code, log_title='未完成委托方向字段未识别'):
    trade_direct = get_order_direct(order_obj)
    if trade_direct in [23, 24]:
        return trade_direct

    write_trade_log(log_title, {
        'stock_code': stock_code,
        'order_debug': obj_to_debug_dict(order_obj),
    })
    return None


def build_retry_order(order_obj, remaining_volume):
    stock_code = get_order_stock_code(order_obj)
    trade_direct = infer_order_direct(order_obj, stock_code)
    remark = get_order_field(order_obj, ['m_strRemark', 'm_strStrategyName', 'remark'], '未完成委托补�?)

    if trade_direct not in [23, 24] or not stock_code or remaining_volume <= 0:
        write_trade_log('未完成委托字段不足，无法补单', {
            'trade_direct': trade_direct,
            'stock_code': stock_code,
            'remaining_volume': remaining_volume,
            'order': obj_to_dict(order_obj),
        })
        return None

    return {
        'trade_direct': trade_direct,
        'trade_type': 1101,
        'price_type': 11,
        'price': get_order_price(order_obj),
        'stock_code': stock_code,
        'remark': remark,
        'trade_amount': remaining_volume,
        'trade_amount_unit': 'volume',
        'retry_unfinished_order': True,
    }


def get_order_traded_volume(order_id):
    if not order_id:
        return None

    try:
        order_obj = get_value_by_order_id(order_id, g.accID, 'STOCK', 'ORDER')
        if order_obj is None:
            write_trade_log('未查询到委托对象', {'order_id': order_id})
            return None

        traded_volume = get_order_field(
            order_obj,
            ['traded_volume', 'm_nVolumeTraded', 'm_nTradedVolume', 'm_nDealVolume', 'm_nFilledVolume', 'm_n成交数量'],
            None
        )
        if traded_volume is None:
            write_trade_log('委托成交量字段未识别，停止后续追�?, {
                'order_id': order_id,
                'order': obj_to_dict(order_obj),
            })
            return None

        return round_lot(traded_volume)
    except Exception as e:
        write_trade_log('查询委托成交量异�?, {'order_id': order_id, 'error': str(e)})
        return None


def cancel_order_if_possible(C, order_id, order_obj=None):
    order_sysid = get_order_sysid_from_obj(order_obj) if order_obj is not None else ''
    market = get_order_market_from_obj(order_obj) if order_obj is not None else ''
    if not order_id and not order_sysid:
        write_trade_log('撤单跳过：委托号为空', obj_to_debug_dict(order_obj) if order_obj is not None else None)
        return

    if order_obj is not None:
        write_trade_log('撤单委托关键字段', {
            'order_id': order_id,
            'order_sysid': order_sysid,
            'market': market,
            'stock_code': get_order_stock_code(order_obj),
            'order_debug': obj_to_debug_dict(order_obj),
        })

    if order_sysid and callable(globals().get('cancel_order_stock_sysid')):
        try:
            cancel_result = cancel_order_stock_sysid(g.accID, market, order_sysid)
            write_trade_log('柜台合同编号撤单已提�?, {
                'order_id': order_id,
                'order_sysid': order_sysid,
                'market': market,
                'result': cancel_result,
                'api': 'cancel_order_stock_sysid',
            })
            return
        except Exception as e:
            write_trade_log('柜台合同编号撤单异常，尝试后续撤单方�?, {
                'order_id': order_id,
                'order_sysid': order_sysid,
                'market': market,
                'error': str(e),
            })

    if order_id and callable(globals().get('cancel_order_stock')):
        try:
            cancel_result = cancel_order_stock(g.accID, order_id)
            write_trade_log('订单编号撤单已提�?, {
                'order_id': order_id,
                'order_sysid': order_sysid,
                'result': cancel_result,
                'api': 'cancel_order_stock',
            })
            return
        except Exception as e:
            write_trade_log('订单编号撤单异常，尝试内置cancel', {
                'order_id': order_id,
                'order_sysid': order_sysid,
                'error': str(e),
            })

    try:
        cancel_ref = order_id or order_sysid
        cancel_result = cancel(cancel_ref, g.accID, 'STOCK', C)
        write_trade_log('撤单已提�?, {
            'order_id': order_id,
            'order_sysid': order_sysid,
            'market': market,
            'result': cancel_result,
            'api': '内置cancel',
        })
    except Exception as e:
        print('撤单异常', order_id or order_sysid, e, flush=True)
        write_trade_log('撤单异常', {
            'order_id': order_id,
            'order_sysid': order_sysid,
            'market': market,
            'error': str(e),
        })


def get_position_market_value(stock_code):
    try:
        positions = get_trade_detail_data(g.accID, 'STOCK', 'POSITION')
    except Exception as e:
        write_trade_log('query position failed before retry guard', {
            'stock_code': stock_code,
            'error': str(e),
        })
        return 0

    stock_code = str(stock_code or '').upper()
    for position in positions:
        code = getattr(position, 'm_strInstrumentID', '') + '.' + getattr(position, 'm_strExchangeID', '')
        if code.upper() == stock_code:
            try:
                return float(getattr(position, 'm_dInstrumentValue', 0) or 0)
            except:
                return 0

    return 0


def is_buy_position_target_reached(stock_code):
    total_asset = get_total_asset()
    target_ratio = float(g.params.get('\u5355\u6b21\u4e70\u5165\u4ed3\u4f4d\u6bd4\u4f8b', 0.02) or 0.02)
    target_value = total_asset * target_ratio if total_asset > 0 else 0
    current_value = get_position_market_value(stock_code)
    reached = target_value > 0 and current_value >= target_value
    return reached, {
        'stock_code': stock_code,
        'total_asset': total_asset,
        'target_ratio': target_ratio,
        'target_value': target_value,
        'current_value': current_value,
    }


def cancel_same_stock_unfinished_buy_orders(C, orders, stock_code):
    cancelled_order_ids = []
    stock_code = str(stock_code or '').upper()

    for order_obj in orders:
        order_stock_code = get_order_stock_code(order_obj)
        if str(order_stock_code or '').upper() != stock_code:
            continue
        if not is_unfinished_order(order_obj):
            continue
        if get_order_direct(order_obj) != 23:
            continue

        order_id = get_order_id_from_obj(order_obj)
        cancel_order_if_possible(C, order_id, order_obj)
        if order_id:
            g.retried_order_ids.add(order_id)
            cancelled_order_ids.append(order_id)

    return cancelled_order_ids

def check_unfinished_orders(C):
    if not g.params.get('检查未完成委托', True):
        return

    try:
        orders = get_trade_detail_data(g.accID, 'STOCK', 'ORDER')
    except Exception as e:
        write_trade_log('检查未完成委托异常：查询ORDER失败', str(e))
        return

    if not orders:
        return

    wait_reorder_ticks = g.params.get('重新下单等待tick�?, 2)
    checked_count = 0
    retry_count = 0

    for order_obj in orders:
        if not is_unfinished_order(order_obj):
            continue

        checked_count += 1
        order_id = get_order_id_from_obj(order_obj)
        stock_code = get_order_stock_code(order_obj)

        if order_id and order_id in g.retried_order_ids:
            continue

        total_volume = get_order_total_volume(order_obj)
        traded_volume = get_order_traded_volume_from_obj(order_obj)
        trade_direct = infer_order_direct(order_obj, stock_code)

        if traded_volume is None:
            write_trade_log('未完成委托成交量字段未识别，跳过补单', {
                'order_id': order_id,
                'order': obj_to_dict(order_obj),
            })
            continue

        if trade_direct == 23 and traded_volume > 0 and order_id and order_id not in g.cost_recorded_order_ids:
            order_price = get_order_price(order_obj)
            update_position_cost_on_buy(stock_code, order_price, traded_volume)
            g.cost_recorded_order_ids.add(order_id)
            write_trade_log('从未完成买入委托回填自维护成�?, {
                'order_id': order_id,
                'stock_code': stock_code,
                'price': order_price,
                'traded_volume': traded_volume,
            })

        remaining_volume = round_lot(total_volume - traded_volume)
        if remaining_volume <= 0:
            continue

        if trade_direct == 23:
            target_reached, target_info = is_buy_position_target_reached(stock_code)
            if target_reached:
                cancelled_order_ids = cancel_same_stock_unfinished_buy_orders(C, orders, stock_code)
                write_trade_log('buy target reached before retry; cancelled same-stock buy orders', {
                    'target_info': target_info,
                    'current_order_id': order_id,
                    'cancelled_order_ids': cancelled_order_ids,
                })
                continue
        write_trade_log('发现未完成委托，准备撤单后补�?, {
            'order_id': order_id,
            'stock_code': stock_code,
            'total_volume': total_volume,
            'traded_volume': traded_volume,
            'remaining_volume': remaining_volume,
            'order': obj_to_dict(order_obj),
        })

        cancel_order_if_possible(C, order_id, order_obj)
        if order_id:
            g.retried_order_ids.add(order_id)

        if stock_code:
            wait_market_ticks(C, stock_code, wait_reorder_ticks)

        retry_order = build_retry_order(order_obj, remaining_volume)
        if retry_order is None:
            continue

        retry_count += 1
        write_trade_log('未完成委托补单开�?, retry_order)
        do_order(C, retry_order)

    if checked_count > 0:
        write_trade_log('未完成委托检查完�?, {
            'checked_count': checked_count,
            'retry_count': retry_count,
        })


def submit_limit_order(C, order, price, volume, log_title):
    order_to_send = order.copy()
    order_to_send['trade_type'] = 1101
    order_to_send['price_type'] = 11
    order_to_send['price'] = price
    order_to_send['trade_amount'] = volume
    order_to_send['trade_amount_unit'] = 'volume'

    print(log_title, order_to_send, flush=True)
    write_trade_log(log_title, order_to_send)

    try:
        before_order_ids = get_current_order_id_set()
        passorder(
            order_to_send['trade_direct'],
            order_to_send['trade_type'],
            g.accID,
            order_to_send['stock_code'],
            order_to_send['price_type'],
            order_to_send['price'],
            order_to_send['trade_amount'],
            g.params['策略名称'],
            2,
            order_to_send['remark'],
            C
        )
        order_id = fetch_submitted_order_id(before_order_ids, order_to_send)
        if not order_id:
            order_id = fetch_last_order_id(g.params['策略名称'])
            write_trade_log('未匹配到新增委托，使用最新委托号兜底', {
                'order': order_to_send,
                'fallback_order_id': order_id,
            })
        write_trade_log('限价单已提交', {'order': order_to_send, 'order_id': order_id})
        return order_id
    except Exception as e:
        print('限价单下单异�?, e, flush=True)
        write_trade_log('限价单下单异�?, {'order': order_to_send, 'error': str(e)})
        return ''


def make_process_result(process_status, process_reason='', order_id='', traded_volume=0, remaining_volume=0):
    traded_volume = round_lot(traded_volume)
    remaining_volume = round_lot(remaining_volume)
    if process_status == 'submitted' and traded_volume > 0:
        process_status = 'filled' if remaining_volume <= 0 else 'partial_filled'

    return {
        'process_status': process_status,
        'process_reason': process_reason,
        'order_id': str(order_id or ''),
        'traded_volume': traded_volume,
        'remaining_volume': remaining_volume,
    }


def add_process_result_to_signal(signal_info, process_result):
    result = dict(signal_info)
    process_result = process_result or make_process_result('failed', '未返回处理状�?)
    result['process_status'] = process_result.get('process_status', '')
    result['process_reason'] = process_result.get('process_reason', '')
    result['order_id'] = process_result.get('order_id', '')
    result['traded_volume'] = process_result.get('traded_volume', 0)
    result['remaining_volume'] = process_result.get('remaining_volume', 0)
    result['processed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return result

def do_order(C, order):
    print('do_order', order, flush=True)
    write_trade_log('准备盘口追单', order)

    if order['trade_amount'] <= 0:
        if order.get('skip_reason'):
            skip_reason = str(order.get('skip_reason'))
            write_trade_log('下单跳过�? + skip_reason, order)
        else:
            skip_reason = '交易数量或金额为0'
            write_trade_log('下单跳过：交易数量或金额�?', order)
        return make_process_result('skipped', skip_reason)

    wait_cancel_ticks = g.params.get('撤单等待tick�?, 1)
    wait_reorder_ticks = g.params.get('重新下单等待tick�?, 2)
    max_rounds = g.params.get('盘口最大轮�?, 10)
    max_slippage_ratio = float(g.params.get('最大滑点比�?, 0.03))

    if order['trade_direct'] == 23:
        if order.get('retry_unfinished_order'):
            remaining_volume = round_lot(order['trade_amount'])
            total_traded_volume = 0
            last_order_id = ''
            slippage_blocked = False

            for i in range(max_rounds):
                if remaining_volume <= 0:
                    break

                best_price, best_volume, side_name = get_best_opposite_quote(C, order['stock_code'], order['trade_direct'])

                if best_price <= 0 or best_volume <= 0:
                    print('买入补单盘口为空，等待重新下单tick', order['stock_code'], flush=True)
                    write_trade_log('买入补单盘口为空，等待重新下单tick', {
                        'round': i + 1,
                        'stock_code': order['stock_code'],
                        'side': side_name,
                        'remaining_volume': remaining_volume,
                    })
                    wait_market_ticks(C, order['stock_code'], wait_reorder_ticks)
                    continue

                slippage_exceeded, slippage_ratio = is_slippage_exceeded(order.get('price', 0), best_price, max_slippage_ratio)
                if slippage_exceeded:
                    print('买入补单盘口价超过最大滑点，等待重新下单tick', order['stock_code'], order.get('price', 0), best_price, flush=True)
                    write_trade_log('买入补单盘口价超过最大滑点，等待重新下单tick', {
                        'round': i + 1,
                        'stock_code': order['stock_code'],
                        'signal_price': order.get('price', 0),
                        'quote_price': best_price,
                        'slippage_ratio': slippage_ratio,
                        'max_slippage_ratio': max_slippage_ratio,
                    })
                    slippage_blocked = True
                    wait_market_ticks(C, order['stock_code'], wait_reorder_ticks)
                    continue

                submit_volume = min(remaining_volume, round_lot(best_volume))
                submit_volume = round_lot(submit_volume)

                if submit_volume <= 0:
                    print('卖一数量不足一手，停止买入补单', order['stock_code'], best_volume, flush=True)
                    write_trade_log('卖一数量不足一手，停止买入补单', {
                        'stock_code': order['stock_code'],
                        'best_volume': best_volume,
                        'remaining_volume': remaining_volume,
                    })
                    break

                write_trade_log('买入未完成委托补单吃卖一', {
                    'round': i + 1,
                    'stock_code': order['stock_code'],
                    'price': best_price,
                    'opposite_volume': best_volume,
                    'submit_volume': submit_volume,
                    'remaining_volume_before': remaining_volume,
                })
                order_id = submit_limit_order(C, order, best_price, submit_volume, '买入未完成委托补单吃卖一')
                if order_id:
                    last_order_id = order_id
                if not order_id:
                    write_trade_log('未获取到委托号，停止后续买入补单，避免重复下�?)
                    break

                wait_market_ticks(C, order['stock_code'], wait_cancel_ticks)

                traded_volume = get_order_traded_volume(order_id)
                cancel_order_if_possible(C, order_id)

                if traded_volume is None:
                    write_trade_log('买入补单已成交数量未知，停止后续追单，避免重复下�?, {'order_id': order_id})
                    break

                update_position_cost_on_buy(order['stock_code'], best_price, traded_volume)
                total_traded_volume += traded_volume
                remaining_volume = remaining_volume - traded_volume
                write_trade_log('买入未完成委托补单本轮结�?, {
                    'round': i + 1,
                    'order_id': order_id,
                    'submit_volume': submit_volume,
                    'traded_volume': traded_volume,
                    'remaining_volume': remaining_volume,
                })

                if remaining_volume <= 0:
                    break

                wait_market_ticks(C, order['stock_code'], wait_reorder_ticks)

            if last_order_id:
                return make_process_result('submitted', '未完成买入委托补单结�?, last_order_id, total_traded_volume, remaining_volume)
            if slippage_blocked:
                return make_process_result('skipped', '买入补单盘口价超过最大滑�?, '', total_traded_volume, remaining_volume)
            return make_process_result('failed', '未完成买入委托补单未提交委托', '', total_traded_volume, remaining_volume)

        remaining_amount = float(order['trade_amount'])
        total_traded_volume = 0
        last_price = 0
        last_order_id = ''
        slippage_blocked = False

        for i in range(max_rounds):
            best_price, best_volume, side_name = get_best_opposite_quote(C, order['stock_code'], order['trade_direct'])
            if best_price > 0:
                last_price = best_price

            if best_price <= 0 or best_volume <= 0:
                print('买入盘口为空，等待重新下单tick', order['stock_code'], flush=True)
                write_trade_log('买入盘口为空，等待重新下单tick', {
                    'round': i + 1,
                    'stock_code': order['stock_code'],
                    'side': side_name,
                    'remaining_amount': remaining_amount,
                })
                wait_market_ticks(C, order['stock_code'], wait_reorder_ticks)
                continue

            slippage_exceeded, slippage_ratio = is_slippage_exceeded(order.get('price', 0), best_price, max_slippage_ratio)
            if slippage_exceeded:
                print('买入盘口价超过最大滑点，等待重新下单tick', order['stock_code'], order.get('price', 0), best_price, flush=True)
                write_trade_log('买入盘口价超过最大滑点，等待重新下单tick', {
                    'round': i + 1,
                    'stock_code': order['stock_code'],
                    'signal_price': order.get('price', 0),
                    'quote_price': best_price,
                    'slippage_ratio': slippage_ratio,
                    'max_slippage_ratio': max_slippage_ratio,
                })
                slippage_blocked = True
                wait_market_ticks(C, order['stock_code'], wait_reorder_ticks)
                continue

            target_volume = round_lot(remaining_amount / best_price)
            submit_volume = min(target_volume, round_lot(best_volume))
            submit_volume = round_lot(submit_volume)

            if submit_volume <= 0:
                print('可提交买入数量不足一手，停止', order['stock_code'], remaining_amount, best_price, best_volume, flush=True)
                write_trade_log('可提交买入数量不足一手，停止', {
                    'stock_code': order['stock_code'],
                    'remaining_amount': remaining_amount,
                    'best_price': best_price,
                    'best_volume': best_volume,
                })
                break

            write_trade_log('买入吃卖一限价�?, {
                'round': i + 1,
                'stock_code': order['stock_code'],
                'price': best_price,
                'opposite_volume': best_volume,
                'submit_volume': submit_volume,
                'remaining_amount_before': remaining_amount,
            })
            order_id = submit_limit_order(C, order, best_price, submit_volume, '买入吃卖一限价�?)
            if order_id:
                last_order_id = order_id
            if not order_id:
                write_trade_log('未获取到委托号，停止后续买入追单，避免重复下�?)
                break

            wait_market_ticks(C, order['stock_code'], wait_cancel_ticks)

            traded_volume = get_order_traded_volume(order_id)
            cancel_order_if_possible(C, order_id)

            if traded_volume is None:
                write_trade_log('买入已成交数量未知，停止后续追单，避免重复下�?, {'order_id': order_id})
                break

            update_position_cost_on_buy(order['stock_code'], best_price, traded_volume)
            total_traded_volume += traded_volume
            remaining_amount = remaining_amount - traded_volume * best_price
            write_trade_log('买入本轮追单结果', {
                'round': i + 1,
                'order_id': order_id,
                'submit_volume': submit_volume,
                'traded_volume': traded_volume,
                'remaining_amount': remaining_amount,
            })

            if remaining_amount < best_price * 100:
                break

            wait_market_ticks(C, order['stock_code'], wait_reorder_ticks)

        remaining_volume = round_lot(remaining_amount / last_price) if last_price > 0 else 0
        if last_order_id:
            return make_process_result('submitted', '买入盘口追单结束', last_order_id, total_traded_volume, remaining_volume)
        if slippage_blocked:
            return make_process_result('skipped', '买入盘口价超过最大滑�?, '', total_traded_volume, remaining_volume)
        return make_process_result('failed', '买入盘口追单未提交委�?, '', total_traded_volume, remaining_volume)

    if order['trade_direct'] == 24:
        remaining_volume = round_lot(order['trade_amount'])
        total_traded_volume = 0
        last_order_id = ''
        slippage_blocked = False

        for i in range(max_rounds):
            if remaining_volume <= 0:
                break

            best_price, best_volume, side_name = get_best_opposite_quote(C, order['stock_code'], order['trade_direct'])

            if best_price <= 0 or best_volume <= 0:
                print('卖出盘口为空，等待重新下单tick', order['stock_code'], flush=True)
                write_trade_log('卖出盘口为空，等待重新下单tick', {
                    'round': i + 1,
                    'stock_code': order['stock_code'],
                    'side': side_name,
                    'remaining_volume': remaining_volume,
                })
                wait_market_ticks(C, order['stock_code'], wait_reorder_ticks)
                continue

            slippage_exceeded, slippage_ratio = is_slippage_exceeded(order.get('price', 0), best_price, max_slippage_ratio)
            if slippage_exceeded:
                print('卖出盘口价超过最大滑点，等待重新下单tick', order['stock_code'], order.get('price', 0), best_price, flush=True)
                write_trade_log('卖出盘口价超过最大滑点，等待重新下单tick', {
                    'round': i + 1,
                    'stock_code': order['stock_code'],
                    'signal_price': order.get('price', 0),
                    'quote_price': best_price,
                    'slippage_ratio': slippage_ratio,
                    'max_slippage_ratio': max_slippage_ratio,
                })
                slippage_blocked = True
                wait_market_ticks(C, order['stock_code'], wait_reorder_ticks)
                continue

            submit_volume = min(remaining_volume, round_lot(best_volume))
            submit_volume = round_lot(submit_volume)

            if submit_volume <= 0:
                print('买一数量不足一手，停止卖出', order['stock_code'], best_volume, flush=True)
                write_trade_log('买一数量不足一手，停止卖出', {
                    'stock_code': order['stock_code'],
                    'best_volume': best_volume,
                    'remaining_volume': remaining_volume,
                })
                break

            write_trade_log('卖出吃买一限价�?, {
                'round': i + 1,
                'stock_code': order['stock_code'],
                'price': best_price,
                'opposite_volume': best_volume,
                'submit_volume': submit_volume,
                'remaining_volume_before': remaining_volume,
            })
            order_id = submit_limit_order(C, order, best_price, submit_volume, '卖出吃买一限价�?)
            if order_id:
                last_order_id = order_id
            if not order_id:
                write_trade_log('未获取到委托号，停止后续卖出追单，避免重复下�?)
                break

            wait_market_ticks(C, order['stock_code'], wait_cancel_ticks)

            traded_volume = get_order_traded_volume(order_id)
            cancel_order_if_possible(C, order_id)

            if traded_volume is None:
                write_trade_log('卖出已成交数量未知，停止后续追单，避免重复下�?, {'order_id': order_id})
                break

            remaining_volume = remaining_volume - traded_volume
            total_traded_volume += traded_volume
            write_trade_log('卖出本轮追单结果', {
                'round': i + 1,
                'order_id': order_id,
                'submit_volume': submit_volume,
                'traded_volume': traded_volume,
                'remaining_volume': remaining_volume,
            })

            if remaining_volume <= 0:
                break

            wait_market_ticks(C, order['stock_code'], wait_reorder_ticks)

        if order.get('sell_stage') == 'half_150' and total_traded_volume > 0:
            mark_half_sell_done(order['stock_code'])

        if last_order_id:
            return make_process_result('submitted', '卖出盘口追单结束', last_order_id, total_traded_volume, remaining_volume)
        if slippage_blocked:
            return make_process_result('skipped', '卖出盘口价超过最大滑�?, '', total_traded_volume, remaining_volume)
        return make_process_result('failed', '卖出盘口追单未提交委�?, '', total_traded_volume, remaining_volume)

    return make_process_result('failed', '未知交易方向')


def get_position_field(obj, field_names, default=0):
    for field_name in field_names:
        try:
            value = getattr(obj, field_name)
            if value is not None:
                return value
        except:
            pass
    return default


def to_float_value(value, default=0):
    try:
        if value is None or value == '':
            return default
        return float(value)
    except:
        return default


def to_int_value(value, default=0):
    try:
        if value is None or value == '':
            return default
        return int(float(value))
    except:
        return default


def get_position_code(position):
    stock_code = str(get_position_field(position, ['stock_code', 'm_strInstrumentID', 'm_strStockCode'], '') or '').strip()
    exchange_id = str(get_position_field(position, ['m_strExchangeID', 'm_strMarket', 'exchange_id', 'market'], '') or '').strip()
    if '.' in stock_code:
        return stock_code.upper()
    if stock_code and exchange_id:
        return (stock_code + '.' + exchange_id).upper()
    return stock_code.upper()


def get_official_position_cost_price(position):
    return to_float_value(get_position_field(
        position,
        [
            'avg_price', 'open_price', 'costPrice', 'cost_price',
            'm_dOpenPrice', 'm_dCostPrice', 'm_dPositionCostPrice'
        ],
        0
    ))


def get_official_position_snapshot(position):
    volume = to_int_value(get_position_field(position, ['volume', 'totalAmt', 'm_nVolume'], 0))
    can_use_volume = to_int_value(get_position_field(position, ['can_use_volume', 'enableAmount', 'm_nCanUseVolume'], 0))
    cost_price = get_official_position_cost_price(position)
    market_value = to_float_value(get_position_field(position, ['market_value', 'marketValue', 'm_dInstrumentValue'], 0))
    cost_balance = to_float_value(get_position_field(position, [
        'costBalance', 'cost_balance', 'position_cost', 'positionCost',
        'm_dPositionCost', 'm_dCostBalance', 'm_dOpenCost'
    ], 0))
    if cost_balance <= 0 and cost_price > 0 and volume > 0:
        cost_balance = cost_price * volume

    return {
        'stock_code': get_position_code(position),
        'volume': volume,
        'can_use_volume': can_use_volume,
        'cost_price': cost_price,
        'market_value': market_value,
        'cost_balance': cost_balance,
        'last_price': to_float_value(get_position_field(position, ['last_price', 'm_dLastPrice'], 0)),
        'profit': to_float_value(get_position_field(position, ['position_profit', 'profit', 'm_dPositionProfit'], 0)),
    }


def get_trade_direct_from_obj(obj):
    value = get_position_field(obj, [
        'offset_flag', 'm_nOffsetFlag', 'm_nEntrustDirection', 'm_nTradeDirect',
        'm_nOrderType', 'm_nDirection', 'm_nSide', 'entrust_direction', 'trade_direct',
        'direction', 'side', 'm_strEntrustDirection', 'm_strTradeDirect', 'm_strDirection', 'm_strSide'
    ], None)
    text = str(value or '')
    if value in [23, 48, '23', '48'] or '�? in text:
        return 23
    if value in [24, 49, '24', '49'] or '�? in text:
        return 24
    return None


def get_deal_price(obj):
    return to_float_value(get_position_field(obj, [
        'price', 'trade_price', 'deal_price', 'm_dPrice', 'm_dTradePrice', 'm_dDealPrice', 'm_dBusinessPrice'
    ], 0))


def get_deal_volume(obj):
    return to_int_value(get_position_field(obj, [
        'volume', 'trade_volume', 'deal_volume', 'm_nVolume', 'm_nTradeVolume', 'm_nDealVolume', 'm_nBusinessAmount'
    ], 0))


def get_deal_amount(obj):
    amount = to_float_value(get_position_field(obj, [
        'amount', 'trade_amount', 'deal_amount', 'm_dTradeAmount', 'm_dDealAmount', 'm_dBusinessBalance', 'm_dTurnover'
    ], 0))
    if amount <= 0:
        price = get_deal_price(obj)
        volume = get_deal_volume(obj)
        amount = price * volume if price > 0 and volume > 0 else 0
    return amount


def flatten_history_trade_detail(history_data):
    rows = []
    for item in history_data or []:
        try:
            timetag, data_list = item
        except:
            timetag, data_list = '', item
        for obj in data_list or []:
            rows.append((timetag, obj))
    return rows


def query_current_deals_for_cost():
    for account_type in ['STOCK', 'stock']:
        for data_type in ['DEAL', 'deal']:
            try:
                deals = get_trade_detail_data(g.accID, account_type, data_type)
                write_trade_log('当前成交兜底查询结果', {
                    'account_type': account_type,
                    'data_type': data_type,
                    'deal_count': len(deals or []),
                    'first_deal': obj_to_debug_dict(deals[0]) if deals else None,
                })
                if deals:
                    return [('current', deal) for deal in deals]
            except Exception as e:
                write_trade_log('当前成交兜底查询异常', {
                    'account_type': account_type,
                    'data_type': data_type,
                    'error': str(e),
                })
    return []


def query_history_deals(start_date, end_date):
    history_func = globals().get('get_history_trade_detail_data')
    if not callable(history_func):
        write_trade_log('历史成交流水接口不可用，改用当前成交兜底', {
            'function': 'get_history_trade_detail_data',
            'available': False,
            'start_date': start_date,
            'end_date': end_date,
        })
        return query_current_deals_for_cost()

    for account_type in ['STOCK', 'stock']:
        for data_type in ['DEAL', 'deal']:
            try:
                rows = flatten_history_trade_detail(
                    history_func(g.accID, account_type, data_type, start_date, end_date)
                )
                write_trade_log('查询历史成交流水结果', {
                    'account_type': account_type,
                    'data_type': data_type,
                    'start_date': start_date,
                    'end_date': end_date,
                    'deal_count': len(rows),
                    'first_deal': obj_to_debug_dict(rows[0][1]) if rows else None,
                })
                if rows:
                    return rows
            except Exception as e:
                write_trade_log('查询历史成交流水异常', {
                    'account_type': account_type,
                    'data_type': data_type,
                    'start_date': start_date,
                    'end_date': end_date,
                    'error': str(e),
                })

    if start_date == datetime.now().strftime('%Y%m%d') and end_date == datetime.now().strftime('%Y%m%d'):
        return query_current_deals_for_cost()

    return []


def build_history_deal_cost_map(start_date, end_date):
    result = {}
    for timetag, deal in query_history_deals(start_date, end_date):
        stock_code = get_position_code(deal)
        if not stock_code:
            continue

        trade_direct = get_trade_direct_from_obj(deal)
        volume = get_deal_volume(deal)
        amount = get_deal_amount(deal)
        price = get_deal_price(deal)
        if volume <= 0 or amount <= 0:
            continue

        item = result.setdefault(stock_code, {
            'stock_code': stock_code,
            'buy_volume': 0,
            'buy_amount': 0.0,
            'sell_volume': 0,
            'sell_amount': 0.0,
            'deal_count': 0,
            'first_timetag': timetag,
            'last_timetag': timetag,
        })
        item['deal_count'] += 1
        item['last_timetag'] = timetag

        if trade_direct == 23:
            item['buy_volume'] += volume
            item['buy_amount'] += amount
        elif trade_direct == 24:
            item['sell_volume'] += volume
            item['sell_amount'] += amount

    for item in result.values():
        item['buy_cost_price'] = item['buy_amount'] / item['buy_volume'] if item['buy_volume'] > 0 else 0
        item['net_volume'] = item['buy_volume'] - item['sell_volume']
        item['net_amount'] = item['buy_amount'] - item['sell_amount']
        item['net_cost_price'] = item['net_amount'] / item['net_volume'] if item['net_volume'] > 0 else 0

    return result


def get_history_cost_start_date():
    return str(g.params.get('历史成交开始日�?, datetime.now().strftime('%Y%m%d')) or datetime.now().strftime('%Y%m%d'))

def get_history_position_cost_price(stock_code):
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = get_history_cost_start_date()
    deal_cost_map = build_history_deal_cost_map(start_date, end_date)
    item = deal_cost_map.get(str(stock_code or '').upper(), {})
    cost_price = to_float_value(item.get('net_cost_price', 0), 0)
    if cost_price <= 0:
        cost_price = to_float_value(item.get('buy_cost_price', 0), 0)
    return cost_price, item

def export_official_position_costs():
    file_path = r'C:\Users\Administrator\Desktop\历史成交流水_持仓成本.txt'
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = get_history_cost_start_date()
    deal_cost_map = build_history_deal_cost_map(start_date, end_date)

    try:
        positions = get_trade_detail_data(g.accID, 'STOCK', 'POSITION')
    except Exception as e:
        write_trade_log('导出历史成交流水成本失败：查询持仓异�?, str(e))
        positions = []

    position_map = {}
    for position in positions or []:
        item = get_official_position_snapshot(position)
        if item['stock_code']:
            position_map[item['stock_code']] = item

    all_codes = sorted(set(position_map.keys()) | set(deal_cost_map.keys()))

    try:
        with open(file_path, 'w', encoding='utf-8-sig') as f:
            f.write('更新时间\t统计开始\t统计结束\t股票代码\t当前持仓\t可用持仓\t官方成本价\t官方成本金额\t官方市值\t官方最新价\t官方持仓盈亏\t历史买入股数\t历史买入金额\t历史买入均价\t历史卖出股数\t历史卖出金额\t历史净股数\t历史净金额\t历史净均价\t成交笔数\t首笔时间\t末笔时间\n')
            now_text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for stock_code in all_codes:
                pos = position_map.get(stock_code, {})
                deal = deal_cost_map.get(stock_code, {})
                f.write(
                    now_text + '\t' +
                    start_date + '\t' +
                    end_date + '\t' +
                    stock_code + '\t' +
                    str(pos.get('volume', 0)) + '\t' +
                    str(pos.get('can_use_volume', 0)) + '\t' +
                    ('%.6f' % pos.get('cost_price', 0.0)) + '\t' +
                    ('%.2f' % pos.get('cost_balance', 0.0)) + '\t' +
                    ('%.2f' % pos.get('market_value', 0.0)) + '\t' +
                    ('%.6f' % pos.get('last_price', 0.0)) + '\t' +
                    ('%.2f' % pos.get('profit', 0.0)) + '\t' +
                    str(deal.get('buy_volume', 0)) + '\t' +
                    ('%.2f' % deal.get('buy_amount', 0.0)) + '\t' +
                    ('%.6f' % deal.get('buy_cost_price', 0.0)) + '\t' +
                    str(deal.get('sell_volume', 0)) + '\t' +
                    ('%.2f' % deal.get('sell_amount', 0.0)) + '\t' +
                    str(deal.get('net_volume', 0)) + '\t' +
                    ('%.2f' % deal.get('net_amount', 0.0)) + '\t' +
                    ('%.6f' % deal.get('net_cost_price', 0.0)) + '\t' +
                    str(deal.get('deal_count', 0)) + '\t' +
                    str(deal.get('first_timetag', '')) + '\t' +
                    str(deal.get('last_timetag', '')) + '\n'
                )
        write_trade_log('导出历史成交流水成本成功', {
            'file_path': file_path,
            'start_date': start_date,
            'end_date': end_date,
            'position_count': len(position_map),
            'deal_stock_count': len(deal_cost_map),
        })
    except Exception as e:
        write_trade_log('导出历史成交流水成本失败：写文件异常', {'file_path': file_path, 'error': str(e)})

def get_total_asset():
    try:
        print("我要获得资产情况", flush=True)
        assets = get_trade_detail_data(g.accID, 'STOCK', 'ACCOUNT')
        if not assets:
            print('未获取到账户资产，不买入', flush=True)
            write_trade_log('未获取到账户资产，不买入')
            return 0

        asset = assets[0]
        total_asset = getattr(asset, 'm_dBalance', 0)

        if total_asset <= 0:
            print('账户总资产字段为空，asset字段�?, asset.__dict__, flush=True)
            write_trade_log('账户总资产字段为�?, obj_to_dict(asset))
            return 0

        write_trade_log('获取账户总资产成�?, total_asset)
        return total_asset
    except Exception as e:
        print('获取账户总资产异�?, e, flush=True)
        write_trade_log('获取账户总资产异�?, str(e))
        return 0


def parse_change_percent(value):
    try:
        if pd.isna(value):
            return None

        text = str(value).strip().replace('%', '')
        if text == '':
            return None

        return float(text)
    except Exception as e:
        write_trade_log('涨跌幅解析异�?, {'value': value, 'error': str(e)})
        return None


def get_change_percent_limit(stock_code):
    code = str(stock_code or '').strip().upper()
    raw_code = code.split('.')[0]

    if raw_code.startswith('30') or raw_code.startswith('688'):
        return 19.5

    if raw_code.startswith('60') or raw_code.startswith('00'):
        return 9.5

    return None


def convert_order(order_info):
    order = {}
    order['trade_direct'] = 24 if order_info['is_sell'] else 23
    order['trade_type'] = 1102
    order['price_type'] = 11
    order['price'] = order_info['price']
    order['stock_code'] = add_market_suffix(order_info['stock_code'])
    order['remark'] = order_info['formula']

    change_percent = parse_change_percent(order_info.get('change_percent', None))
    change_percent_limit = get_change_percent_limit(order['stock_code'])
    if change_percent_limit is not None and change_percent is not None and abs(change_percent) > change_percent_limit:
        order['trade_amount'] = 0
        order['skip_reason'] = f'涨跌幅超过{change_percent_limit}%，不进行交易'
        order['skip_detail'] = {
            'change_percent': change_percent,
            'limit_percent': change_percent_limit,
        }
        print('涨跌幅超过限制，跳过交易', order['stock_code'], change_percent, change_percent_limit, flush=True)
        write_trade_log('涨跌幅超过限制，跳过交易', {
            'stock_code': order['stock_code'],
            'change_percent': change_percent,
            'limit_percent': change_percent_limit,
            'order_info': order_info,
        })
        return order

    # 买入：五日内六级出现时，将单只股票仓位补到总资�?%
    if order['trade_direct'] == 23:
        if int(order_info.get('is_buy', 0)) != 1:
            order['trade_type'] = 1102
            order['trade_amount'] = 0
            order['trade_amount_unit'] = 'amount'
            write_trade_log('非五日内六级买入信号，跳�?, order_info)
            return order

        total_asset = get_total_asset()
        target_ratio = g.params.get('单次买入仓位比例', 0.02)

        if total_asset <= 0:
            order['trade_amount'] = 0
            order['trade_amount_unit'] = 'amount'
            order['skip_reason'] = '获取总资产失败，不买�?
            return order
        target_value = total_asset * target_ratio
        current_value = 0
        positions = get_trade_detail_data(g.accID, 'STOCK', 'POSITION')


        for position in positions:
            code = position.m_strInstrumentID + '.' + position.m_strExchangeID
            if code == order['stock_code']:
                current_value = getattr(position, 'm_dInstrumentValue', 0)
                break

        buy_amount = target_value - current_value

        if buy_amount <= 0:
            order['trade_type'] = 1102
            order['trade_amount'] = 0
            order['trade_amount_unit'] = 'amount'
            print('当前股票仓位已达�?%，不买入', order['stock_code'], current_value, target_value, flush=True)
            write_trade_log('当前股票仓位已达�?%，不买入', {
                'stock_code': order['stock_code'],
                'current_value': current_value,
                'target_value': target_value,
                'total_asset': total_asset,
            })
            return order

        order['trade_type'] = 1102
        order['trade_amount'] = buy_amount
        order['trade_amount_unit'] = 'amount'
        print('五日内六级买入，补足到总资�?%', order['stock_code'], current_value, target_value, buy_amount, flush=True)
        write_trade_log('五日内六级买入，补足到总资�?%', {
            'stock_code': order['stock_code'],
            'total_asset': total_asset,
            'target_ratio': target_ratio,
            'target_value': target_value,
            'current_value': current_value,
            'trade_amount': buy_amount,
        })

    # 卖出：出现卖出信号后，按当前价相对持仓成本分档卖�?
    if order['trade_direct'] == 24:
        stock_code = order['stock_code']
        positions = get_trade_detail_data(g.accID, 'STOCK', 'POSITION')

        pos = None
        for position in positions:
            code = position.m_strInstrumentID + '.' + position.m_strExchangeID
            if code == stock_code:
                pos = position
                break

        if pos is None:
            trade_amount = 0
            print('卖出不在持仓�?, stock_code, flush=True)
            write_trade_log('卖出失败：不在持仓池', stock_code)
        else:
            can_use_volume = getattr(pos, 'm_nCanUseVolume', 0)

            history_cost_price, history_cost_info = get_history_position_cost_price(stock_code)
            official_cost_price = get_official_position_cost_price(pos)
            if history_cost_price > 0:
                cost_price = history_cost_price
                write_trade_log('使用历史成交流水成本进行卖出判断', {
                    'stock_code': stock_code,
                    'cost_price': cost_price,
                    'history_cost_info': history_cost_info,
                    'position_snapshot': get_official_position_snapshot(pos),
                })
            else:
                cost_price = official_cost_price
                write_trade_log('历史成交流水成本为空，使用官方持仓成本兜�?, {
                    'stock_code': stock_code,
                    'cost_price': cost_price,
                    'position_snapshot': get_official_position_snapshot(pos),
                })

            try:
                current_price = float(order_info['price'])
            except:
                current_price = 0

            if can_use_volume <= 0:
                trade_amount = 0
                print('卖出失败：持仓可用为0', stock_code, flush=True)
                write_trade_log('卖出失败：持仓可用为0', {
                    'stock_code': stock_code,
                    'position': obj_to_dict(pos),
                })
            elif cost_price <= 0:
                trade_amount = 0
                print('卖出失败：持仓成本为�?, stock_code, flush=True)
                write_trade_log('卖出失败：持仓成本为�?, {
                    'stock_code': stock_code,
                    'position': obj_to_dict(pos),
                })
            elif current_price <= 0:
                trade_amount = 0
                print('卖出失败：当前价格为�?, stock_code, flush=True)
                write_trade_log('卖出失败：当前价格为�?, {
                    'stock_code': stock_code,
                    'order_info': order_info,
                })
            elif current_price >= cost_price * 2:
                trade_amount = can_use_volume
                trade_amount = trade_amount // 100 * 100
                print('价格达到持仓成本200%，清�?, stock_code, cost_price, current_price, trade_amount, flush=True)
                write_trade_log('价格达到持仓成本200%，清�?, {
                    'stock_code': stock_code,
                    'cost_price': cost_price,
                    'current_price': current_price,
                    'can_use_volume': can_use_volume,
                    'trade_amount': trade_amount,
                })
            elif current_price >= cost_price * 1.5:
                if self_cost_info.get('half_sell_done'):
                    trade_amount = 0
                    print('150%卖出已执行，未达�?00%前不再卖�?, stock_code, cost_price, current_price, flush=True)
                    write_trade_log('150%卖出已执行，未达�?00%前不再卖�?, {
                        'stock_code': stock_code,
                        'cost_price': cost_price,
                        'current_price': current_price,
                        'can_use_volume': can_use_volume,
                        'cost_info': self_cost_info,
                    })
                else:
                    trade_amount = can_use_volume // 2
                    trade_amount = trade_amount // 100 * 100
                    order['sell_stage'] = 'half_150'
                    print('价格达到持仓成本150%，卖�?0%', stock_code, cost_price, current_price, trade_amount, flush=True)
                    write_trade_log('价格达到持仓成本150%，卖�?0%', {
                        'stock_code': stock_code,
                        'cost_price': cost_price,
                        'current_price': current_price,
                        'can_use_volume': can_use_volume,
                        'trade_amount': trade_amount,
                    })
            else:
                trade_amount = 0
                print('卖出信号出现，但价格未达�?50%成本，不卖出', stock_code, cost_price, current_price, flush=True)
                write_trade_log('卖出信号出现，但价格未达�?50%成本，不卖出', {
                    'stock_code': stock_code,
                    'cost_price': cost_price,
                    'current_price': current_price,
                    'can_use_volume': can_use_volume,
                })

        order['trade_type'] = 1101
        order['trade_amount'] = trade_amount
        order['trade_amount_unit'] = 'volume'

    return order


def get_price_type():
    types = {
        '预警�?: 11,
        '对手�?: 14,
        '市价�?: 44,
    }
    return types[g.params['价格类型']]


def load_tdx_signal(file_path):
    df = pd.DataFrame()
    try:
        if not os.path.exists(file_path):
            print('文件不存�?, file_path, flush=True)
        else:
            df = pd.read_csv(
                file_path,
                sep='\t',
                header=None,
                names=['stock_code', 'name', 'datetime', 'price', 'change_percent', 'volume', 'formula'],
                index_col=False,
                dtype={'stock_code': str},
                engine='python'
            )
            print('读取文件', file_path, len(df), flush=True)
    except Exception as e:
        print('读取文件异常', e, file_path, flush=True)
        write_trade_log('读取文件异常', {'file_path': file_path, 'error': str(e)})
        df = pd.DataFrame()

    return df


def get_response_columns():
    signal_columns = ['stock_code', 'name', 'datetime', 'price', 'change_percent', 'volume', 'formula']
    process_columns = ['process_status', 'process_reason', 'order_id', 'traded_volume', 'remaining_volume', 'processed_at']
    return signal_columns + process_columns


def normalize_response_columns(df):
    df = df.copy()
    df.drop(['is_sell', 'is_buy'], axis=1, inplace=True, errors='ignore')
    columns = get_response_columns()
    for column in columns:
        if column not in df.columns:
            df[column] = ''
    return df[columns]


def load_tdx_response(file_path):
    columns = get_response_columns()
    df = pd.DataFrame()
    try:
        if not os.path.exists(file_path):
            print('文件不存�?, file_path, flush=True)
        else:
            df = pd.read_csv(
                file_path,
                sep='\t',
                header=None,
                names=columns,
                index_col=False,
                dtype={'stock_code': str, 'order_id': str},
                engine='python'
            )
            print('读取response文件', file_path, len(df), flush=True)
    except Exception as e:
        print('读取response文件异常', e, file_path, flush=True)
        write_trade_log('读取response文件异常', {'file_path': file_path, 'error': str(e)})
        df = pd.DataFrame()

    return df


def save_tdx_signal_response(df, file_path):
    try:
        df = normalize_response_columns(df)
        df.to_csv(
            file_path,
            sep='\t',
            header=None,
            encoding='gbk',
            index=False
        )
        print(f'保存文件 {file_path} {len(df)}', flush=True)

        write_trade_log('保存response文件成功', {
            'file_path': file_path,
            'count': len(df),
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

        log_all_trade_records(force=True)
        log_current_positions()
        export_official_position_costs()

    except Exception as e:
        print(f'保存文件 {e} {file_path} {len(df)}', flush=True)
        write_trade_log('保存response文件异常', {
            'file_path': file_path,
            'count': len(df),
            'error': str(e),
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })


def add_market_suffix(stock_code):
    if stock_code[-2:] in ['SH', 'SZ', 'BJ', 'sh', 'sz', 'bj']:
        stock_code = stock_code.upper()
    elif stock_code[0:2] in ['SH', 'SZ', 'BJ']:
        stock_code = stock_code[2:] + "." + stock_code[0:2]
    else:
        if (
            stock_code[:3] in ['510', '511', '512', '513', '515', '516', '113', '110', '118', '501']
            or stock_code.startswith('60')
            or stock_code.startswith('68')
            or stock_code.startswith('11')
        ):
            stock_code = stock_code + '.SH'
        elif (
            stock_code[:3] in ['159']
            or stock_code.startswith('00')
            or stock_code.startswith('30')
            or stock_code.startswith('12')
        ):
            stock_code = stock_code + '.SZ'
        elif stock_code[:3] in ['920'] or stock_code[:2] in ['43', '82', '83', '87', '88']:
            stock_code = stock_code + '.BJ'
        else:
            raise Exception(f'unsupport {stock_code}')

    return stock_code
	
	
def log_current_positions():
    try:
        positions = get_trade_detail_data(g.accID, 'STOCK', 'POSITION')
        write_trade_log('当前持仓数量', len(positions))

        for i, p in enumerate(positions):
            position_info = {
                '序号': i + 1,
                '股票代码': getattr(p, 'm_strInstrumentID', '') + '.' + getattr(p, 'm_strExchangeID', ''),
                '总持�?: getattr(p, 'm_nVolume', None),
                '可用持仓': getattr(p, 'm_nCanUseVolume', None),
                '成本�?: getattr(p, 'm_dOpenPrice', None),
                '最新价': getattr(p, 'm_dLastPrice', None),
                '市�?: getattr(p, 'm_dInstrumentValue', None),
                '浮动盈亏': getattr(p, 'm_dPositionProfit', None),
            }
            write_trade_log('当前持仓明细', position_info)

    except Exception as e:
        write_trade_log('当前持仓查询异常', str(e))

