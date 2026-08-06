# 模型有效性页面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增可通过 `edge-float-hud` 进入的“模型有效性”页面，展示 3×2 六个 TradingView 风格的演示图表窗口。

**Architecture:** 页面独立放在 `可视化/模型有效性/`，由 `index.html` 负责结构、`model_validity.css` 负责页面样式、`model_validity.js` 负责确定性演示数据与 SVG 图表绘制。共享导航只在 `可视化/shared/edge_float_nav.js` 增加一条注册项，继续复用现有悬浮球脚本。

**Tech Stack:** UTF-8 HTML、原生 CSS、原生 JavaScript、内联 SVG、现有 `edge_float.css` / `edge_float_hud.js` / `edge_float_mangekyo_canvas.js`。

---

### Task 1: 添加页面契约测试

**Files:**
- Create: `test_model_validity_page.js`

- [ ] **Step 1: 写一个会失败的页面契约测试**

```js
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const root = __dirname;
const page = fs.readFileSync(path.join(root, "可视化", "模型有效性", "index.html"), "utf8");
const nav = fs.readFileSync(path.join(root, "可视化", "shared", "edge_float_nav.js"), "utf8");

assert.match(page, /<title>模型有效性<\/title>/);
assert.match(page, /window\.PAGE_VIEW\s*=\s*["']model-validity["']/);
assert.strictEqual((page.match(/class=["'][^"']*model-chart-card/g) || []).length, 6);
assert.match(page, /edge-float-hud/);
assert.match(nav, /model-validity/);
console.log("模型有效性页面契约通过");
```

- [ ] **Step 2: 运行测试确认它按预期失败**

Run: `node test_model_validity_page.js`

Expected: FAIL，因为新页面目录和导航注册尚未创建。

### Task 2: 创建页面结构和共享悬浮球接入

**Files:**
- Create: `可视化/模型有效性/index.html`
- Modify: `可视化/shared/edge_float_nav.js`

- [ ] **Step 1: 在导航注册表中新增页面项**

在 `PAGES` 数组中加入：

```js
{ id: "model-validity", file: "../%E6%A8%A1%E5%9E%8B%E6%9C%89%E6%95%88%E6%80%A7/index.html", label: "模型有效性" },
```

- [ ] **Step 2: 创建 UTF-8 页面骨架**

页面包含：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>模型有效性</title>
  <link rel="stylesheet" href="../shared/edge_float.css">
  <link rel="stylesheet" href="./model_validity.css">
</head>
<body>
  <header class="model-validity-header">
    <div class="brand">量化研究工作台</div>
    <div><span class="eyebrow">MODEL VALIDITY</span><h1>模型有效性</h1></div>
    <div id="page-clock" class="page-clock">Time: --</div>
  </header>
  <main class="model-validity-shell">
    <section class="intro-line"><span>全历史演示视图</span><span>当前点：实时占位</span></section>
    <section class="model-chart-grid" aria-label="六个风格图表">
      <article class="model-chart-card" data-chart-index="0"><h2>风格图 1</h2><div class="chart-mount" id="chart-0"></div></article>
      <article class="model-chart-card" data-chart-index="1"><h2>风格图 2</h2><div class="chart-mount" id="chart-1"></div></article>
      <article class="model-chart-card" data-chart-index="2"><h2>风格图 3</h2><div class="chart-mount" id="chart-2"></div></article>
      <article class="model-chart-card" data-chart-index="3"><h2>风格图 4</h2><div class="chart-mount" id="chart-3"></div></article>
      <article class="model-chart-card" data-chart-index="4"><h2>风格图 5</h2><div class="chart-mount" id="chart-4"></div></article>
      <article class="model-chart-card" data-chart-index="5"><h2>风格图 6</h2><div class="chart-mount" id="chart-5"></div></article>
    </section>
  </main>
  <div id="edge-float-cluster" class="edge-float-cluster" data-dock="right"><div id="edge-float-hud" class="edge-float-hud" role="note" aria-label="侧边浮标"><canvas id="edge-float-mangekyo-canvas" class="edge-float-mangekyo-canvas" width="600" height="600" aria-hidden="true"></canvas></div></div>
  <div id="edge-float-menu" class="edge-float-menu" role="menu" aria-hidden="true"></div>
  <script>window.PAGE_VIEW = "model-validity";</script>
  <script defer src="../shared/edge_float_nav.js"></script>
  <script defer src="../shared/edge_float_mangekyo_canvas.js"></script>
  <script defer src="../shared/edge_float_hud.js"></script>
  <script defer src="./model_validity.js"></script>
