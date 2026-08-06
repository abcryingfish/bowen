# Multi-Period Momentum, Low-Volatility, and Liquidity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add registered stock-level multi-period momentum, low-volatility, and turnover/amount liquidity factors without changing existing factor formulas.

**Architecture:** Extend the existing `momentum_common` bundle for 20/60/252-day stock momentum and add two focused bundles: `low_volatility` for stock-level risk measures and `liquidity` for rolling amount/turnover/Amihud measures. Reuse the generator's existing bundle registry, factor catalog, valid-bar handling, and `signal_daily` output path.

**Tech Stack:** Python, pandas, NumPy, DuckDB, pytest, UTF-8 JSON/Python source.

---

### Task 1: Lock factor formulas with unit tests

**Files:**
- Modify: `ZXW因子/test_momentum_factor_bundle.py`
- Create: `ZXW因子/test_low_volatility_factor_bundle.py`
- Create: `ZXW因子/test_liquidity_factor_bundle.py`

- [ ] **Step 1: Add failing assertions for 20/60/252 momentum and pure momentum variants**

Use deterministic close data and assert `close / close.shift(window) - 1`; pure momentum is the 120-day return minus the 20-day return for the legacy factor and each new long window minus the 20-day return for new variants.

- [ ] **Step 2: Run the focused momentum tests and verify they fail because the new factor keys are absent**

Run: `& '.\.venv\Scripts\python.exe' -m pytest 'ZXW因子/test_momentum_factor_bundle.py' -q`

- [ ] **Step 3: Add failing low-volatility tests**

Assert annualized volatility, downside volatility, maximum drawdown, ATR volatility, and volatility ratio against direct pandas formulas; assert invalid/zero-price bars remain `NaN`.

- [ ] **Step 4: Add failing liquidity tests**

Use a temporary parquet source with `value`, `turnover_rate`, and close data; assert rolling mean amount, turnover, Amihud (`abs(return) / amount`), amount volatility, and zero-amount ratio.

- [ ] **Step 5: Run the new tests and verify expected failures**

Run: `& '.\.venv\Scripts\python.exe' -m pytest 'ZXW因子/test_low_volatility_factor_bundle.py' 'ZXW因子/test_liquidity_factor_bundle.py' -q`

### Task 2: Implement multi-period momentum and low-volatility bundles

**Files:**
- Modify: `ZXW因子/板块动量策略常用因子.py`
- Create: `ZXW因子/低波因子.py`

- [ ] **Step 1: Add 20/60/252 momentum keys, lookbacks, factor map, and matrices**

Keep `momentum_120d`, `pure_momentum`, and all existing sector formulas unchanged. Add `momentum_20d`, `momentum_60d`, `momentum_252d`, `pure_momentum_60d`, and `pure_momentum_252d` using the same aligned close matrix and `NaN` warm-up behavior.

- [ ] **Step 2: Implement `低波因子.py` with one public builder and catalog**

Expose `build_low_volatility_factor_bundle(C, H=None, L=None)`. Calculate stock-level `annual_vol_20d`, `annual_vol_60d`, `annual_vol_252d`, `downside_vol_20d`, `downside_vol_60d`, `max_drawdown_60d`, `atr_volatility_14d`, and `volatility_ratio_20_60d`. Use `preserve_nan=True` for warm-up and invalid bars.

- [ ] **Step 3: Run focused tests and verify green**

Run: `& '.\.venv\Scripts\python.exe' -m pytest 'ZXW因子/test_momentum_factor_bundle.py' 'ZXW因子/test_low_volatility_factor_bundle.py' -q`

### Task 3: Implement amount-based liquidity bundle

**Files:**
- Modify: `ZXW因子/股票市场数据因子.py`
- Create: `ZXW因子/流动性因子.py`
- Create: `ZXW因子/test_liquidity_factor_bundle.py`

- [ ] **Step 1: Extend the DuckDB query to read `value` and preserve existing market factors**

Do not change the existing four output keys. Read `value` as `trading_value` and align it by `time`/`htsc_code`.

- [ ] **Step 2: Implement the liquidity builder**

Expose `build_liquidity_factor_bundle(C, stock_codes, source_glob=...)`. Output `avg_trading_value_20d`, `avg_trading_value_60d`, `avg_turnover_20d`, `avg_turnover_60d`, `amihud_20d`, `trading_value_volatility_20d`, and `zero_trading_value_ratio_20d`. Preserve source-date validation and stop-on-stale-source behavior.

- [ ] **Step 3: Run liquidity tests and existing market-data tests**

Run: `& '.\.venv\Scripts\python.exe' -m pytest 'ZXW因子/test_liquidity_factor_bundle.py' 'ZXW因子/test_stock_market_data_factors.py' -q`

### Task 4: Register bundles and frontend catalog

**Files:**
- Modify: `ZXW因子/ZXW策略技术因子生成.py`
- Modify: `因子分类/factor_catalog.json`
- Modify: `可视化/market_data_service.py` if factor aliases are required by the existing API catalog
- Add/modify bundle catalog tests under `ZXW因子/`

- [ ] **Step 1: Register imports, bundle IDs, lookback registries, and build branches**

Add `low_volatility` and `liquidity` to the same registry paths used by existing bundles; ensure requested-factor planning includes their maximum lookback days.

- [ ] **Step 2: Add Chinese factor labels and group entries to UTF-8 `factor_catalog.json`**

Keep existing group IDs and factor names unchanged; add new groups for `low_volatility` and `liquidity`, and add the new momentum children to `momentum_common`.

- [ ] **Step 3: Run catalog and planner tests**

Run: `& '.\.venv\Scripts\python.exe' -m pytest 'ZXW因子/test_factor_auto_plan_valid_values.py' 'ZXW因子/test_momentum_factor_bundle.py' 'ZXW因子/test_stock_market_data_catalog.py' -q`

### Task 5: Full verification and regression review

**Files:**
- No additional files.

- [ ] **Step 1: Check syntax and diff encoding**

Run: `& '.\.venv\Scripts\python.exe' -m compileall 'ZXW因子' -q` and `git diff --check`.

- [ ] **Step 2: Run the complete relevant factor suite**

Run: `& '.\.venv\Scripts\python.exe' -m pytest 'ZXW因子' -q`

- [ ] **Step 3: Review output keys and legacy compatibility**

Confirm old factor keys remain present, new factors have explicit lookback values, and no source code or JSON is written with a non-UTF-8 encoding.
