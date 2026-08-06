# Multi-Board Growth And Value Scores Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independent `885/886` multi-board normalized growth and value scores using direct arithmetic means of valid board-level scores, and make sparse-factor progress reliable on all-null dates.

**Architecture:** Copy the corresponding `881` modules into two independent multi-board modules, replace the one-stock-one-industry wide label with a point-in-time long membership table, rank raw factors and composites by `time + board_code`, then average finite board scores by `time + stock_code`. Extend the common persistence layer with one atomic progress JSON per factor directory; this is storage infrastructure only and does not share growth/value business logic.

**Tech Stack:** Python 3.10, pandas, NumPy, SciPy, Polars, DuckDB, pytest, parquet, UTF-8 JSON.

---

## File Structure

- Create `ZXW因子/股票成长多板块标准化因子.py`: snapshot validation, multi-membership expansion, vectorized board ranking, growth composition, direct average, raw-factor loading.
- Create `ZXW因子/股票价值模型多板块标准化评分.py`: independent value implementation with the same membership contract.
- Create `ZXW因子/test_stock_growth_multi_board_normalized_factors.py`: growth behavior, boundaries, time-point and registration tests.
- Create `ZXW因子/test_stock_value_model_multi_board_normalized_score.py`: value behavior, boundaries and registration tests.
- Modify `ZXW因子/ZXW策略技术因子生成.py`: imports, bundle registry, monthly post-write execution, sparse processed-date metadata.
- Modify `ZXW因子/test_factor_progress_logging.py`: sparse all-null progress regression test.
- Modify `因子分类/factor_catalog.json`: two new independent groups.

### Task 1: Growth Multi-Board Module

**Files:**
- Create: `ZXW因子/test_stock_growth_multi_board_normalized_factors.py`
- Create: `ZXW因子/股票成长多板块标准化因子.py`

- [ ] **Step 1: Write failing snapshot and membership tests**

Create tests that write `881/882/885/886` rows to a UTF-8 parquet snapshot and assert only `885/886` remain. Assert one stock may have two board rows, the latest snapshot not after the score date is used, future partitions are ignored, partition/date mismatches raise, and duplicate membership rows collapse.

```python
result = load_ths_multi_board_snapshots(snapshot_dir=tmp_path, end_date=date)
assert set(result["board_code"]) == {"885001", "886001"}
memberships = build_board_memberships(
    dates=pd.DatetimeIndex([date]),
    stock_codes=pd.Index(["000001.SZ"]),
    snapshots=result,
)
assert memberships[["stock_code", "board_code"]].to_records(index=False).tolist() == [
    ("000001.SZ", "885001"),
    ("000001.SZ", "886001"),
]
```

- [ ] **Step 2: Run the new growth tests and verify missing-module failure**

Run: `.\.venv\Scripts\python.exe -m pytest -q ZXW因子/test_stock_growth_multi_board_normalized_factors.py`

Expected: collection fails with `ModuleNotFoundError: 股票成长多板块标准化因子`.

- [ ] **Step 3: Implement point-in-time snapshot and membership functions**

Copy the UTF-8 header, constants, raw-factor maps, pillar configuration and input validation from `股票成长行业标准化因子.py`. Define the constants exactly as follows:

```python
BUNDLE_ID = "stock_growth_multi_board_normalized"
DEFAULT_MIN_BOARD_COUNT = 20
FACTOR_NAME_MAP = {
    "成长风格综合评分(多板块标准化)":
        "growth_style_composite_score_multi_board_normalized"
}

```

Implement `load_ths_multi_board_snapshots(*, snapshot_dir, end_date) -> pd.DataFrame` to return unique `analysis_date, stock_code, board_code` rows matching `(?:885|886)\d{3}`. It must filter snapshot partitions before reading, validate every row date against its partition and normalize A-share codes.

Implement `build_board_memberships(*, dates, stock_codes, snapshots) -> pd.DataFrame` to return unique `time, stock_code, board_code` rows. Use `snapshot_dates.searchsorted(score_date, side="right") - 1` to select the latest snapshot not after each score date, group score dates by selected snapshot date, cross-join each selected date group with its filtered snapshot memberships, concatenate, sort and reject duplicate business keys.

- [ ] **Step 4: Write failing board-rank and direct-average tests**

Cover exactly 20 valid stocks, 19 valid stocks, ties, two boards with different scores, one missing board score, one-board stocks and zero-board stocks. The arithmetic-mean assertion must be explicit:

```python
score, count = average_board_scores(
    pd.Series(
        [90.0, 60.0, 30.0],
        index=pd.MultiIndex.from_tuples(
            [(date, "000001.SZ", "885001"),
             (date, "000001.SZ", "886001"),
             (date, "000002.SZ", "885001")],
            names=["time", "stock_code", "board_code"],
        ),
    ),
    dates=pd.DatetimeIndex([date]),
    stock_codes=pd.Index(["000001.SZ", "000002.SZ", "000003.SZ"]),
)
assert score.loc[date, "000001.SZ"] == 75.0
assert count.loc[date, "000001.SZ"] == 2
assert pd.isna(score.loc[date, "000003.SZ"])
```

