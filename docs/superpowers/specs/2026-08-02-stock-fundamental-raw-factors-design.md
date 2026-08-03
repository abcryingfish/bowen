# 股票基本面原始因子设计

## 目标

在 `ZXW因子/ZXW策略技术因子生成.py` 的自动规划、计算、保存和前端发现链路中，新增十三个仅适用于股票标的的原始基本面因子：

| 中文因子名 | 英文字段名 | 输出单位 |
|---|---|---|
| 净资产收益率_ROE | `return_on_equity_ttm` | 百分数 |
| 销售毛利率 | `sales_gross_margin_ttm` | 百分数 |
| 经营现金流营业收入比 | `operating_cashflow_to_revenue_ttm` | 百分数 |
| 资产负债率 | `debt_to_asset_ratio` | 百分数 |
| 总资产收益率_ROA | `return_on_assets_ttm` | 百分数 |
| 毛利润资产比 | `gross_profit_to_assets_ttm` | 百分数 |
| 净利润现金含量 | `operating_cashflow_to_net_profit_ttm` | 倍数 |
| 应计利润率 | `accruals_to_assets_ttm` | 百分数 |
| 总资产周转率 | `asset_turnover_ttm` | 倍数 |
| ROE标准差_12季度 | `return_on_equity_std_12q` | 百分点 |
| 销售毛利率标准差_12季度 | `sales_gross_margin_std_12q` | 百分点 |
| 营业收入三年复合增长率 | `revenue_cagr_3y_ttm` | 百分数 |
| 市净率_PB | `price_to_book_ratio` | 倍数 |

本阶段只输出原始值，不做极值裁剪、标准化、行业中性化或综合评分。

## 标的范围

因子仅对 `stock_basic_data_daily` 股票成员生成。不能通过 `.SH`、`.SZ` 后缀判断股票，因为 ETF 使用相同后缀。ETF、指数和 `.THS` 标的不进入输出矩阵。

主生成器为唯一运行入口：

`ZXW因子/ZXW策略技术因子生成.py`

本次不修改 `ZXW因子/ZXW策略技术因子生成.ipynb`。

## 数据源与字段

| 因子 | 数据表 | 字段 |
|---|---|---|
| 净资产收益率_ROE | `table=Income` + `table=Balance` | `net_profit_excl_min_int_inc` 与 `tot_shrhldr_eqy_excl_min_int` |
| 销售毛利率 | `table=Income` + `table=PershareIndex` | `revenue` 与 `sales_gross_profit`，后者缺失时回退 `gross_profit` |
| 资产负债率 | `table=Balance` | `tot_liab / tot_assets * 100` |
| 经营现金流营业收入比 | `table=CashFlow` + `table=Income` | `net_cash_flows_oper_act / revenue * 100` |
| ROA、应计利润率 | `table=Income` + `table=CashFlow` + `table=Balance` | TTM合并净利润、TTM经营现金流与平均总资产 |
| 总资产周转率 | `table=Income` + `table=Balance` | TTM营业收入与平均总资产 |
| 毛利润资产比 | `table=Income` + `table=PershareIndex` + `table=Balance` | TTM毛利润与平均总资产 |
| 净利润现金含量 | `table=Income` + `table=CashFlow` | TTM经营现金流与正的TTM合并净利润 |
| 两个12季度标准差 | 财务三表 | 历史TTM ROE与TTM销售毛利率 |
| 营业收入三年复合增长率 | `table=Income` | 同季度 `revenue` |
| 市净率_PB | `table=factor_fundamental_valuation` | `pb` |

季度表使用 `htsc_code + report_date + announce_date` 语义。PB 使用日频 `htsc_code + time`。

## 计算口径

### 公告日生效

季度因子按 `announce_date` 生效，并向后填充到该股票下一份有效财务数据公告。公告日在非交易日时，从其后的第一个交易日开始可见。禁止使用 `report_date` 提前填充，以避免未来函数。

同一报告期发生更正或重述时，逐股票公告事件状态机保存当时可见版本；更晚公告只从自己的 `announce_date` 起覆盖旧值，不回写历史交易日。完全相同的重复披露在读取阶段折叠，真正发生数值变化的版本保留。缺少有效 `announce_date` 的记录在QMT下载标准化阶段直接丢弃，禁止回填 `report_date`。

### TTM 事件值

收入、现金流和利润表中的季度记录是年初至报告期末累计值，先按报告期还原为单季度值，再滚动汇总最近四个季度。Q1 直接使用 Q1；Q2 减 Q1；Q3 减上半年；Q4 减前三季度。季度缺失时不跨空洞拼接 TTM。

### TTM ROE

使用近四个单季度归母净利润之和，除以 TTM 起始期和结束期归母净资产的平均值：

`sum(net_profit_excl_min_int_inc_q[-4:]) / ((equity[-5] + equity[-1]) / 2) * 100`

不对四个季度 ROE 做算术平均。起止净资产非有限或平均值小于等于零时输出空值。

### TTM 销售毛利率

将报告期毛利率乘以报告期营业收入得到累计毛利金额，先还原单季度毛利金额，再计算：

