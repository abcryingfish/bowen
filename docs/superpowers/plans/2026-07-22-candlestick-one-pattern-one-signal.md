# 蜡烛形态“一形态一信号”实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让乌鸦形态和 MultiIndex 输出接口始终以具体子形态名独立输出，不再合并相似形态或多空方向。

**Architecture:** 保留现有形态函数、权重和生成脚本数据流，只调整 `Pattern` 的输出组装边界。用独立的回归测试文件构造真实 OHLC 矩阵，分别验证底层形态返回值与通用矩阵接口。

**Tech Stack:** Python 3.10、pandas、NumPy、pytest、项目 `.venv`

---

### Task 1: 拆分两只乌鸦与三只乌鸦

**Files:**
- Create: `test_candlestick_one_pattern_one_signal.py`
- Modify: `形态趋势通道因子/蜡烛图无成交量.py:655-682`

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parent
PATTERN_FILE = ROOT / "形态趋势通道因子" / "蜡烛图无成交量.py"
META_FILE = ROOT / "形态趋势通道因子" / "morph_candlestick_meta.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _crows_ohlc():
    dates = pd.date_range("2026-01-01", periods=12, freq="D")
    open_prices = pd.DataFrame(
        {
            "TWO.SZ": [1, 1, 1, 2, 2, 3, 3, 4, 5, 6, 8, 9],
            "THREE.SZ": [1, 1, 1, 2, 2, 3, 3, 4, 5, 8, 7, 6],
        },
        index=dates,
        dtype=float,
    )
    close_prices = pd.DataFrame(
        {
            "TWO.SZ": [1, 1, 1, 2, 2, 3, 3, 4, 5, 7, 6.5, 6],
            "THREE.SZ": [1, 1, 1, 2, 2, 3, 3, 4, 5, 7, 6, 5],
        },
        index=dates,
        dtype=float,
    )
    high_prices = pd.DataFrame(
        open_prices.to_numpy().clip(min=close_prices.to_numpy()) + 0.5,
        index=dates,
        columns=open_prices.columns,
    )
    low_prices = pd.DataFrame(
        open_prices.to_numpy().clip(max=close_prices.to_numpy()) - 0.5,
        index=dates,
        columns=open_prices.columns,
    )
    return open_prices, high_prices, low_prices, close_prices


def test_crows_pattern_returns_each_pattern_as_an_independent_signal():
    pattern_module = _load_module("candlestick_patterns", PATTERN_FILE)
    pattern = pattern_module.Pattern()
    open_prices, high_prices, low_prices, close_prices = _crows_ohlc()

    result = pattern.crows_pattern(open_prices, high_prices, low_prices, close_prices)

    assert set(result) == {"two_crows", "three_crows"}
    assert result["two_crows"].iloc[-1]["TWO.SZ"] == pytest.approx(-0.6)
    assert result["three_crows"].iloc[-1]["THREE.SZ"] == pytest.approx(-0.7)
```

- [ ] **Step 2: 运行测试并确认按预期失败**

Run: `.venv\Scripts\python.exe -m pytest test_candlestick_one_pattern_one_signal.py::test_crows_pattern_returns_each_pattern_as_an_independent_signal -v`

Expected: FAIL，实际键为 `{"crows"}`。

- [ ] **Step 3: 写最小实现**

将 `crows_pattern()` 末尾的覆盖合并删除，直接返回两个子矩阵：

```python
        return {
            "two_crows": two_crows.astype(float) * self.signal_strength["two_crows"],
            "three_crows": three_crows.astype(float) * self.signal_strength["three_crows"],
        }
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `.venv\Scripts\python.exe -m pytest test_candlestick_one_pattern_one_signal.py::test_crows_pattern_returns_each_pattern_as_an_independent_signal -v`

Expected: PASS。

- [ ] **Step 5: 检查明细接口输出名称**

Run: `.venv\Scripts\python.exe -m pytest test_candlestick_one_pattern_one_signal.py -v`

Expected: 当前测试全部 PASS，且没有 `crows` 兼容列。

### Task 2: MultiIndex 接口按子形态输出独立列

**Files:**
- Modify: `test_candlestick_one_pattern_one_signal.py`
- Modify: `形态趋势通道因子/蜡烛图无成交量.py:1628-1672`

