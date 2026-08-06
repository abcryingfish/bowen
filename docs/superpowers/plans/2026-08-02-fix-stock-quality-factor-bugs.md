# 股票质量原始因子缺陷修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复基本面原始因子的陈旧值、公告日未来函数、利润口径混用和无用字段硬依赖。

**Architecture:** 保留现有公告事件状态机和bundle接口。每个报告期先清空全部季度因子，再由最新可用输入重算；ROE继续使用归母净利润，ROA、现金含量和应计利润率改用合并净利润；下载层丢弃公告日缺失记录。

**Tech Stack:** Python 3.10、pandas、NumPy、DuckDB、pytest、UTF-8。

---

### Task 1: 修复最新报告期缺失时沿用旧值

**Files:**
- Modify: `ZXW因子/test_stock_fundamental_raw_factors.py`
- Modify: `ZXW因子/股票基本面原始因子.py`

- [ ] 新增测试：历史值有效、最新ROE/毛利率/现金流/负债率/CAGR输入缺失时，对应输出必须为空。
- [ ] 运行新增测试并确认因输出旧值而失败。
- [ ] 在每个报告期开始时清空全部非PB季度因子，再按最新报告期重算。
- [ ] 运行新增测试和现有基本面测试并确认通过。

### Task 2: 统一ROA、现金含量和应计利润率的合并口径

**Files:**
- Modify: `ZXW因子/test_stock_fundamental_raw_factors.py`
- Modify: `ZXW因子/股票基本面原始因子.py`

- [ ] 扩展测试财务夹具，令归母净利润与合并净利润不同，并断言ROE使用归母、ROA/现金含量/应计利润率使用合并净利润。
- [ ] 运行测试并确认三个质量指标因仍使用归母净利润而失败。
- [ ] 读取并还原 `net_profit_incl_min_int_inc` 的单季度及TTM值，仅供三个合并口径质量指标使用。
- [ ] 运行基本面测试并确认通过。

### Task 3: 移除无用源字段硬依赖

**Files:**
- Modify: `ZXW因子/test_stock_fundamental_raw_factors.py`
- Modify: `ZXW因子/股票基本面原始因子.py`

- [ ] 新增测试：PershareIndex缺少 `equity_roe`、`net_roe` 仍可生成全部因子。
- [ ] 运行测试并确认因源字段校验失败。
- [ ] 从PershareIndex读取列中删除两个未使用字段；保留现有毛利率字段。
- [ ] 运行基本面测试并确认通过。

### Task 4: 禁止缺失公告日回填报告期日

**Files:**
- Modify: `工具/test_qmt公司数据获取.py`
- Modify: `工具/qmt公司数据获取.py`

- [ ] 新增测试：`m_anntime`缺失、为空或不可解析的记录不进入标准化结果。
- [ ] 运行测试并确认当前代码错误保留记录且回填 `report_date`。
- [ ] 将缺失 `m_anntime` 视为无公告日，标准化后按 `report_date + announce_date` 丢弃无效记录。
- [ ] 运行QMT下载脚本测试并确认通过。

### Task 5: 文档与完整验证

**Files:**
- Modify: `docs/superpowers/specs/2026-08-02-stock-fundamental-raw-factors-design.md`
- Modify: `docs/superpowers/specs/2026-08-02-stock-quality-raw-factors-design.md`

- [ ] 同步合并净利润口径和公告日缺失处理。
- [ ] 运行相关pytest、Python AST、UTF-8 JSON和真实数据抽样。
- [ ] 复查 `D:\CodexHome\logs_2.sqlite` TRACE触发器、TRACE最大ID和WAL增长。
