"""热点舆情组短历史V2变化模型：前半段训练，后半段封存测试。"""

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


GROUP_PATH = Path(r"D:\database\sector_peak_valley_ml\factor_groups_v1\hot_sentiment.parquet")
TARGET_PATH = Path(r"D:\database\sector_peak_valley_ml\targets_v1\v2_change_targets.parquet")
OUTPUT_PATH = Path("outputs/sector_peak_valley_ml/stage_u_hot_group_model")
MODEL_PATH = Path(r"D:\database\sector_peak_valley_ml\models\hot_group_v1")
KEYS = ["htsc_code", "time"]
FAMILY = "sector_family"
TARGETS = {"delta_peak_ultra_short": 43, "delta_valley_ultra_short": 43,
           "delta_peak_5d": 45, "delta_valley_5d": 45,
           "delta_peak_20d": 60, "delta_valley_20d": 60}
SEED = 20260820


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_model(seed: int, n_jobs: int) -> LGBMRegressor:
    return LGBMRegressor(objective="huber", n_estimators=180, learning_rate=0.04,
                         num_leaves=31, max_depth=7, min_child_samples=100,
                         subsample=0.85, subsample_freq=1, colsample_bytree=0.85,
                         reg_alpha=0.10, reg_lambda=1.50, max_bin=127,
                         random_state=seed, n_jobs=n_jobs, verbosity=-1,
                         deterministic=True, force_col_wise=True)


def purge_train_end(dates: pd.DatetimeIndex, boundary: pd.Timestamp, purge: int) -> pd.Timestamp:
    prior = dates[dates < boundary]
    if len(prior) <= purge:
        raise ValueError(f"热点训练期不足以隔离{purge}日")
    return pd.Timestamp(prior[-purge - 1])


