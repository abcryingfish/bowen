# 同花顺板块重叠关系拆分 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增加20日和60日完全重叠累计收益相关性，并将重叠、无重叠关系分别输出为CSV。

**Architecture:** 保持现有相关性计算不变，只在周期配置中加入滞后0日。全量结果生成后按 `relationship_type` 拆分，中文列名脚本继续对各结果文件做一对一转换。

**Tech Stack:** Python、pandas、pytest、UTF-8 with BOM CSV

---

### Task 1: 锁定新增行为

**Files:**
- Modify: `temp/test_analyze_all_ths_multi_horizon_relations.py`

- [ ] 添加测试，要求5/20/60日配置均包含滞后0日。
- [ ] 添加测试，要求拆分后的两个结果互斥且合计等于全量结果。
- [ ] 运行测试并确认因缺少新行为而失败。

### Task 2: 实现配置与拆分输出

**Files:**
- Modify: `temp/analyze_all_ths_multi_horizon_relations.py`
- Modify: `temp/translate_ths_relation_csv_headers.py`

- [ ] 为20日、60日周期加入滞后0日。
- [ ] 增加纯函数按关系类型拆分结果。
- [ ] 输出 `all_881_multi_horizon_overlap.csv` 与 `all_881_multi_horizon_non_overlap.csv`。
- [ ] 将两个文件加入中文列名转换清单。
- [ ] 运行测试并确认通过。

### Task 3: 重算与核验产物

**Files:**
- Regenerate: `temp/ths_sector_relations/*.csv`

- [ ] 使用项目 `.venv` 重跑分析脚本。
- [ ] 重跑中文列名转换脚本。
- [ ] 核对重叠文件只有 `同期重叠`，并包含 `(20, 0)`、`(60, 0)`。
- [ ] 核对无重叠文件只有 `领先滞后无重叠`。
- [ ] 核对两个拆分文件行数之和等于全量文件。
