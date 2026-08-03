# 单板块 Codex 深度研究运行规范

> 适用范围：同花顺软件一级板块及后续个股深度研究。  
> 核心原则：**一个 Codex 任务只研究一个板块；语义研究由大语言模型主导，Python 只负责确定性计算、存储和校验。**

## 1. 强制使用方式

每个板块必须建立独立 Codex 任务。任务开始后按顺序读取：

1. 仓库根目录 `AGENTS.md`；
2. 仓库根目录 `CONTEXT.md`；
3. 本文件 `docs/单板块Codex深度研究运行规范.md`；
4. 与当前板块类型直接相关的设计文档或ADR。

单个任务只能处理一个 `sector_code + analysis_date`。当前板块没有完成审计和落盘前，不得领取下一个板块，也不得把其他板块的结论直接复制过来。

## 2. 职责边界

### 2.1 Codex大语言模型必须负责

- 理解板块定义、适配类型、成分结构和产业边界；
- 针对当前板块提出专属研究问题；
- 自主生成第一轮搜索词；
- 阅读搜索结果和原始来源，而不是只读标题；
- 根据第一轮发现继续扩展别名、上下游、政策名称、行业口径和成分股线索；
- 判断资料与板块、成分股和分析日期是否相关；
- 判断证据类别、来源质量、支持/反驳方向和冲突关系；
- 将证据关联到具体主张及六维评分；
- 综合形成政策、基本面、资金、技术、估值、风险评分；
- 形成5、20、60交易日预测、置信度和失效条件；
- 对检索不足、无法确认和真实无数据作出不同说明。

### 2.2 Python允许负责

- 读取指数行情、板块清单和成分快照；
- 强制排除北交所`.BJ`股票；
- 计算收益率、均线、波动率、最大回撤和成交指标；
- 聚合财务、估值、资金和成分广度；
- 计算收入/利润分布、盈利覆盖和龙头贡献；
- 下载模型已经决定要访问的结构化接口或原始页面；
- 保存原始响应、正文、摘要、内容哈希和抓取日志；
- 按`published_at`执行分析日期截断；
- 内容哈希去重、Parquet写入、UTF-8校验和字段契约校验；
- 管理任务状态、幂等ID、重试次数和当前指针。

### 2.3 Python禁止负责

- 用`板块名称 + 固定后缀`代替模型设计搜索策略；
- 用字符串包含关系决定研报、政策或产业证据是否适用；
- 用固定关键词把新闻自动判定为政策；
- 用板块名称关键词直接推断成分股业务纯度；
- 因为某类接口返回0条就宣称全网没有资料；
- 用公告数量、新闻数量或ETF稿件数量直接提高评分；
- 用规则生成的模板句代替模型的最终分析；
- 一次性为多个板块生成最终语义评分。

Python可以执行模型提出的查询，但查询设计、结果筛选和语义判断仍由模型完成。

## 3. 单板块任务输入契约

任务领取后只加载当前板块所需输入：

```text
task_id
sector_code
sector_name
analysis_date
latest_complete_trade_date
snapshot_id
analysis_archetype
classification_facets
classification_confidence
eligible_member_count
excluded_bj_count
previous_assessment_summary
previous_evidence_bundle_hash
scoring_policy_version
```

要求：

- `task_id`由上述固定输入的哈希生成，重试不得产生重复正式记录；
- 成分快照在任务内不可变；
- 行情、财务和证据不得晚于`analysis_date`；
- 上一期结果只提供压缩摘要、差异字段和证据ID，不将完整历史正文重新塞入上下文；
- 不加载其他511个板块的完整研究材料。

## 4. 单板块研究流程

### 阶段A：理解板块

模型必须先回答：

1. 该板块是什么，明确包含与不包含什么；
2. 它属于行业、地域、产业链、技术、政策、事件、风格还是样本池；
3. 同花顺名称是否存在简称、产业别名或券商研报口径；
4. 成分股数量、行业分布和龙头集中度如何；
5. 当前分类是否可信，是否需要`review_required`。

别名必须由本板块研究中发现并记录依据。例如“乳业”可能对应“饮料乳品”“原奶”“奶业”“乳制品”，但不得把这个别名集合无条件套用到其他板块。

### 阶段B：读取本地客观数据

Python提供当前板块的可复算数据：

- 指数5/20/60/250日收益；
- MA20、MA60偏离；
- 20日年化波动率、60日最大回撤；
- 成交额、换手率、资金流和拥挤度可用指标；
- 成分股行情、财务和估值覆盖率；
- 收入和利润中位数、P25、P75；
- 盈利成分占比；
- 龙头市值、收入和正利润贡献；
- 负利润规模和亏损贡献单独披露；
- 成分变动及北交所排除数量。

