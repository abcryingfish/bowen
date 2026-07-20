# Gold Sector Rating HTML Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build three UTF-8 standalone HTML views of the 2026-07-14 A-share gold-sector rating JSON.

**Architecture:** Each output is an independent HTML file with the same data snapshot embedded locally. Version A renders a static research report, version B renders syntax-highlighted JSON with a field guide, and version C renders a lightweight interactive dashboard using only native CSS and JavaScript.

**Tech Stack:** HTML5, CSS3, vanilla JavaScript, PowerShell validation, in-app browser visual verification.

---

## File Structure

- Create `temp/黄金板块评分_A_结构化报告.html`: human-readable static report.
- Create `temp/黄金板块评分_B_JSON高亮.html`: syntax-highlighted JSON reader.
- Create `temp/黄金板块评分_C_交互看板.html`: interactive score dashboard.
- No existing application files are modified.

### Task 1: Establish Data Contract Checks

**Files:**
- Test: the three HTML files created by Tasks 2-4

- [ ] **Step 1: Record required shared values**

Use these exact values in all three pages:

```text
analysis_date=2026-07-14
sector_id=sw3_gold
sector_name=黄金
overall_score=7.6
verdict=高位震荡偏强
price_range_low=-4.0
price_range_high=7.0
```

- [ ] **Step 2: Define the failing pre-implementation check**

Run:

```powershell
$files = @(
  'temp/黄金板块评分_A_结构化报告.html',
  'temp/黄金板块评分_B_JSON高亮.html',
  'temp/黄金板块评分_C_交互看板.html'
)
$files | ForEach-Object { Test-Path $_ }
```

Expected before implementation: three `False` results.

### Task 2: Build Version A Static Report

**Files:**
- Create: `temp/黄金板块评分_A_结构化报告.html`

- [ ] **Step 1: Create semantic report structure**

Use this semantic document structure. Each named section renders the corresponding complete array or text field from the approved JSON snapshot:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>黄金板块评分｜结构化报告</title>
</head>
<body>
  <header>
    <p>SW3 · 2026-07-14</p>
    <h1>黄金板块评分</h1>
    <strong>7.6 / 10</strong>
    <p>高位震荡偏强 · 预期区间 -4.0% 至 7.0%</p>
  </header>
  <main>
    <section id="scores"><h2>六维评分</h2></section>
    <section id="logic"><h2>核心判断</h2></section>
    <section id="phases"><h2>阶段推演</h2></section>
    <section id="factors"><h2>多空因素</h2></section>
    <section id="indicators"><h2>关键指标</h2></section>
    <section id="stocks"><h2>关注股票</h2></section>
    <section id="signals"><h2>观察信号</h2></section>
    <section id="sources"><h2>数据来源</h2></section>
  </main>
