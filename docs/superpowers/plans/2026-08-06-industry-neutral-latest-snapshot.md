# Industry-Neutral Latest Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make value and growth industry-neutral scores start at 2010 and use one latest available THS 881 snapshot for all historical score dates.

**Architecture:** Keep raw factor loading and industry ranking unchanged. Add an explicit latest-only snapshot selection and a fixed-snapshot industry frame mode; the bundle builders use the runtime latest available snapshot independently of the requested score end date.

**Tech Stack:** Python, pandas, Parquet, pytest.

---

### Task 1: Lock the latest-snapshot contract with tests

**Files:**
- Modify: `ZXW因子/test_stock_growth_industry_normalized_factors.py`
- Modify: `ZXW因子/test_stock_value_model_industry_normalized_score.py`

- [ ] Add tests that select only the maximum snapshot partition and apply its industry mapping to dates before that partition.
- [ ] Update model-start expectations to accept dates from 2010 onward.
- [ ] Run the focused tests and verify they fail against the current 2026-07-15 and as-of-date behavior.

### Task 2: Implement fixed latest snapshot behavior

**Files:**
- Modify: `ZXW因子/股票成长行业标准化因子.py`
- Modify: `ZXW因子/股票价值模型行业标准化评分.py`

- [ ] Set `MODEL_START_DATE` to 2010-01-01.
- [ ] Add latest-only snapshot selection and a fixed latest mapping mode.
- [ ] Make both bundle builders load the latest available snapshot even when `end_date` is earlier than that snapshot.
- [ ] Update lookback metadata to advertise the 2010 start and fixed-latest policy.

### Task 3: Verify

- [ ] Run both focused test files.
- [ ] Run the related factor-generation contract tests and compile the two generators.
- [ ] Confirm the latest snapshot date and raw factor availability are reported before any full generation.
