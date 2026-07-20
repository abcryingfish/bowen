# 同花顺一级指数日线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将同花顺软件一级512个指数日线按现有月度 Parquet 增量契约写入 `index_data_daily`，并纳入全量数据更新入口。

**Architecture:** 独立下载脚本负责指数清单、年度JSONP请求、标准化、增量计划和月分区合并；合并入口只负责编排与参数透传。生产代码不依赖 ZXW，也不修改现有股票、普通指数和ETF阶段。

**Tech Stack:** Python 3.11、urllib、pandas、polars、duckdb、pytest、同花顺本地名称表和公开行情接口。

---

### Task 1: 下载脚本核心契约测试

**Files:**
- Create: `test_ths_level1_index_daily.py`
- Create: `工具/获得同花顺1级指数日频数据.py`

- [ ] **Step 1: 写失败测试**

测试导入尚不存在的生产模块，并约定：前缀计数为90/33/293/96；JSONP记录转成12列；15:29截止上一工作日、15:30截止当天；已有最大日期从当天重拉。

- [ ] **Step 2: 运行测试确认 RED**

Run: `.venv\Scripts\python.exe -m pytest test_ths_level1_index_daily.py -q`

Expected: FAIL，原因为生产模块尚不存在或约定函数缺失。

- [ ] **Step 3: 实现最小核心函数**

实现 `load_level1_indices`、`parse_year_jsonp`、`resolve_completed_end_date`、`resolve_fetch_start` 和标准12列转换。中文文件使用GB18030读取，Python源码使用UTF-8。

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `.venv\Scripts\python.exe -m pytest test_ths_level1_index_daily.py -q`

Expected: PASS。

### Task 2: 月分区增量合并测试与实现

**Files:**
- Modify: `test_ths_level1_index_daily.py`
- Modify: `工具/获得同花顺1级指数日频数据.py`

- [ ] **Step 1: 写失败测试**

在临时目录构造旧 `merged.parquet` 与同日修订数据，断言合并后主键唯一、新值覆盖旧值、其他指数不受影响、临时part被清理。

- [ ] **Step 2: 运行指定测试确认 RED**

Run: `.venv\Scripts\python.exe -m pytest test_ths_level1_index_daily.py -q`

Expected: FAIL，原因为保存与合并函数缺失。

- [ ] **Step 3: 实现保存、扫描和网络重试**

实现每代码最大日期扫描、年度任务构建、urllib重试、按月临时文件写入、ZSTD merged原子替换、失败清单与统计。HTTP 404 作为该年份无数据，其他异常按线性退避重试。

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `.venv\Scripts\python.exe -m pytest test_ths_level1_index_daily.py -q`

Expected: PASS。

### Task 3: CLI与清理能力

**Files:**
- Modify: `test_ths_level1_index_daily.py`
- Modify: `工具/获得同花顺1级指数日频数据.py`

- [ ] **Step 1: 写失败测试**

覆盖 `--default-start`、`--end`、`--base-dir`、`--workers`、`--codes`、`--dry-run`，以及仅删除 `.THS` 行且保留普通指数的 `--purge-existing`。

- [ ] **Step 2: 运行测试确认 RED**

Run: `.venv\Scripts\python.exe -m pytest test_ths_level1_index_daily.py -q`

Expected: FAIL，原因为CLI或定向清理尚未实现。

- [ ] **Step 3: 实现CLI和安全校验**

`--purge-existing` 逐月原子重写 merged，只过滤 `htsc_code` 后缀 `.THS`；拒绝删除目标根目录之外的文件。正常运行校验512口径、OHLC关系、非负量额和主键唯一。

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `.venv\Scripts\python.exe -m pytest test_ths_level1_index_daily.py -q`

Expected: PASS。

### Task 4: 独立实跑

**Files:**
- Runtime data: `D:\database\index_data_daily`

- [ ] **Step 1: 小样本联网验证**

Run: `.venv\Scripts\python.exe 工具\获得同花顺1级指数日频数据.py --codes 881121 --default-start 2026-07-01`

Expected: `881121.THS` 写入7月分区，字段与主键校验通过。

- [ ] **Step 2: 全量独立运行**

Run: `.venv\Scripts\python.exe 工具\获得同花顺1级指数日频数据.py`

Expected: 512个代码完成或明确列出失败代码；所有成功数据写入月度 merged。

- [ ] **Step 3: 数据库验收**

用DuckDB验证 `.THS` 代码数、最小最大日期、重复主键为0、OHLC非法行为0、原有非THS指数仍存在。

### Task 5: 合并入口集成

**Files:**
- Modify: `工具/全量数据更新_合并入口.py`
- Modify: `工具/AGENTS.md`
- Modify: `test_ths_level1_index_daily.py`

- [ ] **Step 1: 写失败测试**

运行入口 `--dry-run --only ths_level1_index_daily`，断言命令指向新脚本；验证别名和 `--ths-level1-index-daily-args` 透传。

- [ ] **Step 2: 运行测试确认 RED**

Run: `.venv\Scripts\python.exe -m pytest test_ths_level1_index_daily.py -q`

Expected: FAIL，入口尚无该阶段。

- [ ] **Step 3: 添加阶段与文档**

在普通指数后增加 `ths_level1_index_daily`；增加 `ths` 别名和专用参数；更新执行顺序说明与 `工具/AGENTS.md` 数据根、CLI和脚本职责。

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `.venv\Scripts\python.exe -m pytest test_ths_level1_index_daily.py -q`

Expected: PASS。

### Task 6: 清理后从入口完整运行

**Files:**
- Runtime data: `D:\database\index_data_daily`

- [ ] **Step 1: 定向清理独立实跑写入**

Run: `.venv\Scripts\python.exe 工具\获得同花顺1级指数日频数据.py --purge-existing`

Expected: `.THS` 行为0，普通指数行数和主键保持不变。

- [ ] **Step 2: 入口语法和dry-run验证**

Run: `.venv\Scripts\python.exe -m py_compile 工具\获得同花顺1级指数日频数据.py 工具\全量数据更新_合并入口.py`

Run: `.venv\Scripts\python.exe 工具\全量数据更新_合并入口.py --dry-run`

Expected: exit 0，执行顺序包含同花顺阶段。

- [ ] **Step 3: 完整运行入口**

Run: `.venv\Scripts\python.exe 工具\全量数据更新_合并入口.py`

Expected: 所有阶段 exit 0；若出现代码缺陷，先补失败测试再修复并重跑。外部服务失败如实记录，不改无关业务逻辑。

- [ ] **Step 4: 最终验收**

重新运行完整测试、py_compile和DuckDB数据检查，确认512个 `.THS` 指数、重复主键0、非THS数据保留、中文无乱码。
