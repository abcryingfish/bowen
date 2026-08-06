# 股票市值因子时点与自由流通市值设计

## 目标

调整股票市值因子的股本生效时点，并新增日频原始因子 `自由流通市值`。本次只生成个股原始因子，不进行市值排名、分组、标准化、中性化、评分或风格收益计算。

## 因子口径

股票市值 bundle 保留并输出四个原始因子：

| 中文名 | 英文键 | 公式 |
|---|---|---|
| 总市值 | `total_market_value` | `close * total_capital` |
| 流通市值 | `floating_market_value` | `close * circulating_capital` |
| 自由流通市值 | `free_float_market_value` | `close * freeFloatCapital` |
| 换手率 | `turnover_rate` | `volume / circulating_capital * 100` |

`close` 使用未复权收盘价。市值单位与当前源表保持一致，为元；换手率单位为百分数。

## 股本生效时点

Capital 每条记录的生效日期定义为：

```text
capital_effective_date = max(report_date, announce_date)
```

该规则同时保证：

- 公告日晚于报告日时，不在公告前使用该股本记录；
- 公告日早于报告日时，不在报告日所代表的股本变更时点前提前使用；
- 任一日期缺失时使用另一有效日期；两者均缺失的记录丢弃。

日行情按股票代码与 `capital_effective_date` 做向后时点匹配，只使用当日已经生效的最近一条股本记录。相同股票、相同生效日期存在多条记录时，按 `announce_date`、`report_date` 稳定排序后保留最后一条，避免结果依赖文件扫描顺序。

## 数据链路

`工具/获得股票日频换手率.py` 继续作为市值和换手率派生数据的唯一写入方：

```text
stock_basic_data_daily + qmt_company_data/table=Capital
-> qmt_turnover_data
-> ZXW因子/股票市场数据因子.py
-> signal_daily
-> 前端因子目录
```

源表新增 `free_float_market_val`，并保留 `freeFloatCapital` 与 `capital_effective_date`，便于抽样审计。因子模块直接读取四个派生字段，不在读取层重复计算另一套市值口径。

由于历史 `qmt_turnover_data` 使用旧的 `report_date` 对齐方式，代码修改后必须重建目标历史区间，不能只做尾部增量，否则同一因子会在不同时段混用两种时点口径。重建完成前，因子读取层应要求新字段存在，避免把旧源数据误认为新口径。

## 标的和缺失值

- 只对 `stock_basic_data_daily` 股票成员生成，不包含 ETF、指数和 `.THS` 标的。
- `total_capital`、`circulating_capital` 或 `freeFloatCapital` 缺失或非正时，对应市值因子保持空值。
- 停牌日和无成交日沿用当前源表行为，不填零、不反向填充未来股本。
- 不用流通股本替代缺失的自由流通股本，避免两个因子含义混淆。

## 接入范围

同步更新：

- 市值与换手率源数据生成脚本；
- 股票市场数据因子 bundle；
- 主因子生成器的股票专属因子声明；
- `factor_catalog.json` 的“股票市场数据”分组；
- 对应单元测试和前端 catalog 契约测试。

前端继续通过现有自动发现机制展示新因子，不新增风格分组页面或收益曲线。

## 验证

1. 单元测试覆盖公告日晚于、早于和等于报告日三种生效日期。
2. 验证匹配日早于生效日期时不出现对应股本，生效日及以后才出现。
3. 验证 `自由流通市值 = close * freeFloatCapital`，且不影响原有三个因子。
4. 验证 ETF、指数和 `.THS` 标的不生成该因子。
5. 验证缺少新源字段时明确报错，不用旧数据静默生成。
6. 运行股票市场数据 bundle、主生成器 catalog 和前端 catalog 测试。
7. 历史重建后抽样核对源表公式、日期边界和覆盖率。

## 非目标

- 不生成对数市值、市值排名或分位数。
- 不做极值处理、行业中性化或市值中性化。
- 不构建大盘、小盘、微盘组合及其收益率。
- 不修改其他基本面原始因子。
