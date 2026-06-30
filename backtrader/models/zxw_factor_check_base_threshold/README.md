# ZXW Factor Check Base Threshold

在 `zxw_factor_check_profit_threshold_dual_assumption` 基础上新增买入端基本面过滤。

- 继承原模型：双假设、卖出阈值、首日回溯建仓、现金补仓规则不变。
- 买入过滤：前端合成 `strong_buy_signal` 后，仅保留同时满足 `0 < PE < 50`、`PB < 6`、`ROE > 10`、`营业收入同比 > 10` 的信号。
- 数据来源：`PE/PB` 使用 QMT 派生表 `D:\database\qmt_company_data\table=factor_fundamental_valuation`。
- `ROE/营业收入同比` 使用 QMT 原始年报（Q4）表：
  - `D:\database\qmt_company_data\table=PershareIndex`
  - `D:\database\qmt_company_data\table=Income`
- 字段映射：`PE` 使用 `pe_ttm`，`PB` 使用 `pb`；`ROE` 优先使用 Q4 `equity_roe`，为空时依次回退到 `net_roe`、`du_return_on_equity`；`营业收入同比` 用 Q4 年报 `revenue` 对比上一年 Q4 年报 `revenue`。
- 匹配方式：`PE/PB` 按信号日之前或当天最近日频估值匹配；`ROE/营业收入同比` 仅使用 `announce_date <= 信号日` 的最近已公告 Q4 年报，避免未来函数。
