# 洪超迷你底 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 3 日洪超迷你底，以 5% 最大反弹为失效边界、计入洪抄底总分 0.25，并贯通生成、落盘和前端。

**Architecture:** 直接扩展现有 `hong_bottom_fishing` bundle，复用其最近信号低点和最大反弹计算口径。中文映射继续驱动现有自动落盘；展示端只增加显式字段映射与目录项，不新建存储分支。

**Tech Stack:** Python、pandas、NumPy、pytest、JSON、HTML

---

### Task 1: 用测试锁定新因子业务口径

**Files:**
- Create: `ZXW因子/test_hong_ultra_mini_bottom.py`
- Test: `ZXW因子/test_hong_ultra_mini_bottom.py`

- [ ] 编写主实现与 ETF 副本的参数化测试，覆盖 3 日历史门槛、0.25 分、0.5 分优先级和 5% 边界。
- [ ] 运行测试，确认因缺少 `hong_ultra_mini_bottom` 而失败。

### Task 2: 扩展两个洪抄底实现

**Files:**
- Modify: `ZXW因子/洪抄底.py`
- Modify: `ZXW因子-股票池ETF分类/洪抄底.py`

- [ ] 在两个独立实现中分别加入 3 日 LLV、信号低价、最近信号反弹和 `< 0.05` active。
- [ ] 在评分互斥链末尾加入 0.25 分，并补充 bundle 输出、中文映射和回看配置。
- [ ] 运行业务测试并确认通过。

### Task 3: 接入因子目录和前端服务

**Files:**
- Modify: `因子分类/factor_catalog.json`
- Modify: `可视化/market_data_service.py`
- Modify: `可视化/量化因子有效性检验/factor_validation_service.py`
- Test: `ZXW因子/test_hong_ultra_mini_bottom.py`

- [ ] 先扩展契约测试，验证目录与两个服务映射，确认失败。
- [ ] 添加 `洪超迷你底 -> hong_ultra_mini_bottom` 映射和洪抄底类目录项。
- [ ] 运行契约测试并确认通过。

### Task 4: 更新说明并完成验证

**Files:**
- Modify: `因子解释/洪抄底总分构成说明.html`
- Modify: `C:/Users/Administrator/Documents/Codex/2026-07-24/bagn-2/outputs/洪抄底总分逻辑说明.html`

- [ ] 在说明中加入 3 日、0.25 分和 5% 独立阈值。
- [ ] 验证 Python 编译、JSON 解析、UTF-8 解码和完整测试集。
- [ ] 检查变更差异，确认未混入工作区既有修改。
