# 4-28 初始 10% 硬仓位实验快照（zxw_init_10pct_snapshot）

命名对应历史上的 **4-28 初始 10% 硬仓位** notebook 实验：**单票约 10% 上限、MAC/KDJ/OBV/抄底分** 与原版脚本同类逻辑。

**实现说明**：与 `zxw_legacy_mac_kdj_bottom` **共用同一套回测引擎与数据合并**（`zxw_view_results_legacy` 管线），便于维护；若日后需要严格复现 notebook 中「仅三列 feed」等差异，可在本目录单独拆 `data.py`。

- **网页回测**：支持。
- **前端买卖规则**：不参与。
