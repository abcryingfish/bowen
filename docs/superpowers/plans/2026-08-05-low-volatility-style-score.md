# Low Volatility Style Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a daily `0-100` low-volatility style score from seven saved stock risk factors.

**Architecture:** Add a self-contained post-write derived bundle that loads complete monthly source partitions, restricts every component rank to one complete沪深 stock cross-section, builds four risk-dimension scores, and combines them with the approved weights. Register the derived bundle beside the existing raw low-volatility bundle and expose the output in the UTF-8 factor catalog.

**Tech Stack:** Python 3.10, pandas, NumPy, PyArrow Parquet, pytest, JSON.

---

### Task 1: Cross-sectional low-volatility scoring core

**Files:**
- Create: `ZXW因子/股票低波风格评分.py`
- Create: `ZXW因子/test_stock_low_volatility_style_score.py`

- [ ] **Step 1: Write failing direction, weight, completeness, and tie tests**

Create controlled daily factor frames for all seven inputs and import:

```python
from 股票低波风格评分 import (
    BUNDLE_ID,
    FACTOR_NAME_MAP,
    build_low_volatility_style_score_bundle,
    get_factor_catalog,
)
```

Assert the bundle id is `stock_low_volatility_style_score`, the output key is `low_volatility_style_score`, lower values for all risk metrics produce higher scores, ties receive equal scores, and the result remains inside `0-100`. Use `min_valid_count=4` for compact fixtures.

Add a weight-isolation fixture and assert the effective raw-factor weights are:

```python
EXPECTED_EFFECTIVE_WEIGHTS = {
    "annual_vol_20d": 0.05,
    "annual_vol_60d": 0.125,
    "annual_vol_252d": 0.075,
    "downside_vol_20d": 0.075,
    "downside_vol_60d": 0.175,
    "max_drawdown_60d": 0.25,
    "atr_volatility_14d": 0.25,
}
```

