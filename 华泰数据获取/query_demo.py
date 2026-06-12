#!/usr/bin/python3
# -*- coding: utf-8 -*-

from socket import IPPROTO_L2TP
from insight_python.com.insight import common
from insight_python.com.insight.query import *
from insight_python.com.insight.market_service import market_service
from datetime import datetime


# 查询证券的分钟K，日K，周K，月K数据
def get_kline_demo():
    """
    :param htsc_code: 华泰证券代码，支持多个code查询，列表类型
    :param time: 时间范围，list类型，开始结束时间为datetime
    :param frequency: 频率，分钟K（‘1min’，’5min’，’15min’，’60min’），日K（‘daily’），周K（‘weekly’），月K（‘monthly’）
    :param fq: 复权，默认前复权”pre”，后复权为”post”，不复权“none”
    :return:pandas.DataFrame
    """

    time_start_date = "2022-01-16 15:10:11"
    time_end_date = "2023-01-18 11:20:50"
    time_start_date = datetime.strptime(time_start_date, '%Y-%m-%d %H:%M:%S')
    time_end_date = datetime.strptime(time_end_date, '%Y-%m-%d %H:%M:%S')

    # time_start_date = "2021-01-14"
    # time_end_date = "2022-10-20"
    # time_start_date = datetime.strptime(time_start_date, '%Y-%m-%d')
    # time_end_date = datetime.strptime(time_end_date, '%Y-%m-%d')

    result = get_kline(htsc_code=["510050.SH", "601688.SH"], time=[time_start_date, time_end_date],
                       frequency="daily", fq="none")
    print(result)


# 查询证券的行情衍生指标
def get_derived_demo():
    """
    :param htsc_code:华泰证券代码，支持多个code查询，列表类型
    :param trading_day: 时间范围，list类型，开始结束时间为datetime
    :param type:衍生指标类型，可选成本均价线amv，人气和买卖医院指标明细ar_br，乖离率明细bias，布林线明细boll，中间意愿指标明细cr，
    成交量平均线和移动平均线vma_ma，成交量变异率vr，威廉指标明细wr， 北向资金north_bound
    :return: pandas.DataFrame
    """

    # htsc_code = ["601688.SH", "601686.SH", "000001.SZ"]
    # type = "cr"
    # start_date = '2021-01-02'
    # end_date = '2022-12-05'
    # # 转为时间格式
    # start_date = datetime.strptime(start_date, '%Y-%m-%d')
    # end_date = datetime.strptime(end_date, '%Y-%m-%d')

    htsc_code = ["SCHKSBSH.HT", "SCHKSBSZ.HT", "SCSHNBHK.HT", "SCSZNBHK.HT"]
    type = "north_bound"
    start_date = '2023-09-02'
    end_date = '2023-09-27'
    # 转为时间格式
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_derived(htsc_code=htsc_code, trading_day=[start_date, end_date], type=type)
    print(result)


# 查询成交分价
def get_trade_distribution_demo():
    """
    :param htsc_code: 华泰证券代码，支持多个code查询，列表类型
    :param trading_day: 时间范围，list类型，开始结束时间为datetime
    :return: pandas.DataFrame
    """

    start_date = '2021-01-13'
    end_date = '2021-12-11'
    # 转为时间格式
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_trade_distribution(htsc_code=["601688.SH", "601686.SH"], trading_day=[start_date, end_date])
    print(result)


# 筹码分布
def get_chip_distribution_demo():
    """
    :param htsc_code: 华泰证券代码，支持多个code查询，列表类型
    :param trading_day: 时间范围，list类型，开始结束时间为datetime，仅支持当日查询
    :return: pandas.DataFrame
    """
    start_date = '2024-05-30'
    end_date = '2024-05-30'
    # 转为时间格式
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_chip_distribution(htsc_code=["601688.SH"], trading_day=[start_date, end_date])
    print(result)


# 查询资金流向
def get_money_flow_demo():
    """
    :param htsc_code: 华泰证券代码，支持多个code查询，列表类型
    :param trading_day: 时间范围，list类型，开始结束时间为datetime
    :return: pandas.DataFrame
    """

    start_date = '2021-09-13'
    end_date = '2022-09-12'
    # 转为时间格式
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_money_flow(htsc_code=["601688.SH", "601686.SH", "000001.SZ"], trading_day=[start_date, end_date])
    print(result)


# 查询涨跌分析
def get_change_summary_demo():
    """
    :param market:证券市场代码，支持多个市场查询，列表类型 沪A: sh_a_share, 深A: sz_a_share, 全A: a_share, 全B: b_share,
                            创业板: gem, 中小板: sme, 科创板: star
    :param trading_day: 时间范围，list类型，开始结束时间为datetime
    :return: pandas.DataFrame
    """

    start_date = '2021-01-13'
    end_date = '2021-12-27'
    # 转为时间格式
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_change_summary(market=["sh_a_share", "sz_a_share"], trading_day=[start_date, end_date])
    print(result)


# 查询指标排行榜数据
def get_billboard_demo():
    """
    :param type: 排行榜类别 涨幅榜:inc_list, 跌幅榜:dec_list, 振幅榜:amp_list, 量比榜:quant_list,
                        委比榜:comm_list, 换手率榜:turnover_rate_list, 成交额榜:trade_val,
                        成交量榜:trade_vol, 5分钟涨幅榜:inc_list_5min, 5分钟跌幅榜:dec_list_5min,
                        5分钟成交额榜:trade_val_5min, 5分钟成交量榜:trade_vol_5min
    :param market: 证券市场代码，支持多个市场查询，列表类型 沪A: sh_a_share, 深A: sz_a_share, 全A: a_share, 全B: b_share,
                            创业板: gem, 中小板: sme, 科创板: star
    :return: pandas.DataFrame
    """

    result = get_billboard(type="inc_list", market=["sz_a_share", "sh_a_share"])
    print(result)


# 行业分类-按行业查询
def get_industries_demo():
    """
    :param classified: 行业分类，"sw_l1": 申万一级行业
                               "sw_l2": 申万二级行业
                               "sw_l3": 申万三级行业
                               "zjh_l1": 证监会一级行业
                               "zjh_l2": 证监会二级行业
    :return: pandas.DataFrame
    """

    result = get_industries(classified='zjh_l2')
    print(result)