- [ ] **Step 5: Implement vectorized board ranking and growth composition**

Implement `board_rank_normalize()` by stacking a numeric factor frame, merging once with membership rows, and using grouped `rank(method="average")` and `transform("count")` on `time + board_code`. Return percentile and clipped inverse-normal score Series indexed by `time + stock_code + board_code`.

Implement `average_board_scores(board_scores, *, dates, stock_codes) -> tuple[pd.DataFrame, pd.DataFrame]` without per-stock loops. Replace infinities with missing values, drop missing scores, group by MultiIndex levels `time + stock_code`, calculate `mean` and `count`, unstack `stock_code`, and reindex both outputs to the requested sorted dates and stock codes.

Implement `build_growth_multi_board_normalized_factor_bundle(raw_factor_dfs, memberships, *, min_board_count=DEFAULT_MIN_BOARD_COUNT) -> dict[str, object]`. Reuse growth pillar weights, 40% completeness and 50% missing penalty; rank the raw composite again inside each board; call `average_board_scores`; place the score DataFrame in `factor_dfs`; and place the count DataFrame at `diagnostics["valid_board_count"]` without registering it in `factor_name_map`.

Copy the existing monthly raw-factor loader and conflicting-key validation. Add `build_stock_growth_multi_board_normalized_factor_bundle()` with the `2026-07-15` start boundary.

- [ ] **Step 6: Run growth tests**

Run: `.\.venv\Scripts\python.exe -m pytest -q ZXW因子/test_stock_growth_multi_board_normalized_factors.py`

Expected: all growth multi-board tests pass.

### Task 2: Value Multi-Board Module

**Files:**
- Create: `ZXW因子/test_stock_value_model_multi_board_normalized_score.py`
- Create: `ZXW因子/股票价值模型多板块标准化评分.py`

- [ ] **Step 1: Write failing value tests**

Test the existing six weights, minimum four valid factors, missing penalty, invalid `min_valid_factors` values, board minimum of 20, direct averaging and model start boundary. Independently test snapshot time filtering and duplicate input axes so the value module does not rely on growth tests.

- [ ] **Step 2: Run the value tests and verify missing-module failure**

Run: `.\.venv\Scripts\python.exe -m pytest -q ZXW因子/test_stock_value_model_multi_board_normalized_score.py`

Expected: collection fails with `ModuleNotFoundError: 股票价值模型多板块标准化评分`.

- [ ] **Step 3: Implement the independent value module**

Copy the value `881` module and implement the same multi-board snapshot, membership, rank and averaging contracts locally. Use:

```python
BUNDLE_ID = "stock_value_model_multi_board_normalized"
DEFAULT_MIN_BOARD_COUNT = 20
FACTOR_NAME_MAP = {
    "价值模型综合评分(多板块标准化)":
        "value_model_composite_score_multi_board_normalized"
}
```

For every membership key, combine available board percentiles using the current six weights, require `min_valid_factors >= 4`, rank the raw composite again inside each board, apply the current missing-weight penalty, and average finite board scores by stock.

- [ ] **Step 4: Run value and combined new-factor tests**

Run: `.\.venv\Scripts\python.exe -m pytest -q ZXW因子/test_stock_growth_multi_board_normalized_factors.py ZXW因子/test_stock_value_model_multi_board_normalized_score.py`

Expected: all tests pass.

### Task 3: Sparse Processed-Date Watermark

**Files:**
- Modify: `ZXW因子/test_factor_progress_logging.py`
- Modify: `ZXW因子/ZXW策略技术因子生成.py`

- [ ] **Step 1: Write a failing all-null sparse progress test**

Extract the new progress helpers through the existing AST test loader. Save a sparse DataFrame whose final date exists in the index but contains only NaN values. Assert no parquet row is required and the factor progress JSON records that final input date. Assert a failed parquet write does not advance progress.

```python
assert functions["_load_factor_processed_date"](
    str(tmp_path), "测试稀疏因子"
) == pd.Timestamp("2026-08-03")
```

