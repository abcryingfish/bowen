# 股票成长原始因子 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增独立 `stock_growth_raw` bundle，按公告日点时口径生成 12 个成长基础因子，并完成目录、生成器和测试接入，不执行历史信号回填。

**Architecture:** 复制现有股票基本面原始因子的财报读取、累计值转单季、公告日事件对齐和日频展开逻辑到独立成长模块。成长模块只读取 Income、CashFlow、Balance、PershareIndex，计算 TTM、同比、CAGR、加速度、ROE/毛利率变化及研发费用指标。将三年营收 CAGR 的 bundle 归属迁移到成长 bundle，但保持英文输出键不变。

**Tech Stack:** Python 3.10、pandas、NumPy、DuckDB/Parquet、pytest、UTF-8 JSON。

---

### Task 1: 写成长 bundle 的失败测试

**Files:**
- Create: `ZXW因子/test_stock_growth_raw_factors.py`

- [ ] **Step 1: 写测试夹具和目录契约**

在测试文件中建立 2021Q1 到 2025Q1 的单股票累计财报 Parquet 夹具，Income 同时提供 `revenue`、`oper_profit`、`net_profit_incl_min_int_inc_after`、`net_profit_excl_min_int_inc`、`s_fa_eps_basic`、`research_expenses`，CashFlow 提供 `net_cash_flows_oper_act`，Balance 提供权益和资产负债字段，PershareIndex 提供 `sales_gross_profit`。测试期望 `get_factor_catalog()` 返回 12 个中文名到英文键的映射。

- [ ] **Step 2: 写核心数值断言**

调用尚不存在的 `build_stock_growth_raw_factor_bundle`，断言最新日能够输出营收同比、营收 CAGR、营业利润同比、扣非利润同比、EPS 同比、经营现金流同比、两项加速度、ROE 变化、毛利率变化、研发费用同比和研发费用率；用已知四季度和去年同期四季度的和计算期望值。

- [ ] **Step 3: 写负分母和公告时点断言**

将去年同期扣非利润、经营现金流和研发费用 TTM 的一个组成季度改为负数，断言对应同比为 `NaN`；把最新报告的 `announce_date` 放到观测日之后，断言观测日仍使用旧快照，公告日之后才使用新值。

- [ ] **Step 4: 运行测试确认 RED**

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest ZXW因子\test_stock_growth_raw_factors.py -q
```

预期：因成长模块尚不存在而失败，失败原因应为导入或函数缺失，而不是测试夹具错误。

### Task 2: 实现独立成长模块

**Files:**
- Create: `ZXW因子/股票成长原始因子.py`

- [ ] **Step 1: 复制并建立模块骨架**

复制现有 `股票基本面原始因子.py` 的 UTF-8 模块结构、代码规范和 Parquet 读取辅助函数到新文件，改为 `BUNDLE_ID = "stock_growth_raw"`，使用独立的 `FACTOR_NAME_MAP` 和 `DEFAULT_SOURCE_GLOBS`。

- [ ] **Step 2: 定义 12 个输出键和财报字段**

使用以下英文键：`revenue_growth_yoy_ttm`、`revenue_cagr_3y_ttm`、`operating_profit_growth_yoy_ttm`、`adjusted_net_profit_growth_yoy_ttm`、`basic_eps_growth_yoy_ttm`、`operating_cashflow_growth_yoy_ttm`、`revenue_growth_acceleration_ttm`、`adjusted_net_profit_growth_acceleration_ttm`、`return_on_equity_change_yoy_ttm`、`sales_gross_margin_change_yoy_ttm`、`research_expense_growth_yoy_ttm`、`research_expense_to_revenue_ttm`。

- [ ] **Step 3: 实现 TTM 和同比计算**

把累计季度值转换为单季度值后，按连续四个季度求 TTM。同比函数仅当当前值和去年同期值有限且去年同期值大于零时返回 `(current / prior - 1) * 100`，否则返回 `NaN`。CAGR 仅当两端 TTM 大于零时返回 `((current / old) ** (1 / 3) - 1) * 100`。

- [ ] **Step 4: 实现加速度、ROE、毛利率和研发费用率**

加速度使用当前同比减上一报告期同比；ROE 使用 TTM 归母净利润除以期初期末平均归母权益；毛利率从收入和 `sales_gross_profit` 还原 TTM 毛利润后计算；研发费用率使用研发费用 TTM 除以营业收入 TTM，营业收入非正或研发费用缺失时返回 `NaN`。

- [ ] **Step 5: 复用公告日事件和日频展开**

按 `htsc_code + report_date + announce_date` 去重，保留修订公告事件，使用一次 `merge_asof` 将报告事件向后对齐到行情日；只保留传入 `stock_codes` 与行情列的交集。

- [ ] **Step 6: 运行核心测试确认 GREEN**

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest ZXW因子\test_stock_growth_raw_factors.py -q
```

