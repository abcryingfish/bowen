# 统一板块研究看板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将多维度分析页面改造成 JSON 驱动的统一板块研究看板，完整展示乳业研究结果，并支持后续板块通过 URL 参数或页面选择框切换。

**Architecture:** 保留现有全展开 HTML/CSS 视觉结构，在 `可视化/多维度分析/index.html` 内增加统一数据加载器、字段安全读取器和栏目渲染器。板块清单映射到 `D:\database\sector_information\reports` 下的正式 JSON；缺失、无法确认、获取失败和无历史批次分别渲染，不使用静态演示回退。

**Tech Stack:** 原生 HTML/CSS/JavaScript、Fetch API、JSON、PowerShell/Python 本地验证。

---

### Task 1: 建立板块数据入口与安全读取工具

**Files:**
- Modify: `C:\Users\Administrator\Desktop\python_venv\可视化\多维度分析\index.html`

- [ ] **Step 1: 定义板块清单和 URL 解析函数**

加入 `SECTOR_CATALOG`、`DEFAULT_SECTOR`、`getRequestedSector()`，默认返回 `885462.THS`，优先解析 `?sector=`。

- [ ] **Step 2: 定义 JSON 路径和安全字段读取函数**

加入 `resolveReportUrl(code)`、`readPath(object, path, fallback)`、`displayValue(value, kind)`，对缺失值分别输出“未提供”“无法确认”“获取失败”。

- [ ] **Step 3: 添加页面错误状态**

在总览区域增加加载状态节点；Fetch 失败、JSON 解析失败或必需字段缺失时显示错误详情，不展示任何旧演示数据。

### Task 2: 将总览、评分、市场状态和预测改为动态渲染

**Files:**
- Modify: `C:\Users\Administrator\Desktop\python_venv\可视化\多维度分析\index.html`

- [ ] **Step 1: 使用 `sector_name`、`sector_code`、`analysis_archetype` 和 `verdict` 填充总览**
- [ ] **Step 2: 使用 `dimension_scores` 和 `overall_score` 渲染六维评分**
- [ ] **Step 3: 使用 `objective_metrics.index_metrics` 和 `turnover` 渲染市场状态**
- [ ] **Step 4: 使用 `forecasts` 渲染 5/20/60 日预测**
- [ ] **Step 5: 显示真实数据截止日和分析日差异**

### Task 3: 增加分类契约、边界、研究问题和质量状态栏目

**Files:**
- Modify: `C:\Users\Administrator\Desktop\python_venv\可视化\多维度分析\index.html`

- [ ] **Step 1: 增加分类契约面板**

展示 `analysis_archetype`、`classification_facets`、`classification_confidence`、`type_review_status` 和 `classification_reason`。

- [ ] **Step 2: 增加板块边界与研究问题面板**

展示 `boundary` 和 `research_questions` 全部条目。

- [ ] **Step 3: 增加证据类别状态面板**

展示 `evidence_category_statuses` 的状态、数量、冲突和限制。

- [ ] **Step 4: 增加未确认/缺失/失败/重试状态**

从 `unconfirmed_items`、发布警告和搜索日志状态生成独立列表。

### Task 4: 动态渲染成分、聚合、证据、主张和审计信息

**Files:**
- Modify: `C:\Users\Administrator\Desktop\python_venv\可视化\多维度分析\index.html`

- [ ] **Step 1: 渲染成分统计和完整成分明细**

使用 `source_member_count`、`eligible_member_count`、`excluded_bj_codes`、`member_breadth`、`member_market_rows` 输出完整表格和北交所排除记录。

- [ ] **Step 2: 渲染财务、估值和业务纯度聚合**

读取 `member_aggregates`、`same_period_yoy_rows`，显示覆盖率、盈利/亏损、集中度和限制。

- [ ] **Step 3: 渲染证据和搜索日志**

完整展示 `evidence`、`search_logs`、去重统计、发布日期和引用维度。

- [ ] **Step 4: 渲染知识主张和关系**

展示 `claims` 的主体、关系、客体、置信度、有效期、状态及证据关联。

- [ ] **Step 5: 渲染发布与审计信息**

展示 `publication`、`task_id`、`run_id`、`snapshot_id`、`fetched_at`、版本、北交所硬排除和日期审计。

### Task 5: 支持板块选择框和历史数据降级显示

**Files:**
- Modify: `C:\Users\Administrator\Desktop\python_venv\可视化\多维度分析\index.html`

- [ ] **Step 1: 添加板块选择框**

根据 `SECTOR_CATALOG` 生成选项，选择后更新 `history.replaceState` 的 `sector` 参数并重新加载。

- [ ] **Step 2: 禁止伪造历史曲线和情景概率**

无历史序列显示“暂无历史数据”；无正式情景概率显示明确缺失状态。

- [ ] **Step 3: 保留现有锚点导航和全展开布局**

新增栏目加入导航，所有栏目不使用折叠控件。

### Task 6: 验证页面和服务

**Files:**
- Test: `C:\Users\Administrator\Desktop\python_venv\可视化\多维度分析\index.html`

- [ ] **Step 1: 启动或复用本地服务**

确认 `http://127.0.0.1:8086/多维度分析/index.html` 可访问。

- [ ] **Step 2: 验证默认乳业入口**

检查页面显示乳业、综合分 5.4、34 只有效成分和数据截止警告。

- [ ] **Step 3: 验证 URL 参数入口**

打开 `?sector=885462.THS`，确认与默认入口结果一致。

- [ ] **Step 4: 验证选择框入口和错误状态**

选择乳业后 URL 更新；使用不存在的代码时显示错误而不是示例数据。

- [ ] **Step 5: 执行 UTF-8 和静态示例清理检查**

搜索页面不应出现“黄金概念”“示例龙头A”等演示文本，中文应正常显示。
