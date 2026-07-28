# 归母净利润派生表全历史重建 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正归母净利润派生字段，并重建 2010-01-01 至当前日期的 `factor_fundamental_valuation`。

**Architecture:** 原始 QMT 财务表保持只读，派生函数改用 `net_profit_excl_min_int_inc`。现有派生目录经绝对路径校验后直接删除，再按自然年分段调用现有 `--derive-only` 流程，降低内存峰值并支持按年度定位失败。

**Tech Stack:** Python 3.10、pandas、polars、DuckDB、pytest、Parquet、PowerShell

---

### Task 1: 用回归测试锁定归母净利润口径

**Files:**
- Create: `工具/test_qmt公司数据获取.py`
- Modify: `工具/qmt公司数据获取.py:404-448`

- [ ] **Step 1: 写入失败测试**

通过 `importlib.util.spec_from_file_location` 加载脚本，构造同报告期的 Income、Balance、PershareIndex、Capital 和单日行情。Income 同时提供：

```python
"net_profit_excl_min_int_inc": 5_922_815_000.0
"net_profit_incl_min_int_inc_after": 3_727_609_925.9
```

断言生成结果中的 `net_profit_parent` 等于 `5_922_815_000.0`，且 `net_profit_parent_ttm` 使用同一字段。

- [ ] **Step 2: 运行测试确认红灯**

```powershell
& .venv\Scripts\python.exe -m pytest -q "工具\test_qmt公司数据获取.py"
```

预期：断言失败，实际 `net_profit_parent` 为 `3_727_609_925.9`。

- [ ] **Step 3: 最小修改派生字段**

在加载列、标准化列、TTM计算源列和 `net_profit_parent` 赋值四处，将：

```python
net_profit_incl_min_int_inc_after
```

替换为：

```python
net_profit_excl_min_int_inc
```

保持落盘列名与下游契约不变。

- [ ] **Step 4: 运行测试确认绿灯**

```powershell
& .venv\Scripts\python.exe -m pytest -q "工具\test_qmt公司数据获取.py"
```

预期：全部通过。

- [ ] **Step 5: 提交代码与测试**

```powershell
git add -- "工具/qmt公司数据获取.py" "工具/test_qmt公司数据获取.py"
git commit -m "fix: derive valuation from parent profit"
```

### Task 2: 删除旧派生数据并逐年重算

**Data:**
- Delete: `D:\database\qmt_company_data\table=factor_fundamental_valuation`
- Read only: `D:\database\qmt_company_data\table=Income`
- Read only: `D:\database\qmt_company_data\table=Balance`
- Read only: `D:\database\qmt_company_data\table=PershareIndex`
- Read only: `D:\database\qmt_company_data\table=Capital`

- [ ] **Step 1: 校验删除目标**

解析目标和父目录绝对路径，要求目标是父目录的直接子目录，且目录名严格等于 `table=factor_fundamental_valuation`；任一条件不满足立即停止。

- [ ] **Step 2: 删除旧派生目录**

使用 PowerShell `Remove-Item -LiteralPath ... -Recurse -Force` 删除已校验目标，并确认目录不存在、五张原始表仍存在。

- [ ] **Step 3: 按年度重算**

对 2010 至当前年份依次执行：

```powershell
& .venv\Scripts\python.exe "工具\qmt公司数据获取.py" `
  --derive-only `
  --derive-start YYYY-01-01 `
  --derive-end YYYY-12-31
```

当前年份的结束日使用当天日期。任一年度退出码非0时立即停止，不继续后续年份。

### Task 3: 验证全历史结果

**Data:**
- Inspect: `D:\database\qmt_company_data\table=factor_fundamental_valuation\year=*\month=*\merged.parquet`

- [ ] **Step 1: 检查完整性**

使用 DuckDB 检查最小/最大日期、总行数、股票数、月份分区数，以及 `htsc_code + time` 重复键数量；重复键必须为0。

- [ ] **Step 2: 检查伊利样本**

断言 `600887.SH` 在 `2024-04-30` 的 `net_profit_parent` 等于 Income 2024Q1 的 `net_profit_excl_min_int_inc`，不能等于 `net_profit_incl_min_int_inc_after`。

- [ ] **Step 3: 检查随机样本和派生公式**

抽取多个股票公告日样本，核对 `net_profit_parent` 来源；对非零TTM利润行验证：

```text
pe_ttm = total_market_val / net_profit_parent_ttm
```

- [ ] **Step 4: 运行代码与相关测试**

```powershell
& .venv\Scripts\python.exe -m py_compile "工具\qmt公司数据获取.py"
& .venv\Scripts\python.exe -m pytest -q "工具\test_qmt公司数据获取.py" "可视化\test_fundamental_profit_fields.py"
```

预期：编译成功，测试全部通过。
