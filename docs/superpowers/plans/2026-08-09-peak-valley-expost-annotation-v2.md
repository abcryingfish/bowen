# 波峰波谷事后连续标注 v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 `300265.SZ` 生成只用于离线分析的波峰/波谷连续事后标注和逐日期对比报告，不修改现有 v1 标签、生产分区或模型训练链路。

**Architecture:** 新增一个独立的 ASCII 命名 Python 模块，接收 OHLC 宽表并返回两个方向的连续强度、四个诊断分量和确认延迟。新增一个只读真实行情的模拟脚本，将结果写入 `temp/peak_valley_v2_300265/`；人工锚点只用于报告评价，不参与生产因子计算。

**Tech Stack:** Python 3.10、pandas、numpy、DuckDB、pytest、现有 `D:\database\stock_basic_data_daily` Parquet 数据。

---

### Task 1: 建立连续标注模块的测试契约

**Files:**
- Create: `ZXW因子/test_peak_valley_expost_annotation_v2.py`
- Create: `ZXW因子/peak_valley_expost_annotation_v2.py`

- [x] **Step 1: Write the failing tests**

```python
def test_annotation_returns_independent_continuous_peak_and_valley_scores():
    result = annotate_peak_valley_ex_post(high, low, close)
    assert set(result) >= {
        "peak_strength_ex_post",
        "valley_strength_ex_post",
        "peak_local_position",
        "valley_local_position",
        "peak_trend_turn",
        "valley_trend_turn",
        "peak_reversal_strength",
        "valley_reversal_strength",
        "peak_persistence",
        "valley_persistence",
        "peak_confirm_delay",
        "valley_confirm_delay",
    }
    for name in result:
        if name.endswith("strength_ex_post") or name in {
            "peak_local_position", "valley_local_position",
            "peak_trend_turn", "valley_trend_turn",
            "peak_reversal_strength", "valley_reversal_strength",
            "peak_persistence", "valley_persistence",
        }:
            assert result[name].between(0.0, 1.0).all()


def test_annotation_does_not_force_peak_valley_alternation():
    result = annotate_peak_valley_ex_post(high, low, close)
    peak_dates = result["peak_strength_ex_post"]
    assert peak_dates.iloc[5] > 0
    assert peak_dates.iloc[7] > 0


def test_confirm_delay_is_first_directional_barrier_hit():
    result = annotate_peak_valley_ex_post(high, low, close)
    assert result["peak_confirm_delay"].iloc[5] == 2
```

The fixture must contain a rising segment, a peak, a second nearby peak, and a sustained decline so the tests prove continuous values, independent directions, and first-hit delay without relying on production data.

- [x] **Step 2: Run the focused tests and verify the expected failure**

Run:

```powershell
.venv\Scripts\python.exe -m pytest -q "ZXW因子\test_peak_valley_expost_annotation_v2.py"
```

Expected: FAIL because `peak_valley_expost_annotation_v2.py` does not yet expose `annotate_peak_valley_ex_post`.

### Task 2: Implement the deterministic continuous annotation core

**Files:**
- Modify: `ZXW因子/peak_valley_expost_annotation_v2.py`
- Test: `ZXW因子/test_peak_valley_expost_annotation_v2.py`

- [x] **Step 1: Implement input normalization and multi-scale local position**

Implement `annotate_peak_valley_ex_post(high, low, close, *, windows=(3,5,10,20,40,60), horizons=(5,10,20,40), atr_period=20, epsilon=0.02)`.

Normalize and sort the shared DatetimeIndex, remove duplicate timestamps with the last row, and return one Series per output field on the original index. For each window, calculate the percentile position of current High and Low inside the closed local range; average the six scale values separately for peak and valley.

- [x] **Step 2: Implement trend-turn and ATR-normalized reversal components**

Use causal EMA spans 5 and 20 for the historical side and the same spans evaluated on the full offline series for the post-event side. Convert the slope change divided by ATR through a bounded sigmoid into `[0, 1]`. For each horizon, detect the first future directional barrier of `1.0 * ATR_at_event`; store the earliest hit delay and the bounded barrier magnitude. Do not select a single future max/min as the event date.

- [x] **Step 3: Implement persistence and smoothed geometric strength**

After the first directional barrier hit, calculate the fraction of remaining horizon closes that stay beyond the barrier. Combine the four components with:

