# 新增或修改「回测模型」维护说明

前端 **POST** 回测请求体字段保持不变（`adopt_model`、`buy_rules`、`sell_rules` 等）。要增加或调整模型，**只改 `backtrader/` 下后端** 即可；改完后可选：刷新页面以重新拉取 `/api/backtest/models`。

##  checklist（交给 AI 执行时逐条打勾）

1. **目录**：在 `backtrader/models/<你的模型_id>/` 下放置 `README.md`（给人看的业务说明）。
2. **runner**：实现 `runner.py` 中的 `run(...)`，签名与现有模型一致：
   - 关键字参数：`codes`, `start_date`, `end_date`, `run_name`, `frontend_buy_rules`, `frontend_sell_rules`, `frontend_buy_operator`, `frontend_sell_operator`, `progress`（可为 `None`）。
   - 返回值：与 `run_configured_backtest` 相同顶层键：`run_tag`, `summary`, `saved_paths`, `curve_info`, `config`。
3. **注册**：编辑 [`model_registry.py`](model_registry.py)，在 `REGISTRY` 中增加一条 `ModelEntry`：
   - `id`：与前端 `adopt_model` 字符串**完全一致**（建议 ASCII，如 `my_strategy_v1`）。
   - `title`：短标题（出现在模型列表中）。
   - `description_html`：右栏说明，可用 HTML 段落（`<p>...</p>`）。
   - `web_runnable`：`True` 表示可走 `/api/backtest/run`；纯脚本/寻优写 `False`，且 `run=None`。
   - `uses_frontend_buy_sell_rules`：若模型**使用**前端因子规则合并为信号，填 `True`；否则 `False`（仍可把前端规则原样写入 `config` 备注「已接收未使用」）。
   - `run`：可调用对象，或 `None`（仅展示说明的离线项）。
4. **资金与路径**：初始资金、手续费、落盘路径等**优先**使用 [`settings.py`](settings.py) 中的 `run_zxw_backtest` / `create_cerebro`（或现有 ZXW 管线），避免在模型目录再复制一份 `INITIAL_CASH`。
5. **列表顺序**：在 `model_registry.list_models_public` 的 `order` 列表中加入新 `id`（如需固定排序）。
6. **自测**：在 `backtrader` 已加入 `PYTHONPATH` 且能 `import backtrader`（第三方库）的环境中，调用一次 `run_registered_model(...)` 或走网页回测 smoke test。
7. **前端离线兜底**：若改了各模型的 `description_html`，请同步 `可视化/index.html` 中的常量 `BACKTEST_MODEL_FALLBACK`（与 `list_models_public()` 返回的 `models` 条目字段一致），否则 API 不可用时悬停说明会过期。

## 不要做的事

- 不要改计划外的 `可视化/index.html` **POST** 负载字段名（除非你有意做全链路迁移）。
- 不要把「仅线下」的长任务注册为 `web_runnable=True`，否则会拖死线程池或让用户误以为失败。

## 相关文件

| 文件 | 作用 |
|------|------|
| [`model_registry.py`](model_registry.py) | 模型元数据 + `REGISTRY` + `list_models_public` |
| [`configurable_backtest.py`](configurable_backtest.py) | 解析 payload、校验日期与 codes、调用注册表 |
| [`settings.py`](settings.py) | 共用 `run_zxw_backtest`、路径常量 |
| [`models/`](models/) | 各模型 `runner.py` / `strategy.py` / `README.md` |
