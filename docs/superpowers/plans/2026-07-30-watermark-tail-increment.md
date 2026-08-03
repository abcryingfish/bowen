# ZXW Watermark Tail Increment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use the successful batch watermark as the common daily signal write boundary while preserving per-factor lookback queries and full-history generation for new factors.

**Architecture:** Extend the existing planner with an optional completed-watermark date. Existing factors plan from the earlier of their own last valid date and the watermark, then execute against their full output universe; factors with no history retain the existing full-history path. Seed the verified initial watermark only after tests pass.

**Tech Stack:** Python 3.10, pandas, DuckDB, pytest, UTF-8 JSON, Parquet

---

### Task 1: Watermark-aware fill planning

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py:971-1069`
- Test: `ZXW因子/test_factor_auto_plan_valid_values.py`

- [ ] **Step 1: Write failing tests**

Add tests that pass `batch_complete_date=pd.Timestamp("2026-07-24")` and assert an existing factor with incomplete code coverage gets `plan_start=2026-07-25`, while a factor with `last_dt=None` still starts at `2010-01-01`. Add a test asserting a factor last updated on `2026-07-20` starts on `2026-07-21`.

- [ ] **Step 2: Verify the tests fail**

Run: `.venv\Scripts\python.exe -m pytest ZXW因子\test_factor_auto_plan_valid_values.py -q`

Expected: FAIL because `build_factor_fill_plan` does not accept `batch_complete_date`.

- [ ] **Step 3: Implement the planner boundary**

Add `batch_complete_date: Optional[pd.Timestamp] = None`. For existing factors when the watermark is earlier than `end_dt`, set:

```python
tail_base_dt = min(last_dt, completed_dt)
plan_start = max(start_dt, tail_base_dt + pd.Timedelta(days=1))
status = "stale"
reason = f"整批完成水位={completed_dt.date()}，从尾部统一补到{end_dt.date()}"
```

Keep the `last_dt is None` branch as full history and retain the old planner only when no valid watermark exists.

- [ ] **Step 4: Verify the planner tests pass**

Run: `.venv\Scripts\python.exe -m pytest ZXW因子\test_factor_auto_plan_valid_values.py -q`

Expected: all tests pass.

### Task 2: Complete-universe execution and runtime wiring

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py:326-430,1155-1231`
- Test: `ZXW因子/test_factor_auto_plan_valid_values.py`

- [ ] **Step 1: Write the failing dual-gap test**

Build a plan with watermark `2026-07-24`, existing code `000001.SZ`, and newly listed code `688825.SH`; assert the resulting execution plan contains both codes and keeps `plan_start=2026-07-25` while `query_start` is earlier by the configured lookback and buffer.

- [ ] **Step 2: Verify the test fails**

Run the single dual-gap test and confirm the current result contains only `688825.SH`.

- [ ] **Step 3: Wire watermark loading and full-universe execution**

Read `_load_batch_watermark(FACTOR_LIBRARY_BASE_DIR)` before planning, parse `last_complete_date`, pass it to `build_factor_fill_plan`, and ensure watermark-driven reasons do not enter the existing-code subtraction branch. Invalid watermark content must raise rather than silently reverting to an unsafe plan.

- [ ] **Step 4: Verify the dual-gap and planner suites pass**

Run: `.venv\Scripts\python.exe -m pytest ZXW因子\test_factor_auto_plan_valid_values.py ZXW因子\test_factor_batch_watermark.py -q`

Expected: all tests pass.

### Task 3: Seed and verify the initial complete watermark

**Files:**
- Create at runtime: `D:/database/signal_daily/_meta/factor_batch_watermark.json`
- Test: `ZXW因子/test_factor_batch_watermark.py`

- [ ] **Step 1: Add watermark-date parsing tests**

Assert a complete payload returns `2026-07-24`, a missing file returns `None`, and malformed or non-complete payloads raise `ValueError`.

- [ ] **Step 2: Implement and verify parsing**

Add `_get_batch_complete_date` and run the watermark tests to green.

- [ ] **Step 3: Seed the initial record atomically**

Write a UTF-8 JSON record with `status="complete"`, `last_complete_date="2026-07-24"`, an ISO `completed_at`, and `initialized_from_verified_history=true`, without overwriting a newer existing watermark.

- [ ] **Step 4: Run full verification**

Run syntax compilation, the three related pytest files, `git diff --check`, and a read-only query confirming the initial watermark content. Confirm the TRACE-blocking SQLite trigger remains present.