</body>
</html>
```

- [ ] **Step 2: Add self-contained responsive styling**

Define dark neutral colors, gold only as the primary accent, red/green for risk and bullish signals, `max-width: 1280px`, two-column desktop grids, and this narrow-screen rule:

```css
@media (max-width: 760px) {
  .hero-grid, .content-grid, .factor-grid { grid-template-columns: 1fr; }
  body { padding: 12px; }
}
```

- [ ] **Step 3: Validate content and encoding**

Run:

```powershell
$p = 'temp/黄金板块评分_A_结构化报告.html'
$text = Get-Content -Raw -Encoding UTF8 $p
@('黄金','7.6','高位震荡偏强','中金黄金','7544') | ForEach-Object { $text.Contains($_) }
```

Expected: five `True` results.

### Task 3: Build Version B JSON Reader

**Files:**
- Create: `temp/黄金板块评分_B_JSON高亮.html`

- [ ] **Step 1: Embed the complete JSON snapshot**

Store the approved array in a JavaScript constant, then render it with `JSON.stringify(data, null, 2)` so the browser view and source data stay aligned:

```javascript
const data = [{
  analysis_date: "2026-07-14",
  sector_id: "sw3_gold",
  sector_name: "黄金",
  overall_score: 7.6,
  verdict: "高位震荡偏强"
}];
const rawJson = JSON.stringify(data, null, 2);
```

The final object must also contain every approved score, narrative, factor, indicator, stock, signal, and source field.

- [ ] **Step 2: Render syntax highlighting safely**

Escape HTML before adding spans and color tokens without using `innerHTML` on unescaped JSON:

```javascript
function escapeHtml(value) {
  return value.replace(/[&<>]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[char]);
}
function highlightJson(value) {
  return escapeHtml(value).replace(
    /("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"\s*:)|("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*")|\b(true|false|null)\b|-?\d+(?:\.\d+)?/g,
    token => `<span class="token">${token}</span>`
  );
}
```

- [ ] **Step 3: Add a compact Chinese field guide**

Include mappings for `overall_score`, the six dimension scores, `core_logic`, `key_contradiction`, `bullish_factors`, `bearish_factors`, `key_indicators`, `focus_stocks`, `watch_signals`, and `data_sources`.

- [ ] **Step 4: Validate JSON reader content**

Run:

```powershell
$p = 'temp/黄金板块评分_B_JSON高亮.html'
$text = Get-Content -Raw -Encoding UTF8 $p
@('JSON.stringify','highlightJson','overall_score','bullish_factors','data_sources') | ForEach-Object { $text.Contains($_) }
```

Expected: five `True` results.

### Task 4: Build Version C Interactive Dashboard

**Files:**
- Create: `temp/黄金板块评分_C_交互看板.html`

- [ ] **Step 1: Render score bars from structured data**

Use one array as the score source:

```javascript
const scores = [
  ['政策', 8.5], ['基本面', 9.0], ['资金', 7.8],
  ['技术', 6.8], ['估值', 6.0], ['风险', 6.5]
];
```

Each bar width is `${score * 10}%`, with an accessible text value beside it.

- [ ] **Step 2: Add factor tabs**

Create two buttons with `data-factor-view="bullish"` and `data-factor-view="bearish"`. Clicking a button sets its `aria-selected` state and hides the other factor list with the `hidden` attribute.

- [ ] **Step 3: Add collapsible sections and source filter**

Use native `<details>` elements for long sections. Add a `<select>` containing `全部来源`, `官方数据`, `财经门户`, `金融数据`, `行业机构`, and filter source rows by their `data-type` attribute.

- [ ] **Step 4: Validate the interaction contracts**

Run:

```powershell
$p = 'temp/黄金板块评分_C_交互看板.html'
$text = Get-Content -Raw -Encoding UTF8 $p
@('data-factor-view','aria-selected','<details','source-filter','score * 10') | ForEach-Object { $text.Contains($_) }
```

Expected: five `True` results.

### Task 5: Cross-File and Visual Verification

**Files:**
- Verify: all three output HTML files

- [ ] **Step 1: Run cross-file checks**

```powershell
$files = Get-ChildItem 'temp/黄金板块评分_*.html'
if ($files.Count -ne 3) { throw "Expected 3 HTML files, got $($files.Count)" }
foreach ($file in $files) {
  $text = Get-Content -Raw -Encoding UTF8 $file.FullName
  foreach ($required in @('2026-07-14','黄金','7.6','高位震荡偏强')) {
    if (-not $text.Contains($required)) { throw "$required missing from $($file.Name)" }
  }
}
```

Expected: exit code `0` with no output.

- [ ] **Step 2: Open each local HTML in the in-app browser**

Verify at desktop width that the first viewport is nonblank, text does not overlap, and sections remain readable.

- [ ] **Step 3: Verify mobile layout**

Set a 390 x 844 viewport and verify all three pages have no horizontal overflow. In version C, activate both factor tabs, toggle a details section, and change the source filter.

- [ ] **Step 4: Report direct file links**

Return absolute clickable paths to all three HTML files and summarize which version best suits quick reading, raw auditing, and interactive review.
