# 板块 LightGBM / ElasticNet / 动量混合模型 V1

## 1. 实验目标

在波峰事后强度标签 `peak_strength_ex_post` 上，检验 LightGBM 是否能与已有 ElasticNet 和 5 日动量基准形成更稳定的横截面排序模型。

本阶段仍然只做板块波峰，不生成交易信号，不接入 `signal_daily`，也不处理强化学习。

## 2. 混合方式

每个滚动时间折分别训练：

- LightGBM：29 个因子；
- ElasticNet：相同 29 个因子；
- 动量基准：`mkt_momentum_5d` 的当日横截面百分位排名。

最终预测为三者凸组合：

```text
prediction = w_lgbm × pred_lgbm
           + w_elastic × pred_elastic
           + w_momentum × pred_momentum
```

约束：

```text
w_lgbm + w_elastic + w_momentum = 1
w_i >= 0
```

权重网格步长为 0.1，共 66 组候选组合。

## 3. 防止未来函数

时间切分与 V1 LightGBM Demo 一致：

- 测试年份：2023、2024、2025；
- 每个训练/验证和验证/测试边界隔离 40 个交易日；
- 权重只使用对应折的验证集日度横截面 Rank IC 选择；
- 测试集不参与权重选择，只做最终一次评价。

## 4. 评价指标

主指标：日度横截面 Spearman Rank IC。

辅助指标：

- 横截面 ICIR；
- Top10 Lift；
- 单板块时序 Rank IC；
- MAE；
- 881/885/886 分组时序 IC；
- 与动量、ElasticNet、单独 LightGBM 的测试集比较。

## 5. MLflow 保存

实验名：`sector_peak_valley_lgbm_blend_v1`

每个测试折一个 run，保存：

- LightGBM logged model；
- ElasticNet logged model；
- 原生 LightGBM Booster；
- ElasticNet joblib 文件；
- 特征列表；
- 混合权重和验证集 Rank IC；
- 测试集指标。

由于本地模型目录为受控环境，ElasticNet 的 MLflow 模型使用 pickle 序列化，同时保留 joblib artifact。

## 6. 当前结果

三折测试均值：

| 模型 | 横截面 Rank IC | ICIR | Top10 Lift | 时序 Rank IC | MAE |
|---|---:|---:|---:|---:|---:|
| 混合模型 | 0.3134 | 1.2371 | 3.0865 | 0.3708 | 0.2243 |
| 动量基准 | 0.2962 | 1.1368 | 3.1337 | 0.1723 | 0.2916 |
| ElasticNet | 0.2909 | 1.2196 | 2.7945 | 0.4094 | 0.2282 |
| 单独 LightGBM | 0.2483 | 1.0764 | 2.3696 | 0.3634 | 0.2335 |

每折验证集选择的权重：

| 折 | LightGBM | ElasticNet | 动量 |
|---|---:|---:|---:|
| test_2023 | 0.4 | 0.4 | 0.2 |
| test_2024 | 0.2 | 0.7 | 0.1 |
| test_2025 | 0.5 | 0.3 | 0.2 |

结论：混合模型三折测试均超过动量基准，说明 LightGBM 虽然单独排序能力较弱，但提供了可利用的非线性增量信息；下一步可在相同框架下扩展 `valley_strength_ex_post`。
