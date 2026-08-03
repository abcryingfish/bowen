# Sector Short-Move Factors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two vectorized, THS-sector-only time-series factors to the ZXW factor generator and frontend catalog.

**Architecture:** Extend the existing `momentum_common` bundle without changing legacy factor formulas. Both new matrices are calculated from the THS close-price submatrix, retain warm-up and invalid-bar `NaN` values through factor-specific merge policies, and use the generator's existing sector-only execution scope.

**Tech Stack:** Python 3.10, Pandas, NumPy, Pytest, JSON

---

### Task 1: Add Failing Formula And Output-Scope Tests

**Files:**
- Modify: `ZXW因子/test_momentum_factor_bundle.py`
- Test: `ZXW因子/test_momentum_factor_bundle.py`

- [ ] **Step 1: Extend the expected bundle names**

Update the expected factor set and catalog assertions with:

```python
"sector_return_zscore_8d_252d",
"sector_ewma_rms_zscore_252d",
```

- [ ] **Step 2: Add a deterministic formula test**

```python
def test_sector_short_move_factors_match_vectorized_formulas() -> None:
    index = pd.date_range("2024-01-01", periods=360, freq="D")
    phase = np.arange(len(index), dtype=float)
    returns = 0.001 + 0.004 * np.sin(phase / 9.0)
    returns[-8:] = 0.018
    close = pd.DataFrame(
        {
            "881001.THS": 100.0 * np.exp(np.cumsum(returns)),
            "000001.SZ": 20.0 * np.exp(np.cumsum(returns * 0.5)),
        },
        index=index,
    )

    factors = build_momentum_factor_bundle(C=close)["factor_dfs"]
    sector_close = close[["881001.THS"]]
    valid_price = sector_close.where(sector_close > 0.0)

    move_8d = np.log(valid_price / valid_price.shift(8))
    move_mean = move_8d.rolling(252, min_periods=120).mean()
    move_std = move_8d.rolling(252, min_periods=120).std()
    expected_move = ((move_8d - move_mean) / move_std.replace(0.0, np.nan)).clip(-3.0, 3.0)

    log_return = np.log(valid_price / valid_price.shift(1))
    ewma_rms = np.sqrt(
        252.0 * log_return.pow(2).ewm(halflife=5, adjust=False, min_periods=1).mean()
    )
    log_rms = np.log(ewma_rms.where(ewma_rms > 0.0))
    rms_mean = log_rms.rolling(252, min_periods=120).mean()
    rms_std = log_rms.rolling(252, min_periods=120).std()
    expected_rms = ((log_rms - rms_mean) / rms_std.replace(0.0, np.nan)).clip(-3.0, 3.0)

    pd.testing.assert_frame_equal(factors["sector_return_zscore_8d_252d"], expected_move)
    pd.testing.assert_frame_equal(factors["sector_ewma_rms_zscore_252d"], expected_rms)
    assert expected_move.iloc[-1, 0] > 0.0
    assert expected_rms.iloc[-1, 0] > 0.0
```

- [ ] **Step 3: Add downside, THS-only, gap, and vectorization assertions**

Construct a second sector whose final eight returns are `-0.018`, assert its move Z-score is negative and its RMS Z-score is positive. Add a middle invalid bar and assert both output matrices preserve `NaN` there after `compute_bundles_with_valid_bar`. Parse `build_momentum_factor_bundle` with `ast` and assert it contains no `For` or `AsyncFor` nodes.

- [ ] **Step 4: Run the tests and verify RED**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest 'ZXW因子/test_momentum_factor_bundle.py' -q
```

Expected: FAIL because the two new factor keys do not exist.

### Task 2: Implement Both Vectorized Factors

**Files:**
- Modify: `ZXW因子/板块动量策略常用因子.py`
- Test: `ZXW因子/test_momentum_factor_bundle.py`

- [ ] **Step 1: Add constants and lookback entries**

```python
_SECTOR_MOVE_WINDOW = 8
_SECTOR_EWMA_RMS_HALFLIFE = 5
_SECTOR_SHORT_ZSCORE_WINDOW = 252
_SECTOR_SHORT_ZSCORE_MIN_PERIODS = 120
_SECTOR_SHORT_HISTORY_CALENDAR_DAYS = 420
```

Add both English keys to `FACTOR_LOOKBACK_DAYS` with value `_SECTOR_SHORT_HISTORY_CALENDAR_DAYS` and add both Chinese/English pairs to `get_factor_catalog()`.

- [ ] **Step 2: Calculate the 8-day signed move matrix**

After selecting `sector_close`, add:

```python
sector_price = sector_close.where(sector_close > 0.0)
move_8d = np.log(sector_price / sector_price.shift(_SECTOR_MOVE_WINDOW))
move_mean = move_8d.rolling(
    window=_SECTOR_SHORT_ZSCORE_WINDOW,
    min_periods=_SECTOR_SHORT_ZSCORE_MIN_PERIODS,
).mean()
move_std = move_8d.rolling(
    window=_SECTOR_SHORT_ZSCORE_WINDOW,
    min_periods=_SECTOR_SHORT_ZSCORE_MIN_PERIODS,
).std()
sector_return_zscore = (
    (move_8d - move_mean) / move_std.replace(0.0, np.nan)
).clip(lower=-3.0, upper=3.0).where(sector_close.notna())
```

- [ ] **Step 3: Calculate the directionless EWMA-RMS matrix**

```python
sector_log_return = np.log(sector_price / sector_price.shift(1))
sector_ewma_rms = np.sqrt(
    252.0
    * sector_log_return.pow(2).ewm(
        halflife=_SECTOR_EWMA_RMS_HALFLIFE,
        adjust=False,
        min_periods=1,
    ).mean()
)
sector_log_ewma_rms = np.log(sector_ewma_rms.where(sector_ewma_rms > 0.0))
ewma_rms_mean = sector_log_ewma_rms.rolling(
    window=_SECTOR_SHORT_ZSCORE_WINDOW,
    min_periods=_SECTOR_SHORT_ZSCORE_MIN_PERIODS,
).mean()
ewma_rms_std = sector_log_ewma_rms.rolling(
    window=_SECTOR_SHORT_ZSCORE_WINDOW,
    min_periods=_SECTOR_SHORT_ZSCORE_MIN_PERIODS,
).std()
sector_ewma_rms_zscore = (
    (sector_log_ewma_rms - ewma_rms_mean) / ewma_rms_std.replace(0.0, np.nan)
).clip(lower=-3.0, upper=3.0).where(sector_close.notna())
```

- [ ] **Step 4: Expose names and merge policies**

Add both matrices to `factor_dfs`, both names to `factor_name_map`, and give each this independent policy:

```python
{
    "preserve_columns": True,
    "preserve_nan": True,
}
```

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run the Task 1 command. Expected: all tests in `test_momentum_factor_bundle.py` pass.

### Task 3: Connect ZXW Automatic Planning And Sector Scope

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py`
- Modify: `ZXW因子/test_factor_auto_plan_valid_values.py`

