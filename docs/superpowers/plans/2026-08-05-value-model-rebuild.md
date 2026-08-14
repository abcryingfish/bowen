# Value Model Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct EP/BM/SP negative-value semantics, rebuild their normalized factors from 2015 onward, and generate the single `价值模型综合评分` factor.

**Architecture:** Keep raw value calculations in `股票基本面原始因子.py`, normalization in the existing independent `股票价值标准化因子.py`, and add a separate post-write composite module. Rebuild only the three corrected raw factors and their nine derivatives before computing the composite from all six value percentiles.

**Tech Stack:** Python 3.10, pandas, NumPy, Polars, pytest, Parquet monthly partitions.

---

### Task 1: Lock Correct Raw-Factor Semantics

**Files:**
- Modify: `ZXW因子/test_stock_value_raw_factors.py`
- Modify: `ZXW因子/股票基本面原始因子.py`

- [ ] Add regression cases proving negative profit, negative equity, and negative revenue remain finite negative yields when market value is positive.
- [ ] Run the focused test and confirm it fails because the current implementation returns `NaN`.
- [ ] Read `net_profit_parent_ttm`, `equity_parent`, and `revenue_ttm` from the daily valuation table and divide each directly by positive finite `total_market_val`.
- [ ] Run raw-factor and catalog tests and confirm they pass.

### Task 2: Implement Composite Score With TDD

**Files:**
- Create: `ZXW因子/test_stock_value_model_composite_score.py`
- Create: `ZXW因子/股票价值模型综合评分.py`
- Modify: `ZXW因子/ZXW策略技术因子生成.py`
- Modify: `因子分类/factor_catalog.json`

- [ ] Add failing tests for six-factor weighting, four-factor minimum, weighted missing penalty, input range validation, 2015 start date, and latest-part-wins loading.
- [ ] Implement the independent score module with the approved weights and only the `价值模型综合评分` output.
- [ ] Register the post-write bundle after value normalization and add the catalog group.
- [ ] Run composite, generator-contract, and catalog tests until green.

### Task 3: Pre-Deletion Verification

**Files:**
- Verify: `ZXW因子/股票基本面原始因子.py`
- Verify: `ZXW因子/股票价值标准化因子.py`
- Verify: `ZXW因子/股票价值模型综合评分.py`

- [ ] Run focused value tests and the broader `ZXW因子` suite.
- [ ] Compile modified Python files as UTF-8 and inspect the diff for unrelated changes.
- [ ] Confirm no factor generator process is running and inventory the exact 12 target factor directories.

### Task 4: Delete and Rebuild Corrected Data

**Data targets:**
- Delete and rebuild: EP, BM, SP raw directories.
- Delete and rebuild: each raw factor's `_去极值`, `_百分位`, and `_标准分` directories.
- Create: `D:\database\signal_daily\factor=价值模型综合评分`.

- [ ] Resolve and verify all deletion targets are direct children of `D:\database\signal_daily` and exactly match the allowlist.
- [ ] Remove only the 12 allowlisted directories after code verification passes.
- [ ] Run the factor generator from 2015 through the latest available trading day.
- [ ] Compact generated monthly parts using the existing pipeline and confirm a second incremental run writes no historical duplicates.

### Task 5: Data and Runtime Acceptance

**Files:**
- Verify: rebuilt Parquet partitions under `D:\database\signal_daily`.

- [ ] Confirm EP/BM/SP retain expected negative observations and have no infinities.
- [ ] Confirm all nine normalized outputs are bounded according to their contracts and cover valid trading dates.
- [ ] Confirm composite values are in `[0, 100]`, have at least four inputs, start no earlier than 2015, and reach the latest input date.
- [ ] Recompute a sample score independently and compare with the stored value.
- [ ] Check `logs_2.sqlite` TRACE count/MAX(id) twice and confirm the trigger prevents growth.
- [ ] Run the final focused and full regression suites and report row counts, coverage, dates, runtime, and any repaired bugs.
