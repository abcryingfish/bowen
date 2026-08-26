"""训练18个技术子组对三周期V2峰谷变化的LightGBM模型。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import polars as pl
from lightgbm import LGBMRegressor


DEFAULT_SUBGROUP_PATH = Path(
    r"D:\database\sector_peak_valley_ml\technical_subgroups_v1"
)
DEFAULT_TARGET_PATH = Path(
    r"D:\database\sector_peak_valley_ml\targets_v1\v2_change_targets.parquet"
)
DEFAULT_FACTOR_AUDIT_PATH = Path(
    "outputs/sector_peak_valley_ml/stage_p_technical_subgroup_audit/factor_rank_ic_development.csv"
)
DEFAULT_MODEL_PATH = Path(
    r"D:\database\sector_peak_valley_ml\models\technical_subgroups_v1"
)
DEFAULT_OUTPUT_PATH = Path(
    "outputs/sector_peak_valley_ml/stage_q_technical_subgroup_models"
)

KEYS = ["htsc_code", "time"]
FAMILY_COLUMN = "sector_family"
TARGET_SETTINGS = {
    "delta_peak_ultra_short": {"horizon": "ultra_short", "purge_bars": 43},
    "delta_valley_ultra_short": {"horizon": "ultra_short", "purge_bars": 43},
    "delta_peak_5d": {"horizon": "5d", "purge_bars": 45},
    "delta_valley_5d": {"horizon": "5d", "purge_bars": 45},
    "delta_peak_20d": {"horizon": "20d", "purge_bars": 60},
    "delta_valley_20d": {"horizon": "20d", "purge_bars": 60},
}
DEVELOPMENT_START = pd.Timestamp("2016-01-01")
TEST_START = pd.Timestamp("2023-01-01")
OOF_YEARS = (2019, 2020, 2021, 2022)
RANDOM_SEED = 20260819
GENERATOR_VERSION = "v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_feature_map(factor_audit_path: Path) -> dict[str, list[str]]:
    audit = pd.read_csv(factor_audit_path, encoding="utf-8-sig")
    required = {"indicator", "feature"}
    missing = required.difference(audit.columns)
    if missing:
        raise ValueError(f"开发期因子审计缺少字段: {sorted(missing)}")
    return {
        str(indicator): sorted(group["feature"].astype(str).unique())
        for indicator, group in audit.groupby("indicator", sort=True)
    }


def purge_train_end(
    dates: pd.DatetimeIndex,
    boundary: pd.Timestamp,
    purge_bars: int,
) -> pd.Timestamp:
    prior = dates[dates < boundary]
    if len(prior) <= purge_bars:
        raise ValueError(f"{boundary.date()} 前交易日不足以隔离 {purge_bars} 日")
    return pd.Timestamp(prior[-purge_bars - 1])


def make_oof_splits(
    dates: pd.DatetimeIndex,
    purge_bars: int,
    years: tuple[int, ...] = OOF_YEARS,
) -> list[dict[str, object]]:
    splits = []
    for year in years:
        validation_dates = dates[dates.year == year]
        if not len(validation_dates):
            continue
        validation_start = pd.Timestamp(validation_dates[0])
        splits.append(
            {
                "year": year,
                "train_end": purge_train_end(dates, validation_start, purge_bars),
                "validation_start": validation_start,
                "validation_end": pd.Timestamp(validation_dates[-1]),
            }
        )
    return splits


def build_model(seed: int, n_jobs: int) -> LGBMRegressor:
    return LGBMRegressor(
        objective="huber",
        n_estimators=180,
        learning_rate=0.04,
        num_leaves=31,
        max_depth=7,
        min_child_samples=200,
        subsample=0.85,
        subsample_freq=1,
        colsample_bytree=0.85,
        reg_alpha=0.10,
        reg_lambda=1.50,
        max_bin=127,
        random_state=seed,
        n_jobs=n_jobs,
        verbosity=-1,
        deterministic=True,
        force_col_wise=True,
    )


def daily_rank_ic(
    frame: pd.DataFrame,
    actual_column: str,
    prediction_column: str,
    min_count: int = 20,
) -> tuple[float, int]:
    values = []
    for _, block in frame.groupby("time", sort=True):
        valid = block[[actual_column, prediction_column]].replace(
            [np.inf, -np.inf], np.nan
        ).dropna()
        if len(valid) < min_count or valid.nunique().min() < 2:
            continue
        values.append(
            float(valid[actual_column].corr(valid[prediction_column], method="spearman"))
        )
    return (float(np.mean(values)) if values else np.nan, len(values))


def load_training_frame(
    subgroup_path: Path,
    target_path: Path,
    indicator: str,
    features: list[str],
) -> pd.DataFrame:
    group = pd.read_parquet(
        subgroup_path / f"{indicator}.parquet",
        columns=[*KEYS, FAMILY_COLUMN, *features],
    )
    targets = pd.read_parquet(target_path, columns=[*KEYS, *TARGET_SETTINGS])
    for values in (group, targets):
        values["htsc_code"] = values["htsc_code"].astype(str).str.strip().str.upper()
        values["time"] = pd.to_datetime(values["time"], errors="coerce").dt.floor("D")
        if values.duplicated(KEYS).any():
            raise ValueError(f"{indicator} 训练输入存在重复主键")
    frame = group.merge(targets, on=KEYS, how="inner", validate="one_to_one")
    for column in [*features, *TARGET_SETTINGS]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values(["time", "htsc_code"]).reset_index(drop=True)


def _fit_predict(
    frame: pd.DataFrame,
    features: list[str],
    target: str,
    train_mask: np.ndarray,
    predict_mask: np.ndarray,
    *,
    seed: int,
    n_jobs: int,
) -> tuple[LGBMRegressor, np.ndarray, int]:
    finite_target = np.isfinite(frame[target].to_numpy(dtype=float))
    train = train_mask & finite_target
    if train.sum() < 1000:
        raise RuntimeError(f"{target} 有效训练样本不足: {int(train.sum())}")
    model = build_model(seed, n_jobs)
    model.fit(frame.loc[train, features], frame.loc[train, target])
    prediction = model.predict(frame.loc[predict_mask, features])
    return model, np.asarray(prediction, dtype=float), int(train.sum())


def train_subgroup_models(
    *,
    subgroup_path: Path = DEFAULT_SUBGROUP_PATH,
    target_path: Path = DEFAULT_TARGET_PATH,
    factor_audit_path: Path = DEFAULT_FACTOR_AUDIT_PATH,
    model_path: Path = DEFAULT_MODEL_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    n_jobs: int = 8,
) -> dict[str, object]:
    feature_map = load_feature_map(factor_audit_path)
    model_path.mkdir(parents=True, exist_ok=True)
    prediction_path = output_path / "predictions"
    prediction_path.mkdir(parents=True, exist_ok=True)
    metric_rows = []
    fold_rows = []
    subgroup_reports = []

    for indicator_index, (indicator, features) in enumerate(feature_map.items(), start=1):
        print(f"[子组模型 {indicator_index}/{len(feature_map)}] {indicator}: {len(features)}")
        frame = load_training_frame(
            subgroup_path, target_path, indicator, features
        )
        dates = pd.DatetimeIndex(frame["time"].unique()).sort_values()
        oof_base = frame.loc[
            frame["time"].dt.year.isin(OOF_YEARS), [*KEYS, FAMILY_COLUMN, *TARGET_SETTINGS]
        ].copy()
        test_base = frame.loc[
            frame["time"] >= TEST_START, [*KEYS, FAMILY_COLUMN, *TARGET_SETTINGS]
        ].copy()
        oof_predictions = oof_base[[*KEYS, FAMILY_COLUMN, *TARGET_SETTINGS]].copy()
        test_predictions = test_base[[*KEYS, FAMILY_COLUMN, *TARGET_SETTINGS]].copy()

        indicator_model_path = model_path / indicator
        indicator_model_path.mkdir(parents=True, exist_ok=True)
        target_reports = []
        for target_index, (target, settings) in enumerate(TARGET_SETTINGS.items(), start=1):
            purge_bars = int(settings["purge_bars"])
            prediction_column = f"pred_{target}"
            oof_predictions[prediction_column] = np.nan
            for fold_index, split in enumerate(make_oof_splits(dates, purge_bars)):
                train_mask = (
                    (frame["time"] >= DEVELOPMENT_START)
                    & (frame["time"] <= split["train_end"])
                ).to_numpy()
                validation_mask = (
                    (frame["time"] >= split["validation_start"])
                    & (frame["time"] <= split["validation_end"])
                ).to_numpy()
                _, prediction, train_rows = _fit_predict(
                    frame,
                    features,
                    target,
                    train_mask,
                    validation_mask,
                    seed=RANDOM_SEED + indicator_index * 1000 + target_index * 10 + fold_index,
                    n_jobs=n_jobs,
                )
                validation_keys = frame.loc[validation_mask, KEYS]
                positions = pd.MultiIndex.from_frame(oof_predictions[KEYS]).get_indexer(
                    pd.MultiIndex.from_frame(validation_keys)
                )
                if (positions < 0).any():
                    raise RuntimeError(f"{indicator}/{target} OOF主键无法对齐")
                oof_predictions.iloc[
                    positions, oof_predictions.columns.get_loc(prediction_column)
                ] = prediction
                fold_rows.append(
                    {
                        "indicator": indicator,
                        "target": target,
                        "validation_year": int(split["year"]),
                        "purge_bars": purge_bars,
                        "train_end": split["train_end"].strftime("%Y-%m-%d"),
                        "validation_start": split["validation_start"].strftime("%Y-%m-%d"),
                        "validation_end": split["validation_end"].strftime("%Y-%m-%d"),
                        "train_rows": train_rows,
                        "validation_rows": int(validation_mask.sum()),
                    }
                )

            final_train_end = purge_train_end(dates, TEST_START, purge_bars)
            final_train_mask = (
                (frame["time"] >= DEVELOPMENT_START)
                & (frame["time"] <= final_train_end)
            ).to_numpy()
            test_mask = (frame["time"] >= TEST_START).to_numpy()
            final_model, test_prediction, final_train_rows = _fit_predict(
                frame,
                features,
                target,
                final_train_mask,
                test_mask,
                seed=RANDOM_SEED + indicator_index * 1000 + target_index,
                n_jobs=n_jobs,
            )
            model_file = indicator_model_path / f"{target}.txt"
            final_model.booster_.save_model(str(model_file))
            test_predictions[prediction_column] = test_prediction

            for sample, values in (("oof", oof_predictions), ("test", test_predictions)):
                metric_frame = values.dropna(subset=[target, prediction_column])
                ic, days = daily_rank_ic(metric_frame, target, prediction_column)
                metric_rows.append(
                    {
                        "indicator": indicator,
                        "sample": sample,
                        "target": target,
                        "rank_ic": ic,
                        "valid_days": days,
                        "rows": int(len(metric_frame)),
                    }
                )
            target_reports.append(
                {
                    "target": target,
                    "purge_bars": purge_bars,
                    "final_train_end": final_train_end.strftime("%Y-%m-%d"),
                    "final_train_rows": final_train_rows,
                    "model_path": str(model_file),
                    "model_sha256": sha256_file(model_file),
                }
            )

        oof_file = prediction_path / f"{indicator}_oof.parquet"
        test_file = prediction_path / f"{indicator}_test.parquet"
        pl.from_pandas(oof_predictions, include_index=False).write_parquet(
            oof_file, compression="zstd"
        )
        pl.from_pandas(test_predictions, include_index=False).write_parquet(
            test_file, compression="zstd"
        )
        subgroup_reports.append(
            {
                "indicator": indicator,
                "features": len(features),
                "feature_names": features,
                "source_sha256": sha256_file(subgroup_path / f"{indicator}.parquet"),
                "oof_prediction_sha256": sha256_file(oof_file),
                "test_prediction_sha256": sha256_file(test_file),
                "targets": target_reports,
            }
        )

    metrics = pd.DataFrame(metric_rows)
    folds = pd.DataFrame(fold_rows)
    metrics.to_csv(output_path / "subgroup_prediction_metrics.csv", index=False, encoding="utf-8-sig")
    folds.to_csv(output_path / "training_folds.csv", index=False, encoding="utf-8-sig")
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "model": "LightGBM LGBMRegressor objective=huber",
        "model_params": build_model(RANDOM_SEED, n_jobs).get_params(),
        "development_period": "2016-01-01 <= time < 2023-01-01",
        "oof_validation_years": list(OOF_YEARS),
        "test_period": "time >= 2023-01-01",
        "test_usage": "prediction_and_final_evaluation_only",
        "target_settings": TARGET_SETTINGS,
        "random_seed": RANDOM_SEED,
        "indicators": len(feature_map),
        "features": sum(len(values) for values in feature_map.values()),
        "models": len(feature_map) * len(TARGET_SETTINGS),
        "factor_audit_sha256": sha256_file(factor_audit_path),
        "target_sha256": sha256_file(target_path),
        "subgroup_details": subgroup_reports,
    }
    (output_path / "subgroup_model_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: manifest[key] for key in ("models", "features", "target_settings")}, ensure_ascii=False, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="训练板块纯技术子组V2变化模型")
    parser.add_argument("--subgroup-path", type=Path, default=DEFAULT_SUBGROUP_PATH)
    parser.add_argument("--target-path", type=Path, default=DEFAULT_TARGET_PATH)
    parser.add_argument("--factor-audit-path", type=Path, default=DEFAULT_FACTOR_AUDIT_PATH)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--n-jobs", type=int, default=8)
    args = parser.parse_args()
    train_subgroup_models(**vars(args))


if __name__ == "__main__":
    main()
