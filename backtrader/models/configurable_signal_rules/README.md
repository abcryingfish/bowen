# 可配置因子买卖规则（configurable_signal_rules）

- **用途**：首日按现金等权买入；之后根据前端传入的 **`buy_rules` / `sell_rules`**（因子中文名 + 阈值）与 **AND/OR** 组合成 `buy_signal`、`sell_signal`；同时合并 **MAC总 / KDJ信号 / OBV多头排列** 用于「总买入调整」与持仓满一年腰斩禁买等逻辑（与原先 `configurable_backtest.ConfigurableSignalStrategy` 一致）。
- **数据**：日线 `stock_basic_data_daily` + `signal_daily` 分区 parquet。
- **资金与手续费**：由 `settings.run_zxw_backtest` / `create_cerebro` 使用全局默认。
