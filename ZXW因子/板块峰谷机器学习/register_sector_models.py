"""将峰谷长窗口滚动实验的最新 LightGBM 模型注册到 MLflow Model Registry。"""

from __future__ import annotations

import argparse
from pathlib import Path

import mlflow
from mlflow.tracking import MlflowClient


DEFAULT_TRACKING_ROOT = Path(r"D:\database\sector_peak_valley_ml\models\mlflow_artifacts")
DEFAULT_EXPERIMENTS = {
    "peak": "sector_peak_valley_lgbm_long_peak_blend_v1",
    "valley": "sector_peak_valley_lgbm_long_valley_blend_v1",
}
DEFAULT_MODEL_NAMES = {
    "peak": "sector_peak_valley_peak_lgbm",
    "valley": "sector_peak_valley_valley_lgbm",
}


def register_latest_model(
    client: MlflowClient,
    *,
    experiment_name: str,
    registered_name: str,
    alias: str = "champion",
) -> dict[str, str]:
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        raise ValueError(f"找不到 MLflow 实验: {experiment_name}")
    runs = client.search_runs(
        [experiment.experiment_id],
        filter_string="attributes.status = 'FINISHED'",
        order_by=["attributes.start_time DESC"],
        max_results=1,
    )
    if not runs:
        raise ValueError(f"实验没有已完成 Run: {experiment_name}")
    run = runs[0]
    source_uri = f"runs:/{run.info.run_id}/lightgbm_model"
    existing = [
        version
        for version in client.search_model_versions(f"name='{registered_name}'")
        if version.run_id == run.info.run_id
    ]
    model_version = existing[0] if existing else mlflow.register_model(source_uri, registered_name)
    client.set_registered_model_tag(registered_name, "source_experiment", experiment_name)
    client.set_registered_model_tag(registered_name, "model_role", registered_name.rsplit("_", 1)[-1])
    client.set_model_version_tag(registered_name, model_version.version, "source_run_id", run.info.run_id)
    client.set_model_version_tag(registered_name, model_version.version, "fold", run.data.params.get("fold", ""))
    client.set_model_version_tag(registered_name, model_version.version, "target", run.data.params.get("target", ""))
    client.set_registered_model_alias(registered_name, alias, model_version.version)
    client.update_registered_model(
        registered_name,
        description=(
            f"峰谷板块长窗口滚动 LightGBM；来源实验 {experiment_name}，"
            f"最新 Run {run.info.run_id}，滚动折 {run.data.params.get('fold', '')}。"
        ),
    )
    return {
        "registered_name": registered_name,
        "version": str(model_version.version),
        "alias": alias,
        "run_id": run.info.run_id,
        "fold": run.data.params.get("fold", ""),
        "source_uri": source_uri,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="注册峰谷 LightGBM 模型")
    parser.add_argument("--tracking-root", type=Path, default=DEFAULT_TRACKING_ROOT)
    parser.add_argument("--alias", default="champion")
    args = parser.parse_args()

    database_path = args.tracking_root.parent / "mlflow.db"
    mlflow.set_tracking_uri(f"sqlite:///{database_path.as_posix()}")
    client = MlflowClient()
    for key in ("peak", "valley"):
        result = register_latest_model(
            client,
            experiment_name=DEFAULT_EXPERIMENTS[key],
            registered_name=DEFAULT_MODEL_NAMES[key],
            alias=args.alias,
        )
        print(result)


if __name__ == "__main__":
    main()
