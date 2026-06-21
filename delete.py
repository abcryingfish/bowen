#encoding:gbk
import pandas as pd
import numpy as np
import talib
import time
from datetime import datetime
import math
import os
import json
import logging

# 全局参数
class a():pass
g=a()
g.params = {
    '策略名称': '通达信预警交易策略',
    '开始时间': '09:30:00', # 盘中开始监控时间
    '结束时间': '15:05:00', # 盘中结束监控时间
    '最大买入标的数': 1000,    # 当日最大买入预警的股票数
    '买入类型': '金额',    # 金额/数量
    '买入金额': 10000, # 每笔买入金额
    '买入数量': 100, # 每笔买入数量
    '价格类型': '对手价', # 对手价: 以QMT的最新对手价为准; 预警价: 以通达信预警信号的价格为准; 市价单: 对手最优价 
    '预警文件': r'C:\Users\Administrator\Desktop\python_venv\buy.txt',  # 预警信号文件
    '防重规则': '按股票代码',   # 按股票代码：按代码和买卖方向; 按代码/时间/条件: 按代码+时间+公式条件
    '公式配置': r'C:\new_tdx_ok\T0002\signals\预警公式配置.xlsx',  # 已废弃，不再使用
}

# 生成xml文件，方便后续读取
def create_xml_if_not_exists(xml_name):
    xml_content = '''<?xml version="1.0" encoding="utf-8"?>
                <TCStageLayout>
                    <control note="控件">
                        <variable note="控件">
                            <item position="" bind="start_time" value="09:30:00" note="开始时间" name="开始时间" type="intput"/>
                            <item position="" bind="end_time" value="14:57:00" note="结束时间" name="结束时间" type="intput"/>
                            <item position="" bind="max_buy_count" value="10" note="最大买入标的数" name="最大买入标的数" type="intput"/>
                            <item position="" bind="order_type_combo" value="金额" note="买入类型" name="买入类型" type="combo" comboType="custom" list="金额,数量" />
                            <item position="" bind="order_type_value" value="1000" note="买入金额" name="买入金额" type="intput"/>
                            <item position="" bind="order_type_volume" value="100" note="买入数量" name="买入数量" type="intput"/>
                            <item position="" bind="price_type_combo" value="预警价" note="价格类型" name="价格类型" type="combo" comboType="custom" list="预警价,对手价,市价单" />
                            <item position="" bind="request_file" value="C:/new_tdx_ok/T0002/signals/signal_buy.txt" note="预警文件" name="预警文件" type="intput"/>
                            <item position="" bind="avoid_repeat_type" value="按股票代码" note="防重规则" name="防重规则" type="combo" comboType="custom" list="按股票代码,按代码/时间/条件" />
                            <item position="" bind="formula_param" value="C:/new_tdx_ok/T0002/signals/预警公式配置.xlsx" note="公式配置" name="公式配置" type="intput"/>
                      </variable>
                    </control>
                </TCStageLayout>'''

    current_directory = os.getcwd()
    parent_directory = os.path.dirname(current_directory)
    file_path = parent_directory+"\\python\\formulaLayout\\"+xml_name+'.xml'
    
    print("当前工作目录:", os.getcwd())
    print("XML目标路径:", file_path)

    if not os.path.exists(file_path):
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        print("初始化配置！")
        return 0
    else:
        print("file already exists, skipping！")
        return 1

# 策略初始化
def init(C):
    is_exists = create_xml_if_not_exists(g.params['策略名称'])
    if is_exists!=1:
        return
        
    set_param(C)
    set_account(C)
    C.run_time("on_timer", "3nSecond", "2026-02-10 09:30:00")

