# Stock Momentum Style Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a daily `0-100` stock-only momentum style score using 70% 12-1 month momentum and 30% 6-1 month momentum.

**Architecture:** Add a self-contained post-write derived bundle that loads the two saved raw momentum factors plus the authoritative stock daily-bar mask, ranks the complete daily stock cross-section, and writes one composite score. Register it beside the existing post-write style bundles without changing the mixed stock/sector `momentum_common` calculations.

**Tech Stack:** Python 3.10, pandas, NumPy, PyArrow Parquet, pytest, JSON.

---

### Task 1: Pure scoring API

**Files:**
- Create: `ZXW因子/股票动量风格评分.py`
- Create: `ZXW因子/test_stock_momentum_style_score.py`

- [ ] **Step 1: Write failing tests for ranking and weighted composition**

Create tests that import `build_momentum_style_score_bundle` and verify separate cross-sectional ranks, average ties, the fixed 70%/30% weights, the one approved output, and score bounds.

```python
def test_momentum_score_ranks_each_horizon_before_weighting() -> None:
    date = pd.Timestamp("2026-08-03")
    codes = ["000001.SZ", "000002.SZ", "000003.SZ", "600000.SH"]
    momentum_12_1 = pd.DataFrame([[1.0, 2.0, 3.0, 4.0]], index=[date], columns=codes)
    momentum_6_1 = pd.DataFrame([[40.0, 30.0, 20.0, 10.0]], index=[date], columns=codes)
    valid_bar = pd.DataFrame(True, index=[date], columns=codes)

    result = build_momentum_style_score_bundle(
        momentum_12_1,
        momentum_6_1,
        valid_bar=valid_bar,
        min_valid_count=4,
    )
    score = result["factor_dfs"]["momentum_style_score"]
    expected_12_1 = np.array([12.5, 37.5, 62.5, 87.5])
    expected_6_1 = np.array([87.5, 62.5, 37.5, 12.5])
    assert score.loc[date, codes].tolist() == pytest.approx(
        0.70 * expected_12_1 + 0.30 * expected_6_1
    )
    assert result["factor_name_map"] == {"动量风格评分": "momentum_style_score"}
```

Add a second test with tied values and assert average ranks are used for each horizon before composition.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest ZXW因子\test_stock_momentum_style_score.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named '股票动量风格评分'`.

- [ ] **Step 3: Implement the minimal scoring module**

Create the module with UTF-8 encoding and the following public contract:

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

import numpy as np
import pandas as pd

BUNDLE_ID = "stock_momentum_style"
DEFAULT_MIN_VALID_STOCKS = 100
LONG_WEIGHT = 0.70
MEDIUM_WEIGHT = 0.30
FACTOR_NAME_MAP = {"动量风格评分": "momentum_style_score"}


def _as_finite_frame(value: pd.DataFrame) -> pd.DataFrame:
    frame = value.copy()
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index)).floor("D")
    frame.columns = frame.columns.astype(str)
    frame = frame[~frame.index.duplicated(keep="last")]
    return frame.apply(pd.to_numeric, errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    ).astype(float)


def build_momentum_style_score_bundle(
    momentum_12_1: pd.DataFrame,
    momentum_6_1: pd.DataFrame,
    *,
    valid_bar: pd.DataFrame,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
) -> dict[str, object]:
    if int(min_valid_count) < 1:
        raise ValueError("min_valid_count 必须大于等于 1")
    long_frame, medium_frame = _as_finite_frame(momentum_12_1).align(
        _as_finite_frame(momentum_6_1), join="outer"
    )
    valid = valid_bar.reindex(index=long_frame.index, columns=long_frame.columns)
    valid = valid.fillna(False).astype(bool)
    joint_valid = valid & long_frame.notna() & medium_frame.notna()
    long_frame = long_frame.where(joint_valid)
    medium_frame = medium_frame.where(joint_valid)
    valid_counts = joint_valid.sum(axis=1)

    long_rank = long_frame.rank(axis=1, method="average", na_option="keep")
    medium_rank = medium_frame.rank(axis=1, method="average", na_option="keep")
    denominator = valid_counts.replace(0, np.nan)
    long_score = long_rank.sub(0.5).div(denominator, axis=0) * 100.0
    medium_score = medium_rank.sub(0.5).div(denominator, axis=0) * 100.0
    score = LONG_WEIGHT * long_score + MEDIUM_WEIGHT * medium_score
    score.loc[valid_counts < int(min_valid_count), :] = np.nan

    return {
        "bundle_id": BUNDLE_ID,
        "factor_dfs": {"momentum_style_score": score.astype(float)},
        "factor_name_map": dict(FACTOR_NAME_MAP),
    }
```

