# Style Monitor Ledger Full Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the stale style-monitor ledger and rebuild all configured style portfolios from their available factor history.

**Architecture:** Stop the API worker that owns the DuckDB writer, delete only `style_monitor.duckdb`, run the existing incremental engine against a new empty database through `2026-08-03`, then restart the API and verify the neutral model curves. Generated factor Parquet data is read-only during this operation.

**Tech Stack:** Python 3.10, DuckDB, existing style portfolio monitor service, PowerShell, HTTP API.

---

### Task 1: Stop the active ledger writer

**Files:**
- Delete later: `D:\database\style_portfolio_monitor\style_monitor.duckdb`

- [ ] Confirm the active update job and the exact PID listening on port 8000.
- [ ] Stop only the API process tree that owns port 8000.
- [ ] Verify that port 8000 is no longer listening and the DuckDB file is unlocked.

### Task 2: Remove and rebuild the ledger

**Files:**
- Delete: `D:\database\style_portfolio_monitor\style_monitor.duckdb`
- Create through existing service: `D:\database\style_portfolio_monitor\style_monitor.duckdb`

- [ ] Delete the old DuckDB file after resolving its absolute path.
- [ ] Run `run_incremental_update(through_date=date(2026, 8, 3))` with the existing ten model definitions.
- [ ] Verify that all ten models complete without paused or failed models.

### Task 3: Restore and verify the frontend API

**Files:**
- Read: `可视化/api_server.py`
- Read: `可视化/模型有效性/model_validity.js`

- [ ] Restart the API on `127.0.0.1:8000` using `.venv\Scripts\python.exe`.
- [ ] Verify `/api/style-monitor/summary` returns all ten models.
- [ ] Verify growth/value industry-neutral `range=all` curves begin before 2020 and end on `2026-08-03`.
- [ ] Run the style-monitor tests and the page contract test.
