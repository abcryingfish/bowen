# Factor Watermark Increment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the batch watermark follow persisted per-factor `MAX(time)` while preserving null-valued dates, single rewind semantics, and date-tail-only saves.

**Architecture:** Keep per-factor dates authoritative. After successful saves and compaction, reload persisted dates for the complete enabled factor catalog, calculate the common completed date, and atomically update the existing batch watermark only from that evidence. No new metadata file or factor formula changes are introduced.

**Tech Stack:** Python 3.10, Pandas, DuckDB, Pytest, JSON

---

### Task 1: Lock Existing Increment Semantics

**Files:**
- Test: `ZXW因子/test_factor_auto_plan_valid_values.py`
- Test: `ZXW因子/test_factor_progress_logging.py`

- [ ] **Step 1: Run the existing regression tests**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest `
  'ZXW因子/test_factor_auto_plan_valid_values.py' `
  'ZXW因子/test_factor_progress_logging.py' -q
```

Expected: the tests covering all-null dates, new-factor full history, per-factor authoritative dates, one-time query rewind, and date-tail-only saves pass.

- [ ] **Step 2: Confirm the assertions encode the required boundaries**

Verify that the tests assert:

```python
assert last_dates["测试因子B"] == pd.Timestamp("2026-07-24")
assert result.loc["new_factor", "plan_start"] == pd.Timestamp("2010-01-01")
assert result["plan_start"] == pd.Timestamp("2026-07-30")
assert execution_plan["query_start"] == pd.Timestamp("2026-05-02")
assert tasks[0]["start_dt"] == pd.Timestamp("2026-07-25")
```

### Task 2: Add Failing Persisted-Watermark Tests

**Files:**
- Modify: `ZXW因子/test_factor_batch_watermark.py`
- Test: `ZXW因子/test_factor_batch_watermark.py`

- [ ] **Step 1: Add a partial-update regression test**

Call `_finalize_factor_batch` with one updated frame but a two-factor managed catalog. Inject a last-date loader returning `DIF=2026-07-29` and `DEA=2026-07-28`. Assert the written batch watermark is `2026-07-28`, not the requested target date.

- [ ] **Step 2: Add an all-null-date regression test**

Inject persisted last dates that came from `MAX(time)` and assert an all-null factor frame at `2026-07-29` still permits a `2026-07-29` watermark.

- [ ] **Step 3: Add a missing-managed-factor regression test**

Inject a managed catalog containing a factor absent from the persisted date map. Assert the existing watermark is preserved and the writer is not called.

- [ ] **Step 4: Run the focused tests and verify RED**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest 'ZXW因子/test_factor_batch_watermark.py' -q
```

Expected: FAIL because `_finalize_factor_batch` does not accept the managed catalog or persisted-date loader and currently writes `target_date` directly.

### Task 3: Derive Batch Watermark From Persisted Factor Dates

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py`
- Test: `ZXW因子/test_factor_batch_watermark.py`

- [ ] **Step 1: Extend `_finalize_factor_batch` inputs**

Add optional `managed_factor_name_map` and `factor_last_date_loader` arguments. Preserve existing behavior for callers that omit the managed catalog.

- [ ] **Step 2: Reload dates after successful compaction**

Use the injected loader or `_load_factor_last_date_map` after compaction. Normalize directory names with `_sanitize_factor_dir_name` and require every managed Chinese factor name to have a persisted date.

- [ ] **Step 3: Calculate the common completed date**

Set `last_complete_date` to the minimum persisted `MAX(time)` across the managed factor catalog. Do not inspect factor values. If any managed factor has no persisted date, preserve the existing watermark and do not write a new one.

- [ ] **Step 4: Pass the full enabled catalog from the main flow**

Build the managed Chinese/English map from `selected_bundles_for_compute` and `bundle_factor_catalog`, then pass it to `_finalize_factor_batch`. This prevents a manual or partial target run from claiming the whole batch reached `END_DATE`.

- [ ] **Step 5: Run the focused tests and verify GREEN**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest 'ZXW因子/test_factor_batch_watermark.py' -q
```

Expected: all watermark tests pass.

### Task 4: Verify Production State And Regression Safety

**Files:**
- Verify: `ZXW因子/ZXW策略技术因子生成.py`
- Verify: `D:\database\signal_daily\_meta\factor_batch_watermark.json`

- [ ] **Step 1: Run all ZXW tests**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest 'ZXW因子' -q
```

Expected: all tests pass; existing FutureWarnings may remain.

- [ ] **Step 2: Check syntax, UTF-8, and whitespace**

Parse modified Python files as UTF-8 with `ast.parse`, parse the watermark JSON, and run `git diff --check` on modified source and tests.

- [ ] **Step 3: Recalculate the current managed common date read-only**

Read the enabled catalog and each factor's latest persisted `MAX(time)`. Confirm null values are not filtered and compare the calculated common date with the current watermark.

- [ ] **Step 4: Correct the real watermark only when evidence differs**

If the persisted common date differs from `last_complete_date`, atomically rewrite the existing watermark using the same payload format. If they match, leave the file unchanged and report that no correction was necessary.
