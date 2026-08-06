# Liquidity Composite Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a daily `0-100` stock liquidity composite score from the seven saved liquidity raw factors.

**Architecture:** Add a self-contained post-write derived bundle that loads complete monthly factor partitions, builds four cross-sectional subscores, and combines them with the approved weights. Register the bundle beside the existing size and momentum derived bundles, then save the sparse score through the existing partition writer.

**Tech Stack:** Python 3.10, pandas, NumPy, PyArrow Parquet, pytest, JSON.

---

### Task 1: Cross-sectional scoring core

**Files:**
- Create: `ZXW因子/股票流动性综合评分.py`
- Create: `ZXW因子/test_stock_liquidity_composite_score.py`

- [ ] **Step 1: Write failing direction, weight, and gate tests**

Create tests importing `build_liquidity_composite_score_bundle` and asserting:

```python
result = build_liquidity_composite_score_bundle(inputs, min_valid_count=4)
score = result["factor_dfs"]["liquidity_composite_score"]
assert result["bundle_id"] == "stock_liquidity_composite"
assert score.loc[date, "000004.SZ"] > score.loc[date, "000001.SZ"]
assert score.min().min() >= 0.0
assert score.max().max() <= 100.0
```

Use controlled frames to verify average-tie percentile ranks, required amount/Amihud dimensions, at least one optional dimension, non-finite preservation, and the daily 100-stock gate via a smaller test override.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv\Scripts\python.exe -m pytest ZXW因子\test_stock_liquidity_composite_score.py -v`

Expected: collection fails because `股票流动性综合评分` does not exist.

- [ ] **Step 3: Implement constants and scoring API**

Implement:

```python
BUNDLE_ID = "stock_liquidity_composite"
OUTPUT_FACTOR_NAME_MAP = {"流动性综合评分": "liquidity_composite_score"}
DIMENSION_WEIGHTS = {
    "trading_scale": 0.35,
    "price_impact": 0.30,
    "turnover_activity": 0.20,
    "trading_continuity": 0.15,
}

def build_liquidity_composite_score_bundle(
    factor_frames: dict[str, pd.DataFrame],
    *,
    min_valid_count: int = 100,
) -> dict[str, object]:
    ...
