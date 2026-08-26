# 多维度分析页面

## 入口与职责

- 入口：`http://127.0.0.1:8086/多维度分析/index.html`
- 页面文件：`index.html`，当前样式和脚本内嵌在同一文件。
- 服务：`../sector_research_service.py`
- 领域模型：`../../CONTEXT.md`
- 统一设计：`../../docs/板块研究系统统一设计.md`

页面读取板块研究实体（正式实体及白名单 `staging` 候选），以及正式报告或 `staging` 候选预览，展示六维评分、市场状态、历史表现、主张、证据和发布状态。URL 使用 `?sector=<同花顺代码>` 选择实体。

## 主要 API

- `GET /api/sector/entities`
- `GET /api/sector/report?sector_code=...`
- 后端还提供 `GET /api/sector/dashboard?sector_code=...`，当前页面主要使用 report。

实体接口读取失败时，页面使用内置 `FALLBACK_CATALOG` 维持板块选择器可用；该目录只用于选择器兜底，不包含报告数据。报告接口仍必须成功返回正式报告或 `staging` 候选预览，否则页面显示读取错误。

页面内存在加载前的示例占位内容，报告 API 成功后会被返回数据覆盖。示例值不属于研究结果，不能写入数据层或作为报告接口的回退结果发布。

## 修改检查

- 领域术语以 `CONTEXT.md` 为准，不在页面内创造同义字段。
- 保持规则分、模型调整、最终维度分和置信度分离。
- 没有可读取的正式报告或 `staging` 候选预览时明确显示错误，不把占位值当真实值。
- 修改报告字段时同步 `sector_research_service.py`、统一设计文档和接口测试。
- 页面继续扩大时再拆分独立 CSS/JS；拆分前不要建立只有一个调用方的共享文件。
