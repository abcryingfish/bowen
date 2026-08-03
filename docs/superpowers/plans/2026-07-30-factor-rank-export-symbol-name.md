# Factor Rank Export Symbol Name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Chinese symbol-name column to factor-rank CSV exports while preserving row selection, ranking, and UTF-8 Excel compatibility.

**Architecture:** Keep the existing browser button and API contract unchanged. In `market_data_service.py`, build an in-memory code-to-name lookup from the existing stock, ETF, and index universe loaders, then enrich CSV rows during the existing export pass; unknown codes receive an empty name.

**Tech Stack:** Python 3.10, pytest, pandas/Parquet test fixtures, DuckDB, Python `csv` with `utf-8-sig`.

---

### Task 1: Specify the enriched CSV behavior

**Files:**
- Modify: `可视化/test_market_data_service_factor_export_rank.py`

- [x] **Step 1: Extend the existing export test with names and a missing-name case**

```python
monkeypatch.setattr(
    service,
    "_load_stock_universe_records",
    lambda: [{"code": "881101.THS", "name": "行业甲"}],
)
monkeypatch.setattr(service, "_load_etf_universe_records", lambda: [])
monkeypatch.setattr(service, "_load_index_universe_records", lambda: [])

assert list(rows[0]) == ["时间", "标的代码", "标的名称", "因子值"]
assert [row["标的名称"] for row in rows] == ["行业甲", ""]
```

- [x] **Step 2: Run the focused test and verify RED**

Run: `.venv\Scripts\python.exe -m pytest 可视化/test_market_data_service_factor_export_rank.py -q`

Expected: FAIL because the CSV has no `标的名称` column.

### Task 2: Enrich factor-rank CSV rows

**Files:**
- Modify: `可视化/market_data_service.py:3796`

- [x] **Step 1: Build a local name lookup from existing universe loaders**

```python
name_by_code: dict[str, str] = {}
for records in (
    _load_stock_universe_records(),
    _load_etf_universe_records(),
    _load_index_universe_records(),
):
    for item in records:
        code = str(item.get("code") or "").strip().upper()
        if code and code not in name_by_code:
            name_by_code[code] = str(item.get("name") or "").strip()
```

- [x] **Step 2: Add the name to each row and CSV header**

```python
rows_for_csv.append((export_date, code, name_by_code.get(code, ""), value_by_code.get(code)))
writer.writerow(["时间", "标的代码", "标的名称", "因子值"])
```

Keep the current descending factor-value sort, using the updated tuple index for the factor value.

- [x] **Step 3: Run the focused test and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest 可视化/test_market_data_service_factor_export_rank.py -q`

Expected: `1 passed`.

### Task 3: Regression verification

**Files:**
- Verify: `可视化/market_data_service.py`
- Verify: `可视化/test_market_data_service_factor_export_rank.py`

- [x] **Step 1: Run related market-data tests**

Run: `.venv\Scripts\python.exe -m pytest 可视化/test_market_data_service_factor_export_rank.py 可视化/test_market_data_service_index_search.py -q`

Expected: all tests pass.

- [x] **Step 2: Compile the modified Python files**

Run: `.venv\Scripts\python.exe -m py_compile 可视化/market_data_service.py 可视化/test_market_data_service_factor_export_rank.py`

Expected: exit code 0 with no output.
