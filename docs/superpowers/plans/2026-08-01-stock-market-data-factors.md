# 股票市场数据因子 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with review checkpoints.

**Goal:** 为股票标的写入总市值、流通市值和换手率三个日频因子。

**Architecture:** 新增独立 stock_market_data bundle，从 qmt_turnover_data 读取三个已计算字段，按当前股票行情矩阵的日期和股票代码对齐；主生成器负责注册 bundle，并交给现有 signal_daily 保存逻辑。非股票代码在 bundle 内过滤。

**Tech Stack:** Python、pandas、DuckDB、Parquet、pytest、JSON。

---

### Task 1: 写失败测试，锁定数据口径和标的过滤

**Files:**
- Create: ZXW因子/test_stock_market_data_factors.py

- [ ] **Step 1: Write the failing tests**

测试临时 Parquet 中包含股票、ETF 和 THS 代码，断言输出只保留明确传入的股票代码；断言三个中文名分别映射 total_market_value、floating_market_value、turnover_rate；断言源数据缺失日保持 NaN。

- [ ] **Step 2: Run the tests to verify they fail**

Run: .\.venv\Scripts\python.exe -m pytest "ZXW因子\test_stock_market_data_factors.py" -q
Expected: FAIL with ModuleNotFoundError because the new factor module does not exist.

### Task 2: Implement the independent stock market data bundle

**Files:**
- Create: ZXW因子/股票市场数据因子.py

- [ ] **Step 1: Implement the minimal bundle**

实现 get_factor_lookback_config() 返回零回看期、get_factor_catalog() 返回三个中文到英文映射，以及 build_stock_market_data_bundle(close, source_glob, stock_codes)。DuckDB 只读取 htsc_code、time、total_market_val、floating_market_val、turnover_rate；限制日期和代码后 pivot 为 time x htsc_code，并对齐 close 的索引。

按目标年月裁剪 Parquet 文件列表，并校验最新分区的源数据水位覆盖批次结束日；源水位落后时抛错，不能写入空值推进因子水位。

- [ ] **Step 2: Run focused tests**

Run: .\.venv\Scripts\python.exe -m pytest "ZXW因子\test_stock_market_data_factors.py" -q
Expected: PASS.

### Task 3: Register the bundle in the main generator

**Files:**
- Modify: ZXW因子/ZXW策略技术因子生成.py

- [ ] **Step 1: Register loader and catalog**

导入新模块的 lookback、catalog 和 build 函数，并把 stock_market_data 添加到 SELECTED_BUNDLES、BUNDLE_LOOKBACK_LOADERS、BUNDLE_MODULE_NAMES。

- [ ] **Step 2: Add bundle computation**

在 _compute_selected_bundles_raw 中按需调用新 bundle，并把 stock_basic_data_daily 识别出的股票代码传入，不能依靠 SH/SZ 后缀判断。

- [ ] **Step 3: Verify syntax**

Run: .\.venv\Scripts\python.exe -m py_compile "ZXW因子\股票市场数据因子.py" "ZXW因子\ZXW策略技术因子生成.py"
Expected: exit code 0.

### Task 4: Add factor catalog entries

**Files:**
- Modify: 因子分类/factor_catalog.json
- Create: ZXW因子/test_stock_market_data_catalog.py

- [ ] **Step 1: Add group**

新增 group_id 为 stock_market_data、group_name 为 股票市场数据 的分组，children 为 总市值、流通市值、换手率；保留用户已有 catalog 改动。

- [ ] **Step 2: Test catalog and bundle contract**

断言分组和三个映射存在。

- [ ] **Step 3: Run targeted tests**

Run: .\.venv\Scripts\python.exe -m pytest "ZXW因子\test_stock_market_data_factors.py" "ZXW因子\test_stock_market_data_catalog.py" -q
Expected: PASS.

### Task 5: Verify source formulas and regressions

- [ ] **Step 1: Run shared planning tests**

Run: .\.venv\Scripts\python.exe -m pytest "ZXW因子\test_factor_auto_plan_valid_values.py" "ZXW因子\test_momentum_factor_bundle.py" -q
Expected: PASS, or report pre-existing failures separately.

- [ ] **Step 2: Run formula check**

对 qmt_turnover_data 验证总市值等于 close 乘 total_capital、流通市值等于 close 乘 circulating_capital、换手率等于 volume 除 circulating_capital 乘 100。

Expected: 三个最大绝对误差均为零。
