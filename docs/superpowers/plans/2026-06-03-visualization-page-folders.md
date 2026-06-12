# Visualization Page Folders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the busy `可视化` frontend directory into page folders while keeping existing root URLs working.

**Architecture:** Keep backend Python services and launch scripts in `可视化/`. Move reusable frontend runtime assets into `可视化/shared/`. Move each page HTML and page-only JS/CSS into its own folder, and leave lightweight root HTML redirect wrappers for old URLs.

**Tech Stack:** Static HTML/CSS/JavaScript served by `python -m http.server`, Python API service, Windows batch launch scripts.

---

### Task 1: Move Files Into Clear Frontend Boundaries

**Files:**
- Move common assets to `可视化/shared/`.
- Move page-specific assets to `可视化/量化因子/`, `可视化/形态面/`, `可视化/舆情面/`, `可视化/基本面/`, `可视化/结果展示/`, `可视化/组合结果/`, and `可视化/组合图表/`.

- [ ] Move common chart, floating-nav, backtest-context, and vendor files into `shared`.
- [ ] Move each page HTML to `index.html` inside its page folder.
- [ ] Move page-only JS/CSS beside its page.
- [ ] Leave Python API/data service files and `.bat` launch files at the `可视化` root.

### Task 2: Update Resource And Navigation Paths

**Files:**
- Modify HTML files inside page folders.
- Modify `可视化/shared/edge_float_nav.js`.
- Modify `可视化/shared/chart_board_core.js`.
- Modify `可视化/shared/chart_board_info_core.js`.
- Modify page JS files that navigate to old root HTML files.

- [ ] Replace root-relative same-folder resource paths such as `./chart_board_core.js` with `../shared/chart_board_core.js`.
- [ ] Replace page navigation targets such as `量化因子.html` with `../量化因子/`.
- [ ] Replace result navigation targets such as `result.html` with `../组合结果/`.
- [ ] Keep API calls unchanged because API URLs are absolute through `API_BASE_URL`.

### Task 3: Add Compatibility Redirects

**Files:**
- Create root wrappers: `可视化/量化因子.html`, `可视化/形态面.html`, `可视化/舆情面.html`, `可视化/基本面.html`, `可视化/结果展示.html`, `可视化/result.html`, `可视化/index.html`.

- [ ] Each wrapper redirects immediately to the new folder URL.
- [ ] Each wrapper includes a fallback link for browsers with JavaScript disabled.
- [ ] Existing bookmarked URLs continue to work.

### Task 4: Verify Static Loading

**Files:**
- No source file changes expected.

- [ ] Run Python syntax checks for backend files that remain at root.
- [ ] Serve `可视化` with `python -m http.server`.
- [ ] Request each old root URL and each new folder URL.
- [ ] Confirm the returned HTML references existing local JS/CSS files.
