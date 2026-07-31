# THS Sector Minute Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone downloader for the current THS software-level-one universe (`881/882/885/886`) that backfills valid 1-minute history from 2010 into the existing daily Parquet layout and discovers new boards on later runs.

**Architecture:** Read the live THS client name table on every run, diff it against a Parquet universe snapshot, and request one code per calendar-month window from `single_kline`. Normalize responses to the stock-minute schema, write idempotent daily partitions, and persist code-month completion state in Parquet so interrupted runs resume without SQLite.

**Tech Stack:** Python 3.10, Polars, DuckDB, urllib, pytest, THS client files and Fuyao quote API.

---

### Task 1: Establish module contract and month windows

**Files:**
- Create: `工具/获得同花顺板块分钟级数据.py`
- Create: `test_ths_sector_minute.py`

- [ ] **Step 1: Write failing tests for module constants and month windows**

```python
def test_iter_month_windows_covers_requested_range(module):
    windows = module.iter_month_windows(date(2010, 1, 15), date(2010, 3, 2))
    assert windows == [
        (date(2010, 1, 15), date(2010, 1, 31)),
        (date(2010, 2, 1), date(2010, 2, 28)),
        (date(2010, 3, 1), date(2010, 3, 2)),
    ]
    assert module.BASE_DIR == Path(r"D:\database\index_data_mins")
```

- [ ] **Step 2: Run the test and verify RED**

Run: `.venv\Scripts\python.exe -m pytest test_ths_sector_minute.py -q`

Expected: FAIL because `工具/获得同花顺板块分钟级数据.py` does not exist.

- [ ] **Step 3: Create the module skeleton and month implementation**

```python
BASE_DIR = Path(r"D:\database\index_data_mins")
SOFTWARE_LEVEL1_PREFIXES = ("881", "882", "885", "886")

def iter_month_windows(start: date, end: date) -> list[tuple[date, date]]:
    result = []
    cursor = start
    while cursor <= end:
        month_end = date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1])
        result.append((cursor, min(month_end, end)))
        cursor = month_end + timedelta(days=1)
    return result
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest test_ths_sector_minute.py -q`

Expected: PASS.

### Task 2: Discover the dynamic software-level-one universe

**Files:**
- Modify: `工具/获得同花顺板块分钟级数据.py`
- Modify: `test_ths_sector_minute.py`

- [ ] **Step 1: Add failing tests for included/excluded prefixes and snapshot diff**

```python
def test_load_client_universe_only_includes_software_level1(module, tmp_path):
    source = tmp_path / "stockname_48_0.txt"
    source.write_bytes("881101=种植业与林业\n883300=沪深300\n884001=种子生产\n886999=新增板块\n".encode("gb18030"))
    rows = module.load_client_universe(source)
    assert [row["security_id"] for row in rows] == ["881101", "886999"]

def test_merge_universe_marks_removed_and_new_codes(module):
    merged = module.merge_universe_snapshot(current_rows, previous_frame, observed_at)
    assert merged.filter(pl.col("security_id") == "886999")["is_active"].item()
    assert not merged.filter(pl.col("security_id") == "881999")["is_active"].item()
```

- [ ] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest test_ths_sector_minute.py -q`

Expected: FAIL because universe functions are missing.

- [ ] **Step 3: Implement GB18030 parsing, validation, snapshot merge and atomic Parquet write**

```python
def load_client_universe(path: Path) -> list[dict[str, str]]:
    rows = {}
    for line in path.read_bytes().decode("gb18030").splitlines():
        if "=" not in line:
            continue
        code, name = (part.strip() for part in line.split("=", 1))
        if len(code) == 6 and code.isdigit() and code.startswith(SOFTWARE_LEVEL1_PREFIXES):
            if not name or code in rows:
                raise ValueError(f"THS板块名称表异常: {code}")
            rows[code] = name
    if not rows:
        raise ValueError("未从客户端名称表发现软件一级板块")
    return [{"security_id": code, "htsc_code": f"{code}.THS", "name": rows[code]} for code in sorted(rows)]
```

- [ ] **Step 4: Verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest test_ths_sector_minute.py -q`

Expected: PASS.

### Task 3: Build and parse Fuyao requests safely

**Files:**
- Modify: `工具/获得同花顺板块分钟级数据.py`
- Modify: `test_ths_sector_minute.py`

- [ ] **Step 1: Add failing tests for payload, field mapping, empty history and auth errors**

