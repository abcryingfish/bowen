# 板块 LightGBM 模型 V1 设计

## 1. 目标

在已有 881/885/886 板块面板上，建立第一个可复现、可记录、可比较的 LightGBM 回归模型。V1 一次只训练一个目标，使用同一入口分别训练波峰模型和波谷模型：

```text
--target peak   → peak_strength_ex_post
--target valley → valley_strength_ex_post
```

V1 只回答一个问题：截至交易日 t 收盘，因子能否预测该板块在 V2 定义下的事后峰/谷连续强度？它不直接生成买卖信号，也不包含强化学习和组合仓位决策。

## 2. 数据输入

训练面板：

```text
D:\database\sector_peak_valley_ml\panel\panel.parquet
```

当前面板约 839,564 行、477 个板块、29 个数值特征。使用字段：

- X：29 个已通过阶段 B 审计的数值特征；
- y：当前目标列；
- 主键：`htsc_code + time`，仅用于分组评价，不作为数值特征；
- `sector_family`：V1 不直接输入模型，避免模型记忆 881/885/886 标签差异；
- `bars_to_end`：不输入模型，仅用于数据完整性检查。

严禁进入 X：

- `peak_strength_ex_post`、`valley_strength_ex_post`；
- 所有 V2 局部位置、趋势转折、反转、持续性、确认延迟字段；
- 任何含 `label`、`未来`、`事后` 的字段。

## 3. 标签定义

波峰模型：

```text
y = peak_strength_ex_post
```

波谷模型：

```text
y = valley_strength_ex_post
```

两个目标独立训练，不使用 `valley - peak` 作为第一版训练目标。预测完成后才允许构造：

```text
net_score = valley_prediction - peak_prediction
```

训练权重：

```text
weight = 1 + 4 × y²
```

用于提高强峰/强谷样本的影响，但不把低分样本粗暴变成负类。

## 4. 时间切分

采用与现有 ElasticNet 基线一致的扩展窗口滚动验证：

| 折 | 训练结束 | 验证区间 | 测试区间 |
|---|---|---|---|
| test_2023 | 2021-11-05 | 2022-03-08 至 2022-11-07 | 2023 |
| test_2024 | 2022-11-07 | 2023-03-07 至 2023-11-03 | 2024 |
| test_2025 | 2023-11-03 | 2024-03-06 至 2024-11-05 | 2025 |

每个训练/验证、验证/测试边界使用 40 个交易日 purge。V2 最长使用未来 40 日，因此不能随机拆分，也不能把尾部不完整标签放进训练。

## 5. LightGBM 参数

V1 先使用 CPU，RTX 5080 留给后续 TCN/GRU/Transformer。参数固定为：

```python
LGBMRegressor(
    objective="huber",
    n_estimators=500,
    learning_rate=0.03,
    num_leaves=31,
    max_depth=6,
    min_child_samples=100,
    subsample=0.8,
    colsample_bytree=0.8,
    reg_alpha=0.1,
    reg_lambda=1.0,
    random_state=20260818,
    n_jobs=16,
)
```

验证集启用 early stopping 50 轮。预测值最终限制到 `[0,1]`，但训练标签不做额外离散化。

## 6. 对照组

每个目标必须同时记录三个结果：

1. 5 日动量单因子基准；
2. 已有 ElasticNet 基线；
3. LightGBM V1。

LightGBM 不能只和训练集比较，必须在同一个测试折上比较。

## 7. 评价指标

主指标：

- 日度横截面 Spearman Rank IC；
- 横截面 ICIR；
- Top 10% 捕获率和 Top 10% Lift。

辅助指标：

- 单板块时序 Spearman IC；
- Pearson IC；
- MAE、RMSE；
- 按 881/885/886 的分组结果；
- 按年份的稳定性。

V1 暂不把收益率当训练标签，但在模型验收时追加预测后 5/10/20/40 日收益检查。

## 8. MLflow 记录

Tracking URI：

```text
D:\database\sector_peak_valley_ml\models\mlflow_artifacts
```

每个 run 至少记录：

- `target`、`fold`、训练/验证/测试日期；
- 所有 LightGBM 参数；
- 训练行数、特征数、板块数；
- 最佳迭代轮数；
- Rank IC、ICIR、Top10 Lift、MAE、RMSE；
- 881/885/886 分组指标；
- 特征重要性 CSV；
- LightGBM 模型 artifact；
- 训练面板路径和代码版本信息。

模型文件按以下目录保存：

```text
D:\database\sector_peak_valley_ml\models\lightgbm\peak\
D:\database\sector_peak_valley_ml\models\lightgbm\valley\
```

## 9. V1 验收门槛

每个目标至少满足：

- 三个测试折均能完成，无 NaN、无重复主键和无未来字段；
- 测试期横截面 Rank IC 为正；
- 不显著劣于 ElasticNet 基线；
- 881、885、886 的时序 IC 不出现整体负值；
- Top10 Lift 高于随机基线 1.0；
- MLflow 中每个折都有完整参数、指标和模型 artifact。

如果 LightGBM 训练集很高、测试集明显下降，优先降低 `num_leaves`、`max_depth`、`n_estimators`，不直接增加模型复杂度。

## 10. V1 不做的事情

- 不加入强化学习；
- 不把 V2 诊断字段作为特征；
- 不直接产生实盘买卖信号；
- 不把板块代码作为普通数值特征；
- 不用测试集选择参数或混合权重；
- 不把模型结果写回现有 `signal_daily` 生产因子分区。
