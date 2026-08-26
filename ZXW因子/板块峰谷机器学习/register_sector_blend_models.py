"""把峰谷 LightGBM + ElasticNet + 动量权重混合封装并注册到 MLflow。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import lightgbm  # noqa: F401  # 确保 MLflow 模型加载环境包含 LightGBM
import mlflow
import mlflow.lightgbm
import mlflow.pyfunc
import mlflow.sklearn
import numpy as np
import pandas as pd
from mlflow.tracking import MlflowClient


DEFAULT_TRACKING_ROOT = Path(r"D:\database\sector_peak_valley_ml\models\mlflow_artifacts")
SOURCE_EXPERIMENTS = {
    "peak": "sector_peak_valley_lgbm_long_peak_blend_v1",
    "valley": "sector_peak_valley_lgbm_long_valley_blend_v1",
}
REGISTERED_NAMES = {
    "peak": "sector_peak_valley_peak_blend",
    "valley": "sector_peak_valley_valley_blend",
}


class SectorBlendModel(mlflow.pyfunc.PythonModel):
    """复现训练脚本中的混合预测逻辑。"""

    def load_context(self, context: mlflow.pyfunc.PythonModelContext) -> None:
        self.lgbm_model = mlflow.lightgbm.load_model(context.artifacts["lightgbm_model"])
        self.elastic_model = mlflow.sklearn.load_model(context.artifacts["elastic_net_model"])
        self.config = json.loads(Path(context.artifacts["blend_config"]).read_text(encoding="utf-8"))

    def predict(self, context: mlflow.pyfunc.PythonModelContext, model_input: pd.DataFrame) -> pd.DataFrame:
        frame = model_input.copy()
        features = self.config["features"]
        missing = [column for column in features if column not in frame.columns]
        if missing:
            raise ValueError(f"输入缺少模型特征: {missing}")
        if "time" not in frame.columns or "mkt_momentum_5d" not in frame.columns:
            raise ValueError("混合模型需要 time 和 mkt_momentum_5d 列")
        lgbm_prediction = np.clip(self.lgbm_model.predict(frame[features]), 0.0, 1.0)
        elastic_prediction = np.clip(self.elastic_model.predict(frame[features]), 0.0, 1.0)
        momentum = pd.to_numeric(frame["mkt_momentum_5d"], errors="coerce")
        rank = momentum.groupby(frame["time"]).rank(pct=True).fillna(0.5)
        if self.config["target"] == "valley_strength_ex_post":
            rank = 1.0 - rank
        prediction = (
            float(self.config["lgbm_weight"]) * lgbm_prediction
            + float(self.config["elastic_net_weight"]) * elastic_prediction
            + float(self.config["momentum_weight"]) * rank.to_numpy(dtype=float)
        )
        return pd.DataFrame({"prediction": np.clip(prediction, 0.0, 1.0)}, index=frame.index)


def latest_source_run(client: MlflowClient, experiment_name: str):
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        raise ValueError(f"找不到源实验: {experiment_name}")
    runs = client.search_runs(
        [experiment.experiment_id],
        filter_string="attributes.status = 'FINISHED'",
        order_by=["attributes.start_time DESC"],
        max_results=1,
    )
    if not runs:
        raise ValueError(f"源实验没有已完成 Run: {experiment_name}")
    return runs[0]


def register_one(
    client: MlflowClient,
    *,
    key: str,
    registry_experiment_id: str,
    tracking_root: Path,
    alias: str,
) -> dict[str, str]:
    source_run = latest_source_run(client, SOURCE_EXPERIMENTS[key])
    source_run_id = source_run.info.run_id
    registry_name = REGISTERED_NAMES[key]
    existing = [
        version
        for version in client.search_model_versions(f"name='{registry_name}'")
        if version.tags.get("source_run_id") == source_run_id
    ]
    if existing:
        model_version = existing[0]
        package_run_id = model_version.run_id
    else:
        source_prefix = f"runs:/{source_run_id}"
        with mlflow.start_run(
            run_name=f"register_{key}_blend_test_2026",
            experiment_id=registry_experiment_id,
        ) as package_run:
            mlflow.log_params(
                {
                    "source_run_id": source_run_id,
                    "source_experiment": SOURCE_EXPERIMENTS[key],
                    "source_fold": source_run.data.params.get("fold", ""),
                    "target": source_run.data.params.get("target", ""),
                    "model_type": "lightgbm_elastic_net_momentum_blend",
                }
            )
            mlflow.pyfunc.log_model(
                name="blend_model",
                python_model=SectorBlendModel(),
                artifacts={
                    "lightgbm_model": f"{source_prefix}/lightgbm_model",
                    "elastic_net_model": f"{source_prefix}/elastic_net_model",
                    "blend_config": f"{source_prefix}/blend_config/blend_config.json",
                },
            )
            package_run_id = package_run.info.run_id
        model_version = mlflow.register_model(
            f"runs:/{package_run_id}/blend_model", registry_name
        )

    client.set_registered_model_tag(registry_name, "model_type", "lightgbm_elastic_net_momentum_blend")
    client.set_registered_model_tag(registry_name, "source_experiment", SOURCE_EXPERIMENTS[key])
    client.set_model_version_tag(registry_name, model_version.version, "source_run_id", source_run_id)
    client.set_model_version_tag(registry_name, model_version.version, "source_fold", source_run.data.params.get("fold", ""))
    client.set_model_version_alias(registry_name, alias, model_version.version) if hasattr(client, "set_model_version_alias") else client.set_registered_model_alias(registry_name, alias, model_version.version)
    client.update_registered_model(
        registry_name,
        description=(
            f"峰谷板块 LightGBM + ElasticNet + 动量验证集混合模型；"
            f"来源 {SOURCE_EXPERIMENTS[key]} / {source_run_id}。"
        ),
    )
    return {
        "registered_name": registry_name,
        "version": str(model_version.version),
        "alias": alias,
        "source_run_id": source_run_id,
        "package_run_id": package_run_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="注册峰谷完整混合模型")
    parser.add_argument("--tracking-root", type=Path, default=DEFAULT_TRACKING_ROOT)
    parser.add_argument("--alias", default="champion")
    args = parser.parse_args()

    database_path = args.tracking_root.parent / "mlflow.db"
    mlflow.set_tracking_uri(f"sqlite:///{database_path.as_posix()}")
    client = MlflowClient()
    registry_experiment = client.get_experiment_by_name("sector_peak_valley_model_registry_v1")
    if registry_experiment is None:
        experiment_id = client.create_experiment(
            "sector_peak_valley_model_registry_v1",
            artifact_location=args.tracking_root.as_uri(),
        )
    else:
        experiment_id = registry_experiment.experiment_id
    for key in ("peak", "valley"):
        print(register_one(client, key=key, registry_experiment_id=experiment_id, tracking_root=args.tracking_root, alias=args.alias))


if __name__ == "__main__":
    main()
