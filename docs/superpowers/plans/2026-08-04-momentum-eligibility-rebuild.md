# Momentum Eligibility Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the seven existing stock momentum factors, require 250 valid trading days, preserve unavailable values as `NaN`, and rebuild only their existing factor partitions.

**Architecture:** Keep the existing `momentum_common` bundle and Chinese factor names. Apply one vectorized eligibility mask inside the bundle, use interval returns for the three skip-month factors, and opt the seven factors into the existing `preserve_nan` merge policy. Delete and regenerate only the seven corresponding `factor=*` directories after tests pass.

**Tech Stack:** Python 3.10, pandas, NumPy, DuckDB, pytest, UTF-8 source and Parquet.

---

### Task 1: Lock corrected behavior

**Files:**
- Modify: `ZXW因子/test_momentum_factor_bundle.py`

- [x] Add assertions that all seven momentum fields are `NaN` before 250 valid observations.
- [x] Assert 20/60/120-day raw momentum is available at observation 250, while 252-day fields retain their natural longer warm-up.
- [x] Assert skip-month momentum equals `close.shift(20) / close.shift(window) - 1`.
- [x] Assert valid-bar merging preserves pre-listing, warm-up, and gap `NaN` values.
- [x] Run `& '.\.venv\Scripts\python.exe' -m pytest 'ZXW因子/test_momentum_factor_bundle.py' -q` and confirm the new assertions fail against the old implementation.

### Task 2: Correct the bundle

**Files:**
- Modify: `ZXW因子/板块动量策略常用因子.py`

- [x] Add a 250-valid-observation eligibility mask.
- [x] Apply it only to the seven momentum outputs, leaving trend, volatility, sector, and industry formulas unchanged.
- [x] Replace subtraction-based pure momentum with skip-month interval returns for 60, 120, and 252 days.
- [x] Add `preserve_nan=True` merge policies for all seven momentum keys.
- [x] Set their planning lookback to at least 250 observations so incremental computation can evaluate eligibility.
- [x] Run the focused momentum tests and relevant planning tests.

### Task 3: Rebuild only corrected factors

**Data targets:**
- `D:\database\signal_daily\factor=20日动量`
- `D:\database\signal_daily\factor=60日动量`
- `D:\database\signal_daily\factor=120日动量`
- `D:\database\signal_daily\factor=252日动量`
- `D:\database\signal_daily\factor=纯动量`
- `D:\database\signal_daily\factor=60日纯动量`
- `D:\database\signal_daily\factor=252日纯动量`

- [x] Resolve and verify every deletion target is an immediate child of `D:\database\signal_daily`.
- [x] Remove only the seven directories above.
- [x] Run the existing factor generator with only `momentum_common` and the seven target keys enabled.
- [x] Verify the rebuilt data spans the available source history, contains no synthetic zero rows for unavailable observations, and respects the 250-observation eligibility rule.