正利润与亏损必须分开聚合。板块总利润为负或接近0时，不输出普通“利润贡献率”。

### 阶段C：模型制定研究问题

模型基于板块类型和本地数据生成本次专属问题。不得直接使用固定答案模板。

例：

- 周期资源：价格、库存、产能、资本开支和周期位置；
- 技术成长：产品成熟度、渗透率、订单、研发和商业化；
- 政策驱动：政策原文、执行阶段、受益范围和兑现证据；
- 事件驱动：事件真实性、时间表、成功概率和失败回撤；
- 风格策略：风格暴露、拥挤度、收益来源和回撤；
- 普通概念：业务纯度、催化真实性和成分映射。

### 阶段D：模型逐轮联网研究

六类来源都必须尝试检索并记录状态：

1. 政策；
2. 正式研报；
3. 成分股公告；
4. 财经或产业新闻；
5. 产业数据；
6. 资金数据。

每一轮执行：

```text
模型提出查询及理由
→ 工具返回原始结果
→ 模型阅读并筛选
→ 模型记录有效、错配和冲突
→ 模型基于新线索生成下一轮查询
```

至少完成：

- 板块原名检索；
- 模型发现的别名或行业口径检索；
- 关键产业指标检索；
- 龙头公司和代表性成分股检索；
- 利好与风险两个方向的反向检索；
- 官方政策或统计来源定向检索。

不能只看搜索结果页。进入评分的证据必须至少读取摘要或正文，并确认来源、发布日期和关键主张。

### 阶段E：证据判定

每条证据记录：

```text
evidence_id
sector_code
source_type
source_tier
published_at
fetched_at
source
title
url
content_hash
access_level
raw_content_path
raw_content_hash
excerpt_hash
summary
linked_dimensions
stance
evidence_quality
relation_reason
time_validity
```

`access_level`固定为 `full_text | partial | abstract | metadata_only`。`content_hash`与`raw_content_hash`必须对应实际保存的原始响应、正文、有效摘要或Browser正文快照，不得只对模型事后总结计算哈希；`metadata_only`不能进入正式评分。

证据状态必须区分：

| 状态 | 含义 |
|---|---|
| `valid` | 已阅读且能支持或反驳当前板块主张 |
| `no_valid_evidence_after_search` | 已执行多轮搜索，但没有找到有效资料 |
| `retrieval_failed` | 因网络、限流、权限或页面故障未完成检索 |
| `not_applicable` | 该证据类别对当前板块不适用 |
| `conflicted` | 有效来源之间存在实质冲突 |
| `mismatch` | 搜索结果与板块或成分股关系不足 |
| `post_date_excluded` | 发布时间晚于分析日期，只作后续线索 |

`0条证据`本身不能区分上述状态，必须同时保存状态和搜索日志。

### 阶段F：形成主张

先形成主张，再评分。每条主张至少包括：

```text
claim_id
dimension
claim_text
supporting_evidence_ids
adverse_evidence_ids
confidence
limitations
```

一条证据可以关联多个维度，但必须说明关系；一条主张不得只引用无关行情稿或营销稿。

### 阶段G：评分和预测

六维定义保持统一，但模型必须基于当前板块主张和可复算指标解释每一分。

- 没有有效政策证据时，政策维度为`insufficient_evidence`，不能填5分；
- 基本面覆盖不足时，输出部分评估和覆盖率；
- 估值对亏损板块失真时，披露适用范围；
- 风险分表示安全度还是风险压力，必须沿用统一契约，不得临时反转；
- 综合分只在所有必要维度达到发布门槛时生成；
- 5/20/60交易日预测必须使用同一分析日期，并写明置信度和失效条件；
- 不得因为必须输出而编造方向判断。

### 阶段H：落盘和审计

Codex生成结果JSON，Python执行：

- JSON Schema检查；
- 六维范围和缺失状态检查；
- 证据ID存在性检查；
- `published_at <= analysis_date`检查；
- 北交所排除恒等式检查；
- 输入哈希和幂等检查；
- UTF-8和Parquet读取检查；
- 正文与摘要内容哈希检查。

独立研究任务的内部审计通过后只写隔离staging和更新候选。主任务完成二次硬审计后，才串行写入正式Parquet、报告、共享知识库并更新当前指针；未通过则保留上一份正式结果并记录本轮失败。

## 5. 搜索停止条件

不能按固定token数量停止。满足以下条件后模型才能结束检索：