```python
def test_parse_quote_payload_maps_fields_and_preserves_nullable_volume(module):
    payload = {"status_code": 0, "data": {"quote_data": [{
        "market": "48", "code": "881101",
        "data_fields": ["1", "7", "8", "9", "11", "13", "19"],
        "value": [[1514856600000, 10.0, 11.0, 9.0, 10.5, None, None]],
    }]}}
    rows = module.parse_quote_payload(payload, "881101", date(2018, 1, 1), date(2018, 1, 31))
    assert rows[0]["close"] == 10.5
    assert rows[0]["volume"] is None

def test_parse_quote_payload_rejects_nonzero_status(module):
    with pytest.raises(module.QuoteAuthError):
        module.parse_quote_payload({"status_code": 401}, "881101", date(2018, 1, 1), date(2018, 1, 31))
```

- [ ] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest test_ths_sector_minute.py -q`

- [ ] **Step 3: Implement request construction, Shanghai timestamp conversion, strict response parsing and retry**

```python
FIELD_IDS = {"1": "timestamp", "7": "open", "8": "high", "9": "low", "11": "close", "13": "volume", "19": "amount"}

def build_request_payload(code: str, start: date, end: date) -> dict[str, object]:
    return {
        "code_list": [{"codes": [code], "market": "48"}],
        "trade_class": "intraday", "time_period": "min_1", "trade_date": 0,
        "begin_time": shanghai_millis(start, dt_time(9, 30)),
        "end_time": shanghai_millis(end, dt_time(15, 0)),
        "adjust_type": "actual", "gpid": 2,
    }
```

- [ ] **Step 4: Verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest test_ths_sector_minute.py -q`

Expected: PASS with no live network calls.

### Task 4: Normalize schema and continuous derived columns

**Files:**
- Modify: `工具/获得同花顺板块分钟级数据.py`
- Modify: `test_ths_sector_minute.py`

- [ ] **Step 1: Add failing tests for schema, OHLC validation and cross-window previous close**

```python
def test_normalize_rows_matches_stock_minute_schema(module):
    frame, last_close, next_index = module.normalize_rows(raw_rows, "881101", prior_close=9.5, index_offset=7)
    assert frame.columns == module.OUTPUT_COLUMNS
    assert frame.schema == module.OUTPUT_SCHEMA
    assert frame["pre_close"].to_list() == pytest.approx([9.5, 10.5])
    assert frame["__index_level_0__"].to_list() == [7, 8]
    assert last_close == 11.0 and next_index == 9

def test_normalize_rows_rejects_invalid_ohlc(module):
    with pytest.raises(ValueError, match="OHLC"):
        module.normalize_rows(invalid_rows, "881101", None, 0)
```

- [ ] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest test_ths_sector_minute.py -q`

- [ ] **Step 3: Implement exact types, ordering, nullable volume/amount and derived columns**

Use Polars expressions and explicit casts; calculate `pre_close` from shift with the supplied prior close, then `change` and `pct_chg` as Float32.

- [ ] **Step 4: Verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest test_ths_sector_minute.py -q`

### Task 5: Implement idempotent daily Parquet merge and state Parquet

**Files:**
- Modify: `工具/获得同花顺板块分钟级数据.py`
- Modify: `test_ths_sector_minute.py`

- [ ] **Step 1: Add failing filesystem tests**

```python
def test_merge_daily_partition_is_idempotent(module, tmp_path):
    touched = module.write_daily_parts(frame, tmp_path)
    module.rebuild_daily_partitions(tmp_path, touched)
    module.write_daily_parts(frame, tmp_path)
    module.rebuild_daily_partitions(tmp_path, touched)
    saved = pl.read_parquet(tmp_path / "year=2018/month=01/day=02/merged.parquet")
    assert saved.height == frame.height
    assert saved.unique(["htsc_code", "time"]).height == frame.height

def test_state_round_trip_keeps_empty_and_failed_windows(module, tmp_path):
    module.write_download_state(state_rows, tmp_path / "_meta/ths_minute_download_state.parquet")
    loaded = module.read_download_state(tmp_path / "_meta/ths_minute_download_state.parquet")
    assert loaded[("881101.THS", "2010-01")].status == "empty"
```

