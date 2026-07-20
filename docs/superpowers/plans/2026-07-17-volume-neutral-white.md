# 成交量平盘白色 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 主图成交量柱上涨为红色、下跌为绿色、平盘为白色，同时保持 K 线原有配色。

**Architecture:** 在现有主图脚本中增加成交量专用颜色函数，复用既有红绿常量并新增白色常量。成交量映射改用新函数，K 线继续调用原函数。

**Tech Stack:** 原生 JavaScript、Lightweight Charts、Node.js `assert`/`vm`。

---

### Task 1: 成交量平盘颜色

**Files:**
- Create: `可视化/test_volume_bar_color.js`
- Modify: `可视化/shared/chart_board_core.js:1626`
- Modify: `可视化/shared/chart_board_core.js:5061`

- [ ] **Step 1: Write the failing test**

新增 Node 测试，从真实前端源码提取颜色常量与 `getAShareVolumeColor`，验证上涨红、下跌绿、平盘白及前收比较。

- [ ] **Step 2: Run test to verify it fails**

Run: `node 可视化/test_volume_bar_color.js`

Expected: FAIL，提示缺少 `getAShareVolumeColor`。

- [ ] **Step 3: Write minimal implementation**

新增 `A_SHARE_FLAT_VOLUME_COLOR = "#ffffff"` 和 `getAShareVolumeColor(bar, previousBar)`。两个有效比较价格相等时返回白色，大于返回红色，小于返回绿色；没有有效前收时比较 `close` 与 `open`。成交量映射调用该函数，K 线函数保持不变。

- [ ] **Step 4: Run test to verify it passes**

Run: `node 可视化/test_volume_bar_color.js`

Expected: 输出 `成交量颜色测试通过`。

- [ ] **Step 5: Run regression and browser verification**

Run: `node 可视化/test_api_base_url_resolution.js`

Expected: 输出 `API 地址解析测试通过`。刷新量化因子页面，切换 `1min`，确认成交量柱包含白色平盘柱且 K 线红绿配色不变。