Also implement `get_factor_catalog()` and `get_factor_lookback_config()` with `source_history_start="2010-01-01"` and zero post-write lookback.

- [ ] **Step 4: Run the scoring tests and verify GREEN**

Run the Task 1 pytest command. Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit the scoring unit**

```powershell
git add -- 'ZXW因子/股票动量风格评分.py' 'ZXW因子/test_stock_momentum_style_score.py'
git commit -m "feat: add stock momentum style scoring"
```

### Task 2: Monthly factor and stock-validity loaders

**Files:**
- Modify: `ZXW因子/股票动量风格评分.py`
- Modify: `ZXW因子/test_stock_momentum_style_score.py`

- [ ] **Step 1: Write failing loader tests**

Create temporary monthly partitions for `factor=252日纯动量`, `factor=纯动量`, and `stock_basic_data_daily`. Assert all of the following in one disk-bundle test:

```python
result = build_stock_momentum_style_bundle(
    signal_base_dir=signal_dir,
    market_base_dir=market_dir,
    start_date=date,
    end_date=date,
    min_valid_count=2,
)
score = result["factor_dfs"]["momentum_style_score"]
assert set(score.columns) == {"000001.SZ", "600000.SH"}
assert np.isfinite(score.loc[date, "000001.SZ"])
assert "000001.THS" not in score.columns
assert "510300.SH" not in score.columns
```

The test data must include a newer `part_001.parquet` that overwrites one `merged.parquet` factor value, a `.THS` code, an ETF-like code absent from the authoritative stock daily source, and a stock factor row with no real daily bar. Add separate tests for a missing requested month and `start_date > end_date`.

- [ ] **Step 2: Run loader tests and verify RED**

Run the full new test file. Expected: failure because `load_saved_factor_frame`, `load_stock_valid_bar`, and `build_stock_momentum_style_bundle` do not exist.

- [ ] **Step 3: Implement independent monthly loaders**

Copy the existing monthly partition traversal and latest-part overwrite pattern into the new module rather than importing the pure-size module. Implement:

```python
DEFAULT_SIGNAL_BASE_DIR = Path(r"D:\database\signal_daily")
DEFAULT_MARKET_BASE_DIR = Path(r"D:\database\stock_basic_data_daily")
INPUT_FACTOR_NAMES = {
    "momentum_12_1": "252日纯动量",
    "momentum_6_1": "纯动量",
}


def _normalize_range(
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    start_dt = pd.Timestamp(start_date).floor("D")
    end_dt = pd.Timestamp(end_date).floor("D")
    if start_dt > end_dt:
        raise ValueError(
            f"start_date 不能晚于 end_date: {start_dt.date()} > {end_dt.date()}"
        )
    return start_dt, end_dt


def _month_starts(
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> Iterable[pd.Timestamp]:
    cursor = pd.Timestamp(start_date.year, start_date.month, 1)
    end_month = pd.Timestamp(end_date.year, end_date.month, 1)
    while cursor <= end_month:
        yield cursor
        cursor += pd.offsets.MonthBegin(1)


def load_saved_factor_frame(
    *,
    base_dir: str | Path,
    factor_name: str,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> pd.DataFrame:
    start_dt, end_dt = _normalize_range(start_date, end_date)
    factor_dir = Path(base_dir) / f"factor={factor_name}"
    files: list[Path] = []
    missing_months: list[str] = []
    for month_start in _month_starts(start_dt, end_dt):
        month_dir = (
            factor_dir
            / f"year={month_start.year}"
            / f"month={month_start.month:02d}"
        )
        month_files: list[Path] = []
        merged_path = month_dir / "merged.parquet"
        if merged_path.is_file():
            month_files.append(merged_path)
        month_files.extend(sorted(month_dir.glob("part_*.parquet")))
        if not month_files:
            missing_months.append(month_start.strftime("%Y-%m"))
        files.extend(month_files)
    if missing_months:
        raise FileNotFoundError(
            f"{factor_name} 缺少月份分区: " + "、".join(missing_months)
        )

    frames: list[pd.DataFrame] = []
    for file_order, path in enumerate(files):
        frame = pd.read_parquet(path, columns=["time", "htsc_code", "value"])
        frame["_file_order"] = file_order
        frames.append(frame)
    long_frame = pd.concat(frames, ignore_index=True)
    long_frame["time"] = pd.to_datetime(
        long_frame["time"], errors="coerce"
    ).dt.floor("D")
    long_frame["htsc_code"] = (
        long_frame["htsc_code"].astype(str).str.strip().str.upper()
    )
    long_frame["value"] = pd.to_numeric(long_frame["value"], errors="coerce")
    long_frame = long_frame[long_frame["time"].between(start_dt, end_dt)]
    long_frame = long_frame.sort_values("_file_order").drop_duplicates(
        ["time", "htsc_code"], keep="last"
    )
    wide = long_frame.pivot(
        index="time", columns="htsc_code", values="value"
    ).sort_index()
    wide.columns.name = None
    return wide.astype(float)


def load_stock_valid_bar(
    *,
    base_dir: str | Path,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> pd.DataFrame:
    start_dt, end_dt = _normalize_range(start_date, end_date)
    files: list[Path] = []
    missing_months: list[str] = []
    for month_start in _month_starts(start_dt, end_dt):
        path = (
            Path(base_dir)
            / f"year={month_start.year}"
            / f"month={month_start.month:02d}"
            / "merged.parquet"
        )
        if path.is_file():
            files.append(path)
        else:
            missing_months.append(month_start.strftime("%Y-%m"))
    if missing_months:
        raise FileNotFoundError(
            "股票日线缺少月份分区: " + "、".join(missing_months)
        )

    frames = [
        pd.read_parquet(path, columns=["time", "htsc_code", "close"])
        for path in files
    ]
    long_frame = pd.concat(frames, ignore_index=True)
    long_frame["time"] = pd.to_datetime(
        long_frame["time"], errors="coerce"
    ).dt.floor("D")
    long_frame["htsc_code"] = (
        long_frame["htsc_code"].astype(str).str.strip().str.upper()
    )
    long_frame["close"] = pd.to_numeric(long_frame["close"], errors="coerce")
    long_frame = long_frame[long_frame["time"].between(start_dt, end_dt)]
    long_frame = long_frame.drop_duplicates(["time", "htsc_code"], keep="last")
    wide = long_frame.pivot(
        index="time", columns="htsc_code", values="close"
    ).sort_index()
    wide.columns.name = None
    values = wide.to_numpy(dtype=float)
    return pd.DataFrame(
        np.isfinite(values), index=wide.index, columns=wide.columns
    )
```

