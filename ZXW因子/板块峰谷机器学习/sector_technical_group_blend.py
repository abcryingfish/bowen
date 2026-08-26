"""用18个技术子组OOF分数合成技术大组，并完成封存期评价。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb
import joblib
import numpy as np
import pandas as pd
import polars as pl
from sklearn.linear_model import Ridge


DEFAULT_PREDICTION_PATH = Path(
    "outputs/sector_peak_valley_ml/stage_q_technical_subgroup_models/predictions"
)
DEFAULT_MARKET_PATH = Path(r"D:\database\index_data_daily")
DEFAULT_MODEL_PATH = Path(
    r"D:\database\sector_peak_valley_ml\models\technical_group_v1"
)
DEFAULT_OUTPUT_PATH = Path(
    "outputs/sector_peak_valley_ml/stage_r_technical_group_blend"
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
RIDGE_ALPHA = 1000.0
TEST_START = pd.Timestamp("2023-01-01")
META_OOF_YEARS = (2020, 2021, 2022)
GROUP_COUNT = 5
GENERATOR_VERSION = "v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_indicators(prediction_path: Path) -> list[str]:
    indicators = sorted(path.name.removesuffix("_oof.parquet") for path in prediction_path.glob("*_oof.parquet"))
    if not indicators:
        raise FileNotFoundError(f"没有找到子组OOF预测: {prediction_path}")
    missing = [name for name in indicators if not (prediction_path / f"{name}_test.parquet").is_file()]
    if missing:
        raise FileNotFoundError(f"子组缺少测试预测: {missing}")
    return indicators


def load_prediction_matrix(
    prediction_path: Path,
    indicators: list[str],
    sample: str,
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    target_columns = list(TARGET_SETTINGS)
    base: pd.DataFrame | None = None
    feature_map: dict[str, list[str]] = {target: [] for target in target_columns}
    for indicator in indicators:
        path = prediction_path / f"{indicator}_{sample}.parquet"
        frame = pd.read_parquet(path)
        frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
        frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
        if frame.duplicated(KEYS).any():
            raise ValueError(f"{path} 存在重复主键")
        if base is None:
            base = frame[[*KEYS, FAMILY_COLUMN, *target_columns]].copy()
        for target in target_columns:
            source = f"pred_{target}"
            destination = f"score_{indicator}_{target}"
            if source not in frame:
                raise ValueError(f"{path} 缺少预测列 {source}")
            values = pd.to_numeric(frame[source], errors="coerce")
            ranked = values.groupby(frame["time"], sort=False).rank(method="average", pct=True)
            score_frame = frame[KEYS].copy()
            score_frame[destination] = ranked.to_numpy(dtype=float)
            assert base is not None
            base = base.merge(score_frame, on=KEYS, how="left", validate="one_to_one")
            if base[destination].isna().any():
                raise ValueError(f"{path} 的 {destination} 存在缺失或主键不一致")
            feature_map[target].append(destination)
    assert base is not None
    return base.sort_values(["time", "htsc_code"]).reset_index(drop=True), feature_map


def purge_train_end(
    dates: pd.DatetimeIndex,
    boundary: pd.Timestamp,
    purge_bars: int,
) -> pd.Timestamp:
    prior = dates[dates < boundary]
    if len(prior) <= purge_bars:
        raise ValueError("第二层OOF历史不足")
    return pd.Timestamp(prior[-purge_bars - 1])


def fit_technical_group(
    oof: pd.DataFrame,
    test: pd.DataFrame,
    feature_map: dict[str, list[str]],
    model_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict[str, object]]]:
    model_path.mkdir(parents=True, exist_ok=True)
    oof_output = oof[[*KEYS, FAMILY_COLUMN, *TARGET_SETTINGS]].copy()
    test_output = test[[*KEYS, FAMILY_COLUMN, *TARGET_SETTINGS]].copy()
    coefficient_rows = []
    target_reports = []
    dates = pd.DatetimeIndex(oof["time"].unique()).sort_values()
    for target, settings in TARGET_SETTINGS.items():
        features = feature_map[target]
        prediction_column = f"pred_{target}"
        oof_output[prediction_column] = np.nan
        purge_bars = int(settings["purge_bars"])
        for year in META_OOF_YEARS:
            validation = oof["time"].dt.year.eq(year)
            if not validation.any():
                continue
            boundary = oof.loc[validation, "time"].min()
            train_end = purge_train_end(dates, boundary, purge_bars)
            train = (oof["time"] <= train_end) & oof[target].notna()
            model = Ridge(alpha=RIDGE_ALPHA)
            model.fit(oof.loc[train, features], oof.loc[train, target])
            oof_output.loc[validation, prediction_column] = model.predict(
                oof.loc[validation, features]
            )

        final_train_end = purge_train_end(dates, TEST_START, purge_bars)
        final_train = (oof["time"] <= final_train_end) & oof[target].notna()
        final_model = Ridge(alpha=RIDGE_ALPHA)
        final_model.fit(oof.loc[final_train, features], oof.loc[final_train, target])
        test_output[prediction_column] = final_model.predict(test[features])
        model_file = model_path / f"{target}.joblib"
        joblib.dump(
            {
                "model": final_model,
                "features": features,
                "target": target,
                "input_transform": "daily_cross_sectional_percentile_rank",
            },
            model_file,
        )
        for feature, coefficient in zip(features, final_model.coef_):
            coefficient_rows.append(
                {
                    "target": target,
                    "indicator": feature.removeprefix("score_").removesuffix(f"_{target}"),
                    "coefficient": float(coefficient),
                }
            )
        target_reports.append(
            {
                "target": target,
                "purge_bars": purge_bars,
                "final_train_end": final_train_end.strftime("%Y-%m-%d"),
                "train_rows": int(final_train.sum()),
                "intercept": float(final_model.intercept_),
                "model_path": str(model_file),
                "model_sha256": sha256_file(model_file),
            }
        )
    return oof_output, test_output, pd.DataFrame(coefficient_rows), target_reports


def _safe_rank_ic(block: pd.DataFrame, actual: str, prediction: str, minimum: int = 20) -> float:
    valid = block[[actual, prediction]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(valid) < minimum or valid.nunique().min() < 2:
        return np.nan
    return float(valid[actual].corr(valid[prediction], method="spearman"))


def evaluate_rank_ic(
    frame: pd.DataFrame,
    actual: str,
    prediction: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    daily_rows = []
    family_rows = []
    for time, block in frame.groupby("time", sort=True):
        daily_rows.append({"time": time, "rank_ic": _safe_rank_ic(block, actual, prediction)})
    for (time, family), block in frame.groupby(["time", FAMILY_COLUMN], sort=True):
        family_rows.append(
            {"time": time, FAMILY_COLUMN: family, "rank_ic": _safe_rank_ic(block, actual, prediction)}
        )
    daily = pd.DataFrame(daily_rows).dropna(subset=["rank_ic"])
    family_daily = pd.DataFrame(family_rows).dropna(subset=["rank_ic"])
    overall = pd.DataFrame(
        [{"ic_mean": daily["rank_ic"].mean(), "ic_median": daily["rank_ic"].median(), "valid_days": len(daily)}]
    )
    annual = (
        daily.assign(year=daily["time"].dt.year)
        .groupby("year")["rank_ic"]
        .agg(ic_mean="mean", ic_median="median", valid_days="count")
        .reset_index()
    )
    family = (
        family_daily.groupby(FAMILY_COLUMN)["rank_ic"]
        .agg(ic_mean="mean", ic_median="median", valid_days="count")
        .reset_index()
    )
    return overall, annual, family


def evaluate_quintiles(
    frame: pd.DataFrame,
    actual: str,
    prediction: str,
) -> pd.DataFrame:
    daily_parts = []
    for time, block in frame.dropna(subset=[actual, prediction]).groupby("time", sort=True):
        if len(block) < 20 or block[prediction].nunique() < 5:
            continue
        values = block[[actual, prediction]].copy()
        ranks = values[prediction].rank(method="first", pct=True)
        values["quintile"] = np.ceil(ranks * GROUP_COUNT).astype(int).clip(1, GROUP_COUNT)
        means = values.groupby("quintile")[actual].mean().reindex(range(1, GROUP_COUNT + 1))
        if means.notna().all():
            daily_parts.append(pd.DataFrame({"time": time, "quintile": means.index, "actual_mean": means.values}))
    if not daily_parts:
        return pd.DataFrame()
    daily = pd.concat(daily_parts, ignore_index=True)
    return (
        daily.groupby("quintile")["actual_mean"]
        .agg(mean="mean", median="median", valid_days="count")
        .reset_index()
    )


def _market_glob(path: Path) -> str:
    return str(path / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")


def load_forward_returns(market_path: Path, max_prediction_date: pd.Timestamp) -> pd.DataFrame:
    with duckdb.connect() as con:
        market = con.execute(
            """
            SELECT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                   CAST(time AS DATE) AS time,
                   MAX(TRY_CAST(close AS DOUBLE)) AS close
            FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
            WHERE CAST(time AS DATE) >= CAST('2023-01-01' AS DATE)
              AND (htsc_code LIKE '881%' OR htsc_code LIKE '885%' OR htsc_code LIKE '886%')
            GROUP BY 1, 2 ORDER BY 1, 2
            """,
            [_market_glob(market_path)],
        ).df()
    market["time"] = pd.to_datetime(market["time"]).dt.floor("D")
    market = market.sort_values(["htsc_code", "time"]).reset_index(drop=True)
    close = market.groupby("htsc_code", sort=False)["close"]
    for days in (1, 2, 3, 5, 20):
        market[f"forward_return_{days}d"] = close.shift(-days) / market["close"] - 1.0
    market["forward_return_ultra_short"] = (
        0.5 * market["forward_return_1d"]
        + 0.3 * market["forward_return_2d"]
        + 0.2 * market["forward_return_3d"]
    )
    return market[market["time"] <= max_prediction_date][
        [*KEYS, "forward_return_ultra_short", "forward_return_5d", "forward_return_20d"]
    ]


def evaluate_direction_and_long_short(
    test: pd.DataFrame,
    market_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    returns = load_forward_returns(market_path, test["time"].max())
    values = test.merge(returns, on=KEYS, how="left", validate="one_to_one")
    direction_ic_parts = []
    direction_annual_parts = []
    direction_family_parts = []
    group_parts = []
    spread_parts = []
    for horizon in ("ultra_short", "5d", "20d"):
        peak = f"pred_delta_peak_{horizon}"
        valley = f"pred_delta_valley_{horizon}"
        actual = f"actual_direction_{horizon}"
        score = f"direction_score_{horizon}"
        ret = f"forward_return_{horizon}"
        values[actual] = values[f"delta_valley_{horizon}"] - values[f"delta_peak_{horizon}"]
        peak_rank = values[peak].groupby(values["time"]).rank(method="average", pct=True)
        valley_rank = values[valley].groupby(values["time"]).rank(method="average", pct=True)
        values[score] = valley_rank - peak_rank
        overall, annual, family = evaluate_rank_ic(values, actual, score)
        overall.insert(0, "horizon", horizon)
        annual.insert(0, "horizon", horizon)
        family.insert(0, "horizon", horizon)
        direction_ic_parts.append(overall)
        direction_annual_parts.append(annual)
        direction_family_parts.append(family)

        payload = values.dropna(subset=[score, actual, ret]).copy()
        payload["group"] = np.ceil(
            payload[score].groupby(payload["time"]).rank(method="first", pct=True) * GROUP_COUNT
        ).astype(int).clip(1, GROUP_COUNT)
        daily_group = (
            payload.groupby(["time", "group"], as_index=False)[[actual, ret]].mean()
            .rename(columns={actual: "actual_direction", ret: "forward_return"})
        )
        group_summary = (
            daily_group.groupby("group")[["actual_direction", "forward_return"]]
            .agg(["mean", "median", "count"])
        )
        group_summary.columns = ["_".join(column) for column in group_summary.columns]
        group_summary = group_summary.reset_index()
        group_summary.insert(0, "horizon", horizon)
        group_parts.append(group_summary)

        actual_pivot = daily_group.pivot(
            index="time", columns="group", values="actual_direction"
        )
        return_pivot = daily_group.pivot(
            index="time", columns="group", values="forward_return"
        )
        common = actual_pivot.index.intersection(return_pivot.index)
        spread = pd.DataFrame(
            {
                "time": common.to_numpy(),
                "horizon": horizon,
                "direction_spread_q5_minus_q1": (
                    actual_pivot.loc[common, 5] - actual_pivot.loc[common, 1]
                ).to_numpy(),
                "return_spread_q5_minus_q1": (
                    return_pivot.loc[common, 5] - return_pivot.loc[common, 1]
                ).to_numpy(),
            }
        )
        spread["year"] = pd.to_datetime(spread["time"]).dt.year
        spread_parts.append(spread)
    direction_ic = pd.concat(direction_ic_parts, ignore_index=True)
    direction_annual = pd.concat(direction_annual_parts, ignore_index=True)
    direction_family = pd.concat(direction_family_parts, ignore_index=True)
    groups = pd.concat(group_parts, ignore_index=True)
    spreads = pd.concat(spread_parts, ignore_index=True)
    return direction_ic, direction_annual, direction_family, groups, spreads


def run_blend(
    *,
    prediction_path: Path = DEFAULT_PREDICTION_PATH,
    market_path: Path = DEFAULT_MARKET_PATH,
    model_path: Path = DEFAULT_MODEL_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> dict[str, object]:
    indicators = discover_indicators(prediction_path)
    oof, feature_map = load_prediction_matrix(prediction_path, indicators, "oof")
    test, test_feature_map = load_prediction_matrix(prediction_path, indicators, "test")
    if feature_map != test_feature_map:
        raise ValueError("OOF与测试子组特征不一致")
    output_path.mkdir(parents=True, exist_ok=True)
    oof_output, test_output, coefficients, target_reports = fit_technical_group(
        oof, test, feature_map, model_path
    )

    overall_parts = []
    annual_parts = []
    family_parts = []
    quintile_parts = []
    for target in TARGET_SETTINGS:
        prediction = f"pred_{target}"
        overall, annual, family = evaluate_rank_ic(test_output, target, prediction)
        quintile = evaluate_quintiles(test_output, target, prediction)
        for values in (overall, annual, family, quintile):
            values.insert(0, "target", target)
        overall_parts.append(overall)
        annual_parts.append(annual)
        family_parts.append(family)
        quintile_parts.append(quintile)
    target_ic = pd.concat(overall_parts, ignore_index=True)
    target_annual = pd.concat(annual_parts, ignore_index=True)
    target_family = pd.concat(family_parts, ignore_index=True)
    target_quintile = pd.concat(quintile_parts, ignore_index=True)
    direction_ic, direction_annual, direction_family, groups, spreads = (
        evaluate_direction_and_long_short(test_output, market_path)
    )
    spread_summary = (
        spreads.groupby("horizon")
        .agg(
            days=("return_spread_q5_minus_q1", "count"),
            direction_spread_mean=("direction_spread_q5_minus_q1", "mean"),
            direction_positive_rate=("direction_spread_q5_minus_q1", lambda x: (x > 0).mean()),
            return_spread_mean=("return_spread_q5_minus_q1", "mean"),
            return_positive_rate=("return_spread_q5_minus_q1", lambda x: (x > 0).mean()),
        )
        .reset_index()
    )
    spread_annual = (
        spreads.groupby(["horizon", "year"])
        .agg(
            days=("return_spread_q5_minus_q1", "count"),
            direction_spread_mean=("direction_spread_q5_minus_q1", "mean"),
            return_spread_mean=("return_spread_q5_minus_q1", "mean"),
            return_positive_rate=("return_spread_q5_minus_q1", lambda x: (x > 0).mean()),
        )
        .reset_index()
    )

    files_and_frames = {
        "ridge_coefficients.csv": coefficients,
        "target_rank_ic_test.csv": target_ic,
        "target_rank_ic_annual_test.csv": target_annual,
        "target_rank_ic_sector_family_test.csv": target_family,
        "target_quintile_test.csv": target_quintile,
        "direction_rank_ic_test.csv": direction_ic,
        "direction_rank_ic_annual_test.csv": direction_annual,
        "direction_rank_ic_sector_family_test.csv": direction_family,
        "direction_group_summary_test.csv": groups,
        "long_short_summary_test.csv": spread_summary,
        "long_short_annual_test.csv": spread_annual,
    }
    for filename, frame in files_and_frames.items():
        frame.to_csv(output_path / filename, index=False, encoding="utf-8-sig")
    oof_file = output_path / "technical_group_oof_predictions.parquet"
    test_file = output_path / "technical_group_test_predictions.parquet"
    spread_file = output_path / "long_short_daily_test.parquet"
    pl.from_pandas(oof_output, include_index=False).write_parquet(oof_file, compression="zstd")
    pl.from_pandas(test_output, include_index=False).write_parquet(test_file, compression="zstd")
    pl.from_pandas(spreads, include_index=False).write_parquet(spread_file, compression="zstd")

    output_files = [output_path / name for name in files_and_frames]
    output_files.extend([oof_file, test_file, spread_file])
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "subgroups": indicators,
        "subgroup_count": len(indicators),
        "targets": list(TARGET_SETTINGS),
        "ridge_alpha": RIDGE_ALPHA,
        "ridge_fit_input": "2019-2022 first-layer OOF daily percentile scores only",
        "meta_oof_years": list(META_OOF_YEARS),
        "test_period": "time >= 2023-01-01",
        "test_usage": "final_evaluation_only",
        "direction_definition": "daily_rank(pred_valley_change) - daily_rank(pred_peak_change)",
        "long_short_definition": "daily_equal_weight_Q5_return_minus_Q1_return",
        "group_count": GROUP_COUNT,
        "return_note": "overlapping forward returns without transaction costs; diagnostic, not portfolio NAV",
        "target_reports": target_reports,
        "target_rank_ic_test": target_ic.to_dict(orient="records"),
        "direction_rank_ic_test": direction_ic.to_dict(orient="records"),
        "long_short_summary_test": spread_summary.to_dict(orient="records"),
        "output_sha256": {path.name: sha256_file(path) for path in output_files},
    }
    (output_path / "technical_group_blend_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: manifest[key] for key in ("target_rank_ic_test", "direction_rank_ic_test", "long_short_summary_test")}, ensure_ascii=False, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="合成板块技术大组分数并评价")
    parser.add_argument("--prediction-path", type=Path, default=DEFAULT_PREDICTION_PATH)
    parser.add_argument("--market-path", type=Path, default=DEFAULT_MARKET_PATH)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()
    run_blend(**vars(args))


if __name__ == "__main__":
    main()