# 行业分类-按标的查询
def get_industry_demo():
    """
    :param htsc_code: 华泰证券代码
    :param classified: 行业分类 申万行业划分“sw”，证监会行业划分“zjh”，默认为申万行业划分
    :return: pandas.DataFrame
    """

    result = get_industry(htsc_code='601688.SH', classified='sw')
    print(result)


# 行业分类-按行业代码查询
def get_industry_stocks_demo():
    """
    :param industry_code: 行业代码
    :param classified: 行业分类 申万行业划分“sw”，证监会行业划分“zjh”，默认为申万行业划分
    :return: pandas.DataFrame
    """

    result = get_industry_stocks(industry_code='C26', classified='zjh')
    print(result)


# 股票基础信息-按证券ID查询
def get_stock_info_demo():
    """
    :param htsc_code: 华泰证券代码 字符串类型
    :param listing_date: 上市时间范围，列表类型，datetime格式 [start_date, end_date]
    :param listing_state: 上市状态: 上市交易/终止上市
    :return: pandas.DataFrame
    """

    listing_start_date = "2014-01-14"
    listing_end_date = "2022-10-20"
    listing_start_date = datetime.strptime(listing_start_date, '%Y-%m-%d')
    listing_end_date = datetime.strptime(listing_end_date, '%Y-%m-%d')

    result = get_stock_info(htsc_code="603980.SH", listing_date=[listing_start_date, listing_end_date],
                            listing_state="上市交易")
    print(result)


# 股票基础信息-按市场查询
def get_all_stocks_info_demo():
    """
    :param listing_date: 上市时间范围，列表类型，datetime格式 [start_date, end_date]
    :param exchange: 交易市场代码
    :param listing_state: 上市状态: 上市交易/终止上市
    :return: pandas.DataFrame
    """

    listing_start_date = "2014-01-14"
    listing_end_date = "2022-10-20"
    listing_start_date = datetime.strptime(listing_start_date, '%Y-%m-%d')
    listing_end_date = datetime.strptime(listing_end_date, '%Y-%m-%d')

    result = get_all_stocks_info(listing_date=[listing_start_date, listing_end_date],
                                 exchange='XSHG',
                                 listing_state="上市交易")
    print(result)


# 交易日历
def get_trading_days_demo():
    """
    :param exchange: 交易市场代码
    :param trading_day: 查询时间范围
    :param count: 倒计时，0代表今天， -1代表返回前一天到今天的交易日，1代表返回今天到后一天，int类型，和trading_day二选一
    :return: pandas.DataFrame
    """

    trading_day_start_date = "2022-01-14"
    trading_day_end_date = "2022-10-20"
    trading_day_start_date = datetime.strptime(trading_day_start_date, '%Y-%m-%d')
    trading_day_end_date = datetime.strptime(trading_day_end_date, '%Y-%m-%d')

    result = get_trading_days(exchange='XHKG', count=-500)
    # result = get_trading_days(count=-500)
    # result = get_trading_days(trading_day=[trading_day_start_date, trading_day_end_date])
    print(result)


# 新股上市
def get_new_share_demo():
    """
    :param htsc_code: 华泰证券ID
    :param book_start_date_online: 网上申购开始日期时间范围
    :param listing_date: 上市日期时间范围
    :return: pandas.DataFrame
    """

    book_start_date_online_start_date = "2010-02-05"
    book_start_date_online_end_date = "2022-10-20"
    book_start_date_online_start_date = datetime.strptime(book_start_date_online_start_date, '%Y-%m-%d')
    book_start_date_online_end_date = datetime.strptime(book_start_date_online_end_date, '%Y-%m-%d')

    listing_start_date = "2010-02-05"
    listing_end_date = "2022-10-20"
    listing_start_date = datetime.strptime(listing_start_date, '%Y-%m-%d')
    listing_end_date = datetime.strptime(listing_end_date, '%Y-%m-%d')

    result = get_new_share(htsc_code="601688.SH",
                           book_start_date_online=[book_start_date_online_start_date,
                                                   book_start_date_online_end_date],
                           listing_date=[listing_start_date, listing_end_date])
    print(result)


# 日行情接口
def get_daily_basic_demo():
    """
    :param htsc_code: 华泰证券ID
    :param trading_day: 交易日期
    :return: pandas.DataFrame
    """

    htsc_code = "601688.SH"
    start_date = "2022-02-05"
    end_date = "2022-10-20"
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_daily_basic(htsc_code=htsc_code,
                             trading_day=[start_date, end_date])
    print(result)


# 市值数据
def get_stock_valuation_demo():
    """
    :param htsc_code: 华泰证券ID
    :param trading_day: 交易日期
    :return: pandas.DataFrame
    """

    htsc_code = "601688.SH"
    start_date = "2023-02-05"
    end_date = "2023-03-20"
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_stock_valuation(htsc_code=htsc_code,
                                 trading_day=[start_date, end_date])
    print(result)


# 债券基础信息-按证券ID查询
def get_bond_info_demo():
    """
    :param htsc_code: 华泰证券ID
    :param secu_category_code: 证券类别代码（细分），string类型
                                1    1301    国债
                                2    1302    央行票据
                                3    1310    政策性金融债
                                4    1319    普通金融债
                                5    1320    普通企业债
                                6    1326    资产支持票据
                                7    1327    大额可转让同业存单
                                8    1328    项目收益票据
                                9    1329    大额存单
                                10   1331    标准化票据
                                11   1340    国际开发机构债券
                                12   1350    常规可转债
                                13   1360    地方政府债
                                14   1370    可交换公司债券
                                15   1380    特种金融债券
                                16   1390    券商专项资产管理
                                17   1391    场外债券
                                18   133002    资产支持证券化(ABS)
                                19   13300101    住房抵押贷款证券化
                                20   13300102    汽车抵押贷款证券化
    :param listing_date: 上市时间范围，列表类型，datetime格式 [start_date, end_date]
    :param issue_start_date: 发行时间范围，列表类型，datetime格式 [start_date, end_date]
    :param end_date: 到期时间范围，列表类型，datetime格式 [start_date, end_date]
    :return: pandas.DataFrame
    """

    htsc_code = "019402.SH"
    secu_category_code = "1301"

    listing_start_date = "2014-01-14"
    listing_end_date = "2022-10-20"
    listing_start_date = datetime.strptime(listing_start_date, '%Y-%m-%d')
    listing_end_date = datetime.strptime(listing_end_date, '%Y-%m-%d')

    issue_start_date = "2014-01-07"
    issue_end_date = "2022-10-20"
    issue_start_date = datetime.strptime(issue_start_date, '%Y-%m-%d')
    issue_end_date = datetime.strptime(issue_end_date, '%Y-%m-%d')

    end_start_date = "2015-01-08"
    end_end_date = "2022-10-20"
    end_start_date = datetime.strptime(end_start_date, '%Y-%m-%d')
    end_end_date = datetime.strptime(end_end_date, '%Y-%m-%d')

    result = get_bond_info(htsc_code=htsc_code,
                           secu_category_code=secu_category_code,
                           listing_date=[listing_start_date, listing_end_date],
                           issue_start_date=[issue_start_date, issue_end_date],
                           end_date=[end_start_date, end_end_date])
    print(result)