Both loaders must fail with a Chinese `FileNotFoundError` listing every missing requested month. `load_saved_factor_frame` may retain non-stock columns temporarily; final columns are restricted by `load_stock_valid_bar` inside the scorer.

- [ ] **Step 4: Implement the disk bundle entry point**

```python
def build_stock_momentum_style_bundle(
    *,
    signal_base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    market_base_dir: str | Path = DEFAULT_MARKET_BASE_DIR,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    min_valid_count: int = DEFAULT_MIN_VALID_STOCKS,
) -> dict[str, object]:
    momentum_12_1 = load_saved_factor_frame(
        base_dir=signal_base_dir,
        factor_name=INPUT_FACTOR_NAMES["momentum_12_1"],
        start_date=start_date,
        end_date=end_date,
    )
    momentum_6_1 = load_saved_factor_frame(
        base_dir=signal_base_dir,
        factor_name=INPUT_FACTOR_NAMES["momentum_6_1"],
        start_date=start_date,
        end_date=end_date,
    )
    valid_bar = load_stock_valid_bar(
        base_dir=market_base_dir,
        start_date=start_date,
        end_date=end_date,
    )
    stock_columns = valid_bar.columns
    return build_momentum_style_score_bundle(
        momentum_12_1.reindex(columns=stock_columns),
        momentum_6_1.reindex(columns=stock_columns),
        valid_bar=valid_bar,
        min_valid_count=min_valid_count,
    )
```

- [ ] **Step 5: Run loader and scoring tests and verify GREEN**

Run the full new test file. Expected: every module and loader test passes.

- [ ] **Step 6: Commit the loader unit**

```powershell
git add -- 'ZXW因子/股票动量风格评分.py' 'ZXW因子/test_stock_momentum_style_score.py'
git commit -m "feat: load stock momentum score inputs"
```

