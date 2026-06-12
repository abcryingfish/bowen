# ZXW 组合规则回测（zxw_rule_backtest）

对应本目录 **`zxw_view_results_full.py`** 中的 **`ZxwRuleBacktestStrategy`**：首日等权满仓、止损与分档止盈、回撤加仓、总仓位与次买逻辑、未来腰斩禁买等；信号列由固定 `FACTOR_COLUMN_MAP` 与 `signal_daily` 合并得到。注册表中的 **ZXW 组合规则（30%盈利分档）** 通过 `profit_tier_mode="profit30"` 调用同一策略类，分档止盈为 >100% 清仓 / >50% 约 75% / >30% 约 50%（`either_combo`）。

- **前端买卖规则**：不参与；`buy_rules` / `sell_rules` 仅写入结果备注「已接收未使用」。
- **执行壳**：`settings.run_zxw_backtest`，`create_cerebro` 与基准策略均来自 `zxw_view_results_full.py`。
