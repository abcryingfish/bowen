# MLflow 板块峰谷实验使用说明

本文针对本项目的 `sector_peak_valley_lgbm_v1` 实验，说明如何查看训练结果、比较 Run 和下载模型文件。

## 一、启动 MLflow

在项目根目录执行：

```powershell
.venv\Scripts\python.exe -m mlflow ui `
  --backend-store-uri sqlite:///D:/database/sector_peak_valley_ml/models/mlflow.db `
  --host 127.0.0.1 `
  --port 5000 `
  --workers 1
```

然后打开：

```text
http://127.0.0.1:5000/#/experiments/1
```

当前实验数据位置：

```text
SQLite 数据库：D:\database\sector_peak_valley_ml\models\mlflow.db
Artifacts：D:\database\sector_peak_valley_ml\models\mlflow_artifacts
```

## 二、页面怎么用

### 1. Experiment 页面

实验名称：

```text
sector_peak_valley_lgbm_v1
```

列表中的一行就是一个 Run。当前最重要的三个 Run 是：

```text
peak_test_2023
peak_test_2024
peak_test_2025
```

它们分别代表三个时间外测试折。

### 2. 比较多个 Run

在 Run 列表中勾选多个 Run，然后选择对比功能。建议优先比较这些指标：

| MLflow 指标 | 含义 | 越大越好还是越小越好 |
|---|---|---|
| `test_cross_sectional_rank_ic` | 每天板块排序与真实波峰标签排序的一致性 | 越大越好 |
| `test_cross_sectional_icir` | Rank IC 的稳定性 | 越大越好 |
| `test_cross_sectional_positive_rate` | Rank IC 为正的交易日比例 | 越大越好 |
| `test_top10_lift` | 预测前 10% 板块捕获强波峰的能力 | 越大越好 |
| `test_mae` | 预测值与标签的平均绝对误差 | 越小越好 |
| `test_rmse` | 对大误差更敏感的误差指标 | 越小越好 |

不要只看训练集或验证集指标，模型是否有效主要看 `test_` 指标。

### 3. 查看单个 Run

进入某个 Run 后重点看三个区域：

- **Metrics**：模型效果和误差；
- **Parameters**：树数量、学习率、叶子数、训练规模等；
- **Artifacts**：模型、特征列表、对比数据和图片。

## 三、Artifacts 怎么看

进入 Run → `Artifacts` 后，当前主要目录如下：

```text
feature_columns.txt
lightgbm_booster/model.txt
visualizations/
visualizations/data/
```

### `visualizations/`

当前已经记录了：

```text
test_metrics_by_fold.png
test_family_temporal_ic.png
test_2025_daily_rank_ic.png
test_2025_prediction_vs_actual.png
```

分别用于查看：

- 三个测试年份的 Rank IC、ICIR、Top10 Lift；
- 881、885、886 分组时序 IC；
- 2025 每日 Rank IC 和 20 日均值；
- 预测值与真实标签的关系。

### `visualizations/data/`

这里是可下载到本地继续分析的 CSV：

```text
metrics_for_comparison.csv
family_metrics_for_comparison.csv
```

## 四、当前结果应该怎么判断

当前 Demo 预测的是：

```text
peak_strength_ex_post
```

它只做波峰模型，谷值模型尚未正式接入这版 Demo。

判断顺序建议是：

1. 测试 Rank IC 是否为正；
2. 是否稳定超过简单动量基准；
3. 881、885、886 是否方向一致；
4. Top10 Lift 是否稳定；
5. 不同测试年份之间是否明显退化。

如果模型 Rank IC 为正，但低于动量基准，说明模型有预测关系，但还没有产生增量信息。

## 五、如何重新生成可视化工件

如果重新训练生成了新的报告，可以执行：

```powershell
.venv\Scripts\python.exe ZXW因子\板块峰谷机器学习\mlflow_visualize_demo.py
```

脚本会读取：

```text
outputs\sector_peak_valley_ml\stage_c_lgbm_demo
```

并将图表重新写入最新的 `peak_test_*` Run。

## 六、常见问题

### 页面打不开

确认端口是否被占用：

```powershell
Get-NetTCPConnection -LocalPort 5000 -State Listen
```

如果没有监听进程，重新执行启动命令。

### 页面能打开但没有模型

确认启动命令使用的是：

```text
sqlite:///D:/database/sector_peak_valley_ml/models/mlflow.db
```

不要误用项目根目录下默认的 `mlruns`，那里不是本次板块实验的主数据库。

### 页面是英文

MLflow 官方页面目前没有完整的中文界面。可以使用浏览器的“翻译成中文”功能；指标名和 Artifact 文件名建议保留英文，避免程序读取时出现乱码或名称不一致。

