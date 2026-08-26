"""训练四个长期可用非技术板块因子组的三周期V2变化模型。"""

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


DEFAULT_GROUP_PATH = Path(r"D:\database\sector_peak_valley_ml\factor_groups_v1")
DEFAULT_TARGET_PATH = Path(r"D:\database\sector_peak_valley_ml\targets_v1\v2_change_targets.parquet")
DEFAULT_OUTPUT_PATH = Path("outputs/sector_peak_valley_ml/stage_s_core_group_models")
DEFAULT_MODEL_PATH = Path(r"D:\database\sector_peak_valley_ml\models\core_groups_v1")

GROUPS = (
    "sideways_volatility",
    "relative_strength",
    "constituent_breadth",
    "leader_diffusion",
)
KEYS = ["htsc_code", "time"]
FAMILY = "sector_family"
TARGETS = {
    "delta_peak_ultra_short": 43,
    "delta_valley_ultra_short": 43,
    "delta_peak_5d": 45,
    "delta_valley_5d": 45,
    "delta_peak_20d": 60,
    "delta_valley_20d": 60,
}
DEV_START = pd.Timestamp("2016-01-01")
TEST_START = pd.Timestamp("2023-01-01")
OOF_YEARS = (2019, 2020, 2021, 2022)
SEED = 20260820


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def purge_train_end(dates: pd.DatetimeIndex, boundary: pd.Timestamp, purge: int) -> pd.Timestamp:
    prior = dates[dates < boundary]
    if len(prior) <= purge:
        raise ValueError(f"交易日不足以隔离{purge}日")
    return pd.Timestamp(prior[-purge - 1])


def build_model(seed: int, n_jobs: int) -> LGBMRegressor:
    return LGBMRegressor(
        objective="huber", n_estimators=180, learning_rate=0.04,
        num_leaves=31, max_depth=7, min_child_samples=200,
        subsample=0.85, subsample_freq=1, colsample_bytree=0.85,
        reg_alpha=0.10, reg_lambda=1.50, max_bin=127,
        random_state=seed, n_jobs=n_jobs, verbosity=-1,
        deterministic=True, force_col_wise=True,
    )


def load_group_frame(group_path: Path, target_path: Path, group_id: str) -> tuple[pd.DataFrame, list[str]]:
    group = pd.read_parquet(group_path / f"{group_id}.parquet")
    targets = pd.read_parquet(target_path, columns=[*KEYS, *TARGETS])
    required = {"htsc_code", "time", FAMILY}
    missing = required.difference(group.columns)
    if missing:
        raise ValueError(f"{group_id}缺少字段: {sorted(missing)}")
    for frame in (group, targets):
        frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
        frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
        if frame.duplicated(KEYS).any():
            raise ValueError(f"{group_id}存在重复主键")
    features = [c for c in group.columns if c not in {*KEYS, FAMILY}]
    if not features:
        raise ValueError(f"{group_id}没有因子")
    frame = group.merge(targets, on=KEYS, how="inner", validate="one_to_one")
    for col in [*features, *TARGETS]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame.sort_values(["time", "htsc_code"]).reset_index(drop=True), features