`sum(gross_profit_q[-4:]) / sum(revenue_q[-4:]) * 100`

优先使用 `sales_gross_profit`，缺失时使用同口径 `gross_profit`。不直接平均季度毛利率。

### TTM 经营现金流营业收入比

现金流量表与利润表按股票和相同 `report_date` 匹配，分别还原单季度值后汇总：

`sum(net_cash_flows_oper_act_q[-4:]) / sum(revenue_q[-4:]) * 100`

营业收入为零或任一字段非有限值时输出空值，不填 0。

### 资产负债率

资产负债率是资产负债表时点指标，使用最新公告报告期的 `tot_liab / tot_assets * 100`，不做 TTM。

### 质量扩展指标

平均总资产使用TTM结束季度与四个季度前总资产的算术平均值，且必须大于0。ROE继续使用归母净利润与归母净资产；ROA、应计利润率和净利润现金含量使用与合并总资产、合并经营现金流一致的合并净利润。ROA、毛利润资产比、应计利润率和总资产周转率分别使用TTM合并净利润、TTM毛利润、`TTM合并净利润-TTM经营现金流`和TTM营业收入除以平均总资产；前三个百分比指标乘100，总资产周转率保持倍数。净利润现金含量使用 `TTM经营现金流 / TTM合并净利润`，分母小于等于0时输出空值。

ROE标准差和销售毛利率标准差使用最近12个连续报告季度各自的TTM指标计算总体标准差（`ddof=0`）。窗口不连续、任一TTM值缺失时输出空值。质量扩展指标以最新报告期为准；最新必需输入无效时清空，不沿用更早报告期的旧值。

### 营业收入三年复合增长率

使用最新 TTM 营业收入与三年前同一时点的 TTM 营业收入：

`((revenue_ttm / revenue_ttm_minus_3y) ** (1 / 3) - 1) * 100`

该因子至少需要约四年季度历史。起点或终点 TTM 营业收入小于等于零、三年前对应 TTM 不完整或字段非有限时输出空值。

### 字段单位

源表中的 `sales_gross_profit` 和 `gross_profit` 已经是百分数，但 TTM ROE、TTM 毛利率和现金流比率由金额重新计算后再乘 100。PB 保持倍数。

## 代码结构

新增独立模块 `ZXW因子/股票基本面原始因子.py`，采用现有 bundle 契约：

- `get_factor_catalog()`：返回十三个中英文因子映射。
- `get_factor_lookback_config()`：行情矩阵回看为 0，并单独声明约四年的财务源历史需求，避免单日增量额外加载四年 OHLC。
- `build_stock_fundamental_raw_factor_bundle(...)`：批量读取、计算并对齐日频矩阵。

主生成器负责：

- 注册 bundle 和 lookback 配置。
- 将十三个因子规划为股票专属范围。
- 只把股票代码传入 bundle。
- 复用现有增量保存、月度合并和整批水位流程。

`因子分类/factor_catalog.json` 新增“股票基本面原始因子”分组。前端仍以实际已落盘因子目录为可用范围，不为尚未生成的数据展示空入口。

## 性能设计

- 使用 DuckDB 批量读取所需列，不逐股票循环。
- 根据计算区间裁剪 PB 年月分区。
- 季度表只读取生成区间需要的公告历史；TTM CAGR 额外读取约四年季度历史。
- 财务事件先在长表中计算，再按股票和公告日批量展开到交易日矩阵。
- 十三个因子共享同一次基础财务表查询和事件整理。
- 不新增中间数据仓库，不改写 `D:\database\qmt_company_data`。

## 错误与缺失处理

- 必需目录或必需字段完全缺失时抛出明确错误，停止该 bundle，避免空值推进水位。
- 个别股票或个别报告期缺失时保留空值，不阻断其他股票。
- PB 日频源落后于本次股票行情结束日期时停止生成，避免将空值写到最新日期。
- 非有限值、无穷值和非法分母统一转为空值，不转成 0。
- 季度因子允许在最新交易日沿用最近一次已公告值，不要求财报表每天更新。

## 测试与验收

采用测试驱动开发，至少覆盖：

1. 十三个因子目录和 lookback 契约。
2. ROE归母利润口径与ROA、现金含量、应计利润率的合并利润口径。
3. 现金流营业收入比公式、同报告期匹配和零分母。
4. 三年 CAGR 同季度公式、缺失同期和非正营收。
5. 公告日前不可见、公告日后向前填充以及重述的生效时间。
6. 股票成员过滤，确保 ETF、指数和 `.THS` 不进入输出。
7. PB 日频对齐及源数据落后保护。
8. 主生成器自动规划、保存映射和前端目录发现。
9. 真实本地数据抽样公式核对、全股票单日有效值和运行耗时。
10. `ZXW因子` 相关完整回归和前端因子服务回归。

## 非目标与后续工作

本次不实现：

- 横截面标准化或稳健标准化。
- 行业中性化。
- 极值处理。
- 质量、成长、价值综合得分及权重。
- notebook 同步。

当前任务交付时必须提醒后续应单独设计标准化和行业中性化，并优先明确极值处理、行业分类日期口径和缺失值规则。
