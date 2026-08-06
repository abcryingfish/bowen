# Factor MAX(time) Tail Increment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ZXW daily factor updates use each factor's latest stored row date, including null-valued rows, without scanning stock coverage or backfilling historical code gaps.

**Architecture:** Keep the existing factor-partitioned Parquet layout and batch watermark. Build the daily plan from one `MAX(time) GROUP BY factor` query, use each factor's own maximum date as the write boundary, and keep historical lookback data read-only for calculation. The batch watermark remains an all-tasks-success marker and never rewinds an individual factor.

**Tech Stack:** Python 3.10, pandas, Polars, DuckDB, Parquet, pytest

---

### Task 1: Lock the new factor-watermark semantics in tests

**Files:**
- Modify: `ZXW因子/test_factor_auto_plan_valid_values.py`
- Modify: `ZXW因子/test_factor_batch_watermark.py`

- [ ] **Step 1: Replace the valid-value-only expectation with row-date semantics**

Update the existing null-row test so its core assertions are:

```python
assert last_dates == {
    "测试因子A": pd.Timestamp("2026-07-24"),
    "测试因子B": pd.Timestamp("2026-07-24"),
}
assert planner["_get_factor_last_date"](str(tmp_path), "测试因子A") == pd.Timestamp("2026-07-24")
assert planner["_get_factor_last_date"](str(tmp_path), "测试因子B") == pd.Timestamp("2026-07-24")
```

Remove assertions and extracted-function requirements for `_load_factor_code_count_map`, `_load_factor_code_set_map`, `_factor_target_code_count`, and `_factor_covered_code_count`.

- [ ] **Step 2: Add a test proving batch watermark cannot rewind a factor**

```python
def test_factor_last_date_is_authoritative_when_batch_watermark_lags() -> None:
    result = planner["build_factor_fill_plan"](
        factor_dfs_dict={},
        factor_name_map_dict={"DIF": "dif"},
        selected_bundles=["macd"],
        start_date="2010-01-01",
        end_date="2026-07-30",
        base_dir="unused",
        buffer_days=20,
        available_factor_keys={"dif"},
        factor_last_dt_map={"DIF": pd.Timestamp("2026-07-29")},
        batch_complete_date=pd.Timestamp("2026-07-24"),
    ).iloc[0]
    assert result["plan_start"] == pd.Timestamp("2026-07-30")
```

- [ ] **Step 3: Change save-task coverage tests to tail-only behavior**

Assert that `_build_factor_save_tasks` ignores `existing_codes` and creates only `last_dt + 1 ... end_dt`; when `last_dt >= end_dt`, assert it returns no task.

- [ ] **Step 4: Run the focused tests and verify they fail for the old implementation**

Run:

```powershell
.venv\Scripts\python.exe -m pytest ZXW因子\test_factor_auto_plan_valid_values.py ZXW因子\test_factor_batch_watermark.py -q
```

Expected: failures showing null rows stop at `2026-07-23`, the batch watermark rewinds the factor, or historical missing-code tasks are still created.

### Task 2: Implement factor-level tail planning without stock scans

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py`

- [ ] **Step 1: Make row date, not valid value, define the factor watermark**

Use this aggregation in `_load_factor_last_date_map` and the single-factor fallback:

```sql
SELECT CAST(factor AS VARCHAR) AS factor_partition,
       MAX(CAST(time AS DATE)) AS max_dt
FROM read_parquet(..., hive_partitioning=1, union_by_name=true)
GROUP BY 1
```

Delete the `value IS NOT NULL` and `isfinite(value)` predicates.

- [ ] **Step 2: Remove stock coverage from planning**

Delete the code-count/code-set loaders and their planning call sites. Remove `factor_code_count_map`, `target_code_count`, and `factor_target_code_count_map` from `build_factor_fill_plan`. Remove `factor_code_set_map` and the `target_codes -= existing_codes` branch from `_build_factor_scope_execution_plans`.

- [ ] **Step 3: Make each factor's last date authoritative**

Replace the watermark-first branch with:

```python
elif last_dt < end_dt:
    plan_start = max(start_dt, last_dt + pd.Timedelta(days=1))
    status = "stale"
    reason = f"因子水位={last_dt.date()}，需尾部补到{end_dt.date()}"
else:
    plan_start = None
    status = "up_to_date"
    reason = f"因子水位={last_dt.date()}，已覆盖目标区间"
```

Keep `batch_complete_date` only for compatibility and whole-run reporting; do not use it to choose an existing factor's write start.

- [ ] **Step 4: Make save planning tail-only**

Rewrite `_load_factor_storage_summary` to reuse one `_load_factor_last_date_map(base_dir)` result and return only `last_dt`. Rewrite `_build_factor_save_tasks` so an existing factor creates exactly one task from `max(start_dt, last_dt + 1 day)` to `end_dt`, regardless of `existing_codes`.

- [ ] **Step 5: Run focused tests until green**

Run the Task 1 pytest command. Expected: all selected tests pass.

### Task 3: Regression verification

**Files:**
- Verify: `ZXW因子/ZXW策略技术因子生成.py`
- Verify: `ZXW因子/test_factor_auto_plan_valid_values.py`
- Verify: `ZXW因子/test_factor_batch_watermark.py`
- Verify: `ZXW因子/test_factor_progress_logging.py`

- [ ] **Step 1: Run all relevant tests**

```powershell
.venv\Scripts\python.exe -m pytest ZXW因子\test_factor_auto_plan_valid_values.py ZXW因子\test_factor_batch_watermark.py ZXW因子\test_factor_progress_logging.py -q
```

Expected: all tests pass with zero failures.

- [ ] **Step 2: Verify syntax and whitespace**

```powershell
.venv\Scripts\python.exe -m py_compile ZXW因子\ZXW策略技术因子生成.py
git diff --check -- ZXW因子/ZXW策略技术因子生成.py ZXW因子/test_factor_auto_plan_valid_values.py ZXW因子/test_factor_batch_watermark.py
```

Expected: both commands exit successfully with no output.

- [ ] **Step 3: Confirm no coverage scans remain in the runtime path**

```powershell
rg -n "_load_factor_code_count_map|_load_factor_code_set_map|DISTINCT.*htsc_code|missing_columns" ZXW因子/ZXW策略技术因子生成.py
```

Expected: no matches belonging to factor-library coverage planning or historical missing-code save tasks.

- [ ] **Step 4: Commit only the implementation files**

```powershell
git add -- ZXW因子/ZXW策略技术因子生成.py ZXW因子/test_factor_auto_plan_valid_values.py ZXW因子/test_factor_batch_watermark.py
git commit -m "fix: use factor row dates for tail updates"
```

