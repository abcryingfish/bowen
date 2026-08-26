"""为板块峰谷 LightGBM Demo 生成并记录 MLflow 可视化工件。"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import numpy as np
import pandas as pd
from mlflow.tracking import MlflowClient


DEFAULT_TRACKING_DB = Path(r"D:\database\sector_peak_valley_ml\models\mlflow.db")
DEFAULT_REPORT_ROOT = Path("outputs/sector_peak_valley_ml/stage_c_lgbm_demo")
EXPERIMENT_NAME = "sector_peak_valley_lgbm_v1"


def _savefig(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()


def build_charts(report_root: Path, output_root: Path) -> list[Path]:
    metrics = pd.read_csv(report_root / "metrics.csv")
    family = pd.read_csv(report_root / "family_metrics.csv")
    test_metrics = metrics[metrics["split"].eq("test")].copy()
    test_family = family[family["split"].eq("test")].copy()
    paths: list[Path] = []

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))
    for ax, column, title in zip(
        axes,
        ["cross_sectional_rank_ic", "cross_sectional_icir", "top10_lift"],
        ["Test Rank IC", "Test ICIR", "Test Top10 Lift"],
    ):
        ax.bar(test_metrics["fold"], test_metrics[column], color="#2878b5")
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=25)
        ax.grid(axis="y", alpha=0.25)
    path = output_root / "test_metrics_by_fold.png"
    _savefig(path)
    paths.append(path)

    pivot = test_family.pivot(index="sector_family", columns="fold", values="temporal_rank_ic")
    ax = pivot.plot(kind="bar", figsize=(8, 4.5), color=["#2878b5", "#f28e2b", "#59a14f"])
    ax.set_title("Test Temporal Rank IC by Sector Family")
    ax.set_xlabel("Sector family")
    ax.set_ylabel("Temporal Rank IC")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(title="Fold")
    path = output_root / "test_family_temporal_ic.png"
    _savefig(path)
    paths.append(path)

    prediction_path = report_root / "predictions_test_2025_test.parquet"
    prediction = pd.read_parquet(prediction_path)
    daily = []
    for time, group in prediction.groupby("time", sort=True):
        valid = group[["actual", "prediction"]].dropna()
        if len(valid) >= 20 and valid.nunique().min() >= 2:
            daily.append({"time": time, "rank_ic": valid["actual"].corr(valid["prediction"], method="spearman")})
    daily_frame = pd.DataFrame(daily)
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(daily_frame["time"], daily_frame["rank_ic"], color="#2878b5", linewidth=0.8, label="Daily Rank IC")
    ax.plot(
        daily_frame["time"],
        daily_frame["rank_ic"].rolling(20, min_periods=5).mean(),
        color="#e15759",
        linewidth=2,
        label="20-day mean",
    )
    ax.axhline(0, color="black", linewidth=0.7)
    ax.set_title("2025 Test Daily Cross-sectional Rank IC")
    ax.set_ylabel("Rank IC")
    ax.legend()
    ax.grid(alpha=0.25)
    path = output_root / "test_2025_daily_rank_ic.png"
    _savefig(path)
    paths.append(path)

    sample = prediction.sample(min(len(prediction), 30_000), random_state=20260818)
    fig, ax = plt.subplots(figsize=(6, 5.5))
    hb = ax.hexbin(sample["actual"], sample["prediction"], gridsize=35, mincnt=1, cmap="viridis")
    ax.plot([0, 1], [0, 1], "--", color="#e15759", linewidth=1.5, label="Ideal y=x")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Actual peak strength")
    ax.set_ylabel("Predicted peak strength")
    ax.set_title("2025 Test Prediction vs Actual")
    ax.legend()
    fig.colorbar(hb, ax=ax, label="Count")
    path = output_root / "test_2025_prediction_vs_actual.png"
    _savefig(path)
    paths.append(path)

    metrics.to_csv(output_root / "metrics_for_comparison.csv", index=False, encoding="utf-8-sig")
    test_family.to_csv(output_root / "family_metrics_for_comparison.csv", index=False, encoding="utf-8-sig")
    return paths


def resolve_run_ids(client: MlflowClient, experiment_id: str, run_ids: list[str] | None) -> list[str]:
    if run_ids:
        return run_ids
    runs = client.search_runs([experiment_id], order_by=["attributes.start_time DESC"], max_results=20)
    final_runs = [run.info.run_id for run in runs if run.data.tags.get("mlflow.runName", "").startswith("peak_test_")]
    return final_runs[:3]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracking-db", type=Path, default=DEFAULT_TRACKING_DB)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_REPORT_ROOT / "mlflow_visualizations")
    parser.add_argument("--run-id", action="append", dest="run_ids")
    args = parser.parse_args()

    mlflow.set_tracking_uri(f"sqlite:///{args.tracking_db.as_posix()}")
    client = MlflowClient()
    experiment = client.get_experiment_by_name(EXPERIMENT_NAME)
    if experiment is None:
        raise RuntimeError(f"MLflow experiment not found: {EXPERIMENT_NAME}")
    charts = build_charts(args.report_root, args.output_root)
    for run_id in resolve_run_ids(client, experiment.experiment_id, args.run_ids):
        for chart in charts:
            client.log_artifact(run_id, str(chart), artifact_path="visualizations")
        for data_file in [args.output_root / "metrics_for_comparison.csv", args.output_root / "family_metrics_for_comparison.csv"]:
            client.log_artifact(run_id, str(data_file), artifact_path="visualizations/data")
        print(f"logged run={run_id} charts={len(charts)}")
    print(f"output_root={args.output_root}")


if __name__ == "__main__":
    main()
