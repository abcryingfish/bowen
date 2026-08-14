# Growth Coverage Penalty Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the growth model's multiple completeness gates with one weighted completeness threshold and add an explicit missing-data penalty score.

**Architecture:** Extend the pure computation in `股票成长标准化因子.py`; keep raw-data loading and post-write orchestration unchanged. Calculate per-pillar completeness beside each pillar score, use completeness-adjusted pillar weights for the composite, then expose four additional factor matrices and catalog entries.

**Tech Stack:** Python 3.10, pandas, NumPy, SciPy, pytest, JSON factor catalog.

---

### Task 1: Lock the revised scoring behavior with failing tests

**Files:**
- Modify: `ZXW因子/test_stock_growth_normalized_factors.py`

- [ ] **Step 1: Add tests for one-input pillars and weighted completeness**

Create a one-date, multi-stock fixture where one stock has only one scale input, all profit inputs, half the quality inputs, and no research inputs. Assert:

```python
assert factor_dfs["growth_scale_score"].notna()
assert factor_dfs["growth_data_completeness"].loc[date, code] == pytest.approx(
    (1 / 3) * 0.30 + 1.0 * 0.35 + (2 / 4) * 0.25
)
```

- [ ] **Step 2: Add tests for the 40% gate and penalty formula**

Assert that a stock below `Q=0.40` has missing composite outputs. For an eligible stock assert:

```python
base = factor_dfs["growth_style_percentile"].loc[date, code] * 100
penalty = base * 0.5 * (1 - completeness)
assert factor_dfs["growth_style_base_score"].loc[date, code] == pytest.approx(base)
assert factor_dfs["growth_data_missing_penalty"].loc[date, code] == pytest.approx(penalty)
assert factor_dfs["growth_style_score"].loc[date, code] == pytest.approx(max(0, base - penalty))
```

- [ ] **Step 3: Run the focused tests and observe the expected failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q ZXW因子\test_stock_growth_normalized_factors.py
```

Expected: FAIL because the four new factor keys and revised one-input pillar behavior are absent.

### Task 2: Implement completeness-adjusted composite scoring

**Files:**
- Modify: `ZXW因子/股票成长标准化因子.py`
- Test: `ZXW因子/test_stock_growth_normalized_factors.py`

- [ ] **Step 1: Add scoring constants and factor names**

Add:

```python
MIN_GROWTH_DATA_COMPLETENESS = 0.40
MISSING_DATA_PENALTY_RATE = 0.50
```

Register:

```python
"成长数据完整度": "growth_data_completeness"
"成长风格基础分": "growth_style_base_score"
"成长数据缺失扣分": "growth_data_missing_penalty"
"成长风格评分": "growth_style_score"
```

- [ ] **Step 2: Return pillar scores and completeness separately**

Calculate each pillar with every available standardized input and calculate:

```python
pillar_completeness = valid_count / len(weights)
```

A pillar with zero valid inputs remains missing; a pillar with one or more valid inputs is computed.

- [ ] **Step 3: Build the completeness-adjusted composite**

For each pillar:

```python
effective_weight = base_weight * pillar_completeness
```

Calculate the weighted composite using effective weights. Mask the composite wherever weighted completeness is below `0.40`.

- [ ] **Step 4: Build the four new output matrices**

Calculate:

```python
completeness_output = weighted_completeness * 100
base_score = composite_percentile * 100
missing_penalty = base_score * 0.5 * (1 - weighted_completeness)
final_score = (base_score - missing_penalty).clip(0, 100)
```

Mask base score, penalty and final score with the same eligibility mask as the composite.

- [ ] **Step 5: Run focused tests to verify green**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q ZXW因子\test_stock_growth_normalized_factors.py
```

Expected: all focused tests pass.

### Task 3: Expose new factors in the frontend catalog

**Files:**
- Modify: `因子分类/factor_catalog.json`
- Modify: `ZXW因子/test_stock_growth_normalized_factors.py`

- [ ] **Step 1: Extend the catalog contract test**

The existing catalog assertion uses `DERIVED_FACTOR_NAME_MAP`; after Task 2 it must fail until the frontend group includes all four new Chinese factor names.

- [ ] **Step 2: Add new factors to the growth normalized group**

Add all four factors to `children`; add `成长风格评分` and `成长数据完整度` to `core_factors`.

- [ ] **Step 3: Validate JSON and run catalog tests**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import json,pathlib; json.loads(pathlib.Path(r'因子分类\factor_catalog.json').read_text(encoding='utf-8')); print('JSON OK')"
.\.venv\Scripts\python.exe -m pytest -q ZXW因子\test_stock_growth_normalized_factors.py 可视化\test_market_data_service_stock_fundamental_catalog.py
```

Expected: JSON OK and all tests pass.

### Task 4: Regression and real-data verification

**Files:**
- Verify: `ZXW因子/股票成长标准化因子.py`
- Verify: `ZXW因子/ZXW策略技术因子生成.py`
- Verify: `因子分类/factor_catalog.json`

- [ ] **Step 1: Compile changed Python files**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile ZXW因子\股票成长标准化因子.py ZXW因子\ZXW策略技术因子生成.py
```

Expected: exit code 0.

- [ ] **Step 2: Run the complete factor test suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q ZXW因子
```

Expected: all tests pass; existing third-party-style indicator warnings may remain.

- [ ] **Step 3: Run a read-only 2026-08-03 smoke test**

Build the normalized bundle from `D:\database\signal_daily` and assert:

```python
assert len(result["factor_dfs"]) == 35
assert completeness.dropna().between(0, 100).all()
assert penalty.dropna().ge(0).all()
assert penalty.dropna().le(base_score.dropna() * 0.5).all()
assert final_score.dropna().between(0, 100).all()
```

Report eligible coverage and compare it with the expected approximately 4,988 / 5,214.

- [ ] **Step 4: Check formatting and TRACE logging state**

Run `git diff --check` for changed files. Query `logs_2.sqlite` twice to verify the TRACE trigger remains installed, `MAX(id)` for TRACE does not increase, and the WAL size stays zero.