# 债券基础信息-按市场查询
def get_all_bonds_demo():
    """
    :param exchange: 交易市场
    :param secu_category_code: 证券类别代码（细分），str类型
                                1    1301    国债
                                2    1302    央行票据
                                3    1310    政策性金融债
                                4    1319    普通金融债
                                5    1320    普通企业债
                                6    1326    资产支持票据
                                7    1327    大额可转让同业存单
                                8    1328    项目收益票据
                                9    1329    大额存单
                                10   1331    标准化票据
                                11   1340    国际开发机构债券
                                12   1350    常规可转债
                                13   1360    地方政府债
                                14   1370    可交换公司债券
                                15   1380    特种金融债券
                                16   1390    券商专项资产管理
                                17   1391    场外债券
                                18   133002    资产支持证券化(ABS)
                                19   13300101    住房抵押贷款证券化
                                20   13300102    汽车抵押贷款证券化
    :param listing_date: 上市时间范围，列表类型，datetime格式 [start_date, end_date]
    :param issue_start_date: 发行时间范围，列表类型，datetime格式 [start_date, end_date]
    :param end_date: 到期时间范围，列表类型，datetime格式 [start_date, end_date]
    :return: pandas.DataFrame
    """

    listing_start_date = "2014-01-14"
    listing_end_date = "2022-10-20"
    listing_start_date = datetime.strptime(listing_start_date, '%Y-%m-%d')
    listing_end_date = datetime.strptime(listing_end_date, '%Y-%m-%d')

    issue_start_date = "2014-01-07"
    issue_end_date = "2022-10-20"
    issue_start_date = datetime.strptime(issue_start_date, '%Y-%m-%d')
    issue_end_date = datetime.strptime(issue_end_date, '%Y-%m-%d')

    end_start_date = "2015-01-08"
    end_end_date = "2022-10-20"
    end_start_date = datetime.strptime(end_start_date, '%Y-%m-%d')
    end_end_date = datetime.strptime(end_end_date, '%Y-%m-%d')

    result = get_all_bonds(exchange='XSHE',
                           secu_category_code="1301",
                           listing_date=[listing_start_date, listing_end_date],
                           issue_start_date=[issue_start_date, issue_end_date],
                           end_date=[end_start_date, end_end_date])
    print(result)


# 债券回购行情
def get_repo_price_demo():
    """
    :param htsc_code: 华泰证券ID
    :param exchange: 交易市场
    :param trading_day: 交易日期（范围）
    :return: pandas.DataFrame
    """

    trading_day_start_date = "2019-01-14"
    trading_day_end_date = "2022-10-20"
    trading_day_start_date = datetime.strptime(trading_day_start_date, '%Y-%m-%d')
    trading_day_end_date = datetime.strptime(trading_day_end_date, '%Y-%m-%d')

    result = get_repo_price(htsc_code='206007.SH',
                            exchange='XSHG',
                            trading_day=[trading_day_start_date, trading_day_end_date])
    print(result)


# 可转债发行列表
def get_new_con_bond_demo():
    """
    :param htsc_code: 华泰证券ID
    :param exchange: 交易市场
    :param book_start_date_online: 网上申购开始日期时间范围
    :param listing_date: 上市日期时间范围
    :param issue_date: 发行日期范围
    :param convert_code: 转股代码，与htsc_code二选一
    :return: pandas.DataFrame
    """

    book_start_date_online_start_date = "2014-01-14"
    book_start_date_online_end_date = "2022-10-20"
    book_start_date_online_start_date = datetime.strptime(book_start_date_online_start_date, '%Y-%m-%d')
    book_start_date_online_end_date = datetime.strptime(book_start_date_online_end_date, '%Y-%m-%d')

    listing_start_date = "2014-01-14"
    listing_end_date = "2022-10-20"
    listing_start_date = datetime.strptime(listing_start_date, '%Y-%m-%d')
    listing_end_date = datetime.strptime(listing_end_date, '%Y-%m-%d')

    issue_start_date = "2014-01-07"
    issue_end_date = "2022-10-20"
    issue_start_date = datetime.strptime(issue_start_date, '%Y-%m-%d')
    issue_end_date = datetime.strptime(issue_end_date, '%Y-%m-%d')

    result = get_new_con_bond(htsc_code='113628.SH',
                              exchange='XSHG',
                              book_start_date_online=[book_start_date_online_start_date,
                                                      book_start_date_online_end_date],
                              listing_date=[listing_start_date, listing_end_date],
                              issue_date=[issue_start_date, issue_end_date],
                              convert_code='603685')
    print(result)


# 债券市场行情
def get_bond_price_demo():
    """
    :param htsc_code: 华泰证券ID
    :param exchange: 交易市场代码
    :param trading_day: 交易日期（范围）
    :return: pandas.DataFrame
    """

    trading_day_start_date = "2018-03-14"
    trading_day_end_date = "2018-10-27"
    trading_day_start_date = datetime.strptime(trading_day_start_date, '%Y-%m-%d')
    trading_day_end_date = datetime.strptime(trading_day_end_date, '%Y-%m-%d')

    result = get_bond_price(htsc_code='100803.SZ',
                            exchange='XSHE',
                            trading_day=[trading_day_start_date, trading_day_end_date])
    print(result)


