# 乳业浏览研究方法固化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将乳业报告已验证的数据获取方式固化为板块与个股深度研究 Skill 的唯一联网研究路径。

**Architecture:** 每个研究对象由一个独立顶层 Codex 任务处理，使用 Codex 内置 Browser、Bing 逐轮检索和正文阅读；Python仅负责确定性数据计算与保存。协作子 Agent 不承担需要 Browser 的语义研究，且不新增本地 MCP 或其他抓取路线。

**Tech Stack:** Codex Browser Skill、Browser Client、Markdown Skill、现有 JSON/Parquet 审计契约。

---

### Task 1: 验证旧 Skill 的调度歧义

**Files:**
- Read: `C:\Users\Administrator\.codex\skills\sector-stock-deep-research\SKILL.md`

- [x] 使用未修改 Skill 运行并发研究调度场景。
- [x] 确认它没有强制区分顶层 Codex 任务与协作子 Agent，或没有固定乳业 Browser 获取方法。

### Task 2: 固化乳业获取方法

**Files:**
- Modify: `C:\Users\Administrator\.codex\skills\sector-stock-deep-research\SKILL.md`
- Modify: `C:\Users\Administrator\.codex\skills\sector-stock-deep-research\references\quality-gate.md`

- [x] 增加顶层任务、Browser Skill、`agent.browsers.getDefault()`、独立标签页和逐轮正文阅读要求。
- [x] 明确禁止本地 MCP、固定关键词抓取和协作子 Agent 承担联网语义研究。
- [x] 将乳业12轮日志与13条证据作为方法基准而非机械数量要求。

### Task 3: 回归验证

**Files:**
- Test: `C:\Users\Administrator\.codex\skills\sector-stock-deep-research\SKILL.md`
- Test: `C:\Users\Administrator\.codex\skills\sector-stock-deep-research\references\quality-gate.md`

- [x] 运行相同调度场景，确认执行者选择独立顶层 Codex 任务和内置 Browser。
- [x] 检查 UTF-8、必需规则文本、禁止项和乳业金标准字段。
- [x] 确认没有修改评分公式、输出契约和业务逻辑。
