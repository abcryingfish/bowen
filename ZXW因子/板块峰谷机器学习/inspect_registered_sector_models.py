"""生成峰谷注册模型的特征重要性与训练摘要，并记录到 MLflow。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import mlflow
import numpy as np
import pandas as pd
from mlflow.tracking import MlflowClient


DEFAULT_TRACKING_ROOT = Path(r"D:\database\sector_peak_valley_ml\models\mlflow_artifacts")
SOURCE_EXPERIMENTS = {
    "peak": "sector_peak_valley_lgbm_long_peak_blend_v1",
    "valley": "sector_peak_valley_lgbm_long_valley_blend_v1",
}
REGISTERED_NAMES = {
    "peak": "sector_peak_valley_peak_lgbm",
    "valley": "sector_peak_valley_valley_lgbm",
}


def latest_run(client: MlflowClient, experiment_name: str):
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        raise ValueError(f"找不到实验: {experiment_name}")
    runs = client.search_runs(
        [experiment.experiment_id],
        filter_string="attributes.status = 'FINISHED'",
        order_by=["attributes.start_time DESC"],
        max_results=1,
    )
    if not runs:
        raise ValueError(f"实验没有已完成 Run: {experiment_name}")
    return runs[0]


def inspect_one(client: MlflowClient, key: str, report_root: Path) -> dict[str, object]:
    run = latest_run(client, SOURCE_EXPERIMENTS[key])
    booster_path = client.download_artifacts(run.info.run_id, "lightgbm_booster/lightgbm_model.txt")
    config_path = client.download_artifacts(run.info.run_id, "blend_config/blend_config.json")
    feature_path = client.download_artifacts(run.info.run_id, "feature_columns.txt")
    booster = lgb.Booster(model_file=booster_path)
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    feature_names = [line.strip() for line in Path(feature_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(feature_names) != len(booster.feature_name()):
        raise ValueError(f"特征数量与 LightGBM 模型不一致: {len(feature_names)} != {len(booster.feature_name())}")
    importance = pd.DataFrame(
        {
            "feature": feature_names,
            "gain": booster.feature_importance(importance_type="gain"),
            "split": booster.feature_importance(importance_type="split"),
        }
    ).sort_values("gain", ascending=False, ignore_index=True)
    gain_total = float(importance["gain"].sum())
    importance["gain_pct"] = importance["gain"] / gain_total if gain_total > 0 else 0.0
    report_root.mkdir(parents=True, exist_ok=True)
    importance_path = report_root / f"{key}_lgbm_feature_importance.csv"
    importance.to_csv(importance_path, index=False, encoding="utf-8-sig")
    summary = {
        "target_key": key,
        "target": config.get("target"),
        "source_experiment": SOURCE_EXPERIMENTS[key],
        "source_run_id": run.info.run_id,
        "fold": run.data.params.get("fold"),
        "feature_count": len(feature_names),
        "best_iteration": run.data.params.get("lgbm_best_iteration"),
        "blend_weights": {
            "lightgbm": config.get("lgbm_weight"),
            "elastic_net": config.get("elastic_net_weight"),
            "momentum": config.get("momentum_weight"),
        },
        "test_metrics": {
            key_name: value
            for key_name, value in run.data.metrics.items()
            if key_name.endswith("_test")
        },
        "top10_features_by_gain": importance.head(10).to_dict(orient="records"),
        "lightgbm_params": booster.params,
    }
    summary_path = report_root / f"{key}_lgbm_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"key": key, "importance_path": str(importance_path), "summary_path": str(summary_path), **summary}


def main() -> None:
    parser = argparse.ArgumentParser(description="生成峰谷 LGBM 模型解释报告")
    parser.add_argument("--tracking-root", type=Path, default=DEFAULT_TRACKING_ROOT)
    parser.add_argument("--report-root", type=Path, default=Path("outputs/sector_peak_valley_ml/stage_j_model_inspection"))
    args = parser.parse_args()
    database_path = args.tracking_root.parent / "mlflow.db"
    mlflow.set_tracking_uri(f"sqlite:///{database_path.as_posix()}")
    client = MlflowClient()
    results = [inspect_one(client, key, args.report_root) for key in ("peak", "valley")]
    experiment_name = "sector_peak_valley_model_inspection_v1"
    experiment = client.get_experiment_by_name(experiment_name)
    experiment_id = experiment.experiment_id if experiment else client.create_experiment(experiment_name, artifact_location=args.tracking_root.as_uri())
    with mlflow.start_run(run_name="registered_models_feature_importance", experiment_id=experiment_id) as run:
        mlflow.log_params({"models": "peak_lgbm,valley_lgbm", "source_fold": "test_2026", "feature_count": 29})
        for result in results:
            mlflow.log_artifact(result["importance_path"], artifact_path=result["key"])
            mlflow.log_artifact(result["summary_path"], artifact_path=result["key"])
            top = result["top10_features_by_gain"][0]
            mlflow.log_metric(f"{result['key']}_top1_gain_pct", float(top["gain_pct"]))
        mlflow.set_tag("purpose", "查看注册模型学习到的特征与训练摘要")
        print("inspection_run_id=", run.info.run_id)
    for result in results:
        print(result["key"], "top10=", [row["feature"] for row in result["top10_features_by_gain"]])


if __name__ == "__main__":
    main()
