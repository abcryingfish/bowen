# Codex Sector Deep Research V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 对12个跨类型同花顺一级板块执行截至2026-07-18的深度证据研究试跑，验证后再决定是否扩展到其余500个板块。

**Architecture:** 在现有批次摘要和结果提交链路上增加严格截止日过滤、六类证据去重/分类、成分股聚合摘要和V2质量报告；旧的2026-07-15结果只读保留，新结果按analysis_date=2026-07-18独立落盘。

**Tech Stack:** Python 3、Polars、Pandas、Parquet/ZSTD、现有东方财富证据库和同花顺成分快照。

---

### Task 1: 建立试点清单和截止日快照

**Files:**
- Modify: `工具/导出Codex研究批次摘要.py`
- Create: `工具/导出Codex深度试点摘要.py`
- Test: `temp/test_codex_deep_research_contract.py`

- [ ] 选择12个覆盖板块适配类型的代码，并写入批次JSON。
- [ ] 对行情、财务、估值和证据统一应用`analysis_date=2026-07-18`，行情最大日期使用不晚于分析日的最近交易日。
- [ ] 对`published_at > 2026-07-18 23:59:59`的证据直接排除并记录`post_date_excluded`计数。
- [ ] 测试一个晚于截止日的假证据不会进入试点摘要。

### Task 2: 六类证据去重和维度关联

**Files:**
- Create: `工具/构建Codex深度证据包.py`
- Create: `工具/证据分类规则_v2.json`
- Test: `temp/test_codex_deep_evidence.py`

- [ ] 按`content_hash`去重，同一文章多来源转载只保留一个主记录并保留来源集合。
- [ ] 统一输出`policy`、`research_report`、`announcement`、`news`、`industry_data`、`capital`六类。
- [ ] 为每条记录输出`linked_dimensions`、`stance`、`source_tier`、`evidence_quality`和`time_validity`。
- [ ] 将行情稿、ETF稿和无关公告标记为`mismatch`或排除，不得自动作为政策证据。
- [ ] 测试重复hash、错配政策标签和冲突证据三种情况。

### Task 3: 成分股聚合

**Files:**
- Create: `工具/构建Codex板块成分聚合.py`
- Test: `temp/test_codex_member_aggregate.py`

- [ ] 读取沪深有效成分快照，强制排除`.BJ`并验证数量恒等式。
- [ ] 计算盈利覆盖、收入/利润中位数及P25/P75、龙头贡献度、业务纯度和缺失原因。
- [ ] 缺失值保持null并记录`no_data`原因，不填充中性分。
- [ ] 输出`sector_member_aggregates/analysis_date=2026-07-18`的Parquet。

### Task 4: 试点研究结果和V2契约

**Files:**
- Create: `工具/提交Codex深度研究结果_v2.py`
- Modify: `工具/提交Codex板块研究结果.py`
- Test: `temp/test_codex_deep_result_contract.py`

- [ ] 为12个试点分别生成六维评分、三周期预测、10至20条有效证据引用和成分聚合摘要。
- [ ] 结果必须携带`run_id`、`analysis_date`、`evidence_bundle_hash`、`member_aggregate_hash`和`research_method=codex_deep_research_v2`。
- [ ] 证据少于10条、关键类别缺失、时间边界失败或聚合不完整时进入重试/复核状态，不发布完整综合分。
- [ ] 新结果写入独立分区，不修改2026-07-15旧结果。

### Task 5: 试点质量审计

**Files:**
- Create: `工具/审计Codex深度试点.py`
- Create: `D:/database/sector_information/codex_assessments/analysis_date=2026-07-18/pilot_quality_report.json`

- [ ] 核验12个代码唯一、日期一致、无晚于分析日证据。
- [ ] 输出每个来源类别证据数、去重数、时间剔除数、缺失类别和错配数。
- [ ] 核验成分聚合覆盖、北交所排除恒等式、龙头贡献和业务纯度字段。
- [ ] 核验UTF-8、Parquet字段和现有HTML读取。
- [ ] 只有12个试点全部通过，才允许创建全量500板块批次；否则记录问题并修复后重试。
