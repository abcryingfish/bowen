# 股票质量原始因子扩展 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有股票基本面原始因子 bundle 中增加七个公告日点时、可复算的质量原始指标。

**Architecture:** 扩展现有 `FACTOR_NAME_MAP` 和 `_snapshot_factor_values`，复用已经读入内存的收入、利润、现金流、资产和毛利数据。稳定性指标在单个公告事件快照内按连续报告季度计算历史TTM序列，不增加磁盘扫描。

**Tech Stack:** Python 3.10、pandas、NumPy、DuckDB、pytest、UTF-8 JSON。

---

### Task 1: 用失败测试定义新增目录和公式

**Files:**
- Modify: `ZXW因子/test_stock_fundamental_raw_factors.py`
- Modify: `ZXW因子/test_stock_fundamental_raw_factor_catalog.py`
- Modify: `可视化/test_market_data_service_stock_fundamental_catalog.py`

- [ ] 扩展期望映射，加入七个中文名与英文字段名。
- [ ] 扩展财务夹具，使标准样例可独立核对ROA、毛利润资产比、现金含量、应计利润率、资产周转率和两个12季度标准差。
- [ ] 增加净利润非正时现金含量为空的边界测试。
- [ ] 运行 `.venv\Scripts\python.exe -m pytest ZXW因子\test_stock_fundamental_raw_factors.py ZXW因子\test_stock_fundamental_raw_factor_catalog.py 可视化\test_market_data_service_stock_fundamental_catalog.py -q`，确认因目录和输出缺失而失败。

### Task 2: 实现七个原始指标

**Files:**
- Modify: `ZXW因子/股票基本面原始因子.py`

- [ ] 扩展 `FACTOR_NAME_MAP`。
- [ ] 在 `_snapshot_factor_values` 中按设计公式计算五个最新TTM指标。
- [ ] 构造每个连续季度的历史TTM ROE与TTM毛利率，仅在最近12个报告季度完整时输出总体标准差。
- [ ] 运行Task 1测试，确认全部通过。

### Task 3: 同步因子目录与说明

**Files:**
- Modify: `因子分类/factor_catalog.json`
- Modify: `docs/superpowers/specs/2026-08-02-stock-fundamental-raw-factors-design.md`

- [ ] 将七个指标追加到 `stock_fundamental_raw` 的 `core_factors` 与 `children`，保持UTF-8中文。
- [ ] 在现有原始因子设计中记录新增字段、单位及公式。
- [ ] 运行目录与前端发现测试。

### Task 4: 回归与真实数据抽样

**Files:**
- Test only; no production file required.

- [ ] 运行所有 `stock_fundamental_raw` 相关测试。
- [ ] 运行 `ZXW因子` 中主生成器规划相关测试，确认股票专属范围未改变。
- [ ] 用本地最新财务数据抽样调用快照公式，确认七个指标存在有限值且无无穷值。
- [ ] 检查目标文件差异、Python语法和JSON解析。
- [ ] 复查 `D:\CodexHome\logs_2.sqlite` TRACE触发器、TRACE最大ID和WAL增长。