- [ ] **Step 1: 追加失败测试**

```python
def test_multi_index_matrix_keeps_crows_as_independent_columns():
    pattern_module = _load_module("candlestick_patterns_matrix", PATTERN_FILE)
    pattern = pattern_module.Pattern()
    open_prices, high_prices, low_prices, close_prices = _crows_ohlc()
    volume = pd.DataFrame(0.0, index=close_prices.index, columns=close_prices.columns)

    result = pattern.get_multi_index_signal_matrix(
        open_prices,
        high_prices,
        low_prices,
        close_prices,
        volume,
        enabled_signals=["crows"],
    )

    assert list(result.columns) == ["two_crows", "three_crows"]
    assert result.loc[(20260112, "TWO.SZ"), "two_crows"] == pytest.approx(-0.6)
    assert result.loc[(20260112, "THREE.SZ"), "three_crows"] == pytest.approx(-0.7)


def test_pattern_names_match_strength_and_span_metadata():
    pattern_module = _load_module("candlestick_patterns_metadata", PATTERN_FILE)
    meta_module = _load_module("candlestick_metadata", META_FILE)

    assert set(pattern_module.Pattern().signal_strength) == set(meta_module.SIGNAL_BAR_SPAN)
```

- [ ] **Step 2: 运行测试并确认按预期失败**

Run: `.venv\Scripts\python.exe -m pytest test_candlestick_one_pattern_one_signal.py::test_multi_index_matrix_keeps_crows_as_independent_columns -v`

Expected: FAIL，旧实现输出家族列 `crows`，而不是两个子形态列。

- [ ] **Step 3: 写最小实现**

用子形态矩阵集合替代家族合并矩阵：

```python
        individual_signal_matrices = {}

        for signal_name in enabled_signals:
            if signal_name not in signal_mapping:
                print(f"警告: 未知的信号名称 '{signal_name}'，已忽略")
                continue

            result_dict = signal_mapping[signal_name]()
            for sub_signal_name, sub_signal_matrix in result_dict.items():
                if sub_signal_matrix is not None:
                    individual_signal_matrices[sub_signal_name] = sub_signal_matrix
```

并让后续 Series 组装循环遍历 `individual_signal_matrices.items()`；空结果列名也从该字典生成。

- [ ] **Step 4: 运行定向测试并确认通过**

Run: `.venv\Scripts\python.exe -m pytest test_candlestick_one_pattern_one_signal.py -v`

Expected: 3 tests PASS。

- [ ] **Step 5: 运行现有生成脚本回归测试**

Run: `.venv\Scripts\python.exe -m pytest test_morph_candlestick_signal_generation.py test_candlestick_one_pattern_one_signal.py -v`

Expected: 5 tests PASS。

### Task 3: 静态一致性与最终验证

**Files:**
- Verify: `形态趋势通道因子/蜡烛图无成交量.py`
- Verify: `形态趋势通道因子/morph_candlestick_meta.py`
- Verify: `工具/形态蜡烛信号生成_合并保存.py`

- [ ] **Step 1: 编译修改文件**

Run: `.venv\Scripts\python.exe -m py_compile "形态趋势通道因子\蜡烛图无成交量.py" "工具\形态蜡烛信号生成_合并保存.py"`

Expected: 退出码 0，无输出。

- [ ] **Step 2: 检查差异格式**

Run: `git diff --check -- "形态趋势通道因子/蜡烛图无成交量.py" "test_candlestick_one_pattern_one_signal.py"`

Expected: 退出码 0，无输出。

- [ ] **Step 3: 检查旧合并名称仅存在于兼容输入或文档中**

Run: `rg -n 'return \{"crows"|combined_signal_matrices|total_crows_signal' "形态趋势通道因子/蜡烛图无成交量.py"`

Expected: 无匹配。

- [ ] **Step 4: 提交（仅当 Git 锁已解除）**

```powershell
git add -- "形态趋势通道因子/蜡烛图无成交量.py" "test_candlestick_one_pattern_one_signal.py"
git commit -m "fix: split candlestick pattern signals"
```

Expected: 只提交本任务文件；若 `.git/index.lock` 仍存在，跳过提交并在交付说明中报告。