预期：成长模块测试全部通过。

### Task 3: 接入生成器和因子目录

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py`
- Modify: `因子分类/factor_catalog.json`
- Modify: `ZXW因子/test_stock_fundamental_raw_factor_catalog.py`
- Modify: `可视化/test_market_data_service_stock_fundamental_catalog.py`

- [ ] **Step 1: 写注册失败断言**

先在目录测试中加入 `stock_growth_raw` 的 12 个因子、生成器 import 和 bundle 注册断言，运行相关测试确认在注册缺失时失败。

- [ ] **Step 2: 注册成长 bundle**

在生成器的 lookback、module、label、默认 bundle 和 raw bundle dispatch 表中加入 `stock_growth_raw`，导入 `get_factor_lookback_config` 和 `build_stock_growth_raw_factor_bundle`。

- [ ] **Step 3: 迁移 CAGR 目录归属**

从 `stock_fundamental_raw` 的 `children` 和 `core_factors` 移除 `营业收入三年复合增长率`，新增 `stock_growth_raw` 分组并放入完整 12 项；保留英文键 `revenue_cagr_3y_ttm`，避免已有信号列名变化。

- [ ] **Step 4: 更新目录发现测试并运行 GREEN**

同步测试中的期望分组和因子列表，运行：

```powershell
.\.venv\Scripts\python.exe -m pytest ZXW因子\test_stock_growth_raw_factors.py ZXW因子\test_stock_fundamental_raw_factor_catalog.py 可视化\test_market_data_service_stock_fundamental_catalog.py -q
```

预期：所有成长和目录注册测试通过。

### Task 4: 真实数据抽样和回归验证

**Files:**
- Test only; no production data write.

- [ ] **Step 1: 运行 Python 语法和 JSON 检查**

运行：

```powershell
.\.venv\Scripts\python.exe -m py_compile ZXW因子\股票成长原始因子.py ZXW因子\ZXW策略技术因子生成.py
.\.venv\Scripts\python.exe -c "import json; json.load(open('因子分类/factor_catalog.json', encoding='utf-8')); print('JSON_OK')"
```

- [ ] **Step 2: 使用本地真实 Parquet 做只读抽样**

读取 `D:\database\qmt_company_data` 最近报告期的少量股票和 `D:\database\stock_basic_data_daily` 最近交易日，调用成长 bundle，确认研发费用非空样本能生成研发费用率，所有输出不含正负无穷；不调用保存函数，不写 `D:\database\signal_daily`。

- [ ] **Step 3: 运行相关全量测试**

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest ZXW因子\test_stock_growth_raw_factors.py ZXW因子\test_stock_fundamental_raw_factors.py ZXW因子\test_stock_fundamental_raw_factor_catalog.py 可视化\test_market_data_service_stock_fundamental_catalog.py -q
```

- [ ] **Step 4: 复查日志和工作区差异**

只读检查 `D:\CodexHome\logs_2.sqlite` 的 TRACE 行数、TRACE 最大 ID、`-wal` 大小和是否存在日志 trigger；运行 `git diff --check`，确认没有编码或空白错误，并确认没有修改用户无关文件。
