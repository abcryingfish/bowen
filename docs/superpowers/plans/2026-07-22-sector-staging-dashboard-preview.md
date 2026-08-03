# Sector Staging Dashboard Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在统一多维度分析页中选择并查看乳业、化学制药和半导体报告，同时保持两个新增报告为只读 staging 候选。

**Architecture:** `sector_research_service.py` 维护显式 staging 预览白名单，实体列表合并正式报告和白名单，报告读取优先正式目录、再按白名单精确路径回退。前端继续使用现有 API，只新增报告阶段标识和候选提示。

**Tech Stack:** Python 3、DuckDB、标准库 JSON/Path、原生 HTML/CSS/JavaScript、pytest、Codex Browser。

---

### Task 1: 锁定只读预览服务契约

**Files:**
- Create: `test_sector_research_service.py`
- Modify: `可视化/sector_research_service.py`

- [ ] 编写失败测试：断言实体列表包含 `885462.THS`、`881140.THS`、`881121.THS`，两个新增实体带 `report_stage=staging`。
- [ ] 编写失败测试：断言两个 staging 代码分别读取 `report.json` 与 `report_candidate.json`，返回 `_report_stage=staging`。
- [ ] 编写失败测试：断言未知代码不会扫描其他 staging，仍返回 `NOT_FOUND`。
- [ ] 运行 `.venv\Scripts\python.exe -m pytest test_sector_research_service.py -q`，确认因预览功能不存在而失败。
- [ ] 在服务中增加固定代码到固定文件的白名单，合并实体并实现正式优先、白名单回退。
- [ ] 重跑测试并确认通过。

### Task 2: 显示报告阶段

**Files:**
- Modify: `可视化/多维度分析/index.html`
- Test: `temp/test_sector_research_dashboard_template.py`

- [ ] 扩展现有模板测试，先断言页面包含 `_report_stage` 的正式/候选展示逻辑并确认失败。
- [ ] 在顶部元信息和徽标中显示“正式报告”或“staging候选”，不改变全展开栏目。
- [ ] 对 staging 报告显示显著但克制的候选提示，不把 `publication.status` 改写为正式发布。
- [ ] 运行 `.venv\Scripts\python.exe -m pytest temp/test_sector_research_dashboard_template.py -q` 并确认通过。

### Task 3: 集成与视觉验证

**Files:**
- Verify: `可视化/api_server.py`
- Verify: `可视化/多维度分析/index.html`

- [ ] 启动或复用 `127.0.0.1:8000` API 与 `127.0.0.1:8086` 静态服务。
- [ ] 调用 `/api/sector/entities` 和三个 `/api/sector/report` 请求，核对代码、名称、阶段和UTF-8。
- [ ] 用浏览器分别选择乳业、化学制药、半导体，检查总览、六维评分、预测、研究过程、证据和审计栏目。
- [ ] 检查桌面与移动宽度无重叠、无控制台错误。
- [ ] 重新运行两组pytest，并确认正式目录和 `current` 未被修改。
