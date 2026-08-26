"""板块波峰 LightGBM / ElasticNet / 动量验证集混合实验。

该脚本是 Stage D 独立实验，只读取训练面板，不修改 signal_daily 或普通因子链路。
混合权重严格在每个滚动折的验证集上选择，测试集只做一次最终评价。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import lightgbm as lgb
import mlflow
import mlflow.lightgbm
import mlflow.sklearn
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from mlflow.tracking import MlflowClient
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler


DEFAULT_PANEL_PATH = Path(r"D:\database\sector_peak_valley_ml\panel\panel.parquet")
DEFAULT_MODEL_ROOT = Path(r"D:\database\sector_peak_valley_ml\models\lightgbm_blend\peak")
DEFAULT_TRACKING_ROOT = Path(r"D:\database\sector_peak_valley_ml\models\mlflow_artifacts")
DEFAULT_REPORT_ROOT = Path("outputs/sector_peak_valley_ml/stage_d_lgbm_blend")
TARGETS = {
    "peak": "peak_strength_ex_post",
    "valley": "valley_strength_ex_post",
}
TARGET = TARGETS["peak"]
PURGE_BARS = 40
ID_COLUMNS = {
    "htsc_code",
    "time",
    "sector_family",
    "bars_to_end",
    *TARGETS.values(),
    "valley_strength_ex_post",
}


def make_splits(
    frame: pd.DataFrame,
    purge_bars: int = PURGE_BARS,
    test_years: tuple[int, ...] = (2023, 2024, 2025),
) -> list[dict[str, object]]:
    dates = pd.DatetimeIndex(pd.to_datetime(frame["time"]).dt.floor("D").unique()).sort_values()
    splits: list[dict[str, object]] = []
    times = pd.to_datetime(frame["time"])
    for test_year in test_years:
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


def build_lgbm(seed: int) -> LGBMRegressor:
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


def build_elastic_net(seed: int) -> Pipeline:
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("scaler", RobustScaler(quantile_range=(10, 90))),
            (
                "model",
                ElasticNet(alpha=0.001, l1_ratio=0.15, max_iter=3000, random_state=seed),
            ),
        ]
    )


def baseline_prediction(frame: pd.DataFrame, target: str) -> np.ndarray:
    momentum = pd.to_numeric(frame["mkt_momentum_5d"], errors="coerce")
    rank = momentum.groupby(frame["time"]).rank(pct=True).fillna(0.5)
    if target == TARGETS["valley"]:
        rank = 1.0 - rank
    return rank.to_numpy(dtype=float)


def resolve_target_settings(
    target_key: str,
    model_root: Path | None,
    report_root: Path | None,
) -> tuple[str, Path, Path, str]:
    if target_key not in TARGETS:
        raise ValueError(f"target 必须是 {sorted(TARGETS)} 之一")
    target = TARGETS[target_key]
    if model_root is None:
        model_root = Path(r"D:\database\sector_peak_valley_ml\models\lightgbm_blend") / target_key
    if report_root is None:
        report_root = Path(f"outputs/sector_peak_valley_ml/stage_d_lgbm_blend_{target_key}")
    experiment_name = (
        "sector_peak_valley_lgbm_blend_v1"
        if target_key == "peak"
        else f"sector_peak_valley_lgbm_{target_key}_blend_v1"
    )
    return target, model_root, report_root, experiment_name


def _spearman(left: pd.Series, right: pd.Series, minimum: int) -> float:
    valid = pd.DataFrame({"left": left, "right": right}).replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    if len(valid) < minimum or valid.nunique().min() < 2:
        return float("nan")
    return float(valid["left"].corr(valid["right"], method="spearman"))


def rank_ic_only(metadata: pd.DataFrame, actual: np.ndarray, prediction: np.ndarray) -> float:
    """仅计算验证集权重选择所需的日度横截面 Rank IC。"""

    data = metadata[["time"]].copy()
    data["actual"] = np.asarray(actual, dtype=float)
    data["prediction"] = np.asarray(prediction, dtype=float)
    values = []
    for _, group in data.groupby("time", sort=True):
        ic = _spearman(group["prediction"], group["actual"], minimum=20)
        if np.isfinite(ic):
            values.append(ic)
    return float(np.mean(values)) if values else float("nan")


def evaluate_predictions(
    metadata: pd.DataFrame, actual: np.ndarray, prediction: np.ndarray
) -> tuple[dict[str, float], pd.DataFrame, pd.DataFrame]:
    data = metadata[["time", "htsc_code", "sector_family"]].copy()
    data["actual"] = np.asarray(actual, dtype=float)
    data["prediction"] = np.clip(np.asarray(prediction, dtype=float), 0.0, 1.0)
    daily_rows: list[dict[str, object]] = []
    for time, group in data.groupby("time", sort=True):
        ic = _spearman(group["prediction"], group["actual"], minimum=20)
        if not np.isfinite(ic):
            continue
        pred_top = group["prediction"] >= group["prediction"].quantile(0.90)
        actual_top = group["actual"] >= group["actual"].quantile(0.90)
        precision = float((pred_top & actual_top).sum() / max(int(pred_top.sum()), 1))
        daily_rows.append({"time": time, "rank_ic": ic, "top10_lift": precision / 0.10})
    temporal_rows: list[dict[str, object]] = []
    for code, group in data.groupby("htsc_code", sort=True):
        ic = _spearman(group["prediction"], group["actual"], minimum=60)
        if np.isfinite(ic):
            temporal_rows.append(
                {
                    "htsc_code": code,
                    "sector_family": str(group["sector_family"].iloc[0]),
                    "temporal_rank_ic": ic,
                }
            )
    daily = pd.DataFrame(daily_rows)
    temporal = pd.DataFrame(temporal_rows)
    std = float(daily["rank_ic"].std()) if len(daily) > 1 else float("nan")
    metrics = {
        "rows": int(len(data)),
        "codes": int(data["htsc_code"].nunique()),
        "mae": float(mean_absolute_error(data["actual"], data["prediction"])),
        "rmse": float(mean_squared_error(data["actual"], data["prediction"]) ** 0.5),
        "cross_sectional_rank_ic": float(daily["rank_ic"].mean()) if len(daily) else float("nan"),
        "cross_sectional_icir": float(daily["rank_ic"].mean() / std) if std and np.isfinite(std) else float("nan"),
        "cross_sectional_positive_rate": float((daily["rank_ic"] > 0).mean()) if len(daily) else float("nan"),
        "top10_lift": float(daily["top10_lift"].mean()) if len(daily) else float("nan"),
        "temporal_rank_ic": float(temporal["temporal_rank_ic"].mean()) if len(temporal) else float("nan"),
        "temporal_positive_rate": float((temporal["temporal_rank_ic"] > 0).mean()) if len(temporal) else float("nan"),
    }
    return metrics, daily, temporal


def candidate_weights(step: float = 0.1) -> list[tuple[float, float, float]]:
    if step <= 0 or step > 1:
        raise ValueError("step 必须位于 (0, 1]")
    units = round(1.0 / step)
    if not np.isclose(units * step, 1.0):
        raise ValueError("step 必须能整除 1")
    return [
        (i / units, j / units, (units - i - j) / units)
        for i in range(units + 1)
        for j in range(units - i + 1)
    ]


def select_blend_weights(
    metadata: pd.DataFrame,
    actual: np.ndarray,
    lgbm_prediction: np.ndarray,
    elastic_prediction: np.ndarray,
    momentum_prediction: np.ndarray,
    step: float = 0.1,
) -> tuple[tuple[float, float, float], float]:
    """在验证集选择 (LightGBM, ElasticNet, 动量) 的凸组合权重。"""

    best_weights = (0.0, 0.0, 1.0)
    best_score = -np.inf
    for weights in candidate_weights(step):
        blended = (
            weights[0] * lgbm_prediction
            + weights[1] * elastic_prediction
            + weights[2] * momentum_prediction
        )
        score = rank_ic_only(metadata, actual, blended)
        if np.isfinite(score) and score > best_score:
            best_weights = weights
            best_score = score
    if not np.isfinite(best_score):
        raise RuntimeError("验证集无法计算有效 Rank IC，不能选择混合权重")
    return best_weights, float(best_score)


def _sample_indices(mask: np.ndarray, maximum: int, seed: int) -> np.ndarray:
    indices = np.flatnonzero(mask)
    if len(indices) <= maximum:
        return indices
    rng = np.random.default_rng(seed)
    return np.sort(rng.choice(indices, maximum, replace=False))


def run_blend(
    *,
    target_key: str = "peak",
    panel_path: Path = DEFAULT_PANEL_PATH,
    model_root: Path | None = None,
    tracking_root: Path = DEFAULT_TRACKING_ROOT,
    report_root: Path | None = None,
    max_train_rows: int = 350_000,
    weight_step: float = 0.1,
    test_years: tuple[int, ...] = (2023, 2024, 2025),
    experiment_name: str | None = None,
) -> dict[str, object]:
    target, model_root, report_root, default_experiment_name = resolve_target_settings(
        target_key, model_root, report_root
    )
    experiment_name = experiment_name or default_experiment_name
    panel = pd.read_parquet(panel_path)
    panel["time"] = pd.to_datetime(panel["time"]).dt.floor("D")
    features = [column for column in panel.columns if column not in ID_COLUMNS]
    if target not in panel.columns or not features:
        raise ValueError("训练面板缺少目标或特征")
    forbidden = [
        column
        for column in features
        if any(token in column.lower() for token in ("label", "未来", "事后", "peak_", "valley_"))
    ]
    if forbidden:
        raise ValueError(f"特征含疑似未来字段: {forbidden}")
    splits = make_splits(panel, test_years=test_years)
    if len(splits) != len(test_years):
        raise RuntimeError(f"预期 {len(test_years)} 个滚动折，实际 {len(splits)} 个")
    model_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)
    tracking_root.mkdir(parents=True, exist_ok=True)
    database_path = tracking_root.parent / "mlflow.db"
    mlflow.set_tracking_uri(f"sqlite:///{database_path.as_posix()}")
    client = MlflowClient()
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        experiment_id = client.create_experiment(experiment_name, artifact_location=tracking_root.as_uri())
    else:
        experiment_id = experiment.experiment_id
    mlflow.set_experiment(experiment_name)

    metric_rows: list[dict[str, object]] = []
    family_rows: list[dict[str, object]] = []
    weight_rows: list[dict[str, object]] = []
    manifest: list[dict[str, object]] = []

    for fold_index, split in enumerate(splits):
        train_mask = split["train"]
        valid_mask = split["validation"]
        test_mask = split["test"]
        train_indices = _sample_indices(train_mask, max_train_rows, 20260818 + fold_index)
        x_train = panel.iloc[train_indices][features]
        y_train = panel.iloc[train_indices][target]
        x_valid = panel.loc[valid_mask, features]
        y_valid = panel.loc[valid_mask, target]
        x_test = panel.loc[test_mask, features]
        y_test = panel.loc[test_mask, target]
        weights = 1.0 + 4.0 * np.square(y_train.to_numpy(dtype=float))
        momentum_valid = baseline_prediction(panel.loc[valid_mask], target)
        momentum_test = baseline_prediction(panel.loc[test_mask], target)

        with mlflow.start_run(run_name=f"{target_key}_blend_{split['fold']}", experiment_id=experiment_id) as run:
            lgbm_model = build_lgbm(20260818 + fold_index)
            lgbm_model.fit(
                x_train,
                y_train,
                sample_weight=weights,
                eval_X=x_valid,
                eval_y=y_valid,
                callbacks=[lgb.early_stopping(50, verbose=False)],
            )
            elastic_model = build_elastic_net(20260818 + fold_index)
            elastic_model.fit(x_train, y_train, model__sample_weight=weights)
            lgbm_valid = np.clip(lgbm_model.predict(x_valid), 0.0, 1.0)
            lgbm_test = np.clip(lgbm_model.predict(x_test), 0.0, 1.0)
            elastic_valid = np.clip(elastic_model.predict(x_valid), 0.0, 1.0)
            elastic_test = np.clip(elastic_model.predict(x_test), 0.0, 1.0)
            blend_weights, validation_ic = select_blend_weights(
                panel.loc[valid_mask],
                y_valid.to_numpy(dtype=float),
                lgbm_valid,
                elastic_valid,
                momentum_valid,
                step=weight_step,
            )
            prediction_sets = {
                "momentum": (momentum_valid, momentum_test),
                "elastic_net": (elastic_valid, elastic_test),
                "lightgbm": (lgbm_valid, lgbm_test),
                "blend": (
                    blend_weights[0] * lgbm_valid
                    + blend_weights[1] * elastic_valid
                    + blend_weights[2] * momentum_valid,
                    blend_weights[0] * lgbm_test
                    + blend_weights[1] * elastic_test
                    + blend_weights[2] * momentum_test,
                ),
            }
            for split_name, mask, actual in (
                ("validation", valid_mask, y_valid.to_numpy(dtype=float)),
                ("test", test_mask, y_test.to_numpy(dtype=float)),
            ):
                for model_name, predictions in prediction_sets.items():
                    prediction = predictions[0 if split_name == "validation" else 1]
                    metrics, _, temporal = evaluate_predictions(panel.loc[mask], actual, prediction)
                    metric_rows.append(
                        {
                            "fold": split["fold"],
                            "split": split_name,
                            "target": target,
                            "model": model_name,
                            "lgbm_weight": blend_weights[0] if model_name == "blend" else np.nan,
                            "elastic_net_weight": blend_weights[1] if model_name == "blend" else np.nan,
                            "momentum_weight": blend_weights[2] if model_name == "blend" else np.nan,
                            **metrics,
                        }
                    )
                    for family, group in temporal.groupby("sector_family"):
                        family_rows.append(
                            {
                                "fold": split["fold"],
                                "split": split_name,
                                "model": model_name,
                                "sector_family": family,
                                "temporal_rank_ic": float(group["temporal_rank_ic"].mean()),
                                "codes": int(len(group)),
                            }
                        )
                    pred_frame = panel.loc[mask, ["time", "htsc_code", "sector_family", target]].copy()
                    pred_frame["prediction"] = np.clip(prediction, 0.0, 1.0)
                    pred_frame.to_parquet(
                        report_root / f"predictions_{split['fold']}_{split_name}_{model_name}.parquet",
                        index=False,
                    )
            weight_rows.append(
                {
                    "fold": split["fold"],
                    "lgbm_weight": blend_weights[0],
                    "elastic_net_weight": blend_weights[1],
                    "momentum_weight": blend_weights[2],
                    "validation_rank_ic": validation_ic,
                }
            )
            model_dir = model_root / split["fold"]
            model_dir.mkdir(parents=True, exist_ok=True)
            booster_path = model_dir / "lightgbm_model.txt"
            lgbm_model.booster_.save_model(str(booster_path))
            elastic_path = model_dir / "elastic_net.joblib"
            joblib.dump(elastic_model, elastic_path)
            config_path = model_dir / "blend_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "target": target,
                        "features": features,
                        "lgbm_weight": blend_weights[0],
                        "elastic_net_weight": blend_weights[1],
                        "momentum_weight": blend_weights[2],
                        "validation_rank_ic": validation_ic,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            mlflow.log_params(
                {
                    "target": target,
                    "fold": split["fold"],
                    "feature_count": len(features),
                    "train_rows_used": int(len(train_indices)),
                    "validation_rows": int(valid_mask.sum()),
                    "test_rows": int(test_mask.sum()),
                    "purge_bars": PURGE_BARS,
                    "weight_step": weight_step,
                    "lgbm_weight": blend_weights[0],
                    "elastic_net_weight": blend_weights[1],
                    "momentum_weight": blend_weights[2],
                    "lgbm_best_iteration": int(lgbm_model.best_iteration_),
                }
            )
            blend_metrics = [row for row in metric_rows if row["fold"] == split["fold"] and row["split"] == "test" and row["model"] == "blend"][0]
            mlflow.log_metrics(
                {
                    f"{key}_test": float(value)
                    for key, value in blend_metrics.items()
                    if key in {"mae", "rmse", "cross_sectional_rank_ic", "cross_sectional_icir", "top10_lift", "temporal_rank_ic"}
                    and np.isfinite(value)
                }
            )
            mlflow.log_text("\n".join(features), "feature_columns.txt")
            mlflow.log_artifact(str(booster_path), artifact_path="lightgbm_booster")
            mlflow.log_artifact(str(elastic_path), artifact_path="elastic_net")
            mlflow.log_artifact(str(config_path), artifact_path="blend_config")
            mlflow.lightgbm.log_model(lgbm_model, name="lightgbm_model")
            # 本地模型目录是受控环境；MLflow 3 的 skops 默认序列化会拒绝 numpy.dtype，
            # 这里显式使用 pickle，并同时保留上面的 joblib artifact。
            mlflow.sklearn.log_model(
                elastic_model,
                name="elastic_net_model",
                serialization_format="pickle",
            )
            mlflow.set_tag("run_id_local", run.info.run_id)
        manifest.append(
            {
                key: value
                for key, value in split.items()
                if key not in {"train", "validation", "test"}
            }
            | {"run_id": run.info.run_id}
        )

    metrics_frame = pd.DataFrame(metric_rows)
    family_frame = pd.DataFrame(family_rows)
    weights_frame = pd.DataFrame(weight_rows)
    metrics_frame.to_csv(report_root / "metrics.csv", index=False, encoding="utf-8-sig")
    family_frame.to_csv(report_root / "family_metrics.csv", index=False, encoding="utf-8-sig")
    weights_frame.to_csv(report_root / "blend_weights.csv", index=False, encoding="utf-8-sig")
    test_frame = metrics_frame[metrics_frame["split"] == "test"]
    summary = (
        test_frame.groupby("model")[["cross_sectional_rank_ic", "cross_sectional_icir", "top10_lift", "temporal_rank_ic", "mae"]]
        .mean()
        .reset_index()
    )
    summary.to_csv(report_root / "test_summary.csv", index=False, encoding="utf-8-sig")
    summary_index = summary.set_index("model")
    blend = summary_index.loc["blend"]
    momentum = summary_index.loc["momentum"]
    elastic = summary_index.loc["elastic_net"]
    lgbm = summary_index.loc["lightgbm"]
    pipeline_passed = bool(
        test_frame.loc[test_frame["model"] == "blend", "cross_sectional_rank_ic"].gt(0).all()
        and test_frame.loc[test_frame["model"] == "blend", "top10_lift"].gt(1).all()
    )
    report = {
        "target": target,
        "test_years": list(test_years),
        "feature_count": len(features),
        "features": features,
        "folds": manifest,
        "selected_weights": weight_rows,
        "test_summary": summary.to_dict(orient="records"),
        "comparison_to_baselines": {
            "blend_minus_momentum_rank_ic": float(blend["cross_sectional_rank_ic"] - momentum["cross_sectional_rank_ic"]),
            "blend_minus_elastic_net_rank_ic": float(blend["cross_sectional_rank_ic"] - elastic["cross_sectional_rank_ic"]),
            "blend_minus_lightgbm_rank_ic": float(blend["cross_sectional_rank_ic"] - lgbm["cross_sectional_rank_ic"]),
        },
        "pipeline_passed": pipeline_passed,
        "passed": pipeline_passed,
    }
    (report_root / "blend_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(summary.to_string(index=False))
    print(weights_frame.to_string(index=False))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="运行板块波峰 LightGBM / ElasticNet / 动量混合实验")
    parser.add_argument("--target", dest="target_key", choices=sorted(TARGETS), default="peak")
    parser.add_argument("--panel-path", type=Path, default=DEFAULT_PANEL_PATH)
    parser.add_argument("--model-root", type=Path, default=None)
    parser.add_argument("--tracking-root", type=Path, default=DEFAULT_TRACKING_ROOT)
    parser.add_argument("--report-root", type=Path, default=None)
    parser.add_argument("--max-train-rows", type=int, default=350_000)
    parser.add_argument("--weight-step", type=float, default=0.1)
    parser.add_argument("--test-years", default="2023,2024,2025")
    parser.add_argument("--experiment-name", default=None)
    args = parser.parse_args()
    args.test_years = tuple(int(value.strip()) for value in args.test_years.split(",") if value.strip())
    run_blend(**vars(args))


if __name__ == "__main__":
    main()
