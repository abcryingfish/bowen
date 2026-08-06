# 纯技术因子组展开 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 纯技术因子组折叠时只显示指标组名，点击组头后加载并展示该组全部因子和值。

**Architecture:** 保留现有因子目录和快照 API。前端在核心快照缺少某组因子值时仍保留无核心因子组的入口，组头点击沿用现有展开集合和 `union` 快照请求；带核心因子的旧分组保持当前摘要展示。

**Tech Stack:** 原生 JavaScript、Node.js `assert` 回归测试、现有 CSS。

---

### Task 1: 增加纯技术组渲染与交互回归测试

**Files:**
- Create: `可视化/test_pure_technical_factor_group_expand.js`

- [ ] 写测试，验证无核心因子的目录组在核心快照中仍保留。
- [ ] 写测试，验证折叠组头只显示组名、不渲染因子值。
- [ ] 写测试，验证点击组头会切换展开状态并刷新快照。
- [ ] 运行 `node 可视化/test_pure_technical_factor_group_expand.js`，确认因现有行为不符合要求而失败。

### Task 2: 最小修改组渲染与点击逻辑

**Files:**
- Modify: `可视化/量化因子/board_quant.js`
- Modify: `可视化/shared/chart_board.css`

- [ ] 让无核心因子组在值集合为空时仍作为目录入口显示。
- [ ] 无核心因子组使用 `group_name` 作为标题，且不渲染摘要值。
- [ ] 将组头点击接入现有展开/收起逻辑，因子项点击仍保持原行为。
- [ ] 为可点击组头补充指针和悬停反馈。

### Task 3: 验证

**Files:**
- Test: `可视化/test_pure_technical_factor_group_expand.js`
- Test: `可视化/test_market_data_service_pure_technical_catalog.py`

- [ ] 运行 Node 回归测试并确认通过。
- [ ] 运行纯技术目录 API 测试并确认通过。
- [ ] 对 `board_quant.js` 执行 Node 语法检查。
- [ ] 检查差异只包含本次功能相关文件。