# 可转债赎回信息
def get_con_bond_redemption_demo():
    """
    :param htsc_code: 华泰证券ID
    :param exchange: 交易市场代码
    :param register_date: 登记时间范围
    :return: pandas.DataFrame
    """

    register_date_start_date = "2011-01-14"
    register_date_end_date = "2022-10-27"
    register_date_start_date = datetime.strptime(register_date_start_date, '%Y-%m-%d')
    register_date_end_date = datetime.strptime(register_date_end_date, '%Y-%m-%d')

    result = get_con_bond_redemption(htsc_code='110040.SH',
                                     exchange='XSHG',
                                     register_date=[register_date_start_date, register_date_end_date])
    print(result)


# 可转债转股价变动
def get_con_bond_2_shares_change_demo():
    """
    :param htsc_code: 华泰证券ID
    :param exchange: 交易市场
    :param pub_date: 公告日期范围
    :param convert_code: 转股代码
    :return: pandas.DataFrame
    """

    pub_date_start_date = "2008-01-14"
    pub_date_end_date = "2022-10-27"
    pub_date_start_date = datetime.strptime(pub_date_start_date, '%Y-%m-%d')
    pub_date_end_date = datetime.strptime(pub_date_end_date, '%Y-%m-%d')

    result = get_con_bond_2_shares_change(htsc_code='110567.SH',
                                          exchange='XSHG',
                                          pub_date=[pub_date_start_date, pub_date_end_date])
    print(result)


# 可转债转股结果
def get_con_bond_2_shares_demo():
    """
    :param htsc_code: 华泰证券ID
    :param pub_date: 信息发布日期范围
    :param exer_begin_date: 行权起始日范围
    :param exer_end_date: 行权截止日范围
    :param convert_code: 转股代码
    :param exchange: 交易市场
    :return: pandas.DataFrame
    """

    pub_date_start_date = "2008-01-14"
    pub_date_end_date = "2022-10-27"
    pub_date_start_date = datetime.strptime(pub_date_start_date, '%Y-%m-%d')
    pub_date_end_date = datetime.strptime(pub_date_end_date, '%Y-%m-%d')

    exer_begin_date_start_date = "2008-01-14"
    exer_begin_date_end_date = "2022-10-27"
    exer_begin_date_start_date = datetime.strptime(exer_begin_date_start_date, '%Y-%m-%d')
    exer_begin_date_end_date = datetime.strptime(exer_begin_date_end_date, '%Y-%m-%d')

    exer_end_date_start_date = "2008-01-14"
    exer_end_date_end_date = "2022-10-27"
    exer_end_date_start_date = datetime.strptime(exer_end_date_start_date, '%Y-%m-%d')
    exer_end_date_end_date = datetime.strptime(exer_end_date_end_date, '%Y-%m-%d')

    result = get_con_bond_2_shares(htsc_code='110971.SH',
                                   pub_date=[pub_date_start_date, pub_date_end_date],
                                   exer_begin_date=[exer_begin_date_start_date, exer_begin_date_end_date],
                                   exer_end_date=[exer_end_date_start_date, exer_end_date_end_date],
                                   exchange='XSHG')
    print(result)


# 利润表
def get_income_statement_demo():
    """
    :param htsc_code: 华泰证券ID
    :param end_date: 限定时间范围
    :param period: 报表类型，Q1，Q2，Q3，Q4
    :return: pandas.DataFrame
    """

    end_date_start_date = "2017-01-14"
    end_date_end_date = "2022-10-27"
    end_date_start_date = datetime.strptime(end_date_start_date, '%Y-%m-%d')
    end_date_end_date = datetime.strptime(end_date_end_date, '%Y-%m-%d')

    result = get_income_statement(htsc_code='601688.SH', end_date=[end_date_start_date, end_date_end_date], period='Q2')
    print(result)


# 资产负债表
def get_balance_sheet_demo():
    """
    :param htsc_code: 华泰证券ID
    :param end_date: 限定时间范围
    :param period: 报表类型，Q1，Q2，Q3，Q4
    :return: pandas.DataFrame
    """

    end_date_start_date = "2007-01-14"
    end_date_end_date = "2022-10-27"
    end_date_start_date = datetime.strptime(end_date_start_date, '%Y-%m-%d')
    end_date_end_date = datetime.strptime(end_date_end_date, '%Y-%m-%d')

    result = get_balance_sheet(htsc_code='601166.SH', end_date=[end_date_start_date, end_date_end_date], period='Q1')
    print(result)


# 现金流量表
def get_cashflow_statement_demo():
    """
    :param htsc_code: 华泰证券ID
    :param end_date: 限定时间范围
    :param period: 报表类型，Q1，Q2，Q3，Q4
    :return: pandas.DataFrame
    """

    end_date_start_date = "2007-01-14"
    end_date_end_date = "2022-10-27"
    end_date_start_date = datetime.strptime(end_date_start_date, '%Y-%m-%d')
    end_date_end_date = datetime.strptime(end_date_end_date, '%Y-%m-%d')

    result = get_cashflow_statement(htsc_code='601688.SH',
                                    end_date=[end_date_start_date, end_date_end_date],
                                    period='Q2')
    print(result)


# 财务指标
def get_fin_indicator_demo():
    """
    :param htsc_code: 华泰证券ID
    :param end_date: 限定时间范围
    :param period: 报表类型，Q1，Q2，Q3，Q4
    :return: pandas.DataFrame
    """

    end_date_start_date = "2007-01-14"
    end_date_end_date = "2022-10-27"
    end_date_start_date = datetime.strptime(end_date_start_date, '%Y-%m-%d')
    end_date_end_date = datetime.strptime(end_date_end_date, '%Y-%m-%d')

    result = get_fin_indicator(htsc_code='601688.SH', end_date=[end_date_start_date, end_date_end_date], period='Q2')
    print(result)


# 公司概况
def get_company_info_demo():
    """
    :param htsc_code: 华泰证券ID
    :param name: 证券简称 与htsc_code选填一个)
    :return: pandas.DataFrame
    """

    result = get_company_info(htsc_code='601688.SH')
    # result = get_company_info(name='华泰证券')
    print(result)


# 股票配售
def get_allotment_share_demo():
    """
    :param htsc_code: 华泰证券ID
    :param ini_pub_date: 首次公告日期范围
    :param is_allot_half_year: 半年内是否有配股事件
    :return: pandas.DataFrame
    """

    ini_pub_date_start_date = "2014-01-14"
    ini_pub_date_end_date = "2022-10-20"
    ini_pub_date_start_date = datetime.strptime(ini_pub_date_start_date, '%Y-%m-%d')
    ini_pub_date_end_date = datetime.strptime(ini_pub_date_end_date, '%Y-%m-%d')

    result = get_allotment_share(htsc_code="603633.SH",
                                 ini_pub_date=[ini_pub_date_start_date, ini_pub_date_end_date],
                                 is_allot_half_year="0")
    print(result)


