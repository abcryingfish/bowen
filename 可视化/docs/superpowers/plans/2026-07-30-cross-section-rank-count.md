# 横截面排名名次筛选 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为横截面排名规则增加按具体名次筛选，同时保持百分比模式兼容。

**Architecture:** 在现有 `cross_section_percentile` 规则中增加 `rank_unit` 分支。面板负责选择单位和输入，归一化函数负责验证并提交百分比或名次字段，因子值模式不变。

**Tech Stack:** 原生 JavaScript、HTML 字符串模板、Node.js `assert` 源码测试。

---

### Task 1: Add failing coverage

**Files:**
- Modify: `C:\Users\Administrator\Desktop\python_venv\可视化\test_backtest_factor_filter_modes.js`

- [ ] Add assertions for rank unit, rank inputs, rank payload fields, and positive-integer validation.
- [ ] Run `node test_backtest_factor_filter_modes.js`; confirm it fails because the new strings are absent.

### Task 2: Implement rank-unit controls and payload normalization

**Files:**
- Modify: `C:\Users\Administrator\Desktop\python_venv\可视化\shared\chart_board_backtest.js`

- [ ] Default `rank_unit` to `percentile` and initialize rank defaults.
- [ ] Render unit selector and rank inputs for top, bottom, and range directions.
- [ ] Persist unit/input changes through the existing control handler.
- [ ] Validate positive integer rank values and emit `rank`, `min_rank`, or `max_rank` fields while retaining existing percentile fields.

### Task 3: Verify

**Files:**
- Test: `C:\Users\Administrator\Desktop\python_venv\可视化\test_backtest_factor_filter_modes.js`

- [ ] Run the focused test and any adjacent JavaScript tests in the visualization directory.
- [ ] Review the diff for UTF-8 preservation and unrelated changes.

### Task 4: Implement backend rank filtering

**Files:**
- Modify: `C:\Users\Administrator\Desktop\python_venv\backtrader\models\configurable_signal_rules\data.py`
- Test: `C:\Users\Administrator\Desktop\python_venv\backtrader\test_factor_rule_filter_modes.py`

- [ ] Add failing tests for exact top-N selection, inclusive rank ranges, payload preservation, and invalid ranks.
- [ ] Extend rule normalization and payload serialization with `rank_unit`, `rank`, `min_rank`, and `max_rank`.
- [ ] Apply stable exact-count selection per daily cross section.
- [ ] Run `python -m unittest test_factor_rule_filter_modes.py` and confirm all cases pass.
