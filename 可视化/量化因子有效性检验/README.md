# 量化因子有效性检验页面

## 入口与职责

- 入口：`http://127.0.0.1:8086/量化因子有效性检验/dashboard.html`
- 前端：`dashboard.html`、`factor_validation.js`、`factor_validation.css`
- 服务与计算：`factor_validation_service.py`
- 因子分组：`../../因子分类/factor_catalog.json`

页面读取普通因子和形态因子，按选择的股票池、日期与收益观察窗口运行有效性检验。计算以异步任务执行，结果可保存为本地记录。

## 主要 API

- `GET /api/factor-validation/factors`
- `GET /api/factor-validation/stock-pools`
- `POST /api/factor-validation/run`
- `GET /api/factor-validation/jobs?id=...`
- `GET|POST|DELETE /api/factor-validation/records`

记录默认写入本目录的 `records/`，属于运行产物，后续新记录原则上不应提交 Git。仓库中可能存在已被 Git 跟踪的历史记录；新增忽略规则不会自动取消跟踪，是否保留或取消跟踪应单独确认，不能在页面修改中顺带删除。任务状态保存在进程内存中，API 服务重启后未完成任务不会自动恢复。

## 计算边界

- 因子输入来自 `D:\database\signal_daily\factor=*`，形态因子使用其独立读取契约。
- 当前前瞻 `n` 日收益按 `close[t+n] / close[t] - 1` 计算，并与 `t` 日因子值对齐，收益起点是因子当日收盘价。该口径适用于因子在当日收盘可获得、可按收盘研究的场景；若因子只能收盘后确定，实盘检验应改用下一交易日开盘价或收盘价起算，避免执行时点偏差。
- 股票池、可用行情、因子覆盖率和有效样本数应分别报告。
- 调整收益轴、回看天数、分组或标签时，不要改变历史记录 schema 而不提供兼容处理。

## 修改检查

- API 请求字段变化时同步前端、`api_server.py` 和服务测试。
- 新因子应通过 catalog 自动发现；不要为普通因子重复维护硬编码列表。
- 检查窗口不足、无行情、无因子值、重复主键、停牌和股票池为空。
- 运行本目录的 `test_factor_validation_jobs.py`、`test_factor_validation_labels.js`，以及根目录的 `test_factor_validation_service.py`、`test_edge_float_navigation.js`。
