# 财务 Parquet Schema 兼容 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复板块研究读取历史财务 Parquet 时，早期全空列 `Null` 与后续 `Float64` 冲突导致的退出。

**Architecture:** 在现有 `load_fundamental_features` 内枚举匹配的分区文件，并以最新分区的完整 schema 交给 Polars 扫描器。该改动仅统一物理读取类型，保留空值和后续财务计算逻辑。

**Tech Stack:** Python 3.10、Polars 1.39、pandas、pytest、Parquet

---

### Task 1: 锁定并修复跨分区类型冲突

**Files:**
- Modify: `工具/获得同花顺板块和成分股.py:783`
- Test: `test_ths_level1_index_daily.py`

- [x] **Step 1: 写入失败测试**

创建两个临时月分区：首个分区的 `revenue_ttm` 和 `net_profit_parent_ttm` 为 `Null`，第二个分区为 `Float64`。将模块的 `VALUATION_GLOB` 指向临时文件，调用 `load_fundamental_features` 并断言成功返回板块聚合结果。

- [x] **Step 2: 运行测试确认红灯**

```powershell
& .venv\Scripts\python.exe -m pytest -q test_ths_level1_index_daily.py -k fundamental_features
```

预期：Polars 抛出 `SchemaError: incoming: Float64 != target: Null`。

- [x] **Step 3: 写入最小修复**

在生产脚本中导入标准库 `glob`，在 `load_fundamental_features` 内获得匹配文件；无文件时抛出明确的 `FileNotFoundError`，有文件时读取最新分区完整 schema：

```python
valuation_paths = sorted(glob.glob(VALUATION_GLOB))
if not valuation_paths:
    raise FileNotFoundError(f"未找到财务估值数据：{VALUATION_GLOB}")
valuation_schema = pl.read_parquet_schema(valuation_paths[-1])
```

并使用 `pl.scan_parquet(valuation_paths, schema=valuation_schema)` 继续原有查询。

- [x] **Step 4: 运行定向测试确认绿灯**

```powershell
& .venv\Scripts\python.exe -m pytest -q test_ths_level1_index_daily.py -k fundamental_features
```

预期：测试通过。

- [x] **Step 5: 运行相关测试和语法检查**

```powershell
& .venv\Scripts\python.exe -m pytest -q test_ths_level1_index_daily.py
& .venv\Scripts\python.exe -m py_compile "工具\获得同花顺板块和成分股.py"
```

预期：全部测试通过且语法检查退出码为 0。
