# 原版 MAC/KDJ/OBV/抄底 引擎（`zxw_legacy_mac_kdj_bottom`）

**说明**：本包**不再**在 `model_registry` 中单独注册；网页/OpenClaw 请选用 **`zxw_init_10pct_snapshot`**（内部调用本目录 `runner.run`）。以下为策略与数据说明。

- **数据**：日线 parquet + `signal_daily` 按原版 `FACTOR_COLUMN_MAP` 合并（**无**当前主力脚本中的复权扩展与未来腰斩列）。
- **前端买卖规则**：不参与。
