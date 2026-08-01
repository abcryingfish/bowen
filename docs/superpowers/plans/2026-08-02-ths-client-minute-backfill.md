# 同花顺客户端板块分钟数据补全 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (not used here because the repository task is being executed inline).

**Goal:** Remove all external行情请求 from the THS minute pipeline and provide a resumable client-only acquisition, parsing, validation, and retry workflow.

**Architecture:** Keep the existing Parquet normalization and daily partition merge logic. Replace the Fuyao request adapter with a local client adapter that drives the standard download/export windows where supported, records the client cache windows that require historical replay, and never writes a window as complete without a validation result.

**Tech Stack:** Python 3.10, ctypes Win32 messaging, Polars, DuckDB, pytest, local 同花顺 `hexin.exe`/`HxDataService.exe`.

---

### Task 1: Lock the source boundary with tests

**Files:**
- Modify: `test_ths_sector_minute.py`
- Modify: `工具/获得同花顺板块分钟级数据.py`

- [ ] **Step 1: Write the failing tests**

Add tests asserting the production module has no Fuyao URL, no auth-token argument, no `urllib.request`, and exposes a client export parser plus a client-only source error for unavailable historical windows.

- [ ] **Step 2: Run the focused tests**

Run `\.venv\Scripts\python.exe -m pytest test_ths_sector_minute.py -q` and confirm the new source-boundary tests fail against the current Fuyao implementation.

- [ ] **Step 3: Remove the external request adapter**

Delete `QUOTE_URL`, `DEFAULT_FUYAO_AUTH`, `_request_headers`, `build_request_payload`, `fetch_quote_window`, and the Fuyao CLI option. Replace the request call site with a `ClientMinuteSource` interface whose implementation only accepts local export/cache files.

- [ ] **Step 4: Run focused tests again**

Run the same command and confirm all source-boundary and existing normalization tests pass.

### Task 2: Implement client export parsing and safe persistence

**Files:**
- Modify: `工具/获得同花顺板块分钟级数据.py`
- Modify: `test_ths_sector_minute.py`

- [ ] **Step 1: Add failing parser tests**

Cover UTF-8 BOM, UTF-8, GB18030, tab/comma delimiters, Chinese/English headers, code normalization to `.THS`, minute timestamp parsing, and rejection of rows outside the requested window.

- [ ] **Step 2: Implement the parser**

Read bytes, decode using BOM/UTF-8/GB18030 fallback, detect the delimiter with `csv.Sniffer`, map localized columns, and return the existing `OUTPUT_SCHEMA` without changing stock-minute semantics.

- [ ] **Step 3: Add atomic merge tests**

Verify duplicate `htsc_code + time` rows collapse to one row, failed validation leaves the previous `merged.parquet` untouched, and a successful retry removes temporary part files.

- [ ] **Step 4: Implement atomic merge**

Write temporary Parquet files, read them back, validate, then replace only touched day partitions. Preserve existing `_meta` state and UTF-8-BOM failure reports.

### Task 3: Add Win32 client orchestration and resumable state

**Files:**
- Create: `工具/ths_client_automation.py`
- Modify: `工具/获得同花顺板块分钟级数据.py`
- Create: `test_ths_client_automation.py`

- [ ] **Step 1: Add failing automation tests**

Test window discovery by title/class, visible duplicate-control selection, Win64 remote `SYSTEMTIME` transfer, and rejection of any non-client source path.

- [ ] **Step 2: Implement bounded Win32 helpers**

Use `EnumWindows`/`EnumChildWindows`, `PostMessage`/`SendMessageTimeout`, visible-control filtering, remote-process memory for pointer-bearing messages, and window-relative coordinates. Never use a network URL or store credentials.

- [ ] **Step 3: Implement task state**

Persist code, date window, attempt, export path, status, and error in `_meta/ths_client_minute_state.parquet`. On restart load only pending/failed windows.

- [ ] **Step 4: Implement client-only stages**

Use the export dialog for windows the client exposes. For historical windows that the client reports unavailable to export, mark `needs_history_replay` with the exact date and cache path; do not mark them successful.

### Task 4: Validate, retry, and produce the final report

**Files:**
- Modify: `工具/获得同花顺板块分钟级数据.py`
- Create: `工具/检查同花顺板块分钟完整性.py`
- Create: `test_ths_minute_integrity.py`

- [ ] **Step 1: Add failing integrity tests**

Cover effective trading-day baselines, missing days, duplicate minutes, non-monotone timestamps, 241/242 client grids, OHLC constraints, and non-negative volume/amount.

- [ ] **Step 2: Implement integrity scan**

Scan local client-exported daily/minute data, infer the observed client grid per period, and emit CSV/JSON missing-window reports.

- [ ] **Step 3: Implement retry escalation**

Retry batch/year, then code/month, then code/day; restart the client service between escalation levels. Re-scan after every pass and continue until the pending queue is empty or the client itself reports a source-unavailable window.

- [ ] **Step 4: Run verification**

Run all focused tests, then the existing visualization tests. Inspect `logs_2.sqlite` trigger, TRACE count/max id, and WAL size before and after a dry-run.

### Task 5: Start the client-only batch job

**Files:**
- Use: `工具/获得同花顺板块分钟级数据.py`
- Write: `D:\database\index_data_mins\_meta\ths_client_minute_report.json`

- [ ] **Step 1:** Run a dry-run for the database’s existing `.THS` universe.
- [ ] **Step 2:** Run a single-code `881102.THS` probe against the known missing windows.
- [ ] **Step 3:** Re-scan and retry only unresolved windows.
- [ ] **Step 4:** Start the full 500+ code batch with checkpoint state and leave the process resumable.
- [ ] **Step 5:** Return only after the final report shows zero actionable missing windows, or clearly report client-source-unavailable windows with evidence.
