# THS Sector Minute Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route all THS sector codes to their existing minute Parquet data and expose them through the same chart workflow as stocks.

**Architecture:** Extend the existing market-data service with an index-minute root, route `.THS` codes to it only for `1min`, include that root in day-partition discovery, and expose the THS universe in code search for both intervals. The existing frontend requires no separate rendering path.

**Tech Stack:** Python 3.10, DuckDB, Polars, pytest, existing browser JavaScript.

---

### Task 1: Add failing regression tests

**Files:**
- Modify: `test_market_data_service_index_search.py`
- Create: `test_ths_sector_minute_chart.py`

- [ ] Add tests asserting `get_base_path_by_code_and_interval("881101.THS", "1min")` returns `D:\\database\\index_data_mins`, the same code remains on `index_data_daily` for `1day`, and minute partition paths include the THS minute root.
- [ ] Add a search test with a temporary THS universe and interval `1min`, asserting the result includes `.THS` code and name.
- [ ] Run the focused tests and confirm they fail because the current service rejects index minute queries and omits the THS universe for `1min`.

### Task 2: Implement THS minute routing and search

**Files:**
- Modify: `可视化/market_data_service.py`

- [ ] Add `INDEX_MINUTE_BASE_PATH = r"D:\\database\\index_data_mins"`.
- [ ] In `get_base_path_by_code_and_interval`, route index codes ending in `.THS` to `INDEX_MINUTE_BASE_PATH` for `1min`; keep other index codes daily-only and keep `1day` on `INDEX_DAILY_BASE_PATH`.
- [ ] Include `INDEX_MINUTE_BASE_PATH` in the minute-base set used by `build_partition_paths`.
- [ ] Load index universe records in `search_market_codes` for both intervals, while only advertising the minute-capable THS records when `interval == "1min"`; retain existing daily fallback index records for `1day`.
- [ ] Preserve the user’s unrelated working-tree edits in this file.

### Task 3: Verify API and frontend behavior

**Files:**
- No frontend source change expected; verify `可视化/量化因子/index.html` and `可视化/shared/chart_board_core.js` use the existing interval and `/api/market/bars` flow.

- [ ] Run the new and existing market-data tests.
- [ ] Compile `可视化/market_data_service.py` and run a live query for one available `.THS` code across a known minute range, checking non-empty bars and `meta.base_path`.
- [ ] Start the existing visualization server if not already running and verify the page can search a THS name/code, switch to `1min`, and render the curve without a JavaScript error.
