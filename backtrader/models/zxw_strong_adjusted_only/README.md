# ZXW 组合规则（只采用强点交易策略）

- **策略类**：`strong_adjusted_strategy.StrongAdjustedZxwStrategy`
- **入口**：`runner.run`（注册表 id：`zxw_strong_adjusted_only`）

## 信号

- **强买**：前端**买入因子**合成 → `strong_buy_signal`（并写入 `total_buy_signal` 供 feed）
- **止盈触发**：前端**卖出因子**合成 → `strong_sell_signal`（**不**覆盖宽表 `total_sell_signal`）
- **止损触发**：宽表固定列 `total_sell_signal`（与面板卖出因子遍历无关）
- **止盈三档**：浮盈 >30% / >60% / >100% 预挂 → `strong_sell_signal≥1` 时卖原仓 60% / 85% / 清仓
- **止损**：收盘 < 成本×0.8 预挂 → `total_sell_signal≥1` 清仓

## 参数遍历（穷举）

- **买入**非空子集 × **卖出**非空子集（各 n 个因子 → 2^n−1 组）
- 卖出子集只改变 `strong_sell_signal` 与 run 名 `_卖…`；止损逻辑各 trial 相同
- 合计组合数上限 4096

## 风控写死

见 `strategy_params.DEFAULT_PROFIT_TIERS`、`DEFAULT_STOP_LOSS_COST_MULTIPLIER = 0.8`

## 单票 5% 上限（强买）

- 持仓已达 `max_weight`（默认 5%）时，强买信号日不再加仓。
- 同日：阶段一 `order_target` 补至上限；`inv_gate` 不足时阶段二仅分现金，**不再**重复 `order_target`。
- 同 bar 内用 `_bar_planned_buy_value` 累计待发单市值，避免 target 与分现金在同日叠仓。
