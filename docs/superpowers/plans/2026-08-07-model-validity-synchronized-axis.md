# Model Validity Synchronized Axis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Synchronize every model-validity chart to one date window and re-base each visible curve to 100 at its first valid point in that window.

**Architecture:** Keep each API payload immutable in chart state. A page-level coordinator listens to the source chart's visible time range, applies the same date range to every chart under a re-entrancy guard, and re-renders normalized series from raw data. Range buttons use the same coordinator path after charts are rebuilt.

**Tech Stack:** Vanilla JavaScript, Lightweight Charts, existing Node page-contract test.

---

### Task 1: Add pure time-window normalization helpers

**Files:**
- Modify: `可视化/模型有效性/model_validity.js`
- Test: `test_model_validity_page.js`

- [ ] Add `normalizeSeriesForRange(data, from, to)` that filters points inside the date range, finds the first finite value, and maps each point to `{ time, value: raw / base * 100 }`; return `[]` when no valid base exists.
- [ ] Add `normalizePayloadForRange(rawSeries, range)` to normalize `high`, `low`, and `relative` independently without mutating API arrays.
- [ ] Extend the page contract test to assert these helper names/behaviors are present in the script source.
- [ ] Run `node test_model_validity_page.js`; expected result is the existing contract failure until the helpers are wired into chart rendering.

### Task 2: Store raw chart data and synchronize visible ranges

**Files:**
- Modify: `可视化/模型有效性/model_validity.js`

- [ ] Add page state fields `visibleRange` and `syncingTimeRange`.
- [ ] Store `{ chart, series, rawSeries, card }` in `state.charts` after `setData` uses the raw payload.
- [ ] Add `subscribeChartTimeRange(chart)` using `chart.timeScale().subscribeVisibleTimeRangeChange`; ignore null ranges and nested events, then apply the source `{ from, to }` with `setVisibleRange` to every other chart.
- [ ] After applying the shared range, call a render helper that replaces each series data with `normalizePayloadForRange(rawSeries, range)`. Keep the current range in state so later charts use it.
- [ ] Use date-range synchronization, never logical indexes, so charts with different history lengths remain aligned.

### Task 3: Apply one range during initial load and range changes

**Files:**
- Modify: `可视化/模型有效性/model_validity.js`

- [ ] After all model charts finish loading, derive the requested `state.range` bounds from the union of loaded raw dates and call the coordinator once; retain the existing `60d`, `1y`, and `all` semantics.
- [ ] When a range button rebuilds charts, clear the prior coordinator state, load all charts, then apply one shared range so no card calls an independent `fitContent()`.
- [ ] Replace the per-chart `fitContent()` call with the shared-range initialization path.
- [ ] Preserve series legend visibility after normalized `setData` updates.

### Task 4: Verify behavior and regression safety

**Files:**
- Modify: `test_model_validity_page.js` if assertions need exact helper contracts.

- [ ] Run `node test_model_validity_page.js`; expected output: `模型有效性页面契约通过`.
- [ ] Run the style-monitor/API tests with `.venv\Scripts\python.exe -m pytest ... -q`; expected result: all existing tests pass.
- [ ] Open `http://127.0.0.1:8086/模型有效性/index.html` and verify dragging/zooming one card changes every card's visible dates, range buttons preserve one shared window, and each in-window first valid point is 100.
- [ ] Commit the implementation and focused test changes with `feat: synchronize model validity chart ranges`.
