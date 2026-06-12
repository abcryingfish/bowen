backtrader 目录说明
==================

本目录为 ZXW 相关日线回测与可视化后台对接代码。

给维护者
--------
- 多模型注册表：model_registry.py（adopt_model id、web_runnable、右栏 description_html）。
- 网页任务入口：configurable_backtest.py（校验 payload 后调用注册表）。
- 新增模型流程：MODEL_AUTHORING.md。
- 前端模型列表：GET /api/backtest/models（可视化/api_server.py），index.html 启动时拉取。
- **sys.path**：向 `backtrader` 工程根目录应使用 **`append`**，勿对名为 `backtrader` 的文件夹 `insert(0, …)`，否则会注册成 namespace 包并遮蔽 pip 的 `backtrader` 库（`bt.feeds` 丢失）。`backtest_job_service` 与各 runner 已按此处理。

settings.py
-----------
回测公共配置与工具：初始资金、手续费、D:\\database 下各类路径、组合/现金/买入持有曲线代码、
FactorPandasData（通用五列）、create_duckdb_view、create_cerebro、核心 **run_zxw_backtest** 等。
各模型 runner 应优先调用此处逻辑，避免重复常量。

model_registry.py
-----------------
`REGISTRY`：`adopt_model` -> `ModelEntry`（标题、HTML 说明、是否可走网页任务、是否消费前端买卖规则、`run` 函数）。
`list_models_public()`：供 API 与前端构建模型列表与右栏说明。

models/
-------
**一模型一子目录**：`runner.py`（及可选 `strategy.py`）、`README.md`。
当前注册并支持网页任务：`hong_ziming_avg_position`、`zxw_rule_backtest`、`zxw_rule_backtest_profit30`、
`zxw_strong_adjusted_only`、`zxw_init_10pct_snapshot`、`configurable_signal_rules`。
`models/zxw_legacy_mac_kdj_bottom/` 为 **10% MAC/KDJ 引擎实现**，供 `zxw_init_10pct_snapshot` 内部调用，**不再单独作为 adopt_model 暴露**。

洪梓铭策略类
-----------
源码在 **`models/hong_ziming_avg_position/strategy.py`**（`HongZimingAvgPositionStrategy`）。

ZXW回测_看结果（主力管线模块）
----------------------------
源码文件：**`models/zxw_rule_backtest/zxw_view_results_full.py`**（原根目录 `ZXW回测_看结果.py`，已迁入以避免与 `models` 重复）。

ZXW回测_看结果--原版（legacy 管线模块，仅供 10% 快照入口内部使用）
--------------------------------------------------
源码文件：**`models/zxw_legacy_mac_kdj_bottom/zxw_view_results_legacy.py`**（原根目录 `--原版.py`，已迁入）。网页 adopt_model 不再列出「原版 MAC/KDJ」独立项；需同款策略请选 **`zxw_init_10pct_snapshot`**。

（原 `ZXW回测_看结果.ipynb` 与 `4-28初始10%硬仓位控制/` 已删除：与 `.py` 或 `zxw_init_10pct_snapshot` 重复，且未被任务代码引用。）

configurable_backtest.py
------------------------
解析前端 JSON（codes、日期、`adopt_model`、买卖规则等），调用 **`model_registry.run_registered_model`**；本身不再内嵌大段策略代码。

网页侧 **4-28 实验命名** 请选用模型 id **`zxw_init_10pct_snapshot`**（与 legacy 同引擎，见 `models/zxw_init_10pct_snapshot/README.md`）。

关系简述
--------
`settings` 为执行与路径底座；`models/*/zxw_view_results_*.py` 为数据/策略实现；`models/*/runner` 为各产品化入口；`model_registry` 为单一注册与说明源；`configurable_backtest` 为 API 薄壳。
