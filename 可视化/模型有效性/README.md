# 模型有效性页面

## 入口与职责

- 正式入口：`http://127.0.0.1:8086/模型有效性/index.html`
- 兼容入口：`../模型有效性.html`
- 前端：`index.html`、`model_validity.js`、`model_validity.css`
- 查询服务：`../style_monitor_service.py`
- 更新任务：`../style_monitor_job_service.py`
- 组合实现：`../../backtrader/models/style_portfolio_monitor/`

页面用于比较个股风格模型高分腿、低分腿和组合曲线，并查看持仓与交易明细。它不是普通策略回测结果页，也不使用前端回测模型注册表。

## 主要 API

- `GET /api/style-monitor/summary`
- `GET /api/style-monitor/curves`
- `GET /api/style-monitor/positions`
- `GET /api/style-monitor/trades`

曲线和明细来自持久化风格组合账本。因子生成完成后的更新 hook、复权行情、调仓日期、目标股票数和高低分方向必须保持一致。

## 修改检查

- 不要在页面端重新计算组合收益或用图表点反推持仓。
- 修改模型 ID、显示名、账本 schema 或高低分腿语义时同步前端、服务、repository 和测试。
- 复权方式必须与因子生成器一致；缺失复权因子不能静默按 1.0 处理。
- 修改回看天数时验证 URL、API 参数和图表范围同步。
- 运行 `test_style_monitor_api.py`、`test_style_monitor_job_service.py` 和 `backtrader/tests/style_portfolio_monitor/`。
