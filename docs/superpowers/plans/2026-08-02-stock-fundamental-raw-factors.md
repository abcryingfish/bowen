# 股票基本面原始因子实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** 在 `.py` 主生成器中新增六个股票专属基本面原始因子，按公告日无未来函数地展开到日频并接入前端。

**Architecture:** 新增独立 `股票基本面原始因子.py` bundle，使用 DuckDB 批量读取季度表和日频 PB 表。季度累计数据先还原单季度，再计算 TTM；公告事件通过 `announce_date` 对齐到行情交易日。主生成器只负责 bundle 注册、股票范围规划和复用现有保存链路。

**Tech Stack:** Python、pandas、DuckDB、PyArrow/Parquet、pytest。

---

### Task 1: 固化最终口径与测试接口

**Files:**
- Modify: `docs/superpowers/specs/2026-08-02-stock-fundamental-raw-factors-design.md`
- Create: `ZXW因子/test_stock_fundamental_raw_factors.py`

- [ ] **Step 1: Write failing unit tests for factor catalog and formulas**

测试固定以下字段映射和口径：

```python
EXPECTED = {
    "净资产收益率_ROE": "return_on_equity_ttm",
    "销售毛利率": "sales_gross_margin_ttm",
    "经营现金流营业收入比": "operating_cashflow_to_revenue_ttm",
    "资产负债率": "debt_to_asset_ratio",
    "营业收入三年复合增长率": "revenue_cagr_3y_ttm",
    "市净率_PB": "price_to_book_ratio",
}
```

用 5 个季度的累计收入、归母净利润、现金流、权益和毛利率构造一只股票，断言：Q2/Q3/Q4 先差分，TTM 使用最近四个单季度，ROE 使用 TTM 起点和终点权益平均值，毛利率按收入加权，现金流比率按金额汇总，CAGR 使用三年前 TTM。另加入公告日前为空、公告日后可见、ETF/THS 被过滤、负收入和零分母为空的测试。

- [ ] **Step 2: Run the new tests and verify expected failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest ZXW因子\test_stock_fundamental_raw_factors.py -q
```

Expected: FAIL because `股票基本面原始因子.py` and its bundle functions do not yet exist.

### Task 2: 实现基本面 bundle

**Files:**
- Create: `ZXW因子/股票基本面原始因子.py`

- [ ] **Step 1: Implement source loading and partition pruning**

实现 `get_factor_catalog()`、`get_factor_lookback_config()`、`build_stock_fundamental_raw_factor_bundle()`。按 `htsc_code` 过滤股票代码；按目标日期裁剪 `factor_fundamental_valuation` 日频分区；季度表一次性读取必要列：Income 的 `revenue`、`net_profit_excl_min_int_inc`，Balance 的 `tot_liab`、`tot_assets`、`tot_shrhldr_eqy_excl_min_int`，CashFlow 的 `net_cash_flows_oper_act`，PershareIndex 的 `sales_gross_profit`、`gross_profit`、`equity_roe`、`net_roe`，以及各表的 `report_date`、`announce_date`、`period`。

- [ ] **Step 2: Implement cumulative-to-quarter conversion**

按股票、报告年度和季度排序，将 Q1 保留，Q2 减 Q1，Q3 减 Q2，Q4 减 Q3。若季度缺失、报告期重复或数据无法确定累计序列，则该季度相关值为空。重复报告按公告日期排序，在事件生效日使用当时最后一版可见记录。

- [ ] **Step 3: Implement TTM and point-in-time formulas**

实现以下向量化计算：

```python
ttm_revenue = revenue_q.rolling(4).sum()
ttm_net_profit = net_profit_q.rolling(4).sum()
ttm_cfo = operating_cashflow_q.rolling(4).sum()
roe_ttm = ttm_net_profit / ((equity_q.shift(4) + equity_q) / 2) * 100
gross_margin_ttm = gross_profit_q.rolling(4).sum() / ttm_revenue * 100
cfo_to_revenue_ttm = ttm_cfo / ttm_revenue * 100
revenue_cagr_3y_ttm = ((ttm_revenue / ttm_revenue.shift(12)) ** (1 / 3) - 1) * 100
debt_ratio = tot_liab / tot_assets * 100
```

仅在窗口完整、分母大于零且输入有限时保留结果。季度事件的生效日使用当前事件及其依赖表中最晚的公告日；随后用 `merge_asof` 对齐到行情交易日。PB 使用日频源的 `pb`，负净资产或非有限值为空。

- [ ] **Step 4: Run focused tests and verify green**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest ZXW因子\test_stock_fundamental_raw_factors.py -q
```