### Task 3: Generator and factor catalog integration

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py`
- Modify: `因子分类/factor_catalog.json`
- Modify: `ZXW因子/test_stock_momentum_style_score.py`

- [ ] **Step 1: Write failing integration contract tests**

Assert that the generator contains all of these exact contracts:

```python
assert "get_stock_momentum_style_lookback_config" in generator
assert "build_stock_momentum_style_bundle" in generator
assert '"stock_momentum_style"' in generator
assert "STOCK_ONLY_FACTOR_KEYS.update(MOMENTUM_STYLE_FACTOR_NAME_MAP.values())" in generator
assert "_run_stock_momentum_style_post_write" in generator
```

Parse `因子分类/factor_catalog.json` with UTF-8 and assert:

```python
group = groups["stock_momentum_style"]
assert group["group_name"] == "股票动量风格评分"
assert group["core_factors"] == ["动量风格评分"]
assert group["children"] == ["动量风格评分"]
```

- [ ] **Step 2: Run the integration test and verify RED**

Run the full new test file. Expected: only the generator/catalog contract test fails.

- [ ] **Step 3: Register the post-write bundle in the generator**

Add imports for the lookback helper, `FACTOR_NAME_MAP as MOMENTUM_STYLE_FACTOR_NAME_MAP`, and `build_stock_momentum_style_bundle`. Add `stock_momentum_style` to `SELECTED_BUNDLES`, `BUNDLE_LOOKBACK_LOADERS`, `BUNDLE_MODULE_NAMES`, `POST_WRITE_DERIVED_BUNDLES`, and `STOCK_ONLY_FACTOR_KEYS`.

Add `_run_stock_momentum_style_post_write` immediately after the pure-size post-write runner. It must:

```python
score_keys = set(MOMENTUM_STYLE_FACTOR_NAME_MAP.values())
needed = plan_df[
    plan_df["factor_en"].astype(str).isin(score_keys)
    & plan_df["status"].isin(["missing", "stale"])
    & plan_df["plan_start"].notna()
    & plan_df["plan_end"].notna()
].copy()
```

For every requested month, call:

```python
chunk_result = build_stock_momentum_style_bundle(
    signal_base_dir=base_dir,
    market_base_dir=BASE_PATH,
    start_date=chunk_start,
    end_date=chunk_end,
)
```

Then save only `momentum_style_score` with `save_factor_dfs_to_factor_partitioned_parquet`, passing the existing factor ranges and watermark map. Keep all messages in Chinese and do not alter the existing raw momentum or `.THS` paths.

- [ ] **Step 4: Add the standalone frontend catalog group**

Insert this object after the existing `momentum_common` group without modifying that group:

```json
{
  "group_id": "stock_momentum_style",
  "group_name": "股票动量风格评分",
  "core_factors": ["动量风格评分"],
  "children": ["动量风格评分"]
}
```

- [ ] **Step 5: Run integration tests and verify GREEN**

Run the full new test file. Expected: all tests pass.

- [ ] **Step 6: Commit only the scoped integration edits**

```powershell
git add -- 'ZXW因子/ZXW策略技术因子生成.py' '因子分类/factor_catalog.json' 'ZXW因子/test_stock_momentum_style_score.py'
git commit -m "feat: integrate stock momentum style score"
```

Before committing, inspect the staged diff because the generator and catalog already contain user changes. Do not stage unrelated hunks; if clean hunk staging is not possible, leave integration edits uncommitted and report that fact.

### Task 4: Focused verification and real-data backfill

**Files:**
- Verify: `ZXW因子/股票动量风格评分.py`
- Verify: `ZXW因子/ZXW策略技术因子生成.py`
- Verify: `因子分类/factor_catalog.json`
- Output: `D:\database\signal_daily\factor=动量风格评分\year=*\month=*\*.parquet`

- [ ] **Step 1: Run focused and regression tests**

```powershell
.venv\Scripts\python.exe -m pytest ZXW因子\test_stock_momentum_style_score.py ZXW因子\test_momentum_factor_bundle.py ZXW因子\test_factor_auto_plan_valid_values.py ZXW因子\test_factor_batch_watermark.py -q
```

Expected: all selected tests pass with zero failures.

- [ ] **Step 2: Compile and parse UTF-8 artifacts**

```powershell
.venv\Scripts\python.exe -m py_compile 'ZXW因子/股票动量风格评分.py' 'ZXW因子/ZXW策略技术因子生成.py'
.venv\Scripts\python.exe -c "import json, pathlib; json.loads(pathlib.Path(r'因子分类/factor_catalog.json').read_text(encoding='utf-8')); print('JSON_OK')"
```

Expected: compilation is silent and JSON prints `JSON_OK`.

- [ ] **Step 3: Backfill from saved real data month by month**

Use `build_stock_momentum_style_bundle` for each available month from `2010-01-01` through the latest shared date, and write through the existing partition writer contract. Do not rewrite the two raw input factors. Empty early-history scores are allowed until stocks accumulate 253 valid trading days.

- [ ] **Step 4: Validate real output invariants**

Query `factor=动量风格评分` and assert:

```text
primary key duplicates (time, htsc_code) = 0
finite score minimum > 0
finite score maximum < 100
latest date = latest stock daily source date
latest non-null stock count >= 100
.THS rows = 0
non-stock rows = 0, using stock_basic_data_daily as the authoritative membership set
```

Also recompute one latest-date sample from the two raw momentum inputs and confirm exact 70%/30% equality within floating-point tolerance.

- [ ] **Step 5: Check TRACE write protection and scoped diff**

Inspect `codex/logs_2.sqlite` for the `block_trace_logs_insert` trigger, record `MAX(id)`, TRACE `MAX(id)`, and WAL size twice, and confirm they do not grow. Review the final repository diff without reverting unrelated user files.
