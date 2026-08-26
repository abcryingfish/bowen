# 市场研究页面

## 入口与职责

- 正式入口：`http://127.0.0.1:8086/市场研究/index.html`
- 兼容入口：`../市场研究.html`
- 前端：`index.html`、`market_research.js`、`market_research.css`
- 服务：`../market_research_service.py`
- API：`GET /api/market/research/concentration`

页面当前提供沪、深、科创、全 A 四类市场的成交额集中度、RSI 比值和市场等权价格基准曲线。价格基准使用后复权收盘价的每日等权收益累积计算，首个交易日归一化为 100，不代表交易所官方指数。不要在未确认需求时加入行业、概念或个股研究内容。

## 当前市场定义

| ID | 展示名 | 当前代码规则 |
|----|--------|--------------|
| `sh` | 沪 | 所有 `.SH` 代码，包含科创板 |
| `sz` | 深 | 所有 `.SZ` 代码 |
| `star` | 科创 | `688xxx.SH` 与 `689xxx.SH` |
| `all-a` | 全 A | `.SH` 与 `.SZ` 合集 |

这里按查询日实际存在且 `close > 0`、`trade_value > 0` 的行情行形成当日样本，不使用今天的固定股票名单覆盖历史。停牌或无成交股票不会进入当日集中度分母；页面必须同时展示 `stock_count` 和 RSI 覆盖数，避免把样本变化误读成集中度变化。

## 当前公式

- 每个交易日按 `trade_value` 降序排列。
- `top_count = ceil(stock_count * 5%)`。
- `concentration = Top 5% 股票成交额合计 / 当日有效股票成交额合计 * 100`。
- RSI 使用后复权收盘价计算 Wilder RSI(14)。
- `rsi_ratio = Top 5% 股票 RSI 均值 / 全部有效股票 RSI 均值`。

集中度是成交额加权后的占比；RSI 比值是两个等权均值之比，两者应分开解释。

## 数据与已知校验项

- 日线与成交额：`D:\database\qmt_turnover_data`。
- 当前复权输入优先使用 `D:\database\stock_adj_daily\adj_factor_daily`；`adj_factor_segments.parquet` 仅作为兼容回退。
- RSI 预热：查询起点前 400 个自然日。
- 最大返回点数：2000。

复权因子由原始事件按 `htsc_code + event_date` 生成；`xdy/dr` 是单次事件乘数，相同数值但不同日期的事件会继续累乘。事件前没有历史因子时使用 `1.0`，已有事件后沿用最近的累计因子。复权文件和兼容分段均缺失时直接报错，不使用未复权收盘价。

## 修改检查

- 市场规则、Top 比例、公式或返回字段变化时，同步更新服务测试与本文件。
- 保持四个市场 ID、URL 参数和前端按钮一致。
- 检查新股、停牌、退市、无成交、复权事件、RSI 窗口不足和零分母。
- 性能修改后验证缓存签名仍会在 Parquet 更新时失效。
- 运行 `test_market_research_service.py` 和前端页面测试。
