# Model Validity Lookback Days Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a numeric lookback-days control anchored to `style-range-end` while preserving manual From/To and existing preset ranges.

**Architecture:** Keep the existing `custom` API request and date inputs. Add a page-only numeric input; when applying, subtract `lookbackDays - 1` calendar days from the end date to populate the start date, then reuse the current custom-range flow.

**Tech Stack:** Vanilla HTML/CSS/JavaScript and the existing Node page-contract test.

---

### Task 1: Add the failing page contract

**Files:**
- Modify: `test_model_validity_page.js`
- Create: `test_model_validity_lookback.js`

- [x] Assert the page has `style-range-lookback` and the script contains the lookback calculation and validation behavior.
- [x] Run `node test_model_validity_page.js` and confirm it fails because the new control/logic is absent.

### Task 2: Add the lookback control and calculation

**Files:**
- Modify: `可视化/模型有效性/index.html`
- Modify: `可视化/模型有效性/model_validity.css`
- Modify: `可视化/模型有效性/model_validity.js`

- [x] Add a numeric input before `style-range-end`, with a positive minimum and a clear Chinese label.
- [x] Add `calculateLookbackStart(endDate, days)` using calendar-day subtraction and format the result as `YYYY-MM-DD`.
- [x] In `applyCustomRange`, use the calculated start when lookback days is entered; retain manual From when it is empty.
- [x] Reject non-positive or non-finite lookback values with the existing range status message and keep the backend contract unchanged.

### Task 3: Verify regression safety

**Files:**
- No additional production files.

- [x] Run `node test_model_validity_page.js`.
- [x] Run `.venv\Scripts\python.exe -m pytest -q "backtrader/tests/style_portfolio_monitor" "可视化/test_style_monitor_job_service.py"`.
- [x] Confirm only the requested page, stylesheet, test, and plan files changed.
