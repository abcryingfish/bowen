# Factor Batch Watermark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record one global completion watermark only after every ZXW factor partition has been saved, compacted, and verified for the target date.

**Architecture:** Store a UTF-8 JSON watermark under `signal_daily/_meta` and replace it atomically. The existing save and compaction pipeline remains the owner of completion; compaction failures become fatal, and a final verifier checks representative output coverage before advancing the watermark.

**Tech Stack:** Python, pathlib, json, Polars/Parquet, pytest.

---

### Task 1: Watermark persistence

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py`
- Test: `ZXW因子/test_factor_batch_watermark.py`

- [ ] Write failing tests for missing watermark, valid UTF-8 JSON loading, and atomic replacement.
- [ ] Run `pytest ZXW因子/test_factor_batch_watermark.py -q` and confirm the helpers are missing.
- [ ] Implement `_load_batch_watermark` and `_write_batch_watermark_atomic` using a same-directory temporary file and `os.replace`.
- [ ] Re-run the focused tests and confirm they pass.

### Task 2: Completion gate

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py`
- Test: `ZXW因子/test_factor_batch_watermark.py`

- [ ] Write failing tests proving compaction failures prevent completion and incomplete target dates reject watermark advancement.
- [ ] Change `compact_signal_daily_parts` to collect worker failures and raise after all workers finish.
- [ ] Add a verifier that checks each factor produced by the current run reaches the target date in its merged Parquet partition.
- [ ] Update the watermark only after save, compaction, and verification return successfully.

### Task 3: Regression verification

**Files:**
- Test: `ZXW因子/test_factor_batch_watermark.py`
- Test: `ZXW因子/test_factor_auto_plan_valid_values.py`
- Test: `ZXW因子/test_momentum_factor_bundle.py`

- [ ] Run the focused watermark tests.
- [ ] Run the existing factor planning and momentum suites.
- [ ] Compile the generator and run scoped `git diff --check`.
