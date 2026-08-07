# 风格等权指数账本 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (recommended). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the cash/share style-monitor simulation with a post-factor-generation, T+1-effective, back-adjusted, no-fee equal-weight return index and rebuild the ledger from 2016.

**Architecture:** Add a dedicated style-monitor index module imported only after `ZXW策略技术因子生成.py` finishes saving all factors. The module reads saved scores and the same back-adjustment source used by the generator, computes high/low target weights and daily index returns, and persists weight snapshots plus index NAVs. Existing API routes remain available but return index-compatible payloads with no cash, shares, or trade commissions.

**Tech Stack:** Python 3.10, pandas, DuckDB, Parquet, pytest, browser JavaScript, UTF-8.

---

### Task 1: Lock equal-weight and T+1 semantics with failing tests

**Files:**
- Create: `backtrader/tests/style_portfolio_monitor/test_equal_weight_index.py`
- Modify: `backtrader/tests/style_portfolio_monitor/test_portfolio.py`

- [ ] **Step 1: Add a failing test for T+1 activation**

Create a three-day score/price fixture where the score changes on day 2. Assert that day 2 return uses day 1 weights and day 3 return uses day 2's new weights. The expected calculation must be:

```python
assert nav.loc[date(2026, 1, 2)] == pytest.approx(100.0 * 1.10)
assert nav.loc[date(2026, 1, 3)] == pytest.approx(110.0 * 0.90)
```

The test must fail because the new index builder does not exist.

- [ ] **Step 2: Add a failing test for equal-weight normalization**

Use three selected stocks and assert each target weight is `1 / 3`, the weight sum is exactly 1 within `1e-12`, and no cash, shares, commission, or lot-size fields are returned.

- [ ] **Step 3: Add a failing test for score direction and selection cap**

Assert high selects descending scores, low selects ascending scores, ties use code order, and 20% selection is `ceil(count * 0.20)` capped at 200.

- [ ] **Step 4: Run the focused tests and verify RED**

Run:

```powershell
$env:PYTHONPATH = (Resolve-Path 'backtrader').Path
.venv\Scripts\python.exe -m pytest backtrader\tests\style_portfolio_monitor\test_equal_weight_index.py -q
```

Expected: collection or import failure for the new index builder, not a fixture error.

### Task 2: Implement the dedicated adjusted equal-weight index module

**Files:**
- Create: `backtrader/models/style_portfolio_monitor/equal_weight_index.py`
- Modify: `backtrader/tests/style_portfolio_monitor/test_equal_weight_index.py`

- [ ] **Step 1: Implement pure target selection and weight calculation**

Expose `select_target_weights(snapshot, ratio=0.20, max_count=200)` returning `{"high": {code: weight}, "low": {code: weight}}`. Drop missing scores, sort high descending and low ascending by `(score, htsc_code)`, apply `ceil(len(valid) * ratio)`, cap at 200, and normalize each leg to a weight sum of 1.

- [ ] **Step 2: Implement the T+1 index calculation**

Expose `build_equal_weight_index(score_frame, adjusted_close, valid_bar, rebalance_dates, ratio=0.20, max_count=200)`. For each date, create target weights only after the T-day score is known; apply them from the next valid market date. Calculate each daily return from adjusted close ratios, use zero return for unchanged/forward-filled suspended prices, and start each leg at 100. Return index series, target weight snapshots, coverage diagnostics, and rebalance dates. Do not accept or produce cash, shares, commission, or trade rows.

- [ ] **Step 3: Add explicit adjusted-price loading with the approved fallback**

Implement `load_adjusted_close(...)` in the same dedicated module. Primary path uses `adj_factor_daily` with DuckDB and multiplies raw close by `adj_factor`. If the primary source is unavailable, copy the existing `wide_xdy` ratio-adjustment logic into this dedicated module rather than importing generator internals. A missing factor for a real bar must raise a Chinese `StyleDataError`; never substitute an unadjusted factor of 1.0. Add a parity test for a temporary Parquet fixture covering both paths.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the Task 1 command. Expected: all equal-weight, cap, T+1, zero-fee, and adjusted-price parity tests pass.

### Task 3: Persist index data and adapt the style-monitor API

**Files:**
- Modify: `backtrader/models/style_portfolio_monitor/repository.py`
- Modify: `backtrader/models/style_portfolio_monitor/query.py`
- Modify: `backtrader/models/style_portfolio_monitor/service.py`
- Modify: `backtrader/tests/style_portfolio_monitor/test_repository.py`
- Modify: `backtrader/tests/style_portfolio_monitor/test_queries.py`
- Modify: `backtrader/tests/style_portfolio_monitor/test_service.py`

- [ ] **Step 1: Add index-native DuckDB tables**

