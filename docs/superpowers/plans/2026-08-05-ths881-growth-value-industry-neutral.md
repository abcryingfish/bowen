# THS881 Growth And Value Industry Neutral Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independent THS881 industry-normalized growth and value composite scores without changing the existing raw scores.

**Architecture:** Two independent Python bundles copy the relevant existing growth and value construction rules. Both load point-in-time 881 snapshots, normalize each raw input within industry, compose the score, normalize the composite within industry, and return one sparse factor for the existing post-write pipeline.

**Tech Stack:** Python 3.10, pandas, NumPy, SciPy, Polars/Parquet, pytest.

---

### Task 1: Growth industry-normalized bundle

**Files:**
- Create: `ZXW因子/股票成长行业标准化因子.py`
- Create: `ZXW因子/test_stock_growth_industry_normalized_factors.py`

- [ ] **Step 1: Write failing tests**

Test that `load_ths881_industry_snapshots()` filters non-881 rows, rejects duplicate stock mappings, and that `build_growth_industry_normalized_factor_bundle()` ranks identical raw values independently inside two industries while preserving missing-data penalties.

- [ ] **Step 2: Verify RED**

Run: `.venv/Scripts/python.exe -m pytest ZXW因子/test_stock_growth_industry_normalized_factors.py -q`

Expected: collection fails because `股票成长行业标准化因子` does not exist.

- [ ] **Step 3: Implement the bundle**

Create these public functions:

```python
def load_ths881_industry_snapshots(*, snapshot_dir: str | Path, end_date: str | pd.Timestamp) -> pd.DataFrame: ...
def build_industry_frame(*, dates: pd.DatetimeIndex, stock_codes: pd.Index, snapshots: pd.DataFrame) -> pd.DataFrame: ...
def industry_rank_normalize(frame: pd.DataFrame, industry_frame: pd.DataFrame, *, min_industry_count: int = 3) -> tuple[pd.DataFrame, pd.DataFrame]: ...
def build_growth_industry_normalized_factor_bundle(raw_factor_dfs: dict[str, pd.DataFrame], industry_frame: pd.DataFrame, *, min_industry_count: int = 3) -> dict[str, object]: ...
def build_stock_growth_industry_normalized_factor_bundle(*, base_dir: str | Path, snapshot_dir: str | Path, start_date: str | pd.Timestamp, end_date: str | pd.Timestamp) -> dict[str, object]: ...
```

Return only `growth_style_composite_score_industry_normalized` and keep pre-snapshot dates empty.

- [ ] **Step 4: Verify GREEN**

Run the same pytest command and expect all tests to pass.

### Task 2: Value industry-normalized bundle

**Files:**
- Create: `ZXW因子/股票价值模型行业标准化评分.py`
- Create: `ZXW因子/test_stock_value_model_industry_normalized_score.py`

- [ ] **Step 1: Write failing tests**

Test industry-level subfactor ranks, final composite ranks, the existing six weights, four-factor eligibility, missing-weight penalty, and pre-2015 rejection.

- [ ] **Step 2: Verify RED**

Run: `.venv/Scripts/python.exe -m pytest ZXW因子/test_stock_value_model_industry_normalized_score.py -q`

Expected: collection fails because `股票价值模型行业标准化评分` does not exist.

- [ ] **Step 3: Implement the bundle**

Copy the industry snapshot and raw value loading behavior into the value module. Implement `build_value_model_industry_normalized_score()` and `build_stock_value_model_industry_normalized_score_bundle()` without importing business functions from the existing value modules.

- [ ] **Step 4: Verify GREEN**

Run the same pytest command and expect all tests to pass.

### Task 3: Generator and catalog integration

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py`
- Modify: `因子分类/factor_catalog.json`
- Modify: both new test files

- [ ] **Step 1: Add failing integration assertions**

Assert both bundle ids, builders, post-write runners, Chinese names, internal keys, sparse-save arguments, and catalog groups are present.

- [ ] **Step 2: Verify RED**

Run both new test files and confirm the integration assertions fail.

- [ ] **Step 3: Add generator integration**

Register both lookback configs and module names, defer both bundles to post-write, add monthly post-write runners, and pass `drop_null_factor_keys=set(chunk_factor_dfs)` when saving.

- [ ] **Step 4: Add catalog integration**

Add one focused group for each new final score without modifying existing groups.

- [ ] **Step 5: Verify GREEN**

Run both new test files and existing growth/value test files.

### Task 4: Full verification

**Files:**
- Verify all changed files.

- [ ] **Step 1: Compile**

Run `.venv/Scripts/python.exe -m py_compile` for the generator and both new modules.

- [ ] **Step 2: Run factor tests**

Run `.venv/Scripts/python.exe -m pytest ZXW因子 -q` and report any unrelated collection blockers separately.

- [ ] **Step 3: Validate real snapshots**

Build the latest available date and assert finite values only, no duplicate keys, score range 0-100, unique 881 mapping, and industry medians near 50 before penalties.

- [ ] **Step 4: Check TRACE interception**

Confirm `block_trace_logs_insert` exists and that TRACE `MAX(id)` plus WAL size do not grow during a repeated observation.