```

Normalize dates/codes, filter to `\d{6}.SH|SZ`, align all frames, replace infinities with nulls, and compute `(rank - 0.5) / N * 100` with `method="average"` per date. Build the four approved dimensions; average the available 20/60-day children within the amount and turnover dimensions; cap both turnover percentile frames at 95 and rescale by `100 / 95`; dynamically average informative continuity children. Require a valid amount dimension and Amihud price-impact dimension, plus at least one optional dimension. Reweight remaining valid dimensions per stock using the original weights.

- [ ] **Step 4: Run scoring tests and verify GREEN**

Run the Task 1 pytest command. Expected: all scoring-core tests pass.

### Task 2: Constant-child handling and monthly factor loader

**Files:**
- Modify: `ZXW因子/股票流动性综合评分.py`
- Modify: `ZXW因子/test_stock_liquidity_composite_score.py`

- [ ] **Step 1: Write failing constant-child and loader tests**

Create temporary partitions for all seven `factor=<Chinese name>/year=2026/month=08` inputs. Assert that `merged.parquet` is read before sorted `part_*.parquet`, the latest part overwrites a duplicate key, `.BJ`/`.THS` codes are removed, and a missing factor-month raises `FileNotFoundError` naming both the factor and month.

Add a scoring test where zero-amount ratio is constant across the daily cross-section and amount volatility varies. Assert the continuity dimension and final score are driven only by inverse amount-volatility rank.

- [ ] **Step 2: Run the new tests and verify RED**

Expected: failure because `load_liquidity_raw_factor_frames` and `build_stock_liquidity_composite_bundle` do not exist.

- [ ] **Step 3: Implement deterministic monthly loading**

Implement:

```python
def load_liquidity_raw_factor_frames(
    *,
    base_dir: str | Path,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    ...

def build_stock_liquidity_composite_bundle(
    *,
    base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
) -> dict[str, object]:
    raw = load_liquidity_raw_factor_frames(...)
    return build_liquidity_composite_score_bundle(raw, min_valid_count=min_valid_count)
```

For each factor and requested month, load `merged.parquet` followed by sorted `part_*.parquet`; attach `_file_order`, concatenate, normalize keys and values, then keep the final duplicate. Pivot each input to one wide frame.

- [ ] **Step 4: Run the complete module test and verify GREEN**

Run the Task 1 pytest command. Expected: all scoring and loader tests pass.

### Task 3: Generator and catalog integration

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py`
- Modify: `因子分类/factor_catalog.json`
- Modify: `ZXW因子/test_stock_liquidity_composite_score.py`

- [ ] **Step 1: Write failing integration contract tests**

Parse the generator and catalog and assert these exact contracts exist:

```python
assert "get_stock_liquidity_composite_lookback_config" in generator
assert "build_stock_liquidity_composite_bundle" in generator
assert '"stock_liquidity_composite"' in generator
assert "_run_stock_liquidity_composite_post_write" in generator
assert "STOCK_ONLY_FACTOR_KEYS.update(LIQUIDITY_COMPOSITE_FACTOR_NAME_MAP.values())" in generator
assert groups["stock_liquidity_composite"]["children"] == ["流动性综合评分"]
```

Extract the post-write runner with `ast`, fake its builder and saver, and assert month splitting, single-key filtering, and `drop_null_factor_keys={"liquidity_composite_score"}`.

- [ ] **Step 2: Run the integration tests and verify RED**

Expected: contract tests fail because registrations and runner are absent.

- [ ] **Step 3: Register and execute the derived bundle**

Add imports for the lookback loader, output name map, and disk builder. Add `stock_liquidity_composite` to `SELECTED_BUNDLES`, `BUNDLE_LOOKBACK_LOADERS`, `BUNDLE_MODULE_NAMES`, and `POST_WRITE_DERIVED_BUNDLES`; add its factor key to `STOCK_ONLY_FACTOR_KEYS`.

Implement `_run_stock_liquidity_composite_post_write` using the size-style runner contract: select missing/stale plan rows, split the range by month, build from complete stored inputs, save only the requested output with sparse null dropping, and merge the returned bundle into `factor_dfs`/`factor_name_map`.

- [ ] **Step 4: Add the frontend catalog group**

Add:

```json
{
  "group_id": "stock_liquidity_composite",
  "group_name": "股票流动性综合评分",
  "core_factors": ["流动性综合评分"],
  "children": ["流动性综合评分"]
}
```

Keep the existing raw `liquidity` group unchanged.

- [ ] **Step 5: Run integration and related regression tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest `
  ZXW因子\test_stock_liquidity_composite_score.py `
  ZXW因子\test_liquidity_factor_bundle.py `
  ZXW因子\test_factor_batch_watermark.py -v
```

Expected: all selected tests pass.

### Task 4: Static checks and real-data generation

**Files:**
- Verify: `ZXW因子/股票流动性综合评分.py`
- Verify: `ZXW因子/ZXW策略技术因子生成.py`
- Verify: `因子分类/factor_catalog.json`
- Output: `D:\database\signal_daily\factor=流动性综合评分\...`

- [ ] **Step 1: Compile and parse UTF-8 artifacts**

Run:

```powershell
.venv\Scripts\python.exe -m py_compile `
  ZXW因子\股票流动性综合评分.py `
  ZXW因子\ZXW策略技术因子生成.py
.venv\Scripts\python.exe -c "import json; json.load(open(r'因子分类\factor_catalog.json', encoding='utf-8'))"
```

Expected: both commands exit zero.

- [ ] **Step 2: Generate the score from saved raw inputs**

Call `build_stock_liquidity_composite_bundle` for the available history in month-sized chunks and save only finite values with the existing compatible long partition format. Do not modify any raw factor partition.

- [ ] **Step 3: Validate real outputs**

Check latest date, daily non-null counts, unique `time + htsc_code` keys, score bounds, percentiles, dimension/input Spearman correlations, and top-turnover capping behavior. Confirm the output partition exists and repeated calculation on the latest month is identical.

- [ ] **Step 4: Review the scoped diff and rerun focused tests**

Run `git diff --check` and list only the new module/test/plan plus local generator/catalog additions. Preserve all unrelated and pre-existing user changes. Re-run the focused test file before completion.