Create `index_daily` with `(model_version, leg, trade_date)` primary key, `index_value`, `daily_return`, `cumulative_return`, `rebalanced`, `factor_coverage`, `valid_count`, `valid_price_coverage`, `status`, and `status_message`. Create `index_weight_daily` with `(model_version, leg, trade_date, htsc_code)` primary key, `score`, `rank`, `target_weight`, and `effective_weight`. Keep model definitions and run state, but stop writing cash, shares, commissions, or trade logs for the new index path.

- [ ] **Step 2: Add repository write/read methods for index payloads**

Implement one transaction that deletes and rewrites only the requested model/leg/date rows, then writes `index_daily` and `index_weight_daily`. Enforce weight sum, primary-key uniqueness, and no monetary fields before commit.

- [ ] **Step 3: Adapt curve, summary, positions, and trades API payloads**

Curves and summaries read `index_daily`. Positions return `score`, `rank`, `target_weight`, and `effective_weight`; the UI must not display shares, price, trade value, or commission. The trades endpoint returns rebalance snapshots or an explicit Chinese message that the index has no cash trades.

- [ ] **Step 4: Add regression tests and run them RED before implementation**

Add assertions that T-day scores do not affect T-day return, index NAV starts at 100, no commission is deducted, and API payloads contain no cash/share/trade fields. Run the three style-monitor test files and confirm failures identify the old simulation contract.

- [ ] **Step 5: Implement the minimal repository/service/query changes and run GREEN**

Run:

```powershell
$env:PYTHONPATH = (Resolve-Path 'backtrader').Path
.venv\Scripts\python.exe -m pytest backtrader\tests\style_portfolio_monitor\test_equal_weight_index.py backtrader\tests\style_portfolio_monitor\test_repository.py backtrader\tests\style_portfolio_monitor\test_queries.py backtrader\tests\style_portfolio_monitor\test_service.py -q
```

Expected: zero failures and no cash/share simulation assertions.

### Task 4: Add post-generator import hook, rebuild, and verify the page

**Files:**
- Create: `backtrader/models/style_portfolio_monitor/generator_hook.py`
- Modify: `ZXW因子/ZXW策略技术因子生成.py`
- Modify: `可视化/模型有效性/model_validity.js`
- Modify: `可视化/模型有效性/index.html`
- Modify: `backtrader/tests/style_portfolio_monitor/test_generator_hook.py`

- [ ] **Step 1: Add a failing hook-order contract test**

Assert the generator imports `generator_hook` only after `save_factor_dfs_to_factor_partitioned_parquet(...)` and calls `run_after_factor_generation(...)` exactly once. Assert the hook receives the factor base path and generator end date, not an in-memory batch matrix.

- [ ] **Step 2: Implement the dedicated import hook**

Expose `run_after_factor_generation(signal_base_dir, market_base_dir, through_date=None, rebuild=False)`. It must initialize the index service, detect the latest common score/adjusted-price date, run from `2016-01-01` when `rebuild=True`, and return a structured Chinese status. A failed index update raises after printing the error; it must not silently mark factor generation as fully successful.

- [ ] **Step 3: Wire the hook after all factor and derived-factor saves**

Import the hook at the final executable stage of `ZXW策略技术因子生成.py`, after every post-write derived bundle completes. Do not add strategy code to any factor batch or duplicate existing factor calculations.

- [ ] **Step 4: Add benchmark and diagnostics to the page**

Extend the summary/curves payload with same-range index benchmark series from local index data. Display high/low holdings count, valid-price coverage, and latest rebalance date. Remove cash/share/commission columns from the detail drawer and show a Chinese message for the no-trade index model.

- [ ] **Step 5: Run full focused verification before destructive rebuild**

Run:

```powershell
$env:PYTHONPATH = (Resolve-Path 'backtrader').Path
.venv\Scripts\python.exe -m pytest ZXW因子\test_stock_momentum_style_score.py backtrader\tests\style_portfolio_monitor -q
.venv\Scripts\python.exe -m py_compile backtrader\models\style_portfolio_monitor\equal_weight_index.py backtrader\models\style_portfolio_monitor\generator_hook.py
git diff --check
```

- [ ] **Step 6: Delete the old ledger after exact-path validation**

Resolve `D:\database\style_portfolio_monitor\style_monitor.duckdb` to an absolute path and verify it equals the intended file. Delete only that file, confirm it no longer exists, and do not remove the directory or any other database.

- [ ] **Step 7: Rebuild from 2016 through the latest common date**

Run the dedicated hook with `rebuild=True`. Save the rebuild log and verify every registered model has both legs, every index starts at 100, and latest dates match the common source date.

- [ ] **Step 8: Validate real-data invariants and browser/API output**

Query DuckDB for duplicate primary keys, weight sums, non-finite index values, unintended fee fields, and T+1 rebalance dates. Query the API and load `http://127.0.0.1:8086/模型有效性/index.html`; verify curves, benchmark, positions, and no-trade messaging at desktop and mobile widths.