# 设置全局参数和变量
def set_param(C):
    try:
        g.params['开始时间'] = start_time
        g.params['结束时间'] = end_time
        g.params['最大买入标的数'] = max_buy_count
        g.params['买入类型'] = order_type_combo
        g.params['买入金额'] = order_type_value
        g.params['买入数量'] = order_type_volume
        g.params['价格类型'] = price_type_combo
        g.params['预警文件'] = request_file
        g.params['防重规则'] = avoid_repeat_type
        g.params['公式配置'] = formula_param
    except Exception as e:
        print('参数设置异常', e)
        
    print(json.dumps(g.params, ensure_ascii=False, indent=2))
    
    # ===== 修改：不再读取Excel，直接忽略 =====
    # 原来的Excel读取逻辑废弃，因为我们已经改为直接根据信号文字判断
    g.df_formula = pd.DataFrame()   # 置空，不再使用

# 设置资金账户
def set_account(C):
    try:
        g.accID = account
    except Exception as err:
        g.accID = ''
    C.set_account(g.accID)
    
def on_timer(C):
    curr_dt = datetime.now().strftime('%Y%m%d%H%M%S')
    if curr_dt[-6:] < g.params['开始时间'].replace(':','') or curr_dt[-6:]>=g.params['结束时间'].replace(':',''):
        return
    df_request = load_tdx_signal(g.params['预警文件'])
    if df_request.empty:
        print('预警为空')
        return
    
    # 增加是否卖出列（直接根据信号文字判断）
    df_request = add_col_is_sell(df_request)
    
    response_file_path = get_response_file_path()
    df_response = load_tdx_signal(response_file_path)
    if len(df_response)>=g.params['最大买入标的数']:
        print('已达当日最大买入标的数')
        return
    
    if not df_response.empty:
        df_response = add_col_is_sell(df_response)
        index_cols = ['stock_code', 'is_sell'] if g.params['防重规则']=='按股票代码' else ['stock_code', 'datetime', 'formula']
        unique_indexes = df_response[index_cols].drop_duplicates()
        mask = df_request[index_cols].apply(tuple, axis=1).isin(unique_indexes.apply(tuple, axis=1))
        df_request = df_request[~mask]
    
    if df_request.empty:
        print('没有新增预警')
        return
        
    print('新增预警', len(df_request), df_request)
    
    response_columns = df_request.columns
    for _, row in df_request.iterrows():
        if len(df_response)>=g.params['最大买入标的数']:
            print('已达当日最大买入标的数')
            break
        
        signal_info = row.to_dict()
        order = convert_order(signal_info)
        do_order(C, order)
        df_response_item = pd.DataFrame([signal_info], columns=response_columns)
        df_response = pd.concat([df_response, df_response_item])
    
    df_response.drop('is_sell', axis=1, inplace=True)
    save_tdx_signal_response(df_response, response_file_path)

# ===== 核心修改：直接根据信号名称判断是否卖出 =====
def add_col_is_sell(df_request):
    """
    直接根据预警信号名称判断买卖方向，不依赖外部Excel配置文件。
    规则：如果 formula 列包含 '弱卖'，则标记为卖出(1)，否则为买入(0)
    """
    # 注意：如果同一股票同一时间既有买入又有卖出信号，此逻辑会以最后一个匹配为准
    # 这里我们优先识别 '弱卖'，其他的都视为买入（包括 '五日内六级' 和 '测试临时用'）
    df_request['is_sell'] = df_request['formula'].apply(
        lambda x: 1 if str(x).strip() == '弱卖' else 0
    )
    return df_request

# 获取响应文件路径
def get_response_file_path():
    file_path = g.params['预警文件']
    dir_path = os.path.dirname(file_path)
    file_name_without_ext = os.path.splitext(os.path.basename(file_path))[0]
    curr_date = datetime.now().strftime('%Y%m%d')
    file_name = file_name_without_ext+"_response_"+curr_date+".txt"
    response_file_path = os.path.join(dir_path, file_name)
    return response_file_path
    
def is_valid_order(order_info):
    if order_info['方向'] not in ['买入', '卖出']:
        return False
    if order_info['单位'] not in ['数量', '金额']:
        return False
    if order_info['价格类型'] not in g.price_types:
        return False
    return True

