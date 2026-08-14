# 动量因子 253 个有效交易日门槛实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将七个个股动量因子的统一资格门槛从250个有效交易日调整为253个，并精确重建已有历史分区与复核覆盖率。

**Architecture:** 资格判断继续由 `build_momentum_factor_bundle` 内的有效收盘价累计数统一控制，不改变七项因子公式、停牌 `NaN` 语义或其他因子。先用边界测试锁定第252/253个有效观察，再最小修改常量，最后只替换七个目标因子目录并以行情源复核公式和覆盖率。

**Tech Stack:** Python、pandas、pytest、DuckDB、Parquet、PowerShell。

---

### Task 1: 锁定253日资格边界

**Files:**
- Modify: `ZXW因子/test_momentum_factor_bundle.py`

- [x] 将期望资格掩码改为 `close.notna().cumsum().ge(253)`。
- [x] 断言无前置缺失与有前置缺失的股票，在前252个有效观察上七项均为 `NaN`，第253个有效观察上七项均为有限值。
- [x] 运行 `.venv\Scripts\python.exe -m pytest ZXW因子\test_momentum_factor_bundle.py -k "momentum" -q`，确认旧实现因第250至252个观察提前产生值而失败。

### Task 2: 最小修改资格常量

**Files:**
- Modify: `ZXW因子/板块动量策略常用因子.py`

- [x] 将 `_MOMENTUM_ELIGIBILITY_VALID_DAYS` 从250改为253，并同步模块说明。
- [x] 重跑定向测试，确认资格边界和现有跳月公式均通过。
- [x] 运行相关回归测试：`test_valid_bar_and_precompute.py`、`test_factor_auto_plan_valid_values.py`、`test_factor_batch_watermark.py`。

### Task 3: 精确重建七个因子

**Files:**
- Rebuild: `D:\database\signal_daily\factor=20日动量`
- Rebuild: `D:\database\signal_daily\factor=60日动量`
- Rebuild: `D:\database\signal_daily\factor=120日动量`
- Rebuild: `D:\database\signal_daily\factor=252日动量`
- Rebuild: `D:\database\signal_daily\factor=纯动量`
- Rebuild: `D:\database\signal_daily\factor=60日纯动量`
- Rebuild: `D:\database\signal_daily\factor=252日纯动量`

- [x] 将七个旧目录移动到 `D:\database\temp` 下的唯一备份目录，先核对源和目标绝对路径。
- [x] 使用项目现有生成器，仅启用 `momentum_common` 和七个目标键全量生成。
- [x] 核对每个因子200个 `merged.parquet`、无残留 `part` 文件后删除备份。

### Task 4: 数据与覆盖率验证

**Files:**
- Verify: `D:\database\signal_daily\factor=*动量\year=*\month=*\merged.parquet`

- [x] 校验所有非空动量值均满足有效观察序号 `>=253`。
- [x] 以“当日有行情且累计至少253个有效交易日”为分母，逐日核对七项完整率为100%。
- [x] 与行情源重新计算七项公式，误差保持在存储浮点精度范围。
- [x] 汇总2015年以来按“含当日停牌成熟股”的市场宽度覆盖率，说明低覆盖日期是否仍由停牌造成。
