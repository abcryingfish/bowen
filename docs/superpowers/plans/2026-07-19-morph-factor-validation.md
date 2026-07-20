# 具体形态因子检验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将每个具体形态接入现有因子检验页面，按 start_time 作为因子日期并按日取最大 value。

**Architecture:** 在因子检验服务中增加形态 manifest/partition 读取适配器；普通因子路径和形态因子路径通过稳定的 `morph/` 前缀路由，最终交给现有统计计算。前端只增加形态分组和来源标识，不改变检验图表协议。

**Tech Stack:** Python、DuckDB、pandas、原生 JavaScript、pytest。

---

### Task 1: Add failing tests for morph factor normalization

**Files:**
- Modify: `可视化/量化因子有效性检验/test_factor_validation_jobs.py`
- Test: `可视化/量化因子有效性检验/test_factor_validation_jobs.py`

- [ ] **Step 1: Write tests** for converting `start_time` to a day and taking the maximum value for duplicate stock/day/pattern rows, plus routing a `morph/level1/<pattern>` factor to the morph reader.
- [ ] **Step 2: Run the focused tests** with `pytest 可视化/量化因子有效性检验/test_factor_validation_jobs.py -q`; confirm failure because the helpers do not exist.

### Task 2: Implement morph factor discovery and reading

**Files:**
- Modify: `可视化/量化因子有效性检验/factor_validation_service.py`

- [ ] **Step 1: Add manifest and monthly partition helpers** using the existing morph directory conventions.
- [ ] **Step 2: Add `morph/level/pattern` factor discovery** and return a dedicated catalog group while preserving ordinary factors.
- [ ] **Step 3: Add morph parquet reader** selecting `htsc_code`, `start_time`, `signal_name`, `value`, filtering level/pattern, normalizing dates, and grouping by stock/date with `max(value)`.
- [ ] **Step 4: Route `run_factor_validation`** based on the morph prefix, leaving ordinary `_read_factor_frame` behavior unchanged.
- [ ] **Step 5: Run the focused tests** and confirm they pass.

### Task 3: Expose morph factors in the validation UI

**Files:**
- Modify: `可视化/量化因子有效性检验/factor_validation.js`

- [ ] **Step 1: Render the server-provided `morph` group** with a readable Chinese label and preserve factor selection values exactly.
- [ ] **Step 2: Include the factor source/name in saved records** so restored morph validations remain selectable.
- [ ] **Step 3: Run JavaScript syntax validation** with the project Node runtime or `node --check`.

### Task 4: Verify integration

**Files:**
- Modify: none

- [ ] **Step 1: Run the complete factor-validation tests.**
- [ ] **Step 2: Run the relevant market-data and API tests if available.**
- [ ] **Step 3: Inspect the diff and confirm no `D:\\database` path outside the intended morph source was changed.
