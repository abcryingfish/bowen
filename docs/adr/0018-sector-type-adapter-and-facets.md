---
status: accepted
date: 2026-07-16
---

# 板块采用唯一评分适配类型与多值分类属性

板块分类采用双层模型：每个研究实体只有一个 `analysis_archetype`，用于选择评分适配器、子指标权重、阈值和横截面比较组；同时保存多值 `classification_facets`，用于检索、解释、证据关联和知识图谱。分类属性不改变六维评分定义或顶层权重。

`analysis_archetype` 固定为12类：`standard_industry`、`cyclical_resource`、`regional_basket`、`industry_chain_theme`、`policy_driven`、`technology_growth`、`event_driven`、`company_attribute`、`security_status`、`universe_sample`、`style_strategy`、`general_concept`。

自动分类默认规则：`881`归为行业、`882`归为地域，`885/886`依据名称、成分和证据生成候选类型。最高候选置信度须达到0.70且领先第二候选至少0.10；政策、事件和证券状态还必须存在可追溯证据，否则标记 `review_required`。

未完成语义复核时，技术、资金、风险可以发布；基本面、估值、政策和综合分不发布。这是业务状态，不是程序失败，不进入自动重试队列。

类型变更只对新的分析日期生效，历史评估保留原类型和原策略版本。人工确认后可单板块重跑并更新current，但不覆盖旧分类记录。