def daily_ic(frame: pd.DataFrame, target: str, prediction: str) -> tuple[float, int]:
    values = []
    for _, block in frame.groupby("time", sort=True):
        valid = block[[target, prediction]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(valid) >= 20 and valid.nunique().min() >= 2:
            values.append(valid[target].corr(valid[prediction], method="spearman"))
    return (float(np.mean(values)) if values else np.nan, len(values))


def run(*, group_path=GROUP_PATH, target_path=TARGET_PATH, output_path=OUTPUT_PATH, model_path=MODEL_PATH, n_jobs=8):
    group = pd.read_parquet(group_path)
    targets = pd.read_parquet(target_path, columns=[*KEYS, *TARGETS])
    for frame in (group, targets):
        frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
        frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
        if frame.duplicated(KEYS).any(): raise ValueError("热点输入存在重复主键")
    features = [c for c in group.columns if c not in {*KEYS, FAMILY}]
    frame = group.merge(targets, on=KEYS, how="inner", validate="one_to_one")
    for c in [*features, *TARGETS]: frame[c] = pd.to_numeric(frame[c], errors="coerce")
    # 以真实热点排名是否存在作为样本资格。hot_streak_days 可能因递推
    # 在首个排名日提前出现，不能用它把无舆情日期纳入训练/测试边界。
    valid_hot = frame["sentiment_valid_count"].fillna(0).gt(0)
    valid_dates = pd.DatetimeIndex(frame.loc[valid_hot, "time"].drop_duplicates()).sort_values()
    if len(valid_dates) < 2: raise ValueError("热点组没有足够有效日期")
    # DatetimeIndex 使用位置索引；不能调用 Series 专用的 .iloc。
    split_date = pd.Timestamp(valid_dates[len(valid_dates) // 2])
    train_dates = valid_dates[valid_dates < split_date]
    test_dates = valid_dates[valid_dates >= split_date]
    output_path.mkdir(parents=True, exist_ok=True); model_path.mkdir(parents=True, exist_ok=True)
    train_output = frame.loc[frame.time.isin(train_dates), [*KEYS, FAMILY, *TARGETS]].copy()
    test_output = frame.loc[frame.time.isin(test_dates), [*KEYS, FAMILY, *TARGETS]].copy()
    metrics=[]; details=[]
    for i,(target,purge) in enumerate(TARGETS.items(),1):
        train_end=purge_train_end(valid_dates, split_date, purge)
        train_mask=(frame.time<=train_end)&valid_hot&frame[target].notna()
        test_mask=frame.time.isin(test_dates)&frame[target].notna()
        if train_mask.sum()<1000: raise RuntimeError(f"{target}热点训练样本不足")
        model=build_model(SEED+i,n_jobs); model.fit(frame.loc[train_mask,features],frame.loc[train_mask,target])
        pred_col=f"pred_{target}"
        train_output[pred_col]=np.nan; test_output[pred_col]=np.nan
        train_rows=frame.loc[frame.time.isin(train_dates) & valid_hot,KEYS]
        test_rows=frame.loc[frame.time.isin(test_dates) & valid_hot,KEYS]
        train_positions=pd.MultiIndex.from_frame(train_output[KEYS]).get_indexer(pd.MultiIndex.from_frame(train_rows))
        test_positions=pd.MultiIndex.from_frame(test_output[KEYS]).get_indexer(pd.MultiIndex.from_frame(test_rows))
        train_output.iloc[train_positions,train_output.columns.get_loc(pred_col)]=model.predict(frame.loc[frame.time.isin(train_dates) & valid_hot,features])
        test_output.iloc[test_positions,test_output.columns.get_loc(pred_col)]=model.predict(frame.loc[frame.time.isin(test_dates) & valid_hot,features])
        model_file=model_path/f"{target}.txt"; model.booster_.save_model(str(model_file))
        for sample,values in (("train",train_output),("test",test_output)):
            ic,days=daily_ic(values,target,pred_col); metrics.append({"sample":sample,"target":target,"rank_ic":ic,"valid_days":days,"rows":len(values)})
        details.append({"target":target,"purge_bars":purge,"split_date":split_date.strftime("%Y-%m-%d"),"train_end":train_end.strftime("%Y-%m-%d"),"train_rows":int(train_mask.sum()),"model_path":str(model_file),"model_sha256":sha256_file(model_file)})
    train_file=output_path/'hot_train_predictions.parquet'; test_file=output_path/'hot_test_predictions.parquet'
    pl.from_pandas(train_output,include_index=False).write_parquet(train_file,compression='zstd'); pl.from_pandas(test_output,include_index=False).write_parquet(test_file,compression='zstd')
    pd.DataFrame(metrics).to_csv(output_path/'hot_prediction_metrics.csv',index=False,encoding='utf-8-sig')
    manifest={"version":"v2_rank_direction_and_valid_dates","split_date":split_date.strftime('%Y-%m-%d'),"train_start":valid_dates.min().strftime('%Y-%m-%d'),"test_start":test_dates.min().strftime('%Y-%m-%d'),"features":features,"targets":list(TARGETS),"details":details,"validity_policy":"sentiment_valid_count > 0; rows without an observed history_rank remain NaN predictions","rank_policy":"history_rank=1 is most popular; popularity_strength is higher for lower rank","rank_change_policy":"prior_rank-current_rank is positive when popularity improves; includes 1/3/5-observation short-term changes","output_sha256":{"train":sha256_file(train_file),"test":sha256_file(test_file)}}
    (output_path/'hot_group_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2)); return manifest


def main():
    parser=argparse.ArgumentParser(description='训练热点舆情短历史V2模型')
    parser.add_argument('--group-path',type=Path,default=GROUP_PATH); parser.add_argument('--target-path',type=Path,default=TARGET_PATH); parser.add_argument('--output-path',type=Path,default=OUTPUT_PATH); parser.add_argument('--model-path',type=Path,default=MODEL_PATH); parser.add_argument('--n-jobs',type=int,default=8)
    run(**vars(parser.parse_args()))


if __name__=='__main__': main()
