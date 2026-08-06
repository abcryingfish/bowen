# Sector Report Canonical Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将不同批次板块研究报告统一为固定的前端字段契约，并把生成要求写入深度研究 Skill。

**Architecture:** 后端服务是唯一历史兼容边界，读取报告别名及伴随文件并输出标准字段。前端仅消费标准字段；新研究报告从生成时遵守同一契约。

**Tech Stack:** Python、DuckDB、pytest、原生 HTML/JavaScript、Markdown Skill。

---

### Task 1: 服务端标准字段归一化

**Files:**
- Modify: `test_sector_research_service.py`
- Modify: `可视化/sector_research_service.py`

- [x] 编写中报预增别名、伴随研究问题和分类评估的失败测试。
- [x] 运行目标测试，确认因标准字段缺失而失败。
- [x] 实现固定字段及类型归一化，不推断不存在的研究结论。
- [x] 运行完整服务测试。

### Task 2: 前端固定字段渲染

**Files:**
- Modify: `可视化/多维度分析/index.html`

- [x] 增加分类属性对象与证据类别状态对象的稳定格式化。
- [x] 保持真正缺失字段的明确缺失提示。
- [x] 通过本地 API 和页面验证 `886110.THS`。

### Task 3: 深度研究 Skill 契约

**Files:**
- Modify: `C:/Users/Administrator/.codex/skills/sector-stock-deep-research/SKILL.md`

- [x] 写入标准字段名称、类型、禁止新报告输出别名和硬审计要求。
- [x] 检查 UTF-8 和 Skill 结构。
- [x] 最终运行测试并核对 API 标准字段。