- 当前板块专属研究问题均已有答案或明确无法确认；
- 六类来源均有检索日志和状态；
- 关键利好和关键风险均有独立来源；
- 主要冲突已被识别；
- 新增搜索连续两轮没有产生新的有效主张；
- 证据已达到“足以支撑主张”的饱和状态。

目标通常为10至20条高质量去重证据，但数量不是发布条件。20条无关公告不如5条直接政策、产业和财务证据。

## 6. 上下文控制

每个Codex任务只维护当前板块上下文：

- 本地客观指标使用结构化摘要；
- 原始正文存盘，模型上下文保留必要摘录和证据ID；
- 上一期研究压缩成“旧主张、旧评分、变化点、待验证项”；
- 搜索结果先筛选再进入正式证据集合；
- 不把全市场成分、全量公告或其他板块正文推入当前上下文；
- 每完成一个阶段即保存阶段状态，支持上下文压缩后继续。

模型必须参考上一期有效知识，但不得为了“观点连贯”忽略新证据。观点变化较大时，必须记录变化原因和替代了哪些旧主张。

## 7. 存储契约

统一数据根：

```text
D:\database\sector_information
```

建议分区：

```text
research_tasks/analysis_date=YYYY-MM-DD/<sector_code>.parquet
search_logs/analysis_date=YYYY-MM-DD/<sector_code>.parquet
evidence/year=YYYY/month=MM/merged.parquet
evidence_content/year=YYYY/month=MM/merged.parquet
claims/year=YYYY/month=MM/merged.parquet
claim_evidence_links/year=YYYY/month=MM/merged.parquet
sector_member_aggregates/analysis_date=YYYY-MM-DD/<sector_code>.parquet
codex_assessments/analysis_date=YYYY-MM-DD/<sector_code>.parquet
forecasts/analysis_date=YYYY-MM-DD/<sector_code>.parquet
```

研究结果增量追加，历史不覆盖。`current`只保存可重建指针或最新正式结果，不作为历史事实来源。

## 8. 任务状态和重试

任务状态：

```text
pending
claimed
researching
validating
completed
review_required
retryable_failed
terminal_failed
```

- 网络、限流和临时页面错误进入`retryable_failed`，最多自动重试3次；
- 检索证据不足不是程序失败，进入`review_required`；
- 分类不确定、成分映射错误或契约矛盾进入人工复核；
- 重试必须继续同一个`task_id`并增加`attempt_count`；
- 单板块失败不阻断其他独立任务，但不得静默发布旧结果为本轮结果。

## 9. 单板块Codex任务提示词模板

创建新任务时使用以下模板，并替换尖括号内容：

```text
你正在执行一个独立的单板块深度研究任务。

必须先完整阅读：
1. C:\Users\Administrator\Desktop\python_venv\AGENTS.md
2. C:\Users\Administrator\Desktop\python_venv\CONTEXT.md
3. C:\Users\Administrator\Desktop\python_venv\docs\单板块Codex深度研究运行规范.md

本任务只研究：
- sector_code: <代码>
- sector_name: <名称>
- analysis_date: <日期>
- snapshot_id: <成分快照ID>

必须由大语言模型逐轮制定查询、阅读来源、判断相关性、形成主张并评分。
Python只用于客观计算、下载模型指定的原始资料、去重、存储和硬校验。
禁止使用固定关键词规则或名称包含关系代替模型研究，禁止批量生成其他板块结论。

严格执行分析日期边界，强制排除北交所股票，区分无有效证据、检索失败、不适用、冲突和错配。
完成前必须通过证据、主张、评分、预测、Parquet和UTF-8审计。
审计通过后只提交当前板块结果；失败则按规范记录并重试或进入复核。
```

## 10. 完成检查表

每个任务结束前逐项确认：

- [ ] 只处理了一个板块；
- [ ] 使用固定成分快照并排除北交所；
- [ ] 模型解释了板块边界和类型；
- [ ] 模型提出了当前板块专属研究问题；
- [ ] 六类来源均完成搜索或记录明确状态；
- [ ] 搜索过程包含至少一次基于新线索的查询调整；
- [ ] 有效证据均不晚于分析日期；
- [ ] 没有用关键词规则代替语义判断；
- [ ] 财务、估值、资金和龙头贡献可复算；
- [ ] 正利润和亏损分开聚合；
- [ ] 每条重要主张有证据或客观指标支持；
- [ ] 缺失数据没有填0或5；
- [ ] 六维评分、预测和失效条件解释完整；
- [ ] JSON、Parquet和UTF-8审计通过；
- [ ] 结果已增量落盘，历史未覆盖；
- [ ] 任务状态、重试次数和限制已保存。

只有全部适用检查项通过，任务才能标记为`completed`并领取下一个板块。