Assert any missing or infinite child excludes that stock from every component rank and the final score. Assert an invalid `min_valid_count` raises `ValueError`.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest ZXW因子\test_stock_low_volatility_style_score.py -v
```

Expected: test collection fails because `股票低波风格评分` does not exist.

- [ ] **Step 3: Implement the minimal scoring API**

Define these public constants and helpers in the new UTF-8 Python module:

```python
BUNDLE_ID = "stock_low_volatility_style_score"
DEFAULT_MIN_VALID_STOCKS = 100
FACTOR_NAME_MAP = {"低波风格评分": "low_volatility_style_score"}
SOURCE_FACTOR_NAME_MAP = {
    "20日年化波动率": "annual_vol_20d",
    "60日年化波动率_股票": "annual_vol_60d",
    "252日年化波动率": "annual_vol_252d",
    "20日下行波动率": "downside_vol_20d",
    "60日下行波动率": "downside_vol_60d",
    "60日最大回撤": "max_drawdown_60d",
    "14日ATR波动率": "atr_volatility_14d",
}
```

Normalize all frames to a shared date/code union, filter columns with `r"\d{6}\.(SH|SZ)"`, coerce values to numeric, replace infinities with nulls, and build the complete-case mask across all seven factors before ranking.

Use one helper for all component scores:

```python
def _inverse_percentile_score(risk: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    masked = risk.where(eligible)
    counts = eligible.sum(axis=1).replace(0, np.nan)
    ranks = masked.rank(axis=1, method="average", na_option="keep")
    return ranks.rsub(counts.add(0.5), axis=0).div(counts, axis=0) * 100.0
```

Convert drawdown with `.abs()`, compute the approved dimension weights, then combine four dimensions at `25%` each. Set the whole day to null when the common complete-case count is below `min_valid_count`. Return `bundle_id`, `factor_dfs`, `factor_name_map`, and a null-preserving merge policy.

- [ ] **Step 4: Run scoring tests and verify GREEN**

Run the Task 1 pytest command. Expected: all scoring-core tests pass.

### Task 2: Deterministic monthly source loader

**Files:**
- Modify: `ZXW因子/股票低波风格评分.py`
- Modify: `ZXW因子/test_stock_low_volatility_style_score.py`

- [ ] **Step 1: Write failing loader and disk-bundle tests**

Create temporary partitions for all seven paths:

```text
factor=<中文来源名>/year=2026/month=08/merged.parquet
factor=<中文来源名>/year=2026/month=08/part_001.parquet
```

Assert `merged.parquet` is read before sorted `part_*.parquet`, the latest part overwrites a duplicate `time + htsc_code`, date filtering is inclusive, and `.BJ`/`.THS` codes are excluded. Assert a missing source month raises `FileNotFoundError` containing both the Chinese factor name and `2026-08`.

- [ ] **Step 2: Run loader tests and verify RED**

Run the focused test file. Expected: failure because `load_low_volatility_source_frames` and `build_stock_low_volatility_style_bundle` do not exist.

- [ ] **Step 3: Implement the monthly loader and disk entry point**

Add:

```python
def load_low_volatility_source_frames(
    *,
    base_dir: str | Path,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    ...

def build_stock_low_volatility_style_bundle(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
) -> dict[str, object]:
    source_frames = load_low_volatility_source_frames(...)
    return build_low_volatility_style_score_bundle(
        source_frames,
        min_valid_count=min_valid_count,
    )
```

For every source factor and requested month, load `merged.parquet` followed by sorted `part_*.parquet`, attach `_file_order`, concatenate, normalize `time`, `htsc_code`, and `value`, then keep the last duplicate. Pivot each internal key to a wide frame. Reject reversed date ranges and fail when any source-month has no readable parquet file.

- [ ] **Step 4: Run the full module tests and verify GREEN**

Run the focused test file. Expected: all scoring and loader tests pass.

### Task 3: Generator and factor-catalog integration

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py`
- Modify: `因子分类/factor_catalog.json`
- Modify: `ZXW因子/test_stock_low_volatility_style_score.py`

- [ ] **Step 1: Write failing integration contract tests**

Parse the generator as UTF-8 and assert the following exact contracts exist:

```python
assert "get_stock_low_volatility_style_lookback_config" in generator
assert "build_stock_low_volatility_style_bundle" in generator
assert '"stock_low_volatility_style_score"' in generator
assert "_run_stock_low_volatility_style_post_write" in generator
assert "STOCK_ONLY_FACTOR_KEYS.update(LOW_VOLATILITY_STYLE_FACTOR_NAME_MAP.values())" in generator
```

Parse `factor_catalog.json` and assert the existing `low_volatility` group lists `低波风格评分` in both `core_factors` and `children` without removing any existing raw child.

Extract the new post-write runner with `ast`, inject fake builder and saver functions, and assert month splitting, output-key filtering, and `drop_null_factor_keys={"low_volatility_style_score"}`.

- [ ] **Step 2: Run integration tests and verify RED**

Run the focused test file. Expected: integration tests fail because the generator and catalog registrations are absent.

- [ ] **Step 3: Register and run the derived bundle**

Import the new module's lookback helper, factor-name map, and disk builder under explicit aliases. Register `stock_low_volatility_style_score` in `SELECTED_BUNDLES`, `BUNDLE_LOOKBACK_LOADERS`, `BUNDLE_MODULE_NAMES`, and `POST_WRITE_DERIVED_BUNDLES`, and add the output key to `STOCK_ONLY_FACTOR_KEYS`.

Implement `_run_stock_low_volatility_style_post_write` using the established monthly post-write contract: select only missing or stale output plan rows, split the requested range by calendar month, build from the full stored source cross-section, save only `low_volatility_style_score` with sparse null dropping, and merge the returned frame/name into the in-memory results.

- [ ] **Step 4: Update the existing UTF-8 catalog group**

Change only the `low_volatility` group:

```json
"core_factors": [
  "低波风格评分",
  "60日年化波动率_股票",
  "60日最大回撤"
]
```

Add `低波风格评分` to `children`, retain all eight existing raw children, and do not create a second low-volatility group.

- [ ] **Step 5: Run focused and related regression tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest `
  ZXW因子\test_stock_low_volatility_style_score.py `
  ZXW因子\test_low_volatility_factor_bundle.py `
  ZXW因子\test_factor_batch_watermark.py -v
```

Expected: all selected tests pass.

### Task 4: Static checks and real-data generation

**Files:**
- Verify: `ZXW因子/股票低波风格评分.py`
- Verify: `ZXW因子/ZXW策略技术因子生成.py`
- Verify: `因子分类/factor_catalog.json`
- Output: `D:\database\signal_daily\factor=低波风格评分\...`

- [ ] **Step 1: Compile Python and parse UTF-8 JSON**

Run:

```powershell
.venv\Scripts\python.exe -m py_compile `
  ZXW因子\股票低波风格评分.py `
  ZXW因子\ZXW策略技术因子生成.py
.venv\Scripts\python.exe -c "import json; json.load(open(r'因子分类\factor_catalog.json', encoding='utf-8'))"
```

Expected: both commands exit zero.

- [ ] **Step 2: Generate the score from saved raw inputs**

Call `build_stock_low_volatility_style_bundle` over available source history in month-sized chunks and save only finite `low_volatility_style_score` rows through the existing partition-writer-compatible long format. Do not modify any of the seven source factor partitions.

- [ ] **Step 3: Validate real outputs**

Check the latest output date, daily non-null counts, unique `time + htsc_code` keys, `0-100` bounds, score percentiles, all seven input-direction Spearman correlations, and repeatability of the latest-month calculation. Confirm no `.BJ`, `.THS`, ETF, or index code appears.

- [ ] **Step 4: Review the scoped diff and rerun focused tests**

Run `git diff --check`, list only the new module/test/plan plus local generator/catalog additions, preserve all unrelated user changes, and rerun the focused test file immediately before completion.