- [ ] **Step 1: Write failing planner tests**

Parameterize the existing sector-volatility planner tests over these keys:

```python
[
    "sector_volatility_zscore_20d_252d",
    "sector_return_zscore_8d_252d",
    "sector_ewma_rms_zscore_252d",
]
```

For every key assert:

```python
assert plan["scope"] == "sector_market"
assert plan["codes"] == ["881001.THS", "881002.THS"]
assert plan["query_start"] == plan["plan_start"] - pd.Timedelta(days=440)
assert planner["_momentum_compute_paths"]({factor_key}) == (True, False)
```

- [ ] **Step 2: Run the planner tests and verify RED**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest 'ZXW因子/test_factor_auto_plan_valid_values.py' -q
```

Expected: FAIL because both keys are not registered as sector-only market factors.

- [ ] **Step 3: Register both factor keys**

Add both English keys to `NON_STOCK_FACTOR_KEYS` and `SECTOR_ONLY_MARKET_FACTOR_KEYS`. Do not add them to `THS_ONLY_FACTOR_KEYS`, because they use sector market prices rather than stock-to-sector aggregation.

- [ ] **Step 4: Verify planner tests GREEN**

Run the Task 3 test command. Expected: pass.

### Task 4: Add Frontend Classification Coverage

**Files:**
- Modify: `因子分类/factor_catalog.json`
- Modify: `可视化/test_market_data_service_pure_technical_catalog.py`

- [ ] **Step 1: Add a failing catalog normalization test**

Call `_normalize_factor_catalog` with an available-factor list containing the two Chinese names and assert the normalized `momentum_common` group contains both.

- [ ] **Step 2: Run the frontend service test and verify RED**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest '可视化/test_market_data_service_pure_technical_catalog.py' -q
```

Expected: FAIL because the JSON catalog does not contain the new names.

- [ ] **Step 3: Add both names to the existing group**

Append these values to the `momentum_common.children` array, leaving the core factor unchanged:

```json
"板块8日涨跌幅ZScore_252日",
"板块EWMA_RMS移动强度ZScore_252日"
```

- [ ] **Step 4: Verify frontend test GREEN**

Run the Task 4 command. Expected: pass.

### Task 5: Full Verification Without Production Generation

**Files:**
- Verify: `ZXW因子/板块动量策略常用因子.py`
- Verify: `ZXW因子/ZXW策略技术因子生成.py`
- Verify: `因子分类/factor_catalog.json`

- [ ] **Step 1: Run all ZXW factor tests**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest 'ZXW因子' -q
```

Expected: all tests pass.

- [ ] **Step 2: Run the relevant visualization test**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest '可视化/test_market_data_service_pure_technical_catalog.py' -q
```

Expected: pass.

- [ ] **Step 3: Verify encoding, JSON, syntax, and whitespace**

Read all modified text as UTF-8, parse both Python files with `ast.parse`, parse `factor_catalog.json` with `json.loads`, and run:

```powershell
git diff --check -- 'ZXW因子/板块动量策略常用因子.py' 'ZXW因子/ZXW策略技术因子生成.py' 'ZXW因子/test_momentum_factor_bundle.py' 'ZXW因子/test_factor_auto_plan_valid_values.py' '因子分类/factor_catalog.json' '可视化/test_market_data_service_pure_technical_catalog.py'
```

Expected: exit code 0 and no output.

- [ ] **Step 4: Confirm production data remains untouched**

Verify no new `factor=板块8日涨跌幅ZScore_252日` or `factor=板块EWMA_RMS移动强度ZScore_252日` directory was created under `D:\database\signal_daily` during implementation.
