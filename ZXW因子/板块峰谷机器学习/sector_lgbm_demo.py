"""最简板块波峰 LightGBM + MLflow Demo。

该脚本只读取训练面板，不修改 signal_daily 或普通因子链路。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import mlflow
import mlflow.lightgbm
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from mlflow.tracking import MlflowClient
from sklearn.metrics import mean_absolute_error, mean_squared_error


DEFAULT_PANEL_PATH = Path(r"D:\database\sector_peak_valley_ml\panel\panel.parquet")
DEFAULT_MODEL_ROOT = Path(r"D:\database\sector_peak_valley_ml\models\lightgbm\peak")
DEFAULT_TRACKING_ROOT = Path(r"D:\database\sector_peak_valley_ml\models\mlflow_artifacts")
DEFAULT_REPORT_ROOT = Path("outputs/sector_peak_valley_ml/stage_c_lgbm_demo")
TARGET = "peak_strength_ex_post"
PURGE_BARS = 40
ID_COLUMNS = {"htsc_code", "time", "sector_family", "bars_to_end", TARGET, "valley_strength_ex_post"}


def make_splits(frame: pd.DataFrame, purge_bars: int = PURGE_BARS) -> list[dict[str, object]]:
    dates = pd.DatetimeIndex(pd.to_datetime(frame["time"]).dt.floor("D").unique()).sort_values()
    splits: list[dict[str, object]] = []
    for test_year in (2023, 2024, 2025):
        validation_year = test_year - 1
        val_dates = dates[dates.year == validation_year]
        test_dates = dates[dates.year == test_year]
        pre_val = dates[dates < val_dates[0]] if len(val_dates) else pd.DatetimeIndex([])
        if len(val_dates) <= purge_bars or len(pre_val) <= purge_bars or not len(test_dates):
            continue
        val_start = val_dates[purge_bars]
        train_end = pre_val[-purge_bars - 1]
        val_before_test = val_dates[val_dates < test_dates[0]]
        val_end = val_before_test[-purge_bars - 1]
        times = pd.to_datetime(frame["time"])
        splits.append(
            {
                "fold": f"test_{test_year}",
                "train": (times <= train_end).to_numpy(),
                "validation": ((times >= val_start) & (times <= val_end)).to_numpy(),
                "test": (times.dt.year == test_year).to_numpy(),
                "train_end": train_end.strftime("%Y-%m-%d"),
                "validation_start": val_start.strftime("%Y-%m-%d"),
                "validation_end": val_end.strftime("%Y-%m-%d"),
                "test_start": test_dates[0].strftime("%Y-%m-%d"),
                "test_end": test_dates[-1].strftime("%Y-%m-%d"),
            }
        )
    return splits


def baseline_prediction(frame: pd.DataFrame) -> np.ndarray:
    momentum = pd.to_numeric(frame["mkt_momentum_5d"], errors="coerce")
    return momentum.groupby(frame["time"]).rank(pct=True).fillna(0.5).to_numpy(dtype=float)


def rank_ic_metrics(metadata: pd.DataFrame, actual: np.ndarray, prediction: np.ndarray) -> dict[str, float]:
    data = metadata[["time", "htsc_code", "sector_family"]].copy()
    data["actual"] = np.asarray(actual, dtype=float)
    data["prediction"] = np.clip(np.asarray(prediction, dtype=float), 0.0, 1.0)
    daily_rows: list[dict[str, float]] = []
    temporal_rows: list[dict[str, float | str]] = []
    for time, group in data.groupby("time", sort=True):
        valid = group[["actual", "prediction"]].dropna()
        if len(valid) < 20 or valid.nunique().min() < 2:
            continue
        rank_ic = float(valid["actual"].corr(valid["prediction"], method="spearman"))
        pred_top = valid["prediction"] >= valid["prediction"].quantile(0.90)
        actual_top = valid["actual"] >= valid["actual"].quantile(0.90)
        precision = float((pred_top & actual_top).sum() / max(int(pred_top.sum()), 1))
        daily_rows.append({"time": time, "rank_ic": rank_ic, "top10_lift": precision / 0.10})
    for code, group in data.groupby("htsc_code", sort=True):
        valid = group[["actual", "prediction"]].dropna()
        if len(valid) < 60 or valid.nunique().min() < 2:
            continue
        temporal_rows.append(
            {
                "htsc_code": code,
                "sector_family": str(code)[:3],
                "temporal_rank_ic": float(valid["actual"].corr(valid["prediction"], method="spearman")),
            }
        )
    daily = pd.DataFrame(daily_rows)
    temporal = pd.DataFrame(temporal_rows)
    ic_std = float(daily["rank_ic"].std()) if len(daily) > 1 else float("nan")
    return {
        "rows": int(len(data)),
        "codes": int(data["htsc_code"].nunique()),
        "mae": float(mean_absolute_error(data["actual"], data["prediction"])),
        "rmse": float(mean_squared_error(data["actual"], data["prediction"]) ** 0.5),
        "cross_sectional_rank_ic": float(daily["rank_ic"].mean()) if len(daily) else float("nan"),
        "cross_sectional_icir": float(daily["rank_ic"].mean() / ic_std) if ic_std and np.isfinite(ic_std) else float("nan"),
        "cross_sectional_positive_rate": float((daily["rank_ic"] > 0).mean()) if len(daily) else float("nan"),
        "top10_lift": float(daily["top10_lift"].mean()) if len(daily) else float("nan"),
        "temporal_rank_ic": float(temporal["temporal_rank_ic"].mean()) if len(temporal) else float("nan"),
        "temporal_positive_rate": float((temporal["temporal_rank_ic"] > 0).mean()) if len(temporal) else float("nan"),
    }


def build_model(seed: int) -> LGBMRegressor:
    return LGBMRegressor(
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
        random_state=seed,
        n_jobs=16,
        verbosity=-1,
    )


def run_demo(
    *,
    panel_path: Path = DEFAULT_PANEL_PATH,
    model_root: Path = DEFAULT_MODEL_ROOT,
    tracking_root: Path = DEFAULT_TRACKING_ROOT,
    report_root: Path = DEFAULT_REPORT_ROOT,
    max_train_rows: int = 350_000,
) -> dict[str, object]:
    frame = pd.read_parquet(panel_path)
    frame["time"] = pd.to_datetime(frame["time"]).dt.floor("D")
    feature_columns = [column for column in frame.columns if column not in ID_COLUMNS]
    if not feature_columns or TARGET not in frame.columns:
        raise ValueError("训练面板缺少目标或特征")
    forbidden = [column for column in feature_columns if any(x in column.lower() for x in ("label", "未来", "事后", "peak_", "valley_"))]
    if forbidden:
        raise ValueError(f"特征含疑似未来字段: {forbidden}")
    splits = make_splits(frame)
    if len(splits) != 3:
        raise RuntimeError(f"预期 3 个时间折，实际 {len(splits)} 个")
    model_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)
    tracking_root.mkdir(parents=True, exist_ok=True)
    # MLflow 3 默认拒绝 file-store tracking backend；使用本地 SQLite，artifact 仍放 D 盘。
    database_path = tracking_root.parent / "mlflow.db"
    mlflow.set_tracking_uri(f"sqlite:///{database_path.as_posix()}")
    experiment_name = "sector_peak_valley_lgbm_v1"
    client = MlflowClient()
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        experiment_id = client.create_experiment(
            experiment_name, artifact_location=tracking_root.as_uri()
        )
    else:
        experiment_id = experiment.experiment_id
    mlflow.set_experiment(experiment_name)
    metric_rows: list[dict[str, object]] = []
    family_rows: list[dict[str, object]] = []
    manifest: list[dict[str, object]] = []
    for fold_index, split in enumerate(splits):
        train_mask = split["train"]
        valid_mask = split["validation"]
        test_mask = split["test"]
        train_indices = np.flatnonzero(train_mask)
        if len(train_indices) > max_train_rows:
            rng = np.random.default_rng(20260818 + fold_index)
            train_indices = np.sort(rng.choice(train_indices, max_train_rows, replace=False))
        x_train = frame.iloc[train_indices][feature_columns]
        y_train = frame.iloc[train_indices][TARGET]
        x_valid = frame.loc[valid_mask, feature_columns]
        y_valid = frame.loc[valid_mask, TARGET]
        x_test = frame.loc[test_mask, feature_columns]
        y_test = frame.loc[test_mask, TARGET]
        weights = 1.0 + 4.0 * np.square(y_train.to_numpy(dtype=float))
        with mlflow.start_run(
            run_name=f"peak_{split['fold']}", experiment_id=experiment_id
        ) as run:
            model = build_model(20260818 + fold_index)
            model.fit(
                x_train,
                y_train,
                sample_weight=weights,
                eval_X=x_valid,
                eval_y=y_valid,
                callbacks=[lgb.early_stopping(50, verbose=False)],
            )
            model_dir = model_root / split["fold"]
            model_dir.mkdir(parents=True, exist_ok=True)
            booster_path = model_dir / "model.txt"
            model.booster_.save_model(str(booster_path))
            # 除了 MLflow 3 的 logged model，再显式保存原生 Booster，便于离线审计和兼容旧版 LightGBM。
            mlflow.log_artifact(str(booster_path), artifact_path="lightgbm_booster")
            pred_valid = model.predict(x_valid)
            pred_test = model.predict(x_test)
            baseline_valid = baseline_prediction(frame.loc[valid_mask])
            baseline_test = baseline_prediction(frame.loc[test_mask])
            for split_name, mask, actual, prediction, baseline in (
                ("validation", valid_mask, y_valid.to_numpy(), pred_valid, baseline_valid),
                ("test", test_mask, y_test.to_numpy(), pred_test, baseline_test),
            ):
                metrics = rank_ic_metrics(frame.loc[mask], actual, prediction)
                baseline_metrics = rank_ic_metrics(frame.loc[mask], actual, baseline)
                row = {"fold": split["fold"], "split": split_name, "model": "lightgbm", **metrics}
                row["baseline_rank_ic"] = baseline_metrics["cross_sectional_rank_ic"]
                row["baseline_top10_lift"] = baseline_metrics["top10_lift"]
                metric_rows.append(row)
                prediction_frame = frame.loc[mask, ["time", "htsc_code", "sector_family"]].copy()
                prediction_frame["actual"] = actual
                prediction_frame["prediction"] = np.clip(prediction, 0.0, 1.0)
                prediction_frame.to_parquet(
                    report_root / f"predictions_{split['fold']}_{split_name}.parquet", index=False
                )
                for family, group in prediction_frame.groupby("sector_family"):
                    group_metrics = rank_ic_metrics(group, group["actual"].to_numpy(), group["prediction"].to_numpy())
                    family_rows.append(
                        {
                            "fold": split["fold"],
                            "split": split_name,
                            "sector_family": family,
                            "temporal_rank_ic": group_metrics["temporal_rank_ic"],
                            "rows": len(group),
                        }
                    )
                mlflow.log_metrics({f"{split_name}_{key}": value for key, value in metrics.items() if np.isfinite(value)})
            mlflow.log_params({
                "target": TARGET,
                "fold": split["fold"],
                "feature_count": len(feature_columns),
                "train_rows_full": int(train_mask.sum()),
                "train_rows_used": int(len(train_indices)),
                "validation_rows": int(valid_mask.sum()),
                "test_rows": int(test_mask.sum()),
                "purge_bars": PURGE_BARS,
                "best_iteration": int(model.best_iteration_),
                **{key: value for key, value in model.get_params().items() if isinstance(value, (str, int, float, bool))},
            })
            mlflow.log_text("\n".join(feature_columns), "feature_columns.txt")
            mlflow.lightgbm.log_model(model, name="model")
            mlflow.set_tag("run_id_local", run.info.run_id)
        manifest.append({key: value for key, value in split.items() if key not in {"train", "validation", "test"}} | {"run_id": run.info.run_id})
    metrics_frame = pd.DataFrame(metric_rows)
    family_frame = pd.DataFrame(family_rows)
    metrics_frame.to_csv(report_root / "metrics.csv", index=False, encoding="utf-8-sig")
    family_frame.to_csv(report_root / "family_metrics.csv", index=False, encoding="utf-8-sig")
    summary = metrics_frame.loc[metrics_frame["split"] == "test"].mean(numeric_only=True).to_dict()
    pipeline_passed = bool(
        metrics_frame.loc[metrics_frame["split"] == "test", "cross_sectional_rank_ic"].gt(0).all()
        and metrics_frame.loc[metrics_frame["split"] == "test", "top10_lift"].gt(1).all()
    )
    rank_ic_delta = float(
        summary["cross_sectional_rank_ic"] - summary["baseline_rank_ic"]
    )
    top10_lift_delta = float(summary["top10_lift"] - summary["baseline_top10_lift"])
    report = {
        "target": TARGET,
        "feature_count": len(feature_columns),
        "features": feature_columns,
        "folds": manifest,
        "test_mean": summary,
        # passed 兼容旧调用方，语义是“Demo 链路通过”；模型是否优于基准单独报告。
        "passed": pipeline_passed,
        "pipeline_passed": pipeline_passed,
        "model_passed": bool(pipeline_passed and rank_ic_delta >= 0.0),
        "model_vs_momentum_baseline": {
            "rank_ic_delta": rank_ic_delta,
            "top10_lift_delta": top10_lift_delta,
            "not_worse_on_rank_ic": bool(rank_ic_delta >= 0.0),
        },
    }
    (report_root / "demo_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(metrics_frame.to_string(index=False))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="运行板块波峰 LightGBM Demo")
    parser.add_argument("--panel-path", type=Path, default=DEFAULT_PANEL_PATH)
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--tracking-root", type=Path, default=DEFAULT_TRACKING_ROOT)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--max-train-rows", type=int, default=350_000)
    args = parser.parse_args()
    run_demo(**vars(args))


if __name__ == "__main__":
    main()
