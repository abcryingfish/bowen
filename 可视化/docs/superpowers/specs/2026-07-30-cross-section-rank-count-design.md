# 横截面排名名次筛选设计

## 目标

在现有“横截面排名”百分比筛选基础上，增加按具体名次筛选的能力，同时保持因子值筛选和既有百分比配置兼容。

## 设计

横截面排名规则增加 `rank_unit` 字段：`percentile`（默认，现有行为）或 `rank`（新增名次行为）。百分比模式继续提交 `percentile`、`min_percentile`、`max_percentile`；名次模式提交 `rank`、`min_rank`、`max_rank`。方向仍支持 `top`、`bottom`、`range`，名次为 1-based 正整数，区间两端包含并允许起止名次相同。

前端规则面板新增单位选择，并根据单位渲染百分比或名次输入。规则状态更新和归一化校验沿用现有事件绑定；后端模式值保持 `cross_section_percentile`，避免破坏旧接口分支。后端规则模型识别 `rank_unit: "rank"`，前/后 N 名严格选择最多 N 个标的；并列值按原数据顺序稳定取舍，名次区间两端包含。

## 验证

新增源码断言覆盖单位控件、名次字段和校验分支，并运行现有 `test_backtest_factor_filter_modes.js`。后端新增规则归一化、精确名额、区间和非法输入测试。
