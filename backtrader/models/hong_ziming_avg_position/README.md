# 洪梓铭平均仓位模型（hong_ziming_avg_position）

- **用途**：当前网页回测默认模型；单票仓位上限、冷静期、连续卖点先减半再清仓、跌破成本约 20% 止损等（详见 `strategy.py` 文档字符串）。
- **数据**：与 `models.zxw_rule_backtest.zxw_view_results_full` 相同管线（`build_zxw_rule_bt_dataframe_for_range`），含复权与 ZXW 全套信号列。
- **前端因子**：`buy_rules` / `sell_rules` 会随请求传入，但**不参与**本模型逻辑；结果 summary 中标注已忽略。
