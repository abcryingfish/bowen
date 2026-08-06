# ZXW 策略因子生成进度输出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不增加计算或数据扫描开销的前提下，为 ZXW 因子生成脚本增加计算计划、批次耗时、保存耗时和整批汇总输出。

**Architecture:** 新增纯格式化辅助函数，接收已有执行计划元数据并输出中文终端信息；计算阶段复用现有批次 `perf_counter` 边界；保存阶段在现有保存任务返回值中携带耗时和区间，由调用方打印。因子算法、批次分组、线程池和落盘内容不变。

**Tech Stack:** Python 3.10+, pandas, pathlib, unittest/pytest-compatible tests.

---

### Task 1: Add failing progress-format tests

**Files:**
- Create: `ZXW因子/test_factor_progress_logging.py`
- Test: `ZXW因子/test_factor_progress_logging.py`

- [ ] **Step 1: Write the failing tests**

  Load only the new top-level formatting functions from `ZXW策略技术因子生成.py` with `ast`, so importing the notebook-style script does not execute its data pipeline. Cover factor-name wrapping, date-range formatting, and progress-line content. Add a test for save-task result metadata requiring `elapsed_seconds` and the requested date range.

- [ ] **Step 2: Run the tests to verify they fail for the intended reason**

  Run:

  ```powershell
  python -m unittest -v ZXW因子.test_factor_progress_logging
  ```

  Expected: FAIL because the formatting functions and elapsed metadata do not yet exist.

### Task 2: Implement zero-overhead calculation progress output

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py` near the existing execution-plan helpers and the execution-batch loop.

- [ ] **Step 1: Add minimal pure helpers**

  Add helpers for fixed-width factor-name lines, date-range formatting, and plan-line formatting. They must only transform already available strings, timestamps, counts, and lists.

- [ ] **Step 2: Run the focused tests**

  Run the same unittest command and confirm the formatting tests pass.

- [ ] **Step 3: Add plan/start/finish prints at existing batch boundaries**

  Before each existing compute call, print batch number, bundle/scope, target factor count, code count, query/compute range, write range, and wrapped factor names. Reuse `_task_start` and `_task_sec` for the completion line. Do not add per-factor loops over data or alter `compute_selected_bundles` arguments.

- [ ] **Step 4: Run focused tests again**

  Run:

  ```powershell
  python -m unittest -v ZXW因子.test_factor_progress_logging
  ```

  Expected: PASS.

### Task 3: Add save-task timing and summaries

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py` in `_save_single_factor_task` and `save_factor_dfs_to_factor_partitioned_parquet`.
- Test: `ZXW因子/test_factor_progress_logging.py`

- [ ] **Step 1: Extend the task result with timing metadata**

  Capture `perf_counter()` at the start of `_save_single_factor_task`; return the existing factor name, month count, and row count plus elapsed seconds and task start/end dates. Do not change the generated Parquet frame or task scheduling.

- [ ] **Step 2: Print task completion lines using returned metadata**

  Update sequential and threaded completion branches to print factor name, task index, date range, months, rows, and elapsed seconds. Keep completion order as produced by the existing executor.

- [ ] **Step 3: Add aggregate save timing**

  Capture one timer around the existing save orchestration and print total task count, months, rows, and elapsed seconds. Preserve existing retry behavior and include retry timing in the aggregate.

- [ ] **Step 4: Run focused tests and syntax validation**

  Run:

  ```powershell
  python -m unittest -v ZXW因子.test_factor_progress_logging
  python -m py_compile ZXW因子/ZXW策略技术因子生成.py
  ```

  Expected: all focused tests pass and compilation exits successfully.

### Task 4: Regression verification

**Files:**
- No additional files.

- [ ] **Step 1: Run the existing planner tests that do not require pytest-only fixtures**

  Run the focused unittest and compile checks from Task 3, then run any available existing test command for the planner module. If `pytest` is unavailable, report that limitation explicitly instead of installing dependencies or changing the environment.

- [ ] **Step 2: Review the diff**

  Confirm only progress formatting, timing metadata, tests, and documentation changed; verify no factor formulas, query ranges, target selection, save paths, or concurrency settings changed.
