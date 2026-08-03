# 板块研究报告标准字段设计

## 目标

统一板块研究报告到前端之间的字段名称和数据类型，避免不同研究批次使用别名后在页面显示“未提供”。不修改原始研究结论、评分或历史文件。

## 方案

前端只读取标准字段。`sector_research_service.py` 在读取正式报告或白名单 staging 报告后，把历史别名和伴随文件归一化为标准字段。后续研究任务必须直接生成标准字段，兼容层只服务历史结果。

核心标准字段为：

- `analysis_archetype: string | null`
- `analysis_archetype_version: integer | null`
- `classification_facets: object<string, string[]>`
- `classification_confidence: number | null`
- `type_review_status: string | null`
- `classification_reason: string | null`
- `boundary: object`
- `research_questions: array`
- `evidence_category_statuses: object<string, object>`
- `overall_formula: string | null`
- `overall_explanation: string | null`
- `verdict: string | null`
- `state_regime: string | null`
- `unconfirmed_items: array`

历史兼容映射包括：`sector_adapter -> analysis_archetype`、`facets -> classification_facets`、`source_status -> evidence_category_statuses`、`overall_score_formula -> overall_formula`。研究问题从伴随的 `research_tasks.json/parquet` 提取；分类理由和置信度可以从 `assessment.json` 中的 `object_adapter` 评估提取。

## 缺失处理

兼容层不得根据维度分数编造 `verdict`、`state_regime`、板块边界或类型复核结论。真正未生成的字段保留空值；前端区分“本次研究未生成”和客观指标的“历史不足/不可计算”。

## 验证

增加服务层契约测试，覆盖中报预增报告使用的全部历史别名、伴随文件读取、固定字段类型和缺失不伪造。运行现有服务测试，并通过本地 API 验证 `886110.THS`。
