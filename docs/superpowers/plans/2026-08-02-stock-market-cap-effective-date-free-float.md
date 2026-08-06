# Stock Market Cap Effective Date and Free Float Factor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Capital records effective only after both report and announcement dates, and add the stock-only raw factor `自由流通市值` without creating style portfolios.

**Architecture:** Keep `工具/获得股票日频换手率.py` as the single derivation layer for share-capital market values. It writes a version-complete `qmt_turnover_data` schema, and `ZXW因子/股票市场数据因子.py` only validates, reads, and pivots those fields into the existing bundle contract.

**Tech Stack:** Python 3.10, pandas, Polars, DuckDB, pytest, Parquet, JSON catalog.

---

### Task 1: Capital Effective-Date Alignment

**Files:**
- Create: `工具/test_获得股票日频换手率.py`
- Modify: `工具/获得股票日频换手率.py`

- [ ] **Step 1: Write the failing effective-date test**

Load the script with `importlib.util.spec_from_file_location`, build one stock with a baseline Capital record plus one delayed announcement and one pre-announced future report, and assert the matched capital sequence is `100 -> 200 -> 200 -> 300` on dates before/at the two effective dates.

```python
def test_capital_becomes_effective_after_both_report_and_announcement_dates():
    daily = pd.DataFrame({
        "htsc_code": ["000001.SZ"] * 4,
        "time": pd.to_datetime(["2026-01-09", "2026-01-10", "2026-01-19", "2026-01-20"]),
        "open": [10.0] * 4,
        "high": [10.0] * 4,
        "low": [10.0] * 4,
        "close": [10.0] * 4,
        "volume": [1000.0] * 4,
        "value": [10000.0] * 4,
    })
    capital = pd.DataFrame({
        "htsc_code": ["000001.SZ"] * 3,
        "report_date": pd.to_datetime(["2026-01-01", "2026-01-05", "2026-01-20"]),
        "announce_date": pd.to_datetime(["2026-01-01", "2026-01-10", "2026-01-15"]),
        "total_capital": [100.0, 200.0, 300.0],
        "circulating_capital": [80.0, 160.0, 240.0],
        "freeFloatCapital": [60.0, 120.0, 180.0],
    })

    result = module.calculate_turnover_frame(daily, capital)

    assert result["total_capital"].tolist() == [100.0, 200.0, 200.0, 300.0]
    assert result["capital_effective_date"].tolist() == list(
        pd.to_datetime(["2026-01-01", "2026-01-10", "2026-01-10", "2026-01-20"])
    )
```

- [ ] **Step 2: Run the test and verify the old implementation fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest "工具\test_获得股票日频换手率.py" -q
```

Expected: FAIL because the current merge uses `report_date` and does not output `capital_effective_date`.

- [ ] **Step 3: Implement deterministic effective dates**

In `calculate_turnover_frame`:

```python
capital_df["capital_effective_date"] = capital_df[["report_date", "announce_date"]].max(axis=1)
capital_df = capital_df.dropna(subset=["htsc_code", "capital_effective_date"])
capital_df = (
    capital_df.sort_values(
        ["htsc_code", "capital_effective_date", "announce_date", "report_date"],
        na_position="first",
    )
    .drop_duplicates(["htsc_code", "capital_effective_date"], keep="last")
)
```

Change `merge_asof` to use `right_on="capital_effective_date"`, retain `capital_report_date`, `capital_announce_date`, and add `capital_effective_date` to the output schema. Update the module docstring to state the new rule.

- [ ] **Step 4: Run the source-layer test**

Run the command from Step 2. Expected: PASS.

### Task 2: Free-Float Market Value Source Field

**Files:**
- Modify: `工具/test_获得股票日频换手率.py`
- Modify: `工具/获得股票日频换手率.py`
- Modify: `工具/AGENTS.md`

- [ ] **Step 1: Add a failing formula and missing-input test**

Extend the fixture assertions:

```python
assert result["free_float_market_val"].tolist() == [600.0, 1200.0, 1200.0, 1800.0]
assert result["floating_market_val"].tolist() == [800.0, 1600.0, 1600.0, 2400.0]
assert result["total_market_val"].tolist() == [1000.0, 2000.0, 2000.0, 3000.0]
```

Add a second stock/date with `freeFloatCapital = NaN` and assert only `free_float_market_val` is missing while total market value remains valid.

- [ ] **Step 2: Run the test and verify it fails**

Expected: FAIL because `free_float_market_val` is not currently produced.

- [ ] **Step 3: Add the source calculation**

```python
out["free_float_market_val"] = out["close"] * out["freeFloatCapital"]
```

If `close` is unavailable, create all three market-value columns as missing. Add `free_float_market_val` to `keep_cols`, and document the field under the `qmt_turnover_data` contract in `工具/AGENTS.md`.

- [ ] **Step 4: Run the source-layer tests**

Expected: all tests in `工具/test_获得股票日频换手率.py` PASS.

### Task 3: Stock Market Data Bundle Contract

**Files:**
- Modify: `ZXW因子/test_stock_market_data_factors.py`
- Modify: `ZXW因子/股票市场数据因子.py`

- [ ] **Step 1: Extend the failing bundle tests**

Update `EXPECTED_FACTOR_MAP`:

```python
EXPECTED_FACTOR_MAP = {
    "总市值": "total_market_value",
    "流通市值": "floating_market_value",
    "自由流通市值": "free_float_market_value",
    "换手率": "turnover_rate",
}
```

Add `free_float_market_val` to every valid test source and assert its pivoted value. Add a source without that column and assert a Chinese `ValueError` containing `qmt_turnover_data 缺少字段` and `free_float_market_val`.

- [ ] **Step 2: Run the focused bundle tests and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest "ZXW因子\test_stock_market_data_factors.py" -q
```

