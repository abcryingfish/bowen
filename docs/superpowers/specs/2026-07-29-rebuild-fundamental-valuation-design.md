# 归母净利润派生表全历史重建设计

## 目标

修正 `factor_fundamental_valuation` 将扣非后净利润误作归母净利润的问题，并从 2010-01-01 起重算全历史派生数据。

## 范围

- 修改 `工具/qmt公司数据获取.py` 中派生链路使用的利润字段：
  `net_profit_incl_min_int_inc_after` 改为 `net_profit_excl_min_int_inc`。
- 保持派生表现有列名和下游读取契约不变：
  `net_profit_parent`、`net_profit_parent_ttm`、`pe_ttm`。
- 不修改、不下载原始 `Income/Balance/CashFlow/PershareIndex/Capital` 数据。
- 删除现有 `D:\database\qmt_company_data\table=factor_fundamental_valuation`，不保留备份。
- 按年度分段执行 `--derive-only`，重建 2010-01-01 至当前日期的数据。

## 安全与验证

删除前要求目标解析为 `D:\database\qmt_company_data` 的直接子目录，且目录名严格等于
`table=factor_fundamental_valuation`。先用失败测试证明旧字段问题，再修改代码。

重算后检查：

- 分区覆盖范围与行数；
- `htsc_code + time` 无重复；
- 伊利股份 2024-04-30 的 `net_profit_parent` 等于 2024Q1 的
  `net_profit_excl_min_int_inc`；
- `net_profit_parent_ttm` 和 `pe_ttm` 使用修正后的利润口径；
- 随机样本与原始财报字段一致。

若某年度重算失败，停止后续年度并保留已生成分区用于排查；不得回退或修改原始财务表。