# 股本结构
def get_capital_structure_demo():
    """
    :param htsc_code: 华泰证券ID
    :param end_date: 到期日期范围
    :return: pandas.DataFrame
    """
    htsc_code = "601688.SH"
    end_date_start_date = "2018-01-14"
    end_date_end_date = "2022-10-20"
    end_date_start_date = datetime.strptime(end_date_start_date, '%Y-%m-%d')
    end_date_end_date = datetime.strptime(end_date_end_date, '%Y-%m-%d')

    result = get_capital_structure(htsc_code=htsc_code, end_date=[end_date_start_date, end_date_end_date])
    print(result)


# 股东人数
def get_shareholder_num_demo():
    """
    param htsc_code: 华泰证券ID
    param name: 证券简称(和htsc_code任选其一)
    param end_date: 截止日期范围
    return: pandas.DataFrame
    """

    htsc_code = '601688.SH'
    name = '华泰证券'
    end_date_start_date = "2012-01-14"
    end_date_end_date = "2022-10-27"
    end_date_start_date = datetime.strptime(end_date_start_date, '%Y-%m-%d')
    end_date_end_date = datetime.strptime(end_date_end_date, '%Y-%m-%d')

    result = get_shareholder_num(htsc_code=htsc_code, name=name, end_date=[end_date_start_date, end_date_end_date])
    print(result)


# 股票增发
def get_additional_share_demo():
    """
    :param htsc_code: 华泰证券ID
    :param listing_date: 上市日期范围
    :return: pandas.DataFrame
    """

    listing_start_date = "2015-01-14"
    listing_end_date = "2022-10-20"
    listing_start_date = datetime.strptime(listing_start_date, '%Y-%m-%d')
    listing_end_date = datetime.strptime(listing_end_date, '%Y-%m-%d')

    result = get_additional_share(htsc_code='002665.SZ', listing_date=[listing_start_date, listing_end_date])
    print(result)


# 股票分红
def get_dividend_demo():
    """
    :param htsc_code: 华泰证券ID
    :param right_reg_date: 股权登记日范围
    :param ex_divi_date:  除息日范围
    :param divi_pay_date: 现金红利发放日范围
    :return: pandas.DataFrame
    """

    right_reg_date_start_date = "2014-01-14"
    right_reg_date_end_date = "2022-10-20"
    right_reg_date_start_date = datetime.strptime(right_reg_date_start_date, '%Y-%m-%d')
    right_reg_date_end_date = datetime.strptime(right_reg_date_end_date, '%Y-%m-%d')

    ex_divi_date_start_date = "2014-01-14"
    ex_divi_date_end_date = "2022-10-20"
    ex_divi_date_start_date = datetime.strptime(ex_divi_date_start_date, '%Y-%m-%d')
    ex_divi_date_end_date = datetime.strptime(ex_divi_date_end_date, '%Y-%m-%d')

    divi_pay_date_start_date = "2014-01-14"
    divi_pay_date_end_date = "2022-10-20"
    divi_pay_date_start_date = datetime.strptime(divi_pay_date_start_date, '%Y-%m-%d')
    divi_pay_date_end_date = datetime.strptime(divi_pay_date_end_date, '%Y-%m-%d')

    result = get_dividend(htsc_code='601688.SH',
                          right_reg_date=[right_reg_date_start_date, right_reg_date_end_date],
                          ex_divi_date=[ex_divi_date_start_date, ex_divi_date_end_date],
                          divi_pay_date=[divi_pay_date_start_date, divi_pay_date_end_date])
    print(result)


# 十大股东
def get_shareholders_top10_demo():
    """
    :param htsc_code: 华泰证券ID
    :param change_date: 变动时间范围
    :return: pandas.DataFrame
    """

    change_date_start_date = "2014-01-14"
    change_date_end_date = "2022-10-20"
    change_date_start_date = datetime.strptime(change_date_start_date, '%Y-%m-%d')
    change_date_end_date = datetime.strptime(change_date_end_date, '%Y-%m-%d')

    result = get_shareholders_top10(htsc_code="601688.SH",
                                    change_date=[change_date_start_date, change_date_end_date])
    print(result)


# 十大流通股东
def get_shareholders_floating_top10_demo():
    """
    :param htsc_code: 华泰证券ID
    :param change_date: 变动时间范围
    :return: pandas.DataFrame
    """

    change_date_start_date = "2014-01-14"
    change_date_end_date = "2022-10-20"
    change_date_start_date = datetime.strptime(change_date_start_date, '%Y-%m-%d')
    change_date_end_date = datetime.strptime(change_date_end_date, '%Y-%m-%d')

    result = get_shareholders_floating_top10(htsc_code="601688.SH",
                                             change_date=[change_date_start_date, change_date_end_date])
    print(result)


# 沪深港通持股记录
def get_north_bound_demo():
    """
    :param htsc_code: 华泰证券ID
    :param trading_day: 时间范围
    :return: pandas.DataFrame
    """

    start_date = "2021-01-14"
    end_date = "2022-10-20"
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_north_bound(htsc_code='601688.SH', trading_day=[start_date, end_date])
    print(result)


# 融资融券列表
def get_margin_target_demo():
    """
    :param htsc_code: 华泰证券ID
    :param exchange: 交易市场
    :return: pandas.DataFrame
    """

    result = get_margin_target(htsc_code='', exchange='XSHG')
    print(result)


# 融资融券交易汇总
def get_margin_summary_demo():
    """
    :param htsc_code: 华泰证券ID
    :param trading_day: 时间范围
    :return: pandas.DataFrame
    """

    start_date = "2010-01-14"
    end_date = "2022-10-20"
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_margin_summary(htsc_code='601688.SH', trading_day=[start_date, end_date])
    print(result)


# 融资融券交易明细
def get_margin_detail_demo():
    """
    :param exchange: 交易市场，101 上海证券交易所 105 深圳证券交易所
    :param trading_day: 时间范围
    :return: pandas.DataFrame
    """

    start_date = "2014-01-14"
    end_date = "2022-10-20"
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_margin_detail(exchange='XSHG', trading_day=[start_date, end_date])
    print(result)


