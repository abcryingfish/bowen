"""板块峰谷监督学习基线与滚动时间外评价。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler


DEFAULT_PANEL_PATH = Path(r"D:\database\sector_peak_valley_ml\panel\panel.parquet")
DEFAULT_OUTPUT_PATH = Path("outputs/sector_peak_valley_ml/stage_c_models")
TARGETS = ("peak_strength_ex_post", "valley_strength_ex_post")
ID_COLUMNS = {
    "htsc_code",
    "time",
    "sector_family",
    "bars_to_end",
    *TARGETS,
}
PURGE_BARS = 40


def make_rolling_splits(
    frame: pd.DataFrame,
    *,
    test_years: tuple[int, ...] = (2023, 2024, 2025),
    purge_bars: int = PURGE_BARS,
) -> list[dict[str, np.ndarray | str]]:
    """生成扩展训练窗；验证年和测试年前均按交易日 purge。"""

    dates = pd.DatetimeIndex(pd.to_datetime(frame["time"]).dt.floor("D").unique()).sort_values()
    result = []
    for test_year in test_years:
        validation_year = test_year - 1
        val_dates = dates[dates.year == validation_year]
        test_dates = dates[dates.year == test_year]
        if len(val_dates) <= purge_bars or len(test_dates) == 0:
            continue
        validation_start = val_dates[purge_bars]
        test_start = test_dates[0]
        pre_validation = dates[dates < val_dates[0]]
        if len(pre_validation) <= purge_bars:
            continue
        train_end = pre_validation[-purge_bars - 1]
        pre_test_validation = val_dates[val_dates < test_start]
        validation_end = pre_test_validation[-purge_bars - 1]
        time = pd.to_datetime(frame["time"])
        train_mask = (time <= train_end).to_numpy()
        validation_mask = ((time >= validation_start) & (time <= validation_end)).to_numpy()
        test_mask = (time.dt.year == test_year).to_numpy()
        result.append(
            {
                "fold": f"test_{test_year}",
                "train": train_mask,
                "validation": validation_mask,
                "test": test_mask,
                "train_end": train_end.strftime("%Y-%m-%d"),
                "validation_start": validation_start.strftime("%Y-%m-%d"),
                "validation_end": validation_end.strftime("%Y-%m-%d"),
                "test_start": test_dates[0].strftime("%Y-%m-%d"),
                "test_end": test_dates[-1].strftime("%Y-%m-%d"),
            }
        )
    return result


def _spearman(left: pd.Series, right: pd.Series, minimum: int) -> float:
    valid = pd.DataFrame({"left": left, "right": right}).replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    if len(valid) < minimum or valid["left"].nunique() < 2 or valid["right"].nunique() < 2:
        return float("nan")
    return float(valid["left"].corr(valid["right"], method="spearman"))


def _correlation(left: pd.Series, right: pd.Series, method: str) -> float:
    valid = pd.DataFrame({"left": left, "right": right}).replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    if len(valid) < 2 or valid["left"].nunique() < 2 or valid["right"].nunique() < 2:
        return float("nan")
    return float(valid["left"].corr(valid["right"], method=method))


def evaluate_predictions(
    metadata: pd.DataFrame,
    actual: np.ndarray,
    predicted: np.ndarray,
) -> tuple[dict[str, float], pd.DataFrame, pd.DataFrame]:
    """计算总体、日度横截面和单板块时序评价。"""

    data = metadata[["time", "htsc_code", "sector_family"]].copy()
    data["actual"] = np.asarray(actual, dtype=float)
    data["predicted"] = np.clip(np.asarray(predicted, dtype=float), 0.0, 1.0)
    daily_rows = []
    for date, group in data.groupby("time", sort=True):
        ic = _spearman(group["predicted"], group["actual"], minimum=20)
        if np.isnan(ic):
            continue
        pred_cut = group["predicted"].quantile(0.90)
        actual_cut = group["actual"].quantile(0.90)
        pred_top = group["predicted"] >= pred_cut
        actual_top = group["actual"] >= actual_cut
        precision = float((pred_top & actual_top).sum() / max(int(pred_top.sum()), 1))
        daily_rows.append(
            {
                "time": date,
                "rank_ic": ic,
                "top10_precision": precision,
                "top10_lift": precision / 0.10,
                "n": len(group),
            }
        )
    daily = pd.DataFrame(
        daily_rows,
        columns=["time", "rank_ic", "top10_precision", "top10_lift", "n"],
    )
    temporal_rows = []
    for code, group in data.groupby("htsc_code", sort=True):
        ic = _spearman(group["predicted"], group["actual"], minimum=60)
        if not np.isnan(ic):
            temporal_rows.append(
                {
                    "htsc_code": code,
                    "sector_family": str(code)[:3],
                    "temporal_rank_ic": ic,
                    "n": len(group),
                }
            )
    temporal = pd.DataFrame(
        temporal_rows,
        columns=["htsc_code", "sector_family", "temporal_rank_ic", "n"],
    )
    std = daily["rank_ic"].std() if len(daily) else np.nan
    metrics = {
        "rows": int(len(data)),
        "codes": int(data["htsc_code"].nunique()),
        "mae": float(mean_absolute_error(data["actual"], data["predicted"])),
        "rmse": float(mean_squared_error(data["actual"], data["predicted"]) ** 0.5),
        "pearson": _correlation(data["actual"], data["predicted"], "pearson"),
        "pooled_spearman": _correlation(data["actual"], data["predicted"], "spearman"),
        "cross_sectional_rank_ic": float(daily["rank_ic"].mean()) if len(daily) else float("nan"),
        "cross_sectional_icir": float(daily["rank_ic"].mean() / std) if std else float("nan"),
        "cross_sectional_positive_rate": float((daily["rank_ic"] > 0).mean()) if len(daily) else float("nan"),
        "top10_precision": float(daily["top10_precision"].mean()) if len(daily) else float("nan"),
        "top10_lift": float(daily["top10_lift"].mean()) if len(daily) else float("nan"),
        "temporal_rank_ic": float(temporal["temporal_rank_ic"].mean()) if len(temporal) else float("nan"),
        "temporal_positive_rate": float((temporal["temporal_rank_ic"] > 0).mean()) if len(temporal) else float("nan"),
    }
    return metrics, daily, temporal


def _sample_training_indices(mask: np.ndarray, maximum: int, seed: int) -> np.ndarray:
    indices = np.flatnonzero(mask)
    if len(indices) <= maximum:
        return indices
    rng = np.random.default_rng(seed)
    return np.sort(rng.choice(indices, size=maximum, replace=False))


def build_models(seed: int = 20260813) -> dict[str, object]:
    return {
        "elastic_net": Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
                ("scaler", RobustScaler(quantile_range=(10, 90))),
                (
                    "model",
                    ElasticNet(alpha=0.001, l1_ratio=0.15, max_iter=3000, random_state=seed),
                ),
            ]
        ),
        "hist_gradient_boosting": HistGradientBoostingRegressor(
            loss="squared_error",
            learning_rate=0.05,
            max_iter=160,
            max_leaf_nodes=31,
            min_samples_leaf=80,
            l2_regularization=1.0,
            early_stopping=False,
            random_state=seed,
        ),
    }


def baseline_predictions(frame: pd.DataFrame, target: str) -> np.ndarray:
    raw = pd.to_numeric(frame["mkt_momentum_5d"], errors="coerce")
    rank = raw.groupby(frame["time"]).rank(pct=True)
    if target.startswith("valley"):
        rank = 1.0 - rank
    return rank.fillna(0.5).to_numpy(dtype=float)


def select_blend_weight(
    metadata: pd.DataFrame,
    actual: np.ndarray,
    model_prediction: np.ndarray,
    baseline_prediction: np.ndarray,
) -> tuple[float, float]:
    """只在验证集选择模型权重，目标为日度横截面 Rank IC。"""

    best_weight = 0.0
    best_ic = -np.inf
    for weight in np.linspace(0.0, 1.0, 11):
        blended = weight * model_prediction + (1.0 - weight) * baseline_prediction
        metrics, _, _ = evaluate_predictions(metadata, actual, blended)
        score = metrics["cross_sectional_rank_ic"]
        if np.isfinite(score) and score > best_ic:
            best_weight = float(weight)
            best_ic = float(score)
    return best_weight, best_ic


def run_models(
    *,
    panel_path: Path,
    output_path: Path,
    max_train_rows: int = 350_000,
    seed: int = 20260813,
) -> dict:
    panel = pd.read_parquet(panel_path)
    panel["time"] = pd.to_datetime(panel["time"]).dt.floor("D")
    features = [column for column in panel.columns if column not in ID_COLUMNS]
    forbidden = [
        feature
        for feature in features
        if any(token in feature.lower() for token in ("label", "未来", "事后", "peak_", "valley_"))
    ]
    if forbidden:
        raise ValueError(f"特征中存在疑似未来字段: {forbidden}")
    splits = make_rolling_splits(panel)
    if len(splits) < 3:
        raise RuntimeError("有效滚动时间折少于 3 个")
    output_path.mkdir(parents=True, exist_ok=True)
    metric_rows = []
    group_rows = []
    split_manifest = []
    latest_predictions = []
    for fold_index, split in enumerate(splits):
        train_mask = split["train"]
        validation_mask = split["validation"]
        test_mask = split["test"]
        assert isinstance(train_mask, np.ndarray)
        assert isinstance(validation_mask, np.ndarray)
        assert isinstance(test_mask, np.ndarray)
        train_indices = _sample_training_indices(train_mask, max_train_rows, seed + fold_index)
        split_manifest.append(
            {
                key: value
                for key, value in split.items()
                if key not in {"train", "validation", "test"}
            }
            | {
                "train_rows_full": int(train_mask.sum()),
                "train_rows_used": int(len(train_indices)),
                "validation_rows": int(validation_mask.sum()),
                "test_rows": int(test_mask.sum()),
            }
        )
        x_train = panel.iloc[train_indices][features]
        x_validation = panel.loc[validation_mask, features]
        x_test = panel.loc[test_mask, features]
        for target in TARGETS:
            print(f"[阶段C] {split['fold']} / {target} / baseline")
            baseline_validation = baseline_predictions(panel.loc[validation_mask], target)
            baseline_test = baseline_predictions(panel.loc[test_mask], target)
            for split_name, mask, prediction in (
                ("validation", validation_mask, baseline_validation),
                ("test", test_mask, baseline_test),
            ):
                metrics, daily, temporal = evaluate_predictions(
                    panel.loc[mask], panel.loc[mask, target].to_numpy(), prediction
                )
                metric_rows.append(
                    {"fold": split["fold"], "split": split_name, "target": target, "model": "momentum_5d_baseline", **metrics}
                )
                for family, group in temporal.groupby("sector_family"):
                    group_rows.append(
                        {
                            "fold": split["fold"],
                            "split": split_name,
                            "target": target,
                            "model": "momentum_5d_baseline",
                            "sector_family": family,
                            "temporal_rank_ic": float(group["temporal_rank_ic"].mean()),
                            "codes": int(len(group)),
                        }
                    )

            weights = 1.0 + 4.0 * np.square(panel.iloc[train_indices][target].to_numpy())
            for model_name, model in build_models(seed + fold_index).items():
                print(f"[阶段C] {split['fold']} / {target} / {model_name}，训练={len(train_indices):,}")
                model.fit(x_train, panel.iloc[train_indices][target], **({"model__sample_weight": weights} if model_name == "elastic_net" else {"sample_weight": weights}))
                model_validation = np.clip(model.predict(x_validation), 0.0, 1.0)
                model_test = np.clip(model.predict(x_test), 0.0, 1.0)
                model_predictions = {
                    "validation": model_validation,
                    "test": model_test,
                }
                for split_name, mask in (("validation", validation_mask), ("test", test_mask)):
                    prediction = model_predictions[split_name]
                    metrics, daily, temporal = evaluate_predictions(
                        panel.loc[mask], panel.loc[mask, target].to_numpy(), prediction
                    )
                    metric_rows.append(
                        {"fold": split["fold"], "split": split_name, "target": target, "model": model_name, **metrics}
                    )
                    daily.assign(
                        fold=split["fold"], split=split_name, target=target, model=model_name
                    ).to_csv(
                        output_path / f"daily_{split['fold']}_{split_name}_{target}_{model_name}.csv",
                        index=False,
                        encoding="utf-8-sig",
                    )
                    for family, group in temporal.groupby("sector_family"):
                        group_rows.append(
                            {
                                "fold": split["fold"],
                                "split": split_name,
                                "target": target,
                                "model": model_name,
                                "sector_family": family,
                                "temporal_rank_ic": float(group["temporal_rank_ic"].mean()),
                                "codes": int(len(group)),
                            }
                        )
                    if split["fold"] == "test_2025" and split_name == "test":
                        latest = panel.loc[mask, ["time", "htsc_code", "sector_family", target]].copy()
                        latest["prediction"] = prediction
                        latest["model"] = model_name
                        latest["target"] = target
                        latest_predictions.append(latest)

                blend_weight, validation_blend_ic = select_blend_weight(
                    panel.loc[validation_mask],
                    panel.loc[validation_mask, target].to_numpy(),
                    model_validation,
                    baseline_validation,
                )
                blend_name = f"{model_name}_blend"
                print(
                    f"[阶段C] {split['fold']} / {target} / {blend_name}，"
                    f"验证权重={blend_weight:.1f}，验证IC={validation_blend_ic:.4f}"
                )
                for split_name, mask, model_prediction, baseline_prediction in (
                    ("validation", validation_mask, model_validation, baseline_validation),
                    ("test", test_mask, model_test, baseline_test),
                ):
                    prediction = (
                        blend_weight * model_prediction
                        + (1.0 - blend_weight) * baseline_prediction
                    )
                    metrics, daily, temporal = evaluate_predictions(
                        panel.loc[mask], panel.loc[mask, target].to_numpy(), prediction
                    )
                    metric_rows.append(
                        {
                            "fold": split["fold"],
                            "split": split_name,
                            "target": target,
                            "model": blend_name,
                            "blend_model_weight": blend_weight,
                            **metrics,
                        }
                    )
                    daily.assign(
                        fold=split["fold"], split=split_name, target=target, model=blend_name
                    ).to_csv(
                        output_path / f"daily_{split['fold']}_{split_name}_{target}_{blend_name}.csv",
                        index=False,
                        encoding="utf-8-sig",
                    )
                    for family, group in temporal.groupby("sector_family"):
                        group_rows.append(
                            {
                                "fold": split["fold"],
                                "split": split_name,
                                "target": target,
                                "model": blend_name,
                                "sector_family": family,
                                "temporal_rank_ic": float(group["temporal_rank_ic"].mean()),
                                "codes": int(len(group)),
                            }
                        )
                    if split["fold"] == "test_2025" and split_name == "test":
                        latest = panel.loc[mask, ["time", "htsc_code", "sector_family", target]].copy()
                        latest["prediction"] = prediction
                        latest["model"] = blend_name
                        latest["target"] = target
                        latest_predictions.append(latest)
                model_dir = output_path / "models" / str(split["fold"])
                model_dir.mkdir(parents=True, exist_ok=True)
                joblib.dump(
                    {"model": model, "features": features, "target": target, "split": split_manifest[-1]},
                    model_dir / f"{target}_{model_name}.joblib",
                )

    metrics = pd.DataFrame(metric_rows)
    groups = pd.DataFrame(group_rows)
    metrics.to_csv(output_path / "rolling_metrics.csv", index=False, encoding="utf-8-sig")
    groups.to_csv(output_path / "family_metrics.csv", index=False, encoding="utf-8-sig")
    if latest_predictions:
        pd.concat(latest_predictions, ignore_index=True).to_parquet(
            output_path / "test_2025_predictions.parquet", index=False
        )
    test_metrics = metrics.loc[metrics["split"] == "test"]
    summary = (
        test_metrics.groupby(["target", "model"])[
            ["cross_sectional_rank_ic", "top10_lift", "temporal_rank_ic", "mae"]
        ]
        .mean()
        .reset_index()
    )
    summary.to_csv(output_path / "test_summary.csv", index=False, encoding="utf-8-sig")
    passed_targets = []
    for target in TARGETS:
        target_summary = summary.loc[summary["target"] == target].set_index("model")
        baseline = target_summary.loc["momentum_5d_baseline"]
        learned = target_summary.drop(index="momentum_5d_baseline")
        improved = (
            (learned["cross_sectional_rank_ic"] > baseline["cross_sectional_rank_ic"])
            | (learned["top10_lift"] > baseline["top10_lift"])
        ).any()
        if improved:
            passed_targets.append(target)
    report = {
        "features": features,
        "feature_count": len(features),
        "folds": split_manifest,
        "passed_targets": passed_targets,
        "passed": len(passed_targets) == len(TARGETS),
        "lightgbm_available": False,
        "tree_baseline": "HistGradientBoostingRegressor",
    }
    (output_path / "model_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(summary.to_string(index=False))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="训练板块峰谷监督学习基线")
    parser.add_argument("--panel-path", type=Path, default=DEFAULT_PANEL_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--max-train-rows", type=int, default=350_000)
    args = parser.parse_args()
    run_models(**vars(args))


if __name__ == "__main__":
    main()