def daily_rank_ic(frame: pd.DataFrame, target: str, prediction: str) -> tuple[float, int]:
    values = []
    for _, block in frame.groupby("time", sort=True):
        valid = block[[target, prediction]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(valid) >= 20 and valid.nunique().min() >= 2:
            values.append(valid[target].corr(valid[prediction], method="spearman"))
    return (float(np.mean(values)) if values else np.nan, len(values))


def fit_predict(frame, features, target, train_mask, predict_mask, seed, n_jobs):
    finite = np.isfinite(frame[target].to_numpy(dtype=float))
    train = train_mask & finite
    if train.sum() < 1000:
        raise RuntimeError(f"{target}训练样本不足: {int(train.sum())}")
    model = build_model(seed, n_jobs)
    model.fit(frame.loc[train, features], frame.loc[train, target])
    return model, model.predict(frame.loc[predict_mask, features]), int(train.sum())


def train_core_groups(*, group_path=DEFAULT_GROUP_PATH, target_path=DEFAULT_TARGET_PATH,
                       output_path=DEFAULT_OUTPUT_PATH, model_path=DEFAULT_MODEL_PATH,
                       n_jobs=8):
    output_path.mkdir(parents=True, exist_ok=True)
    prediction_path = output_path / "predictions"
    prediction_path.mkdir(parents=True, exist_ok=True)
    model_path.mkdir(parents=True, exist_ok=True)
    metrics, folds, details = [], [], []
    for gi, group_id in enumerate(GROUPS, 1):
        print(f"[核心组 {gi}/{len(GROUPS)}] {group_id}")
        frame, features = load_group_frame(group_path, target_path, group_id)
        dates = pd.DatetimeIndex(frame.time.unique()).sort_values()
        oof_mask = frame.time.dt.year.isin(OOF_YEARS)
        test_mask = frame.time >= TEST_START
        oof = frame.loc[oof_mask, [*KEYS, FAMILY, *TARGETS]].copy()
        test = frame.loc[test_mask, [*KEYS, FAMILY, *TARGETS]].copy()
        oof_predictions = oof[[*KEYS, FAMILY, *TARGETS]].copy()
        test_predictions = test[[*KEYS, FAMILY, *TARGETS]].copy()
        group_model_path = model_path / group_id
        group_model_path.mkdir(parents=True, exist_ok=True)
        target_details = []
        for ti, (target, purge) in enumerate(TARGETS.items(), 1):
            pred_col = f"pred_{target}"
            oof_predictions[pred_col] = np.nan
            for year in OOF_YEARS:
                validation_dates = dates[dates.year == year]
                if not len(validation_dates):
                    continue
                validation_start = pd.Timestamp(validation_dates[0])
                train_end = purge_train_end(dates, validation_start, purge)
                train_mask = ((frame.time >= DEV_START) & (frame.time <= train_end)).to_numpy()
                valid_mask = ((frame.time >= validation_start) & (frame.time <= validation_dates[-1])).to_numpy()
                _, prediction, train_rows = fit_predict(
                    frame, features, target, train_mask, valid_mask,
                    SEED + gi * 1000 + ti * 10 + year, n_jobs
                )
                keys = pd.MultiIndex.from_frame(frame.loc[valid_mask, KEYS])
                positions = pd.MultiIndex.from_frame(oof_predictions[KEYS]).get_indexer(keys)
                oof_predictions.iloc[positions, oof_predictions.columns.get_loc(pred_col)] = prediction
                folds.append({"group_id": group_id, "target": target, "year": year,
                              "purge_bars": purge, "train_end": train_end.strftime("%Y-%m-%d"),
                              "train_rows": train_rows, "validation_rows": int(valid_mask.sum())})
            final_train_end = purge_train_end(dates, TEST_START, purge)
            final_train = ((frame.time >= DEV_START) & (frame.time <= final_train_end)).to_numpy()
            final_model, test_prediction, train_rows = fit_predict(
                frame, features, target, final_train, test_mask.to_numpy(),
                SEED + gi * 1000 + ti, n_jobs
            )
            test_predictions[pred_col] = test_prediction
            model_file = group_model_path / f"{target}.txt"
            final_model.booster_.save_model(str(model_file))
            for sample, values in (("oof", oof_predictions), ("test", test_predictions)):
                valid = values.dropna(subset=[target, pred_col])
                ic, days = daily_rank_ic(valid, target, pred_col)
                metrics.append({"group_id": group_id, "sample": sample, "target": target,
                                "rank_ic": ic, "valid_days": days, "rows": len(valid)})
            target_details.append({"target": target, "purge_bars": purge,
                                   "final_train_end": final_train_end.strftime("%Y-%m-%d"),
                                   "train_rows": train_rows, "model_path": str(model_file),
                                   "model_sha256": sha256_file(model_file)})
        oof_file = prediction_path / f"{group_id}_oof.parquet"
        test_file = prediction_path / f"{group_id}_test.parquet"
        pl.from_pandas(oof_predictions, include_index=False).write_parquet(oof_file, compression="zstd")
        pl.from_pandas(test_predictions, include_index=False).write_parquet(test_file, compression="zstd")
        details.append({"group_id": group_id, "features": features,
                        "source_sha256": sha256_file(group_path / f"{group_id}.parquet"),
                        "oof_sha256": sha256_file(oof_file), "test_sha256": sha256_file(test_file),
                        "targets": target_details})
    pd.DataFrame(metrics).to_csv(output_path / "core_group_prediction_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(folds).to_csv(output_path / "core_group_training_folds.csv", index=False, encoding="utf-8-sig")
    manifest = {"version": "v1", "groups": list(GROUPS), "targets": list(TARGETS),
                "development": "2016-01-01 <= time < 2023-01-01", "oof_years": list(OOF_YEARS),
                "test": "time >= 2023-01-01", "models": len(GROUPS) * len(TARGETS),
                "seed": SEED, "details": details, "target_sha256": sha256_file(target_path)}
    (output_path / "core_group_model_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"models": manifest["models"], "groups": manifest["groups"]}, ensure_ascii=False, indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser(description="训练四个长期板块因子组")
    parser.add_argument("--group-path", type=Path, default=DEFAULT_GROUP_PATH)
    parser.add_argument("--target-path", type=Path, default=DEFAULT_TARGET_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--n-jobs", type=int, default=8)
    args = parser.parse_args()
    train_core_groups(**vars(args))


if __name__ == "__main__":
    main()