def do_order(C, order):
    print('do_order', order)
    if order['trade_amount']<=0:
        return
    passorder(order['trade_direct'], 
            order['trade_type'], 
            g.accID, 
            order['stock_code'], 
            order['price_type'], 
            order['price'], 
            order['trade_amount'], 
            g.params['策略名称'], 
            2, 
            order['remark'], 
            C)

def convert_order(order_info):
    order = {}
    order['trade_direct'] = 24 if order_info['is_sell'] else 23
    order['trade_type'] = 1102 if g.params['买入类型']=='金额' else 1101
    order['trade_amount'] = g.params['买入金额'] if g.params['买入类型']=='金额' else g.params['买入数量']
    order['price_type'] = get_price_type()
    order['price'] = order_info['price'] if g.params['价格类型']=='市价单' else 0 
    order['stock_code'] = add_market_suffix(order_info['stock_code'])
    order['remark'] = order_info['formula']
    
    # 卖出：全仓卖出（获取持仓可用数量）
    if order['trade_direct']==24:
        stock_code = order['stock_code']
        # 注意：get_trade_detail_data 需要 QMT 环境，这里假定存在
        positions = get_trade_detail_data(g.accID, 'STOCK', 'POSITION')
        hold_list = { position.m_strInstrumentID+'.'+position.m_strExchangeID : position.m_nCanUseVolume for position in positions }
        if stock_code not in hold_list or hold_list[stock_code] <= 0:
            trade_amount = 0
            print('卖出不在持仓池或持仓可用为0',stock_code)
        else:
            trade_amount = hold_list[stock_code]
        order['trade_type'] = 1101   # 卖出必须按数量
        order['trade_amount'] = trade_amount
        
    return order

def get_price_type():
    types = {
        '预警价':11,
        '对手价':14,
        '市价单':44,
    }
    return types[g.params['价格类型']]

def load_tdx_signal(file_path):
    df = pd.DataFrame()
    try:
        if not os.path.exists(file_path):
            print('文件不存在', file_path)
        else:
            df = pd.read_csv(
                file_path,
                sep='\t',
                header=None,
                names=['stock_code', 'name', 'datetime', 'price', 'change_percent', 'volume', 'formula'],
                index_col=False,
                dtype = {'stock_code':str},
                engine='python'
                )
            print('读取文件', file_path, len(df))
    except Exception as e:
        print('读取文件异常', e, file_path)
        df = pd.DataFrame()
    return df
    
def save_tdx_signal_response(df, file_path):
    try:
        df.to_csv(file_path, 
            sep='\t',
            header=None,
            encoding='gbk',
            index=False)
        print(f'保存文件 {file_path} {len(df)}')
    except Exception as e:
        print(f'保存文件 {e} {file_path} {len(df)}')

def add_market_suffix(stock_code):
    if stock_code[-2:] in ['SH', 'SZ', 'BJ', 'sh', 'sz', 'bj']:
        stock_code=stock_code.upper()
    elif stock_code[0:2] in ['SH', 'SZ', 'BJ']:
        stock_code=stock_code[2:]+"."+stock_code[0:2]
    else:
        if (stock_code[:3] in ['510','511', '512','513','515','516','113','110', '118','501'] or
            stock_code.startswith('60') or
            stock_code.startswith('68') or
            stock_code.startswith('11')):
            stock_code=stock_code+'.SH'
        elif (stock_code[:3] in ['159'] or
            stock_code.startswith('00') or
            stock_code.startswith('30') or
            stock_code.startswith('12')):
            stock_code=stock_code+'.SZ'
        elif (stock_code[:3] in ['920'] or
            stock_code[:2] in ['43', '82', '83', '87', '88']):
            stock_code=stock_code+'.BJ'
        else:
            raise Exception(f'unsupport {stock_code}')
    return stock_code