Expected: all new formula, PIT, membership and missing-value tests pass.

### Task 3: 接入主生成器和因子目录

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py`
- Modify: `因子分类/factor_catalog.json`
- Create: `ZXW因子/test_stock_fundamental_raw_factor_catalog.py`

- [ ] **Step 1: Add bundle registration and stock-only scope**

在 `SELECTED_BUNDLES`、lookback loader、bundle module map 和 direct bundle dispatch 中注册 `stock_fundamental_raw`。将六个英文键加入股票专属集合，规划代码只取 `_stock_source_code_set` 与 `C.columns` 的交集。

- [ ] **Step 2: Add frontend catalog mapping**

新增“股票基本面原始因子”分组，children 与 bundle 中文因子名完全一致；不把质量/成长/价值综合分数加入目录。

- [ ] **Step 3: Add planner and catalog regression tests first, then implementation checks**

测试主生成器源代码包含 bundle 注册，规划范围为 `stock_market`，并断言 ETF、指数和 `.THS` 不在 codes。运行：

```powershell
.\.venv\Scripts\python.exe -m pytest ZXW因子\test_stock_fundamental_raw_factor_catalog.py -q
```

Expected: PASS after registration and catalog changes.

### Task 4: 端到端验证与回归

**Files:**
- No new production files.

- [ ] **Step 1: Run syntax and focused tests**

```powershell
.\.venv\Scripts\python.exe -m py_compile 'ZXW因子\股票基本面原始因子.py' 'ZXW因子\ZXW策略技术因子生成.py'
.\.venv\Scripts\python.exe -m pytest ZXW因子\test_stock_fundamental_raw_factors.py ZXW因子\test_stock_fundamental_raw_factor_catalog.py -q
```

- [ ] **Step 2: Validate real local data**

用当前股票行情最后交易日构造全股票 `C`，运行 bundle，抽样核对：TTM ROE、毛利率、现金流比率、资产负债率、CAGR、PB 与 DuckDB 独立查询结果一致；确认 ETF 和 `.THS` 不输出，并记录有效股票数和耗时。

- [ ] **Step 3: Run full regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest ZXW因子 -q
.\.venv\Scripts\python.exe -m pytest 可视化\test_market_data_service_pure_technical_catalog.py 可视化\test_market_data_service_factor_export_rank.py -q
```

Expected: existing tests and all new tests pass; only previously known pandas FutureWarning may remain.

- [ ] **Step 4: Check TRACE logging and final diff**

短间隔比较 `C:\Users\Administrator\.codex\logs_2.sqlite` 的 `MAX(logs.id)`、WAL 大小和 trigger，确认没有高频 TRACE 写盘；运行 `git diff --check`，只报告本任务文件和用户既有改动，不回退其他工作区内容。

### Task 5: 交付说明

- [ ] **Step 1: Report factor names, formulas, data coverage and commands**

说明运行入口为 `ZXW策略技术因子生成.py`，季度因子按公告日向后填充，PB 为日频；列出测试结果和真实数据验证结果。

- [ ] **Step 2: Remind follow-up work**

明确提醒下一阶段还需单独确定标准化、极值处理和行业中性化的时点、行业分类和缺失值规则。
