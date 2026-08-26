"""训练市场状态条件化因子组的独立V2变化模型。"""

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


GROUP_PATH = Path(r"D:\database\sector_peak_valley_ml\factor_groups_v1\market_state_conditioned.parquet")
TARGET_PATH = Path(r"D:\database\sector_peak_valley_ml\targets_v1\v2_change_targets.parquet")
OUTPUT_PATH = Path("outputs/sector_peak_valley_ml/stage_y_market_state_group_model")
MODEL_PATH = Path(r"D:\database\sector_peak_valley_ml\models\market_state_group_v1")
KEYS = ["htsc_code", "time"]
FAMILY = "sector_family"
TARGETS = {
    "delta_peak_ultra_short": 43, "delta_valley_ultra_short": 43,
    "delta_peak_5d": 45, "delta_valley_5d": 45,
    "delta_peak_20d": 60, "delta_valley_20d": 60,
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
        raise ValueError(f"市场状态组历史不足以隔离{purge}日")
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


def daily_rank_ic(frame: pd.DataFrame, target: str, prediction: str) -> tuple[float, int]:
    values = []
    for _, block in frame.groupby("time", sort=True):
        valid = block[[target, prediction]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(valid) >= 20 and valid.nunique().min() >= 2:
            values.append(valid[target].corr(valid[prediction], method="spearman"))
    return (float(np.mean(values)) if values else np.nan, len(values))


def run(*, group_path: Path = GROUP_PATH, target_path: Path = TARGET_PATH, output_path: Path = OUTPUT_PATH, model_path: Path = MODEL_PATH, n_jobs: int = 8) -> dict[str, object]:
    group = pd.read_parquet(group_path)
    targets = pd.read_parquet(target_path, columns=[*KEYS, *TARGETS])
    for frame in (group, targets):
        frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
        frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
        if frame.duplicated(KEYS).any():
            raise ValueError("市场状态组输入存在重复主键")
    features = [c for c in group.columns if c not in {*KEYS, FAMILY}]
    if not features:
        raise ValueError("市场状态组没有因子")
    frame = group.merge(targets, on=KEYS, how="inner", validate="one_to_one")
    for column in [*features, *TARGETS]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    dates = pd.DatetimeIndex(frame["time"].unique()).sort_values()
    oof_mask = frame["time"].dt.year.isin(OOF_YEARS)
    test_mask = frame["time"] >= TEST_START
    oof = frame.loc[oof_mask, [*KEYS, FAMILY, *TARGETS]].copy()
    test = frame.loc[test_mask, [*KEYS, FAMILY, *TARGETS]].copy()
    oof_predictions = oof.copy(); test_predictions = test.copy()
    output_path.mkdir(parents=True, exist_ok=True); model_path.mkdir(parents=True, exist_ok=True)
    metrics = []; folds = []; target_reports = []
    for ti, (target, purge) in enumerate(TARGETS.items(), 1):
        prediction = f"pred_{target}"; oof_predictions[prediction] = np.nan
        for year in OOF_YEARS:
            validation_dates = dates[dates.year == year]
            if not len(validation_dates):
                continue
            validation_start = pd.Timestamp(validation_dates[0])
            train_end = purge_train_end(dates, validation_start, purge)
            train_mask = ((frame["time"] >= DEV_START) & (frame["time"] <= train_end) & frame[target].notna())
            valid_mask = ((frame["time"] >= validation_start) & (frame["time"] <= validation_dates[-1])).to_numpy()
            if int(train_mask.sum()) < 1000:
                raise RuntimeError(f"{target}/{year}训练样本不足")
            model = build_model(SEED + ti * 10 + year, n_jobs)
            model.fit(frame.loc[train_mask, features], frame.loc[train_mask, target])
            prediction_values = model.predict(frame.loc[valid_mask, features])
            positions = pd.MultiIndex.from_frame(oof_predictions[KEYS]).get_indexer(pd.MultiIndex.from_frame(frame.loc[valid_mask, KEYS]))
            oof_predictions.iloc[positions, oof_predictions.columns.get_loc(prediction)] = prediction_values
            folds.append({"target": target, "year": year, "purge_bars": purge, "train_end": train_end.strftime("%Y-%m-%d"), "train_rows": int(train_mask.sum()), "validation_rows": int(valid_mask.sum())})
        final_train_end = purge_train_end(dates, TEST_START, purge)
        final_train = ((frame["time"] >= DEV_START) & (frame["time"] <= final_train_end) & frame[target].notna())
        test_features = frame.loc[test_mask, features]
        final_model = build_model(SEED + ti, n_jobs)
        final_model.fit(frame.loc[final_train, features], frame.loc[final_train, target])
        test_predictions[prediction] = final_model.predict(test_features)
        model_file = model_path / f"{target}.txt"; final_model.booster_.save_model(str(model_file))
        for sample, values in (("oof", oof_predictions), ("test", test_predictions)):
            valid = values.dropna(subset=[target, prediction]); ic, days = daily_rank_ic(valid, target, prediction)
            metrics.append({"sample": sample, "target": target, "rank_ic": ic, "valid_days": days, "rows": len(valid)})
        target_reports.append({"target": target, "purge_bars": purge, "final_train_end": final_train_end.strftime("%Y-%m-%d"), "train_rows": int(final_train.sum()), "model_path": str(model_file), "model_sha256": sha256_file(model_file)})
    oof_file = output_path / "market_state_conditioned_oof_predictions.parquet"; test_file = output_path / "market_state_conditioned_test_predictions.parquet"
    pl.from_pandas(oof_predictions, include_index=False).write_parquet(oof_file, compression="zstd")
    pl.from_pandas(test_predictions, include_index=False).write_parquet(test_file, compression="zstd")
    pd.DataFrame(metrics).to_csv(output_path / "market_state_prediction_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(folds).to_csv(output_path / "market_state_training_folds.csv", index=False, encoding="utf-8-sig")
    manifest = {"version": "v1", "group_id": "market_state_conditioned", "features": features, "targets": list(TARGETS), "development": "2016-01-01 <= time < 2023-01-01", "oof_years": list(OOF_YEARS), "test": "time >= 2023-01-01", "details": target_reports, "output_sha256": {"oof": sha256_file(oof_file), "test": sha256_file(test_file)}}
    (output_path / "market_state_group_model_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2)); return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="训练市场状态条件化板块组")
    parser.add_argument("--group-path", type=Path, default=GROUP_PATH); parser.add_argument("--target-path", type=Path, default=TARGET_PATH); parser.add_argument("--output-path", type=Path, default=OUTPUT_PATH); parser.add_argument("--model-path", type=Path, default=MODEL_PATH); parser.add_argument("--n-jobs", type=int, default=8)
    run(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
