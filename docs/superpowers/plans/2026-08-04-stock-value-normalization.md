# Stock Value Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 18 independently persisted value-factor derivatives: MAD-winsorized values, daily cross-sectional percentiles, and inverse-normal standard scores.

**Architecture:** A new standalone value-normalization module reads the six existing value raw-factor partitions, calculates each date from the full A-share cross-section, and returns wide DataFrames using the current bundle contract. The generator registers it as a post-write derived bundle and writes only factors requested by the incremental plan, while the calculation universe remains complete.

**Tech Stack:** Python 3, pandas, NumPy, SciPy, Polars-backed existing persistence, pytest, UTF-8 JSON.

---

### Task 1: Define value normalization behavior with failing tests

**Files:**
- Create: `ZXW因子/test_stock_value_normalized_factors.py`
- Create: `ZXW因子/股票价值标准化因子.py`

- [ ] **Step 1: Write tests for MAD winsorization and fallback behavior**

Add tests importing `cross_sectional_value_normalize` and asserting:

```python
winsorized, percentiles, scores = cross_sectional_value_normalize(
    raw,
    min_valid_count=4,
    min_coverage_ratio=0.5,
)
```

The tests must cover ordinary MAD bounds, missing/non-finite values, `MAD == 0` quantile fallback, and a constant row.

- [ ] **Step 2: Write tests for sample and coverage gates**

Assert all three outputs are missing when either `valid_count < min_valid_count` or `valid_count / universe_count < min_coverage_ratio`.

- [ ] **Step 3: Write a bundle contract test**

Construct six small raw frames and assert `build_value_normalized_factor_bundle` returns exactly 18 factors with `_winsorized`, `_percentile`, and `_standard_score` suffixes. Assert negative values remain valid and ordered below positive values.

- [ ] **Step 4: Run tests and verify RED**

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest "ZXW因子\test_stock_value_normalized_factors.py" -q
```

Expected: collection fails because `股票价值标准化因子` does not exist.

- [ ] **Step 5: Implement the minimal in-memory module**

Create the module with these public contracts:

```python
RAW_FACTOR_NAME_MAP: dict[str, str]
DERIVED_FACTOR_NAME_MAP: dict[str, str]

def cross_sectional_value_normalize(
    frame: pd.DataFrame,
    *,
    min_valid_count: int = 100,
    min_coverage_ratio: float = 0.30,
    mad_scale: float = 3.0,
    score_clip: float = 3.0,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]: ...

def build_value_normalized_factor_bundle(
    raw_factor_dfs: dict[str, pd.DataFrame],
    *,
    min_valid_count: int = 100,
    min_coverage_ratio: float = 0.30,
) -> dict[str, object]: ...
```

Use vectorized row-wise pandas/NumPy operations. For `MAD == 0`, use row-wise 1%/99% quantiles unless the row is constant. Convert infinities to missing before counting coverage. Use average ranks and `(rank - 0.5) / valid_count`, followed by `scipy.stats.norm.ppf` clipped to `[-3, 3]`.

- [ ] **Step 6: Run tests and verify GREEN**

Run the Task 1 pytest command and expect all tests to pass.

### Task 2: Add partition loading without allowing partial normalization universes

**Files:**
- Modify: `ZXW因子/股票价值标准化因子.py`
- Modify: `ZXW因子/test_stock_value_normalized_factors.py`

- [ ] **Step 1: Write failing loader tests**

Create temporary `factor=<name>/year=2026/month=08` partitions for all six raw factors. Assert:

```python
frames = load_raw_value_factor_dfs(
    base_dir=tmp_path,
    start_date="2026-08-03",
    end_date="2026-08-03",
)
```

loads only six-digit `.SH/.SZ/.BJ` A-share codes, and a later `part_*.parquet` overrides `merged.parquet` for the same key. Also assert the loader has no stock-subset argument, preventing accidental partial-universe normalization.

- [ ] **Step 2: Run the loader test and verify RED**

Expected failure: `load_raw_value_factor_dfs` is missing.

- [ ] **Step 3: Implement month-partition loading**

Add `_is_a_share_code`, `_month_directories`, `load_raw_value_factor_dfs`, and `build_stock_value_normalized_factor_bundle`. Read all A-share rows for the requested dates and all six raw factors. Preserve latest-part-wins semantics and raise a Chinese `FileNotFoundError` listing missing raw factors.

- [ ] **Step 4: Run targeted tests and verify GREEN**

Run the value normalized test file and expect all tests to pass.

### Task 3: Register the derived bundle and factor catalog

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py`
- Modify: `因子分类/factor_catalog.json`
- Modify: `ZXW因子/test_stock_value_normalized_factors.py`

- [ ] **Step 1: Write a failing wiring test**

Assert the generator contains `stock_value_normalized`, imports `build_stock_value_normalized_factor_bundle`, and the JSON catalog contains group `stock_value_normalized` with exactly `DERIVED_FACTOR_NAME_MAP` children.

- [ ] **Step 2: Run the wiring test and verify RED**

Expected: assertions fail because registration and catalog entries are absent.

- [ ] **Step 3: Register imports and bundle metadata**

Add `stock_value_normalized` to `SELECTED_BUNDLES`, `BUNDLE_LOOKBACK_LOADERS`, `BUNDLE_MODULE_NAMES`, `POST_WRITE_DERIVED_BUNDLES`, and `STOCK_ONLY_FACTOR_KEYS`. Import its lookback loader, map, and builder.

- [ ] **Step 4: Add the post-write derived stage**

Add `_run_stock_value_normalized_post_write` after the raw-factor save and before the existing growth normalized stage. It must:

- select only missing/stale derived factor keys from `factor_plan_df`;
- calculate one month at a time;
- call the builder without a stock-code subset so the full A-share cross-section is always loaded;
- filter only output factor keys after calculation;
- reuse the existing factor-partition save function and planned ranges.

- [ ] **Step 5: Add the catalog group**

Insert `stock_value_normalized` after `stock_value_raw`. Its 18 children use the Chinese suffixes `_去极值`, `_百分位`, and `_标准分`; core factors are the six `_标准分` outputs.

- [ ] **Step 6: Run targeted tests and verify GREEN**

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest "ZXW因子\test_stock_value_normalized_factors.py" "ZXW因子\test_stock_value_raw_factors.py" -q
```

Expected: all selected tests pass.

### Task 4: Verify correctness, performance, encoding, and TRACE suppression

**Files:**
- Verify: `ZXW因子/股票价值标准化因子.py`
- Verify: `ZXW因子/ZXW策略技术因子生成.py`
- Verify: `因子分类/factor_catalog.json`

- [ ] **Step 1: Run syntax and JSON checks**

Run `py_compile` on the new module and generator, and parse the catalog with Python using UTF-8.

- [ ] **Step 2: Run the complete factor test suite**

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest "ZXW因子" -q
```

Expected: zero failures.

- [ ] **Step 3: Run a real-data one-month read-only smoke benchmark**

Call `build_stock_value_normalized_factor_bundle` for the latest available month from `D:\database\signal_daily`, without writing results. Report elapsed time, dates, stock count, factor count, and non-null coverage.

- [ ] **Step 4: Confirm TRACE writes remain blocked**

Sample `COUNT(*)`, `MAX(id)` for TRACE rows and WAL size twice around verification. Confirm trigger `block_trace_logs_insert` exists and TRACE count/max do not grow; explain WAL variation separately because non-TRACE logs may legitimately write.

- [ ] **Step 5: Inspect the scoped diff**

Run `git diff --check` and inspect only the new module, its test, generator hunks, and factor catalog. Do not revert or stage unrelated user changes.