# tick数据
def get_tick_demo():
    """
    :param htsc_code: 华泰证券ID（沪深市场标的）
    :param trading_day: 时间范围，仅支持30天内查询
    :param security_type: 证券类型（stock,index,fund,bond,option）
    :return: pandas.DataFrame
    """

    htsc_code = '600000.SH'
    security_type = 'stock'

    # htsc_code = '000001.SH'
    # security_type = 'index'

    # htsc_code = '501000.SH'
    # security_type = 'fund'

    # htsc_code = '010504.SH'
    # security_type = 'bond'
    #
    # htsc_code = '10004679.SH'
    # security_type = 'option'

    start_date = "2024-05-27"
    end_date = "2024-05-27"
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_tick(htsc_code=htsc_code,
                      security_type=security_type,
                      trading_day=[start_date, end_date])
    print(result)


# 复权因子
def get_adj_factor_demo():
    """
    :param htsc_code: 华泰证券ID
    :param begin_date: 时间范围
    :return: pandas.DataFrame
    """

    begin_date_start_date = "2014-01-14"
    begin_date_end_date = "2022-10-20"
    begin_date_start_date = datetime.strptime(begin_date_start_date, '%Y-%m-%d')
    begin_date_end_date = datetime.strptime(begin_date_end_date, '%Y-%m-%d')

    result = get_adj_factor(htsc_code="601688.SH",
                            begin_date=[begin_date_start_date, begin_date_end_date])
    print(result)


# 限售股解禁
def get_locked_shares_demo():
    """
    :param htsc_code: 华泰证券ID
    :param listing_date: 时间范围
    :return: pandas.DataFrame
    """

    start_date = "2024-01-14"
    end_date = "2025-10-20"
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_locked_shares(htsc_code="601688.SH",
                               listing_date=[start_date, end_date])
    print(result)


# 股权质押
def get_frozen_shares_demo():
    """
    :param htsc_code: 华泰证券ID
    :param freezing_start_date: 冻结起始日范围
    :return: pandas.DataFrame
    """

    freezing_start_date_start_date = "2018-09-10"
    freezing_start_date_end_date = "2024-10-20"
    freezing_start_date_start_date = datetime.strptime(freezing_start_date_start_date, '%Y-%m-%d')
    freezing_start_date_end_date = datetime.strptime(freezing_start_date_end_date, '%Y-%m-%d')

    result = get_frozen_shares(htsc_code="601688.SH",
                               freezing_start_date=[freezing_start_date_start_date, freezing_start_date_end_date])
    print(result)


# 港股行业分类-按证券ID查询
def get_hk_industry_demo():
    """
    :param htsc_code: 华泰证券代码
    :return: pandas.DataFrame
    """

    result = get_hk_industry(htsc_code="00750.HK")
    print(result)


# 港股行业分类-按行业代码查询
def get_hk_industry_stocks_demo():
    """
    :param industry_code: 行业代码
    :param classified: 行业分类 申万行业划分“sw”，证监会行业划分“zjh”，默认为申万行业划分
    :return: pandas.DataFrame
    """
    result = get_hk_industry_stocks(industry_code='430102')
    print(result)


# 港股交易日行情
def get_hk_daily_basic_demo():
    """
    :param htsc_code: 华泰证券ID
    :param trading_day: 查询时间范围
    :return: pandas.DataFrame
    """

    start_date = "2023-04-01"
    end_date = "2023-04-30"
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_hk_daily_basic(htsc_code="00750.HK",
                                trading_day=[start_date, end_date])
    print(result)


# 港股估值
def get_hk_stock_valuation_demo():
    """
    :param htsc_code: 华泰证券ID
    :param trading_day: 查询时间范围
    :return: pandas.DataFrame
    """

    start_date = "2023-04-01"
    end_date = "2023-04-30"
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_hk_stock_valuation(htsc_code="00750.HK",
                                    trading_day=[start_date, end_date])
    print(result)


# 港股基本信息
def get_hk_stock_basic_info_demo():
    """
    :param htsc_code: 华泰证券代码 字符串类型
    :param listing_date: 上市时间范围，列表类型，datetime格式 [start_date, end_date]
    :param listing_state: 上市状态: 未上市/上市/退市
    :return: pandas.DataFrame
    """

    listing_start_date = "2007-01-14"
    listing_end_date = "2018-10-20"
    listing_start_date = datetime.strptime(listing_start_date, '%Y-%m-%d')
    listing_end_date = datetime.strptime(listing_end_date, '%Y-%m-%d')

    result = get_hk_stock_basic_info(htsc_code='00817.HK',
                                     listing_date=[listing_start_date, listing_end_date],
                                     listing_state="上市")
    print(result)

# 港股分红
def get_hk_dividend_demo():
    """
    :param htsc_code: 华泰证券ID
    :param ex_divi_date:  除息日范围
    :return: pandas.DataFrame
    """


    ex_divi_date_start_date =  "2024-10-14"
    ex_divi_date_end_date = "2025-10-20"
    ex_divi_date_start_date = datetime.strptime(ex_divi_date_start_date, '%Y-%m-%d')
    ex_divi_date_end_date = datetime.strptime(ex_divi_date_end_date, '%Y-%m-%d')

    result = get_hk_dividend(htsc_code='00817.HK',
                          ex_divi_date=[ex_divi_date_start_date, ex_divi_date_end_date]
                          )

    print(result)

# 个股主营产品
def get_main_product_info_demo():
    """
    :param htsc_code: 华泰证券ID
    :param product_code: 产品编码
    :param product_level: 主营产品层级
    :return: pandas.DataFrame
    """

    htsc_code = '601688.SH'
    product_code = '0x0x'
    product_level = '1'

    result = get_main_product_info(htsc_code=htsc_code,
                                   product_code=product_code,
                                   product_level=product_level
                                   )
    print(result)


# 华泰融券通
def get_htsc_margin_target_demo():
    """
    :return: pandas.DataFrame
    """

    result = get_htsc_margin_target()
    print(result)


# 指数基本信息-按证券ID查询
def get_index_info_demo():
    """
    :param htsc_code: 华泰证券ID
    :param trading_day: 交易日，datetime类型
    :return: pandas.DataFrame
    """

    htsc_code = '000063.SH'
    start_date = "2021-01-10"
    end_date = "2021-11-20"
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_index_info(htsc_code=htsc_code, trading_day=[start_date, end_date])
    print(result)