Expected: FAIL because the fourth factor and source validation do not exist.

- [ ] **Step 3: Implement the fourth factor and schema validation**

Add mappings:

```python
"自由流通市值": "free_float_market_value"
"free_float_market_value": "free_float_market_val"
```

Before querying data, inspect the Parquet schema through DuckDB and raise a stable Chinese `ValueError` when any required source field is absent. Extend the SELECT and pivot loop through the existing mapping rather than adding a separate computation path.

- [ ] **Step 4: Run the focused tests**

Expected: all stock market data factor tests PASS.

### Task 4: Generator, Catalog, and Frontend Discovery

**Files:**
- Modify: `ZXW因子/test_stock_market_data_catalog.py`
- Create: `可视化/test_market_data_service_stock_market_catalog.py`
- Modify: `ZXW因子/ZXW策略技术因子生成.py`
- Modify: `因子分类/factor_catalog.json`

- [ ] **Step 1: Add failing catalog and scope expectations**

Require the catalog children to equal:

```python
["总市值", "流通市值", "自由流通市值", "换手率"]
```

Build the planner test with `factor_en="free_float_market_value"` and assert it uses `scope="stock_market"` with stock codes only. Add a frontend service test patterned after `test_market_data_service_stock_fundamental_catalog.py` and require the same four children.

- [ ] **Step 2: Run the catalog tests and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest "ZXW因子\test_stock_market_data_catalog.py" "可视化\test_market_data_service_stock_market_catalog.py" -q
```

Expected: FAIL until the generator and JSON catalog expose the new factor.

- [ ] **Step 3: Register the factor**

Add `free_float_market_value` to both the primary and fallback `STOCK_ONLY_FACTOR_KEYS` definitions. Add `自由流通市值` to the existing `stock_market_data` group's `core_factors` and `children`, preserving all unrelated user modifications in `factor_catalog.json`.

- [ ] **Step 4: Run the catalog tests**

Expected: PASS, and the frontend service returns the new child through existing automatic discovery.

### Task 5: Regression and Real-Data Audit

**Files:**
- No additional code files unless a test exposes a root-cause bug.

- [ ] **Step 1: Run focused and neighboring test suites**

```powershell
.\.venv\Scripts\python.exe -m pytest "工具\test_获得股票日频换手率.py" "ZXW因子\test_stock_market_data_factors.py" "ZXW因子\test_stock_market_data_catalog.py" "ZXW因子\test_factor_auto_plan_valid_values.py" "ZXW因子\test_factor_batch_watermark.py" "可视化\test_market_data_service_stock_market_catalog.py" -q
```

Expected: all selected tests PASS. Existing pandas warnings may remain but no new warning class should be introduced.

- [ ] **Step 2: Run UTF-8 and syntax checks**

```powershell
.\.venv\Scripts\python.exe -m py_compile "工具\获得股票日频换手率.py" "ZXW因子\股票市场数据因子.py" "ZXW因子\ZXW策略技术因子生成.py"
.\.venv\Scripts\python.exe -c "import json, pathlib; json.loads(pathlib.Path(r'因子分类/factor_catalog.json').read_text(encoding='utf-8')); print('catalog utf-8 ok')"
```

Expected: exit code 0 and `catalog utf-8 ok`.

- [ ] **Step 3: Audit real Capital events without writing data**

Use DuckDB to sample records from all three relationships: announcement after report, announcement before report, and equal dates. Recompute `greatest(report_date, announce_date)` and confirm no joined daily record uses the row before that date.

- [ ] **Step 4: Check repository diff and TRACE write protection**

Verify only intended hunks changed, preserve unrelated dirty-worktree edits, and recheck that TRACE inserts do not increase `MAX(id)` or the WAL in `codex/logs_2.sqlite` if that database exists.

### Task 6: Historical Data Migration

**Files:**
- Data output: `D:\database\qmt_turnover_data\year=YYYY\month=MM\merged.parquet`
- Data output after separate generation: `D:\database\signal_daily\factor=总市值|流通市值|自由流通市值|换手率\...`

- [ ] **Step 1: Resolve and report exact write scope**

Read the latest source date and list the affected 2010-to-current monthly partitions. Confirm disk space and that the requested full interval is explicit before starting the rewrite.

- [ ] **Step 2: Rebuild the derived market-data source**

```powershell
.\.venv\Scripts\python.exe "工具\获得股票日频换手率.py" --start 2010-01-01 --end 2026-07-30
```

Expected: all touched monthly `merged.parquet` files contain `capital_effective_date` and `free_float_market_val`. The merge must make the newly generated rows win for identical `htsc_code + time` keys.

- [ ] **Step 3: Validate source coverage and formulas**

Check row counts, min/max dates, duplicate `htsc_code + time`, null rates, and sampled equality for all three market values. Confirm no future Capital record is matched.

- [ ] **Step 4: Plan signal replacement separately before destructive writes**

Existing total/float/turnover signal partitions and watermarks may prevent historical recomputation or may preserve old values. Do not delete or overwrite those partitions until their backup path, replacement semantics, and affected factors are explicitly reviewed. The new free-float factor can be generated after the source rebuild because it has no old partitions.
