# Model Validity Synchronized Axis Design

## Goal

All style portfolio charts on the model-validity page share one visible time window. Dragging or zooming any chart synchronizes the same date range to every other chart. Within that window, each curve is re-based to 100 at its first valid trading day.

## Scope

- Modify only `可视化/模型有效性/model_validity.js` and focused page tests.
- Keep the backend API, DuckDB ledger, and raw curve data unchanged.
- Preserve existing range selectors, series visibility toggles, model details, and manual update behavior.

## Design

Each model chart stores its chart instance, immutable raw series, and rendered series. A page-level time-axis coordinator is added:

1. Subscribe each chart to `timeScale().subscribeVisibleTimeRangeChange`.
2. The source chart provides `{ from, to }`; under a re-entrancy lock, call `setVisibleRange({ from, to })` on every other chart.
3. For each raw `high`, `low`, and `relative` series, find the first valid point in the visible range and render `raw / base * 100`. Do not synthesize points before a model's first valid date.
4. Keep raw payloads unchanged and recompute normalized render data whenever the window moves.
5. On initial load and range changes, calculate the common date bounds and apply one visible range to all charts. The existing `state.range` remains the range selector source.

## Boundaries and errors

- A series with no valid point in the visible range renders as an empty series without throwing.
- A failed chart load does not block other charts; the coordinator skips charts that were not created.
- Nested time-axis events are ignored while synchronization is in progress.
- Synchronize by date range rather than per-chart logical indexes, avoiding offsets from different start dates or missing trading days.

## Verification

- Update the page contract test for the subscription, shared `setVisibleRange`, and window re-basing behavior.
- Run `test_model_validity_page.js`.
- Browser-check dragging and zooming, range changes (`60d/1y/all`), and first-valid-point value 100 for every visible curve.
