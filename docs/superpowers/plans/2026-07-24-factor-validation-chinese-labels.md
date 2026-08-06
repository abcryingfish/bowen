# Factor Validation Chinese Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在因子有效性检验页面用中文显示普通英文因子名称，同时继续用英文技术键执行检验。

**Architecture:** 因子检验服务复制参考页既有的显示名映射，独立生成 `factor_labels`。前端沿用现有 `factorLabel()`，未知因子原样回退，形态因子继续使用 manifest 标签。

**Tech Stack:** Python 3、`unittest`、JavaScript、UTF-8 JSON/HTML

---

### Task 1: 普通因子中文标签

**Files:**
- Modify: `可视化/量化因子有效性检验/test_factor_validation_jobs.py`
- Modify: `可视化/量化因子有效性检验/factor_validation_service.py`

- [ ] **Step 1: 写普通因子映射失败测试**

在测试中临时创建 `factor=mac_total`、`factor=unknown_factor` 目录，调用 `list_factor_validation_factors()`，断言：

```python
self.assertEqual(payload["factor_labels"]["mac_total"], "MAC总")
self.assertEqual(payload["factor_labels"]["ADX_golden_cross"], "ADX_金叉")
self.assertEqual(payload["factor_labels"]["unknown_factor"], "unknown_factor")
```

- [ ] **Step 2: 验证测试因缺少普通因子映射而失败**

运行：

```powershell
python -m unittest test_factor_validation_jobs.OrdinaryFactorLabelTests -v
```

预期：`mac_total` 实际标签仍为 `mac_total`，测试失败。

- [ ] **Step 3: 复制参考页映射并生成显示标签**

从 `可视化/market_data_service.py` 复制完整 `_FACTOR_DISPLAY_TO_INTERNAL` 到因子检验服务，并在本模块增加：

```python
def _build_factor_display_label_map(available_factors: list[str]) -> dict[str, str]:
    available_set = set(available_factors)
    label_map = {name: name for name in available_factors}
    for display_name, aliases in _FACTOR_DISPLAY_TO_INTERNAL.items():
        if display_name in available_set:
            label_map[display_name] = display_name
        for alias in aliases:
            if alias in available_set and label_map[alias] == alias:
                label_map[alias] = display_name
    return label_map
```

将 `list_factor_validation_factors()` 中普通因子的初始化改为：

```python
factor_labels = _build_factor_display_label_map(ordinary_factors)
factor_labels.update(_load_pure_technical_factor_labels(SIGNAL_DAILY_BASE_PATH))
factor_labels.update(_build_morph_factor_labels(morph_factors))
```

动态纯技术因子标签从参考页使用的 UTF-8 文件 `signal_daily/_meta/pure_technical_factor_catalog_cache.json` 读取，只合并当前存在且标签非空的因子。

- [ ] **Step 4: 验证普通因子测试通过**

运行同一测试，预期全部通过。

### Task 2: 回归与编码验证

**Files:**
- Verify: `可视化/量化因子有效性检验/factor_validation_service.py`
- Verify: `可视化/量化因子有效性检验/test_factor_validation_jobs.py`
- Verify: `可视化/量化因子有效性检验/test_factor_validation_labels.js`

- [ ] **Step 1: 运行完整因子检验服务测试**

```powershell
python -m unittest test_factor_validation_jobs -v
```

预期：所有测试通过。

- [ ] **Step 2: 运行前端标签测试**

```powershell
node test_factor_validation_labels.js
```

预期：输出“有效性检验中文显示名测试通过”。

- [ ] **Step 3: 检查差异、语法与 UTF-8**

```powershell
python -m py_compile factor_validation_service.py test_factor_validation_jobs.py
git diff --check -- 可视化/量化因子有效性检验
```

预期：退出码均为 0，且中文源文件可按 UTF-8 解码。