- [ ] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest test_ths_sector_minute.py -q`

- [ ] **Step 3: Copy the existing stock-minute daily partition pattern and adapt it locally**

Implement `write_daily_parts`, `rebuild_daily_partitions`, `_normalize_merged`, `read_download_state`, and atomic `write_download_state`. Keep all code in the new module; do not create a shared helper.

- [ ] **Step 4: Verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest test_ths_sector_minute.py -q`

### Task 6: Orchestrate resumable full backfill

**Files:**
- Modify: `工具/获得同花顺板块分钟级数据.py`
- Modify: `test_ths_sector_minute.py`

- [ ] **Step 1: Add failing plan tests**

```python
def test_build_plan_skips_success_and_empty_but_retries_failed(module):
    plan = module.build_download_plan(universe, windows, state)
    assert ("881101.THS", "2010-01") not in plan
    assert ("881102.THS", "2010-01") in plan

def test_failure_blocks_later_months_for_same_code(module):
    result = module.run_download_plan(plan, fake_fetcher_that_fails_february, sink)
    assert result.requested_months["881101.THS"] == ["2010-01", "2010-02"]
```

- [ ] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest test_ths_sector_minute.py -q`

- [ ] **Step 3: Implement CLI and month-major bounded concurrency**

Support `--base-dir`, `--default-start`, `--end`, `--codes`, `--workers`, `--timeout`, `--retries`, `--auth-token`, `--include-current-day`, `--dry-run`, and `--rebuild-only`. Commit `success/empty` state only after affected Parquet partitions rebuild successfully. If one code fails, do not process later months for that code during the same run.

- [ ] **Step 4: Verify GREEN and CLI help**

Run: `.venv\Scripts\python.exe -m pytest test_ths_sector_minute.py -q`

Run: `.venv\Scripts\python.exe "工具\获得同花顺板块分钟级数据.py" --help`

Expected: tests pass and all documented options appear.

### Task 7: Register a separate merged-entry stage

**Files:**
- Modify: `工具/全量数据更新_合并入口.py`
- Modify: `test_ths_sector_minute.py`

- [ ] **Step 1: Add a failing stage registration test**

```python
def test_combined_entry_registers_ths_index_mins(entry_module):
    stage = next(stage for stage in entry_module.STAGES if stage.key == "ths_index_mins")
    assert stage.script_name == "获得同花顺板块分钟级数据.py"
```

- [ ] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest test_ths_sector_minute.py -q`

- [ ] **Step 3: Add the independent stage and passthrough argument**

Add `Stage("ths_index_mins", "同花顺板块分钟级数据", "获得同花顺板块分钟级数据.py")`, alias `ths_mins`, CLI `--ths-index-mins-args`, and mapping in `_build_stage_args`.

- [ ] **Step 4: Verify GREEN and dry-run command construction**

Run: `.venv\Scripts\python.exe -m pytest test_ths_sector_minute.py -q`

Run: `.venv\Scripts\python.exe "工具\全量数据更新_合并入口.py" --only ths_index_mins --dry-run`

### Task 8: Smoke-test then start the full job

**Files:**
- Write smoke data only under: project temporary directory
- Write full data under: `D:\database\index_data_mins`

- [ ] **Step 1: Run the complete unit suite and syntax check**

Run: `.venv\Scripts\python.exe -m pytest test_ths_sector_minute.py test_minute_end_time_cutoff.py -q`

Run: `.venv\Scripts\python.exe -m py_compile "工具\获得同花顺板块分钟级数据.py" "工具\全量数据更新_合并入口.py"`

- [ ] **Step 2: Run a two-code one-month smoke download to a temporary directory**

Run: `.venv\Scripts\python.exe "工具\获得同花顺板块分钟级数据.py" --base-dir .tmp\ths_minute_smoke --default-start 2018-01-01 --end 2018-01-31 --codes 881101 881102 --workers 2`

- [ ] **Step 3: Verify smoke Parquet**

Check exact schema, unique `(htsc_code,time)`, OHLC validity, nullable nonnegative volume/amount, first/last timestamps, state status, and absence of leftover part files.

- [ ] **Step 4: Start the full resumable backfill**

Run after smoke validation:

`.venv\Scripts\python.exe "工具\获得同花顺板块分钟级数据.py" --base-dir D:\database\index_data_mins --default-start 2010-01-01 --workers 6`

The process may run for hours. Preserve stdout/stderr logs, monitor progress without interrupting, and report failures from `_meta` rather than claiming full completion prematurely.