</body>
</html>
```

- [ ] **Step 3: 运行契约测试，确认导航和页面骨架通过**

Run: `node test_model_validity_page.js`

Expected: PASS with `模型有效性页面契约通过`.

### Task 3: 实现六个确定性演示图表

**Files:**
- Create: `可视化/模型有效性/model_validity.js`
- Create: `可视化/模型有效性/model_validity.css`

- [ ] **Step 1: 实现无外部依赖的数据适配器**

在 `model_validity.js` 中定义 `buildDemoSeries(index, count = 80)`，使用 `Math.sin`、`Math.cos` 和索引偏移生成可复现的 80 个点；不要调用随机数，确保每次刷新形状稳定。

- [ ] **Step 2: 实现 SVG 图表渲染**

定义 `renderChart(mount, series, index)`：

1. 创建带 `viewBox="0 0 640 220"` 的 SVG。
2. 绘制 4 条水平网格线和底部时间轴。
3. 将数据归一化到绘图区，生成一条折线路径。
4. 在最后一个点绘制高亮圆点，并补充 `<title>` 和 `aria-label`。
5. 将 SVG 插入对应的 `.chart-mount`。

- [ ] **Step 3: 初始化页面时绘制 6 张图并更新时钟**

遍历 `#chart-0` 到 `#chart-5`，分别调用数据适配器与渲染器；页面时钟每秒更新为中文本地时间，不增加实时 API 请求。

- [ ] **Step 4: 编写响应式页面样式**

`model_validity.css` 需要实现：

- 深色研究工作台背景和与现有页面一致的绿色强调色。
- `.model-chart-grid` 默认三列、宽度不足时两列、窄屏单列。
- `.model-chart-card` 只承担图表窗口布局，不覆盖共享悬浮球样式。
- SVG 宽度 100%、高度自动，避免横向溢出。

### Task 4: 静态语法与页面验证

**Files:**
- Test: `test_model_validity_page.js`
- Verify: `可视化/模型有效性/index.html`

- [ ] **Step 1: 运行 JavaScript 语法检查**

Run: `node --check '可视化/模型有效性/model_validity.js'`

Expected: exit code 0 and no output.

- [ ] **Step 2: 运行页面契约测试**

Run: `node test_model_validity_page.js`

Expected: `模型有效性页面契约通过`.

- [ ] **Step 3: 启动静态服务并检查页面返回**

先运行项目已有静态服务脚本 `可视化\start_web_server.bat`，再执行：

```powershell
Invoke-WebRequest 'http://127.0.0.1:8086/模型有效性/index.html' -UseBasicParsing | Select-Object -ExpandProperty StatusCode
```

Expected: `200`，页面源码包含 `模型有效性`、6 个 `.model-chart-card` 和 `edge-float-hud`。

- [ ] **Step 4: 做差异和编码检查**

Run: `git diff --check -- '可视化/模型有效性' '可视化/shared/edge_float_nav.js' 'test_model_validity_page.js'`

Expected: no whitespace errors; all新增中文文件使用 UTF-8。

## Self-review checklist

- 页面、样式、脚本和导航注册均有明确任务覆盖。
- 没有引入真实因子或业务结论，符合当前“先显示图”的范围。
- 没有使用随机数据，刷新后图形稳定可复现。
- 共享导航只新增一条页面注册，不改变已有页面逻辑。
- 验证覆盖 JavaScript 语法、页面结构、HTTP 返回、中文编码和响应式布局。