# 指数基本信息-按市场查询
def get_all_index_demo():
    """
    :param exchange: 交易市场
    :param trading_day: 交易日，datetime类型
    :return: pandas.DataFrame
    """

    exchange = 'XSHG'
    start_date = "2021-11-10"
    end_date = "2021-11-20"
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_all_index(exchange=exchange, trading_day=[start_date, end_date])
    print(result)


# 指数成分股
def get_index_component_demo():
    """
    :param htsc_code: 华泰证券ID
    :param name: 指数简称
    :param stock_code: 成分股代码
    :param trading_day: 交易日，datetime类型
    :return: pandas.DataFrame
    """

    htsc_code = '000300'
    name = '沪深300'
    stock_code = '601688.SH'
    trading_day = "2022-11-30"
    trading_day = datetime.strptime(trading_day, '%Y-%m-%d')

    result = get_index_component(htsc_code=htsc_code,
                                 stock_code=stock_code,
                                 name=name,
                                 trading_day=trading_day)
    print(result)


# 指数成分股详细数据
def get_index_component_pro_demo():
    """
    :param htsc_code: 华泰证券ID
    :param name: 指数简称
    :param stock_code: 成分股代码
    :param trading_day: 交易日，datetime类型
    :return: pandas.DataFrame
    """

    htsc_code = '000300'
    name = '沪深300'
    stock_code = '601688'
    trading_day = "2023-04-20"
    trading_day = datetime.strptime(trading_day, '%Y-%m-%d')

    result = get_index_component_pro(htsc_code=htsc_code,
                                     stock_code=stock_code,
                                     name=name,
                                     trading_day=trading_day)
    print(result)


# 量化因子
def get_factors_demo():
    """
    :param htsc_code: 华泰证券ID
    :param factor_name: 因子名
    :param trading_day: 时间范围
    :return: pandas.DataFrame
    """
    htsc_code = '601688.SH'
    factor_name = 'barra_cne6_beta'
    start_date = "2022-10-01"
    end_date = "2022-10-20"
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_factors(htsc_code=htsc_code, factor_name=factor_name, trading_day=[start_date, end_date])
    print(result)


# 基金交易状态
def get_fund_info_demo():
    """
    :param htsc_code: 华泰证券ID
    :param trading_day: 时间范围
    :return: pandas.DataFrame
    """

    htsc_code = '502055.SH'
    start_date = "2018-04-01"
    end_date = "2022-10-20"
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_fund_info(htsc_code=htsc_code, trading_day=[start_date, end_date])
    print(result)


# 基金衍生数据
def get_fund_target_demo():
    """
    :param htsc_code: 华泰证券ID
    :param exchange: 交易市场，101：上海证券交易所 105：深圳证券交易所 999：其他
    :param end_date: 截止日期
    :return: pandas.DataFrame
    """

    htsc_code = '502055.SH'
    exchange = 'XSHG'
    end_date_start_date = "2018-04-01"
    end_date_end_date = "2022-10-20"
    end_date_start_date = datetime.strptime(end_date_start_date, '%Y-%m-%d')
    end_date_end_date = datetime.strptime(end_date_end_date, '%Y-%m-%d')

    result = get_fund_target(htsc_code=htsc_code,
                             exchange=exchange,
                             end_date=[end_date_start_date, end_date_end_date])
    print(result)


# ETF申赎成份券汇总表
def get_etf_component_demo():
    """
    :param htsc_code: 华泰证券ID
    :param pub_date: 公告日期范围
    :param trading_day: 交易日期范围
    :return: pandas.DataFrame
    """

    htsc_code = "510270.SH"

    pub_date_start_date = "2022-10-14"
    pub_date_end_date = "2022-10-27"
    pub_date_start_date = datetime.strptime(pub_date_start_date, '%Y-%m-%d')
    pub_date_end_date = datetime.strptime(pub_date_end_date, '%Y-%m-%d')

    trading_day_start_date = "2022-10-14"
    trading_day_end_date = "2022-10-27"
    trading_day_start_date = datetime.strptime(trading_day_start_date, '%Y-%m-%d')
    trading_day_end_date = datetime.strptime(trading_day_end_date, '%Y-%m-%d')

    result = get_etf_component(htsc_code=htsc_code,
                               pub_date=[pub_date_start_date, pub_date_end_date],
                               trading_day=[trading_day_start_date, trading_day_end_date])
    print(result)


# 个股公募持仓
def get_public_fund_portfolio_demo():
    """
    :param htsc_code: 华泰证券ID
    :param name: 证券简称
    :param exchange: 交易市场:
                    XSHG	上海证券交易所
                    XSHE	深圳证券交易所
                    XBSE    北京证券交易所
                    NEEQ	三板交易市场
                    XHKG	香港联合交易所
    :param end_date: 期末日期范围
    :return: pandas.DataFrame
    """

    htsc_code = '601128.SH'
    name = ''
    exchange = 'XSHG'
    end_date_start_date = "2022-01-01"
    end_date_end_date = "2022-10-20"
    end_date_start_date = datetime.strptime(end_date_start_date, '%Y-%m-%d')
    end_date_end_date = datetime.strptime(end_date_end_date, '%Y-%m-%d')

    result = get_public_fund_portfolio(htsc_code=htsc_code,
                                       name=name,
                                       exchange=exchange,
                                       end_date=[end_date_start_date, end_date_end_date])
    print(result)


# ETF申购赎回清单
def get_etf_redemption_demo():
    """
    :param htsc_code: 华泰证券ID
    :param exchange: 交易市场，101：上海证券交易所 105：深圳证券交易所
    :param trading_day: 交易日期范围
    :return: pandas.DataFrame
    """

    htsc_code = '510210.SH'
    exchange = 'XSHG'
    trading_day_start_date = "2020-01-14"
    trading_day_end_date = "2020-10-27"
    trading_day_start_date = datetime.strptime(trading_day_start_date, '%Y-%m-%d')
    trading_day_end_date = datetime.strptime(trading_day_end_date, '%Y-%m-%d')

    result = get_etf_redemption(htsc_code=htsc_code,
                                exchange=exchange,
                                trading_day=[trading_day_start_date, trading_day_end_date])
    print(result)


