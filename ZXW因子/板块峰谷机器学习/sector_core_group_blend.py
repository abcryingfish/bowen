"""合成技术大组与四个长期核心组，评价五组V2组合。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import polars as pl
from sklearn.linear_model import Ridge


TECH_PATH = Path("outputs/sector_peak_valley_ml/stage_r_technical_group_blend")
CORE_PATH = Path("outputs/sector_peak_valley_ml/stage_s_core_group_models/predictions")
MARKET_STATE_PATH = Path("outputs/sector_peak_valley_ml/stage_y_market_state_group_model")
MODEL_PATH = Path(r"D:\database\sector_peak_valley_ml\models\core_blend_v1")
OUTPUT_PATH = Path("outputs/sector_peak_valley_ml/stage_t_core_group_blend")
GROUPS = ("technical", "sideways_volatility", "relative_strength", "constituent_breadth", "leader_diffusion", "market_state_conditioned")
BASE_GROUPS = GROUPS[:-1]
TARGET_GROUP_POLICY = {
    "delta_peak_ultra_short": BASE_GROUPS,
    "delta_valley_ultra_short": GROUPS,
    "delta_peak_5d": BASE_GROUPS,
    "delta_valley_5d": BASE_GROUPS,
    "delta_peak_20d": GROUPS,
    "delta_valley_20d": GROUPS,
}
TARGETS = (
    "delta_peak_ultra_short", "delta_valley_ultra_short",
    "delta_peak_5d", "delta_valley_5d", "delta_peak_20d", "delta_valley_20d",
)
KEYS = ["htsc_code", "time"]
FAMILY = "sector_family"
RIDGE_ALPHA = 1000.0
TEST_START = pd.Timestamp("2023-01-01")
# 技术大组当前从2020年才有有效二层OOF分数，因此顶层严格嵌套OOF
# 从2021年开始；不能用缺失的2019技术分数伪造2020验证。
META_OOF_YEARS = (2021, 2022)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_one(path: Path, group_id: str, sample: str) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    if frame.duplicated(KEYS).any():
        raise ValueError(f"{path}存在重复主键")
    required = {*KEYS, FAMILY, *TARGETS}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{path}缺少字段: {sorted(missing)}")
    result = frame[[*KEYS, FAMILY, *TARGETS]].copy()
    for target in TARGETS:
        source = f"pred_{target}"
        if source not in frame:
            raise ValueError(f"{path}缺少预测列: {source}")
        result[f"score_{group_id}_{target}"] = pd.to_numeric(frame[source], errors="coerce")
    return result


def source_paths(sample: str) -> dict[str, Path]:
    """返回顶层合成实际读取的各组预测文件，供 manifest 固化输入哈希。"""

    suffix = "oof" if sample == "oof" else "test"
    return {
        "technical": TECH_PATH / f"technical_group_{suffix}_predictions.parquet",
        **{
            group: CORE_PATH / f"{group}_{sample}.parquet"
            for group in GROUPS[1:-1]
        },
        "market_state_conditioned": MARKET_STATE_PATH
        / f"market_state_conditioned_{sample}_predictions.parquet",
    }


def load_matrix(sample: str) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    sources = source_paths(sample)
    base = None
    feature_map = {}
    for group in GROUPS:
        current = load_one(sources[group], group, sample)
        if base is None:
            base = current
        else:
            base = base.merge(current, on=[*KEYS, FAMILY, *TARGETS], how="inner", validate="one_to_one")
        feature_map.update({target: feature_map.get(target, []) + [f"score_{group}_{target}"] for target in TARGETS})
    assert base is not None
    return base.sort_values(["time", "htsc_code"]).reset_index(drop=True), feature_map


def rank_group_scores(frame: pd.DataFrame, feature_map: dict[str, list[str]]) -> pd.DataFrame:
    result = frame.copy()
    for columns in feature_map.values():
        for column in columns:
            result[column] = result[column].groupby(result["time"]).rank(method="average", pct=True)
    return result


def safe_ic(frame: pd.DataFrame, target: str, prediction: str) -> tuple[float, int]:
    values = []
    for _, block in frame.groupby("time", sort=True):
        valid = block[[target, prediction]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(valid) >= 20 and valid.nunique().min() >= 2:
            values.append(valid[target].corr(valid[prediction], method="spearman"))
    return (float(np.mean(values)) if values else np.nan, len(values))


def purge_train_end(dates: pd.DatetimeIndex, boundary: pd.Timestamp, purge_bars: int) -> pd.Timestamp:
    """返回边界日前排除 purge_bars 个交易日后的最后训练日。"""
    prior = dates[dates < boundary]
    if len(prior) <= purge_bars:
        raise ValueError(f"第二层Ridge历史不足以隔离{purge_bars}日")
    return pd.Timestamp(prior[-purge_bars - 1])


def evaluate_quintiles(frame: pd.DataFrame, target: str, prediction: str) -> pd.DataFrame:
    rows = []
    for time, block in frame.dropna(subset=[target, prediction]).groupby("time", sort=True):
        if len(block) < 20 or block[prediction].nunique() < 5:
            continue
        q = np.ceil(block[prediction].rank(method="first", pct=True) * 5).astype(int).clip(1, 5)
        payload = pd.DataFrame({"q": q.to_numpy(), "actual": block[target].to_numpy()})
        means = payload.groupby("q").actual.mean().reindex(range(1, 6))
        if means.notna().all():
            for group, value in means.items():
                rows.append({"time": time, "quintile": group, "actual": value})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).groupby("quintile").actual.agg(mean="mean", median="median", valid_days="count").reset_index()


def build_group_selection_audit(
    *,
    oof: pd.DataFrame,
    test: pd.DataFrame,
    target: str,
    active_groups: tuple[str, ...],
    coefficients: np.ndarray,
    purge_bars: int,
) -> pd.DataFrame:
    """保存候选组、固定选择策略和系数，明确不使用测试期自动选组。"""

    rows = []
    coefficient_map = dict(zip(active_groups, np.asarray(coefficients, dtype=float)))
    for group in GROUPS:
        column = f"score_{group}_{target}"
        oof_ic, oof_days = safe_ic(oof, target, column)
        test_ic, test_days = safe_ic(test, target, column)
        rows.append(
            {
                "target": target,
                "group": group,
                "selected": group in active_groups,
                "selection_policy": "fixed_target_group_policy",
                "automatic_test_selection": False,
                "manual_selection_provenance": "not_encoded",
                "oof_rank_ic": oof_ic,
                "oof_valid_days": oof_days,
                "test_rank_ic_report_only": test_ic,
                "test_valid_days": test_days,
                "ridge_coefficient": coefficient_map.get(group),
                "ridge_alpha": RIDGE_ALPHA,
                "purge_bars": purge_bars,
                "test_used_for_selection": False,
            }
        )
    return pd.DataFrame(rows)


def run_blend(*, output_path: Path = OUTPUT_PATH, model_path: Path = MODEL_PATH) -> dict[str, object]:
    oof, feature_map = load_matrix("oof")
    test, test_feature_map = load_matrix("test")
    if feature_map != test_feature_map:
        raise ValueError("OOF与测试组结构不一致")
    oof = rank_group_scores(oof, feature_map)
    test = rank_group_scores(test, feature_map)
    output_path.mkdir(parents=True, exist_ok=True)
    model_path.mkdir(parents=True, exist_ok=True)
    oof_out = oof[[*KEYS, FAMILY, *TARGETS]].copy()
    test_out = test[[*KEYS, FAMILY, *TARGETS]].copy()
    coefficient_rows = []
    target_rows = []
    oof_target_rows = []
    fold_rows = []
    annual_rows = []
    family_rows = []
    quintile_frames = []
    group_selection_audits = []
    oof_dates = pd.DatetimeIndex(oof["time"].unique()).sort_values()
    for target in TARGETS:
        active_groups = TARGET_GROUP_POLICY[target]
        columns = [f"score_{group}_{target}" for group in active_groups]
        prediction = f"pred_{target}"
        oof_out[prediction] = np.nan
        purge_bars = 43 if "ultra_short" in target else 45 if "5d" in target else 60

        # 第二层嵌套 OOF：每个验证年度只能使用更早的合规组分数，
        # 并在验证边界前排除本目标对应的未来标签窗口。
        for year in META_OOF_YEARS:
            validation = oof["time"].dt.year.eq(year)
            if not validation.any():
                continue
            validation_start = pd.Timestamp(oof.loc[validation, "time"].min())
            train_end = purge_train_end(oof_dates, validation_start, purge_bars)
            train = (
                (oof["time"] <= train_end)
                & oof[target].notna()
                & oof[columns].notna().all(axis=1)
            )
            if int(train.sum()) < 1000:
                raise RuntimeError(f"{target}/{year}第二层Ridge训练样本不足")
            fold_model = Ridge(alpha=RIDGE_ALPHA)
            fold_model.fit(oof.loc[train, columns], oof.loc[train, target])
            oof_out.loc[validation, prediction] = fold_model.predict(oof.loc[validation, columns])
            fold_rows.append({
                "target": target,
                "validation_year": year,
                "purge_bars": purge_bars,
                "train_end": train_end.strftime("%Y-%m-%d"),
                "train_rows": int(train.sum()),
                "validation_rows": int(validation.sum()),
            })

        final_train_end = purge_train_end(oof_dates, TEST_START, purge_bars)
        final_train = (
            (oof["time"] <= final_train_end)
            & oof[target].notna()
            & oof[columns].notna().all(axis=1)
        )
        model = Ridge(alpha=RIDGE_ALPHA)
        model.fit(oof.loc[final_train, columns], oof.loc[final_train, target])
        if test[columns].isna().any().any():
            raise ValueError(f"{target}测试期组分存在缺失，不能进行最终预测")
        test_out[prediction] = model.predict(test[columns])
        model_file = model_path / f"{target}.joblib"
        joblib.dump({"model": model, "features": columns, "groups": active_groups,
                     "purge_bars": purge_bars, "final_train_end": final_train_end.strftime("%Y-%m-%d"),
                     "meta_oof_years": META_OOF_YEARS}, model_file)
        for group, value in zip(active_groups, model.coef_):
            coefficient_rows.append({"target": target, "group": group, "coefficient": float(value)})
        group_selection_audits.append(
            build_group_selection_audit(
                oof=oof,
                test=test,
                target=target,
                active_groups=active_groups,
                coefficients=model.coef_,
                purge_bars=purge_bars,
            )
        )
        overall, days = safe_ic(test_out, target, prediction)
        target_rows.append({"target": target, "ic_mean": overall, "valid_days": days})
        oof_overall, oof_days = safe_ic(oof_out, target, prediction)
        oof_target_rows.append({"target": target, "ic_mean": oof_overall, "valid_days": oof_days})
        daily = []
        family_daily = []
        for time, block in test_out.groupby("time", sort=True):
            ic, _ = safe_ic(block, target, prediction)
            if np.isfinite(ic): daily.append({"time": time, "rank_ic": ic})
            for family, family_block in block.groupby(FAMILY):
                fic, _ = safe_ic(family_block, target, prediction)
                if np.isfinite(fic): family_daily.append({"time": time, FAMILY: family, "rank_ic": fic})
        daily_frame = pd.DataFrame(daily)
        if not daily_frame.empty:
            daily_frame["year"] = daily_frame.time.dt.year
            annual_rows.extend([{**row, "target": target} for row in daily_frame.groupby("year").rank_ic.agg(ic_mean="mean", ic_median="median", valid_days="count").reset_index().to_dict("records")])
        family_frame = pd.DataFrame(family_daily)
        if not family_frame.empty:
            family_rows.extend([{**row, "target": target} for row in family_frame.groupby(FAMILY).rank_ic.agg(ic_mean="mean", ic_median="median", valid_days="count").reset_index().to_dict("records")])
        quintile = evaluate_quintiles(test_out, target, prediction)
        if not quintile.empty:
            quintile.insert(0, "target", target)
            quintile_frames.append(quintile)
    output_files = {}
    quintile_table = pd.concat(quintile_frames, ignore_index=True) if quintile_frames else pd.DataFrame()
    group_selection_audit = pd.concat(group_selection_audits, ignore_index=True)
    frames = {
        "core_blend_coefficients.csv": pd.DataFrame(coefficient_rows),
        "core_blend_target_ic_test.csv": pd.DataFrame(target_rows),
        "core_blend_annual_ic_test.csv": pd.DataFrame(annual_rows),
        "core_blend_family_ic_test.csv": pd.DataFrame(family_rows),
        "core_blend_quintile_test.csv": quintile_table,
        "core_blend_oof_target_ic.csv": pd.DataFrame(oof_target_rows),
        "core_blend_nested_oof_folds.csv": pd.DataFrame(fold_rows),
        "core_blend_group_selection_audit.csv": group_selection_audit,
    }
    for filename, frame in frames.items():
        path = output_path / filename
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        output_files[filename] = path
    for name, frame in (("core_blend_oof_predictions.parquet", oof_out), ("core_blend_test_predictions.parquet", test_out)):
        path = output_path / name
        pl.from_pandas(frame, include_index=False).write_parquet(path, compression="zstd")
        output_files[name] = path
    manifest = {"version": "v4_selection_audit", "groups": list(GROUPS), "target_group_policy": {target: list(groups) for target, groups in TARGET_GROUP_POLICY.items()}, "targets": list(TARGETS),
                "ridge_alpha": RIDGE_ALPHA, "fit_period": "nested OOF 2021-2022; final fit uses 2020-2022 pre-test purged OOF",
                "meta_oof_years": list(META_OOF_YEARS), "test_period": "2023+",
                "group_selection_audit": {"file": "core_blend_group_selection_audit.csv", "selection_method": "fixed target policy in source code", "automatic_test_selection": False, "manual_selection_provenance": "not_encoded", "test_ic_role": "report_only"},
                "source_inputs": {
                    sample: {
                        group: {"path": str(path), "sha256": sha256_file(path)}
                        for group, path in source_paths(sample).items()
                    }
                    for sample in ("oof", "test")
                },
                "constituent_bias_note": "constituent breadth and leader diffusion use the latest available membership snapshot backfilled across history; historical membership turnover is not reconstructed",
                "limit_proxy_bias_note": "approx_limit_up_ratio and approx_limit_down_ratio use code-based thresholds and close-near-high/low proxies; they are not historical exchange limit records and do not model ST, IPO, or rule changes",
                "purge_bars_by_target": {target: (43 if "ultra_short" in target else 45 if "5d" in target else 60) for target in TARGETS},
                "output_sha256": {name: sha256_file(path) for name, path in output_files.items()},
                "target_ic_test": target_rows}
    (output_path / "core_group_blend_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser(description="合成技术与四个核心板块组")
    parser.add_argument("--output-path", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--model-path", type=Path, default=MODEL_PATH)
    args = parser.parse_args()
    run_blend(**vars(args))


if __name__ == "__main__":
    main()
