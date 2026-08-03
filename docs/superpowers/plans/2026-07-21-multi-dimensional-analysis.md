# 多维度分析页面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建一个仅通过悬浮球访问的空白“多维度分析”页面。

**Architecture:** 页面独立放在 `可视化/多维度分析/index.html`，悬浮球菜单继续由 `shared/edge_float_nav.js` 统一注册和渲染。

**Tech Stack:** UTF-8 HTML、现有 `chart_board.css`、`edge_float.css`、`edge_float_nav.js`、`edge_float_hud.js`。

---

### Task 1: 注册悬浮球菜单项

**Files:**
- Modify: `可视化/shared/edge_float_nav.js`

- [ ] 在 `PAGES` 数组中加入 `multi-dimensional-analysis` 项，路径指向 `../%E5%A4%9A%E7%BB%B4%E5%BA%A6%E5%88%86%E6%9E%90/index.html`，文案为“多维度分析”。
- [ ] 保持现有当前页过滤、查询参数透传和 UTF-8 URL 编码逻辑不变。

### Task 2: 创建独立空白页面

**Files:**
- Create: `可视化/多维度分析/index.html`

- [ ] 创建 UTF-8 HTML 文档，标题和页面主标题使用“多维度分析”。
- [ ] 引入 `../shared/chart_board.css` 和 `../shared/edge_float.css`。
- [ ] 保留品牌页头和悬浮球 DOM，加载现有悬浮球脚本并以 `PAGE_VIEW = "multi-dimensional-analysis"` 初始化。
- [ ] 不加入顶部分析导航，不加载行情、因子、回测脚本，主工作区保持空白。

### Task 3: 验证页面跳转

**Files:**
- Test: `可视化/shared/edge_float_nav.js`
- Test: `可视化/多维度分析/index.html`

- [ ] 使用文本检查确认菜单项、页面标题、UTF-8 声明和脚本路径存在。
- [ ] 启动静态 Web 服务后，从量化因子页面访问新页面 URL，确认返回成功并显示中文标题。