```python
strength = np.prod(np.clip(components, 0.0, 1.0) + epsilon, axis=0) ** (1.0 / len(components))
strength = np.clip((strength - epsilon) / (1.0 - epsilon), 0.0, 1.0)
```

Keep peak and valley computations independent; do not normalize by neighboring event type, enforce alternation, or delete close same-type points.

- [x] **Step 4: Run the focused tests and verify they pass**

Run:

```powershell
.venv\Scripts\python.exe -m pytest -q "ZXW因子\test_peak_valley_expost_annotation_v2.py"
```

Expected: all focused tests pass.

### Task 3: Add the 300265 offline simulation and sparse-anchor report

**Files:**
- Create: `ZXW因子/simulate_peak_valley_expost_v2.py`
- Create: `ZXW因子/test_simulate_peak_valley_expost_v2.py`
- Output: `temp/peak_valley_v2_300265/`

- [x] **Step 1: Write the failing simulation contract test**

```python
def test_simulation_writes_comparison_and_summary(tmp_path):
    result = run_simulation(frame, anchors, tmp_path)
    assert result["comparison_path"].is_file()
    assert result["summary_path"].is_file()
    comparison = pd.read_csv(result["comparison_path"])
    assert {"date", "manual_direction", "peak_strength_ex_post", "valley_strength_ex_post"} <= set(comparison)
```

- [x] **Step 2: Run the simulation test to verify it fails**

Run:

```powershell
.venv\Scripts\python.exe -m pytest -q "ZXW因子\test_simulate_peak_valley_expost_v2.py"
```

Expected: FAIL because `run_simulation` and the report writer do not yet exist.

- [x] **Step 3: Implement read-only DuckDB loading and report generation**

Load only `300265.SZ` from `D:\database\stock_basic_data_daily\**\*.parquet`, call the annotation core, merge the explicit positive/negative manual anchors, and write UTF-8 CSV plus JSON summary under `temp/peak_valley_v2_300265/`. Unknown dates remain blank in `manual_direction`. Include v1 stage labels for comparison only; never write `D:\database\signal_daily*`.

- [x] **Step 4: Run the simulation test and verify it passes**

Run:

```powershell
.venv\Scripts\python.exe -m pytest -q "ZXW因子\test_simulate_peak_valley_expost_v2.py"
```

Expected: all simulation contract tests pass.

### Task 4: Generate and inspect the real 300265 report

**Files:**
- Execute: `ZXW因子/simulate_peak_valley_expost_v2.py`
- Output: `temp/peak_valley_v2_300265/peak_valley_v2_comparison.csv`
- Output: `temp/peak_valley_v2_300265/peak_valley_v2_summary.json`

- [x] **Step 1: Run the real-data simulation**

Run:

```powershell
.venv\Scripts\python.exe "ZXW因子\simulate_peak_valley_expost_v2.py" --code 300265.SZ
```

- [x] **Step 2: Verify report contents and score bounds**

Run:

```powershell
.venv\Scripts\python.exe -c "import pandas as pd; p='temp/peak_valley_v2_300265/peak_valley_v2_comparison.csv'; d=pd.read_csv(p); assert d['peak_strength_ex_post'].between(0,1).all(); assert d['valley_strength_ex_post'].between(0,1).all(); print(d.shape); print(d.head())"
```

Expected: a full historical comparison table, all continuous scores in `[0,1]`, and no writes outside `temp/peak_valley_v2_300265`.

- [x] **Step 3: Review the sparse-anchor summary**

Check that the JSON reports positive-anchor ranks, explicit-negative ranks, score distributions, confirmation-delay distributions, and the v1 comparison. Do not change thresholds or add softmax suppression in this first simulation.

- [x] **Step 4: Run regression verification**

Run:

```powershell
.venv\Scripts\python.exe -m pytest -q "ZXW因子\test_peak_valley_expost_annotation_v2.py" "ZXW因子\test_simulate_peak_valley_expost_v2.py" "可视化\test_market_data_service_peak_valley_snapshot.py"
.venv\Scripts\python.exe -m py_compile "ZXW因子\peak_valley_expost_annotation_v2.py" "ZXW因子\simulate_peak_valley_expost_v2.py"
```

Expected: all tests pass and both new modules compile; existing v1 and frontend behavior remain unchanged.
