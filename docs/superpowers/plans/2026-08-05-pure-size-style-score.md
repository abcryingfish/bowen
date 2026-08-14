# Pure Size Style Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate daily large-cap and small-cap pure market-cap scores from the saved `ln_自由流通市值` cross-section.

**Architecture:** Add a self-contained post-write derived bundle that loads the complete monthly A-share factor partition, ranks each daily cross-section, and returns two complementary score frames. Register it beside the existing value/growth/dividend post-write bundles and expose both Chinese factor names in the frontend catalog.

**Tech Stack:** Python 3.10, pandas, NumPy, PyArrow Parquet, pytest, JSON.

---

### Task 1: Pure size scoring module

**Files:**
- Create: `ZXW因子/股票纯市值风格评分.py`
- Create: `ZXW因子/test_stock_size_style_pure_score.py`

- [ ] **Step 1: Write failing scoring tests**

Create tests that import `build_size_style_score_bundle` and assert average-rank scoring, tie handling, non-finite preservation, the 100-stock minimum, strict complementarity, and input validation.

```python
result = build_size_style_score_bundle(raw, min_valid_count=4)
large = result["factor_dfs"]["large_cap_style_score_pure"]
small = result["factor_dfs"]["small_cap_style_score_pure"]
assert large.loc[date, codes[:4]].tolist() == pytest.approx([12.5, 50.0, 50.0, 87.5])
assert (large + small).dropna().to_numpy() == pytest.approx(100.0)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest ZXW因子\test_stock_size_style_pure_score.py -v`

Expected: collection fails because `股票纯市值风格评分` does not exist.

- [ ] **Step 3: Implement minimal scoring API**

Implement constants `BUNDLE_ID`, `INPUT_FACTOR_NAME`, `INPUT_FACTOR_KEY`, `FACTOR_NAME_MAP`, `DEFAULT_MIN_VALID_STOCKS`; catalog/lookback helpers; and:

```python
def build_size_style_score_bundle(
    ln_free_float_market_value: pd.DataFrame,
    *,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
) -> dict[str, object]:
    numeric = ln_free_float_market_value.apply(pd.to_numeric, errors="coerce")
    numeric = numeric.replace([np.inf, -np.inf], np.nan)
    valid_counts = numeric.notna().sum(axis=1)
    ranks = numeric.rank(axis=1, method="average", na_option="keep")
    large = ranks.sub(0.5).div(valid_counts.replace(0, np.nan), axis=0) * 100.0
    large.loc[valid_counts < min_valid_count, :] = np.nan
    small = 100.0 - large
```

- [ ] **Step 4: Run scoring tests and verify GREEN**

Run the Task 1 pytest command. Expected: scoring tests pass; loader/integration tests remain pending.

### Task 2: Monthly factor loader

**Files:**
- Modify: `ZXW因子/股票纯市值风格评分.py`
- Modify: `ZXW因子/test_stock_size_style_pure_score.py`

- [ ] **Step 1: Write failing loader tests**

Create temporary `factor=ln_自由流通市值/year=2026/month=08` partitions and assert `merged.parquet + sorted part_*.parquet` loading, latest-part overwrite, date filtering, and rejection of `.THS`/`.BJ` codes.

- [ ] **Step 2: Run the loader test and verify RED**

Expected: failure because `load_ln_free_float_market_value` and the disk bundle entry point do not exist.

- [ ] **Step 3: Implement loader and disk bundle**

Implement `load_ln_free_float_market_value` and `build_stock_size_style_pure_bundle`. Accept only `\d{6}.SH|SZ`, normalize dates/codes/values, preserve file order in `_file_order`, fail when any requested month has no partition, and pivot to one wide frame.

- [ ] **Step 4: Run tests and verify GREEN**

Run the full new test file. Expected: all module and loader tests pass.

### Task 3: Generator and catalog integration

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py`
- Modify: `因子分类/factor_catalog.json`
- Modify: `ZXW因子/test_stock_size_style_pure_score.py`

- [ ] **Step 1: Write failing integration contract test**

Assert the generator contains the `stock_size_style_pure` loader/module/selected/post-write registrations and `_run_stock_size_style_pure_post_write`, and the JSON group has exactly the two approved Chinese names.

- [ ] **Step 2: Run integration test and verify RED**

Expected: failure because generator/catalog registrations are absent.

- [ ] **Step 3: Register and invoke the post-write bundle**

Add imports, `SELECTED_BUNDLES`, `BUNDLE_LOOKBACK_LOADERS`, `BUNDLE_MODULE_NAMES`, and `POST_WRITE_DERIVED_BUNDLES` entries. Add a monthly post-write runner patterned after `_run_stock_value_model_post_write`, filtering plan rows to the two output keys and saving with the existing partition writer.

- [ ] **Step 4: Add frontend factor group**

Add `stock_size_style_pure`, with both names in `core_factors` and `children`, without modifying existing groups.

- [ ] **Step 5: Run integration test and verify GREEN**

Run the full new test file. Expected: all tests pass.

### Task 4: Verification and real-data generation

**Files:**
- Verify: `ZXW因子/股票纯市值风格评分.py`
- Verify: `ZXW因子/ZXW策略技术因子生成.py`
- Verify: `因子分类/factor_catalog.json`
- Output: `D:\database\signal_daily\factor=大市值风格评分（纯市值）/...`
- Output: `D:\database\signal_daily\factor=小市值风格评分（纯市值）/...`

- [ ] **Step 1: Run focused and related tests**

Run the new tests plus stock market data and existing post-write factor tests.

- [ ] **Step 2: Compile and parse**

Run `py_compile` for both Python files and parse `factor_catalog.json` as UTF-8 JSON.

- [ ] **Step 3: Generate from real saved input**

Use the new disk bundle and existing partition writer-compatible long format to backfill the approved period from available `ln_自由流通市值` data without changing the raw input.

- [ ] **Step 4: Validate real outputs**

Check latest date, non-null count, min/max, unique keys, exact complementarity, and confirm both output factor partitions exist.

- [ ] **Step 5: Review the scoped diff**

Confirm only the new module/test/plan and intended local additions to generator/catalog belong to this task; do not stage or revert unrelated user changes.
