# 同花顺板块分析排除北交所设计

## 目标

同花顺原始成分快照保持完整，但所有板块评分、行情覆盖、估值覆盖、成分广度和状态计算只使用沪深市场股票，北交所 `.BJ` 永久不进入分析分母。

## 数据边界

- `source_member_count`：来源快照中的完整去重成分数，包含北交所。
- `excluded_bj_count`：因市场范围规则排除的 `.BJ` 成分数。
- `eligible_member_count`：实际参与分析的沪深成分数。
- `actual_member_count`：为兼容现有报告，等于 `eligible_member_count`。
- 来源声明成分数仅与 `source_member_count` 比较，避免过滤后产生虚假的成分数不一致告警。

## 处理顺序

1. 读取并去重同花顺一级板块完整成分快照。
2. 统计来源成分数与北交所排除数。
3. 在任何行情、估值、广度或评分计算前过滤 `.BJ`。
4. 覆盖率只以 `eligible_member_count` 为分母。
5. 报告同时披露来源成分、排除北交所和分析成分三个数量。

## 验收条件

- 分析成员中不存在 `.BJ`。
- 512个板块仍全部保留。
- 原始成分数与来源声明成分数继续一致。
- `source_member_count = excluded_bj_count + eligible_member_count`。
- 北交所缺失不再触发 `D008` 行情覆盖告警。

