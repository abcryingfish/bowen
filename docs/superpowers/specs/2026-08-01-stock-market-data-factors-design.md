# 股票市场数据因子设计

## 目标

在现有因子生成链路中新增三个日频因子：`总市值`、`流通市值`、`换手率`。只对 `stock_basic_data_daily` 中的股票标的生成，不改变 ETF、指数和同花顺板块标的的现有行为。

## 数据口径

统一读取 `D:\database\qmt_turnover_data\year=*\month=*\merged.parquet`：

- `总市值`：源字段 `total_market_val`，单位为元，计算口径为 `close * total_capital`。
- `流通市值`：源字段 `floating_market_val`，单位为元，计算口径为 `close * circulating_capital`。
- `换手率`：源字段 `turnover_rate`，单位为百分数，计算口径为 `volume / circulating_capital * 100`。

不使用 `value` 计算换手率。`value` 是成交额，`volume` 是成交股数。

## 标的范围

股票身份以股票日线数据源的成员关系判断，不以 `.SH` 或 `.SZ` 后缀判断，因为 ETF 与股票使用相同交易所后缀。

因子读取时取“当前计算批次股票代码”与 `qmt_turnover_data` 代码的交集。ETF、指数、`.THS` 板块及其他非股票标的不生成记录，也不写入零值。

## 实现结构

新增独立因子模块，沿用现有 bundle 返回契约：

- bundle id：`stock_market_data`
- 英文键：`total_market_value`、`floating_market_value`、`turnover_rate`
- 中文映射：`总市值`、`流通市值`、`换手率`

主因子生成器注册并按需执行该 bundle。模块直接按目标日期和代码读取三个源字段，转换为以交易日为索引、股票代码为列的宽表，再交给现有 `signal_daily` 保存逻辑。

读取时只扫描目标区间涉及的年月 `merged.parquet`，避免日常单日增量扫描全部历史分区。生成前使用最新年月分区校验 `qmt_turnover_data` 的全局水位；若未覆盖本批次结束日则停止生成，防止 NaN 被写入后错误推进因子水位。

`factor_catalog.json` 新增“股票市场数据”分组，使三个因子可被前端发现和选择。

## 缺失值与增量语义

- 不前向填充，不用零替代缺失值。
- 停牌日或源表缺失日保持缺失。
- 允许单只停牌股票缺失，但要求换手率源表的全市场最新日期覆盖批次结束日。
- 当前源表在 2010 年一季度以前有部分股票缺少股本记录，因此这些日期不生成对应因子；不反向使用后续股本，避免未来数据泄漏。
- 保存继续使用现有 `time + htsc_code` 主键、因子分区和增量水位机制。

## 验证

- 单元测试验证三个字段的中文映射、代码过滤、日期对齐及缺失值行为。
- 验证 ETF、指数和 `.THS` 标的不出现在三个因子结果中。
- 抽样核对 `总市值 = close * total_capital`、`流通市值 = close * circulating_capital`、`换手率 = volume / circulating_capital * 100`。
- 运行相关因子生成测试与 catalog 契约测试，确认不影响其他 bundle。