- [ ] **Step 2: Run the targeted test and verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest -q ZXW因子/test_factor_progress_logging.py`

Expected: failure because processed-date helpers do not exist.

- [ ] **Step 3: Implement atomic per-factor progress metadata**

Add UTF-8 JSON helpers under `factor=<safe name>/_meta/processed_through.json`: `_factor_processed_date_path(base_dir, factor_name) -> Path`, `_load_factor_processed_date(base_dir, factor_name) -> pd.Timestamp | None`, and `_write_factor_processed_date_atomic(base_dir, factor_name, processed_date) -> Path`. The writer must create the parent directory, write `{"last_processed_date": "YYYY-MM-DD", "updated_at": "ISO timestamp"}` to a uniquely named sibling temporary file with `encoding="utf-8"`, flush and `os.fsync`, then call `os.replace`. The loader must return `None` for a missing file and raise `ValueError` for malformed JSON or an invalid date.

After `_save_single_factor_task()` finishes every month successfully, update progress only for sparse tasks and only through the maximum normalized input index inside the requested range. Merge metadata dates into `_load_factor_last_date_map()` and `_get_factor_last_date()` by taking the maximum of parquet and metadata dates. Do not write sentinel factor rows.

- [ ] **Step 4: Run persistence and watermark tests**

Run: `.\.venv\Scripts\python.exe -m pytest -q ZXW因子/test_factor_progress_logging.py ZXW因子/test_factor_batch_watermark.py`

Expected: all tests pass, including all-null sparse progress and failure atomicity.

### Task 4: Generator And Catalog Integration

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py`
- Modify: `因子分类/factor_catalog.json`
- Modify: both new test files.

- [ ] **Step 1: Write failing integration contract tests**

Assert both bundle IDs, lookback imports, builders, monthly post-write functions, start-date clamps, sparse save keys and catalog group children exist. Parse JSON rather than searching raw JSON strings.

- [ ] **Step 2: Add generator imports and bundle registration**

Register both `get_factor_lookback_config()` functions in the same dictionaries and selected-bundle flow as the existing `881` modules. Add builder imports and constants:

```python
from 股票成长多板块标准化因子 import (
    FACTOR_NAME_MAP as GROWTH_MULTI_BOARD_NORMALIZED_FACTOR_NAME_MAP,
    MODEL_START_DATE as GROWTH_MULTI_BOARD_NORMALIZED_START_DATE,
    build_stock_growth_multi_board_normalized_factor_bundle,
)
from 股票价值模型多板块标准化评分 import (
    FACTOR_NAME_MAP as VALUE_MODEL_MULTI_BOARD_NORMALIZED_FACTOR_NAME_MAP,
    MODEL_START_DATE as VALUE_MODEL_MULTI_BOARD_NORMALIZED_START_DATE,
    build_stock_value_model_multi_board_normalized_score_bundle,
)
```

Add independent month-loop post-write stages after their corresponding `881` stages. Pass `drop_null_factor_keys=set(chunk_factor_dfs)` and preserve all unrelated generator logic.

- [ ] **Step 3: Register catalog groups**

Add groups adjacent to their `881` equivalents:

```json
{
  "group_id": "stock_growth_multi_board_normalized",
  "group_name": "股票成长多板块标准化",
  "core_factors": ["成长风格综合评分(多板块标准化)"],
  "children": ["成长风格综合评分(多板块标准化)"]
}
```

Add the corresponding value group with `价值模型综合评分(多板块标准化)`.

- [ ] **Step 4: Run integration and full factor tests**

Run: `.\.venv\Scripts\python.exe -m pytest -q ZXW因子/test_stock_growth_multi_board_normalized_factors.py ZXW因子/test_stock_value_model_multi_board_normalized_score.py`

Run: `.\.venv\Scripts\python.exe -m pytest -q ZXW因子`

Expected: all tests pass; only existing deprecation warnings remain.

### Task 5: Real-Data Verification

**Files:**
- No source changes unless a reproducible defect is found; any defect requires a failing test before its fix.

- [ ] **Step 1: Run both builders on the latest available real-data month**

Use `.\.venv\Scripts\python.exe` and the default `D:\database` paths. Report snapshot date, score date range, finite score count, minimum, maximum, mean, median and valid-board-count distribution.

- [ ] **Step 2: Verify direct arithmetic means**

For at least five stocks with two or more valid boards, compare the stored stock score with the arithmetic mean of internal board scores using `numpy.isclose`. Expected: every sampled comparison passes within floating-point tolerance.

- [ ] **Step 3: Verify time-point and category constraints**

Assert membership data contains only `885/886`, every selected snapshot date is `<=` score date, and at least one stock with multiple boards is represented without duplicate membership keys.

- [ ] **Step 4: Verify output persistence contracts without destructive overwrite**

Run module builders and save-path tests against a temporary directory first. Run the project generator only if its normal incremental plan targets the two new factors; do not delete or replace unrelated user data. Confirm factor keys, month partitions, sparse rows and processed-date metadata.

- [ ] **Step 5: Verify TRACE suppression**

Query `C:\Users\Administrator\.codex\logs_2.sqlite` before and after an observation interval. Assert `block_trace_logs_insert` exists and TRACE `MAX(id)`, TRACE row count and WAL size do not grow.

- [ ] **Step 6: Review scoped diff and report**

Run `git diff --check` on task files, inspect UTF-8 Chinese strings, list any bugs found and fixed, and report tests plus real-data evidence. Preserve all unrelated dirty-worktree changes.
