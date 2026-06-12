#!/usr/bin/python3
# -*- coding: utf-8 -*-

from insight_python.com.interface.mdc_gateway_base_define import GateWayServerConfig
from insight_python.com.insight import common, subscribe
from insight_python.com.insight.subscribe import *
from insight_python.com.insight.market_service import market_service


# ************************************数据订阅************************************
# 根据证券市场订阅行情数据
# 异步接口，返回函数在insightmarketservice
def subscribe_tick_by_type_demo():
    """
    :param query: 交易市场及对应的证券类型，元组类型，支持多市场多交易类型订阅，list类型 [(exchange1,security_type1),(exchange2,security_type2)]
    :param mode: 订阅方式 覆盖(coverage)， 新增（add）， 减少(decrease)， 取消(cancel)， 默认为coverage
    """

    query = [('XSHG', 'stock'), ('XSHE', 'stock')]
    mode = 'add'

    subscribe_tick_by_type(query=query, mode=mode)


def subscribe_kline_by_type_demo():
    """
    :param query: 交易市场及对应的证券类型，元组类型，支持多市场多交易类型订阅，list类型 [(exchange1,security_type1),(exchange2,security_type2)]
    :param mode: 订阅方式  覆盖(coverage)， 新增（add）， 减少(decrease)， 取消(cancel)， 默认为coverage
    :param frequency: 频率，list类型，秒K（15s），分钟K（‘1min’）
    """

    query = [('XSHG', 'stock'), ('XSHE', 'stock')]
    mode = 'add'
    frequency = ["15s", "1min"]

    subscribe_kline_by_type(query=query, frequency=frequency, mode=mode)


def subscribe_trans_and_order_by_type_demo():
    """
    :param query: 交易市场，支持多市场查询，list类型 [(exchange1,security_type1),(exchange2,security_type2)]
    :param mode: 订阅方式 覆盖(coverage)， 新增（add）， 减少(decrease)， 取消(cancel)， 默认为coverage
    """

    query = [('XSHG', 'stock'), ('XSHE', 'stock')]
    mode = 'coverage'

    subscribe_trans_and_order_by_type(query=query, mode=mode)


# 根据证券ID来源订阅行情数据
# 异步接口，返回函数在insightmarketservice
def subscribe_tick_by_id_demo():
    """
    :param htsc_code: 华泰证券ID，支持多ID查询，list类型
    :param mode: 订阅方式 覆盖(coverage)， 新增（add）， 减少(decrease)， 取消(cancel)， 默认为coverage
    """

    htsc_code = ['601688.SH', '603980.SH']
    mode = 'add'

    subscribe_tick_by_id(htsc_code=htsc_code, mode=mode)


def subscribe_kline_by_id_demo():
    """
    :param htsc_code: 华泰证券ID，支持多ID订阅，list类型
    :param mode: 订阅方式 覆盖(coverage)， 新增（add）， 减少(decrease)， 取消(cancel)， 默认为coverage
    :param frequency: 频率，list类型，秒K（15s），分钟K（‘1min’）
    """

    htsc_code = ['601688.SH', '000001.SZ']
    mode = 'add'
    frequency = ["15s", "1min"]

    subscribe_kline_by_id(htsc_code=htsc_code, frequency=frequency, mode=mode)


def subscribe_trans_and_order_by_id_demo():
    """
    :param htsc_code: 华泰证券ID，支持多ID订阅，list类型
    :param mode: 订阅方式
    """

    htsc_code = ['601688.SH', '603980.SH']
    mode = 'add'

    subscribe_trans_and_order_by_id(htsc_code=htsc_code, mode=mode)


def subscribe_derived_demo():
    """
    :param type: 订阅数据类型
    :param htsc_code : 华泰证券ID，支持多ID订阅，list类型
    :param exchange : 证券市场代码
    :param frequency: 频率
    :param mode: 订阅方式 覆盖(coverage)， 新增（add）， 减少(decrease)， 取消(cancel)， 默认为coverage
    :param additional:
    """

    type = 'north_bound'
    htsc_code = ["SCHKSBSH.HT", "SCHKSBSZ.HT", "SCSHNBHK.HT", "SCSZNBHK.HT"]
    frequency = '1min'
    mode = 'coverage'

    subscribe_derived(type=type, htsc_code=htsc_code, frequency=frequency, mode=mode)


# ************************************处理数据订阅返回结果************************************
class insightmarketservice(market_service):

    def on_subscribe_tick(self, result):
        # pass
        print(result)

    def on_subscribe_kline(self, result):
        # pass
        print(result)

    def on_subscribe_trans_and_order(self, result):
        # pass
        print(result)

    def on_subscribe_derived(self, result):
        # pass
        print(result)


# ************************************用户登录************************************
# 登陆
# user 用户名
# password 密码
# login_log 登录日志，默认False
def login():
    markets = insightmarketservice()
    # 登陆前 初始化
    user = "MDIL1_01042"
    password = "weS._+7atE4Vdr"
    result = common.login(markets, user, password, login_log=False)

    print(result)


# 配置日志打开
# open_trace trace日志开关     True为打开日志False关闭日志
# open_file_log  本地file日志开关     True为打开日志False关闭日志
# open_cout_log  控制台日志开关     True为打开日志False关闭日志
def config(open_trace=True, open_file_log=True, open_cout_log=True):
    common.config(open_trace, open_file_log, open_cout_log)


# 获取当前版本号
def get_version():
    print(common.get_version())


# 释放资源
def fini():
    if GateWayServerConfig.IsRealTimeData:
        subscribe.sync()
    common.fini()


# 使用指导：登陆 -> 订阅/查询/回放 -> 退出
def main(markets=None):
    # 登陆部分调用
    get_version()
    login()
    # 配置日志开关
    config(False, False, False)
    # config(True, True, True)

    # 订阅部分接口调用
    # subscribe_tick_by_id_demo()
    # subscribe_tick_by_type_demo()
    # subscribe_kline_by_id_demo()

    htsc_code = ['601688.SH', '000001.SZ']
    mode = 'add'
    frequency = ["15s", "1min"]

    subscribe_kline_by_id(htsc_code=htsc_code, frequency=frequency, mode=mode)



    # subscribe_kline_by_type_demo()
    # subscribe_trans_and_order_by_id_demo()
    # subscribe_trans_and_order_by_type_demo()
    # subscribe_derived_demo()

    # 退出释放资源
    fini()


if __name__ == '__main__':
    main()
