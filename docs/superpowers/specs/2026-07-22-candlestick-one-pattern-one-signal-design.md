# 蜡烛形态“一形态一信号”设计

## 目标

蜡烛形态的每个具体子形态使用独立信号名和独立输出列，不再把相似形态或同一家族的上涨、下跌结果相加。保留现有判断条件、信号强度、方向和落盘结构。

## 当前问题

- `crows_pattern()` 将 `two_crows` 和 `three_crows` 合并为 `crows`，实际落盘目录与 manifest 中的独立形态定义不一致。
- `get_multi_index_signal_matrix()` 将同一家族函数返回的多个子形态矩阵相加，调用方只能看到家族名，无法识别具体上涨或下跌形态。
- 当前生成脚本使用 `get_detailed_signals_dataframe()`，该接口已保留大部分子形态名，因此不需要改变其数据流。

## 设计

### 乌鸦形态

`crows_pattern()` 直接返回两个矩阵：

- `two_crows`
- `three_crows`

两者沿用各自现有判断条件与 `signal_strength`。同一天若同时满足两种形态，允许同时产生两条独立事件，不再使用“三只乌鸦优先”的覆盖规则。

### MultiIndex 矩阵接口

`get_multi_index_signal_matrix()` 仍接受原有家族级 `enabled_signals` 参数，例如 `harami`、`engulfing`、`crows`。计算完成后，不再把子矩阵相加到家族列，而是把返回字典中的每个子形态直接作为独立列。

单一子形态家族的列名也使用具体子形态名。例如请求 `golden_needle` 时输出 `golden_needle_bottom`，从而保证所有输出列均能与 `signal_strength` 和 manifest 一一对应。

### 兼容边界

- 不修改形态识别公式、趋势条件或权重。
- 不修改 `工具/形态蜡烛信号生成_合并保存.py` 的分区、增量、合并与写盘流程。
- 不删除或迁移 `D:\database\signal_daily_形态\candlestick_no_vol\factor=crows`。
- 修复后新生成的数据会写入 `factor=two_crows` 和 `factor=three_crows`；历史数据需另行确认后重新计算。

## 测试

- 验证 `crows_pattern()` 返回两个独立键，不再返回 `crows`。
- 验证 MultiIndex 接口对成对多空形态输出独立列，且数值与对应子矩阵一致。
- 验证所有明细输出名称都存在于 `signal_strength` 和 `SIGNAL_BAR_SPAN`，避免元数据与实际输出再次偏离。
- 运行现有蜡烛信号生成测试，确认日期过滤和写盘前转换行为没有回归。
