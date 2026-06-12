# ZXW 组合规则（只为了检验因子策略）

- **注册 id**：`zxw_factor_check_only`
- **策略类**：`factor_check_strategy.FactorCheckZxwStrategy`
- **入口**：`runner.run`

## 信号

- **强买**：前端买入因子 + `buy_operator`（AND/OR）→ `strong_buy_signal`
- **强卖**：前端卖出因子 + `sell_operator`（AND/OR）→ `strong_sell_signal` ≥1 → **清仓**
- **首日回溯过滤**：信号日至 `start_date` 前无 `strong_sell_signal`（前端卖出因子，不用宽表 `total_sell_signal`）

## 仓位

- 单票强买上限 **2%**（`max_weight=0.02`）；已满 2% 不买；涨超 2% 不卖
- **现金 &lt; 10%**：仅在有强买信号时尽量买到 2%
- **现金 ≥ 10%**（卖完且当日强买处理完后仍满足）：
  - **有持仓**：剩余现金 **等额** 分给全部持仓，**可突破 2%**（仅受整股与佣金限制）
  - **无持仓**：保持空仓，不买

## 与强点模型差异

| 项目 | 强点 `zxw_strong_adjusted_only` | 本模型 |
|------|--------------------------------|--------|
| 单票上限 | 5% | 强买 2%；现金补仓可突破 |
| 现金门控 | 仓位 &lt; 80% 时分现金 | 现金 ≥ 10% 时等额补仓 |
| 卖出 | 止损 + 分档止盈 | 仅 strong_sell 清仓 |
| 参数遍历 | 买入×卖出穷举 | **无**，单次按前端配置 |