# 静态信息-按标的查询
def get_basic_info_demo():
    """
    :param htsc_code: 华泰证券ID,入参为list或者string
    :return: pandas.DataFrame
    """

    htsc_code = ["601688.SH", "000001.SH", "104535.SZ", "159743.SZ", "000002.SH", "157987.SH", "501207.SH", '562520.SH',
                 'IF1406.CF']

    result = get_basic_info(htsc_code=htsc_code)
    print(result)


# 静态信息-按证券类型和市场查询
def get_all_basic_info_demo():
    """
    :param security_type: 证券类型，必填，指数index, 股票stock, 基金fund, 债券bond, 期权option, 期货future
    :param exchange: 证券市场，支持多市场查询，选填（option的XDCE大商所数据暂不支持查询）
    :param today: 是否查询当天最新数据，布尔类型，默认True
    :return: pandas.DataFrame
    """

    security_type = 'stock'
    exchange = ['HGHQ', 'XSHG', 'XSHE']
    today = False

    result = get_all_basic_info(security_type=security_type, exchange=exchange, today=today)
    print(result)


# 查询指定证券的ETF的基础信息
def get_etf_info_demo():
    """
    :param query: 交易市场及对应的证券类型，元组类型，支持多市场多交易类型订阅，list类型 [(exchange1,security_type1),(exchange2,security_type2)]
    """
    query_list = [('XSHG', 'fund')]
    get_etf_info(query=query_list)


# ************************************处理查询请求返回结果************************************
class insightmarketservice(market_service):

    def on_query_response(self, result):
        # pass
        for response in iter(result):
            print(response)


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
    IP2="153.3.219.107"
    port=9362
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
    common.fini()


# 使用指导：登陆 -> 订阅/查询/回放 -> 退出
def main():
    # 登陆部分调用
    get_version()
    login()
    # 配置日志开关
    config(False, False, False)
    

    # 查询接口调用
    # get_etf_info_demo()                       # 查询指定证券的ETF的基础信息

    # get_kline_demo()                          # K线数据
    # get_derived_demo()                        # 行情衍生指标
    # get_trade_distribution_demo()             # 成交分价
                                        # get_chip_distribution_demo()              # 筹码分布
    # get_money_flow_demo()                     # 资金流向
    # get_change_summary_demo()                 # 涨跌分析
    # get_billboard_demo()                      # 指标排行榜
    # get_industries_demo()                     # 行业分类-按行业查询
    # get_industry_demo()                       # 行业分类-按标的查询
    # get_industry_stocks_demo()                # 行业分类-按行业代码查询
    # get_stock_info_demo()                     # 股票基础信息-按证券ID查询
    # get_all_stocks_info_demo()                # 股票基础信息-按市场查询
    # get_trading_days_demo()                   # 交易日历
    # get_new_share_demo()                      # 新股上市
    # get_daily_basic_demo()                    # 日行情接口
    # get_stock_valuation_demo()                # 市值数据
    # get_bond_info_demo()                      # 债券基础信息-按证券ID查询
    # get_all_bonds_demo()                      # 债券基础信息-按市场查询
    # get_repo_price_demo()                     # 债券回购行情
    # get_new_con_bond_demo()                   # 可转债发行列表
    # get_bond_price_demo()                     # 债券市场行情
    # get_con_bond_redemption_demo()            # 可转债赎回信息
    # get_con_bond_2_shares_change_demo()       # 可转债转股价变动
    # get_con_bond_2_shares_demo()              # 可转债转股结果
    # get_income_statement_demo()               # 利润表
    # get_balance_sheet_demo()                  # 资产负债表
    # get_cashflow_statement_demo()             # 现金流量表
    # get_fin_indicator_demo()                  # 财务指标
    # get_company_info_demo()                   # 公司概况
    # get_allotment_share_demo()                # 股票配售
    # get_capital_structure_demo()              # 股本结构
    # get_shareholder_num_demo()                # 股东人数
    # get_additional_share_demo()               # 股票增发
    # get_dividend_demo()                       # 股票分红
    # get_shareholders_top10_demo()             # 十大股东
    # get_shareholders_floating_top10_demo()    # 十大流通股东
    # get_north_bound_demo()                    # 沪深港通持股记录
    # get_margin_target_demo()                  # 融资融券列表
    # get_margin_detail_demo()                  # 融资融券交易明细
    # get_margin_summary_demo()                 # 融资融券交易汇总
    # get_tick_demo()                           # tick数据
    # get_adj_factor_demo()                     # 复权因子
    # get_locked_shares_demo()                  # 限售股解禁
    # get_frozen_shares_demo()                  # 股权质押
    # get_hk_industry_demo()                    # 港股行业分类-按证券ID查询
    # get_hk_industry_stocks_demo()             # 港股行业分类-按行业代码查询
    # get_hk_daily_basic_demo()                 # 港股交易日行情
    # get_hk_stock_valuation_demo()             # 港股估值
    # get_hk_stock_basic_info_demo()            # 港股基本信息
    # get_hk_dividend_demo()                    # 港股分红
    # get_main_product_info_demo()              # 个股主营产品
    # get_htsc_margin_target_demo()             # 华泰融券通
    # get_index_info_demo()                     # 指数基本信息-按证券ID查询
    # get_all_index_demo()                      # 指数基本信息-按市场查询
    # get_index_component_demo()                # 指数成分股
    # get_index_component_pro_demo()            # 指数成分股详细数据
    # get_factors_demo()                        # 量化因子
    # get_fund_info_demo()                      # 基金交易状态
    # get_fund_target_demo()                    # 基金衍生数据
    # get_etf_component_demo()                  # ETF申赎成份券汇总表
    # get_public_fund_portfolio_demo()          # 个股公募持仓
    # get_etf_redemption_demo()                 # ETF申购赎回清单
    # get_basic_info_demo()                     # 静态信息-按标的查询
    # get_all_basic_info_demo()                 # 静态信息-按证券类型和市场查询

# 市值数据
# def get_stock_valuation_demo():
    """
    :param htsc_code: 华泰证券ID
    :param trading_day: 交易日期
    :return: pandas.DataFrame
    """

    htsc_code = "601688.SH"
    start_date = "2026-02-05"
    end_date = "2026-03-20"
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_stock_valuation(htsc_code=htsc_code,
                                 trading_day=[start_date, end_date])
    print(result)



    result.to_csv(r'C:\Users\Administrator\Desktop\python_venv\华泰数据获取\123.csv',index=False, encoding='utf-8-sig')

# 退出释放资源
fini()



if __name__ == '__main__':
    main()
