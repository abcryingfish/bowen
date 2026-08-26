"""峰谷综合分数的板块分组与多空测试。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import mlflow
import numpy as np
import pandas as pd
from mlflow.tracking import MlflowClient


DEFAULT_PEAK_ROOT = Path("outputs/sector_peak_valley_ml/stage_d_lgbm_blend")
DEFAULT_VALLEY_ROOT = Path("outputs/sector_peak_valley_ml/stage_d_lgbm_blend_valley")
DEFAULT_MARKET_PATH = Path(r"D:\database\index_data_daily")
DEFAULT_REPORT_ROOT = Path("outputs/sector_peak_valley_ml/stage_f_peak_valley_combined")
DEFAULT_TRACKING_ROOT = Path(r"D:\database\sector_peak_valley_ml\models\mlflow_artifacts")
MODELS = ("blend", "elastic_net", "lightgbm", "momentum")
GROUP_COUNTS = (5, 10)
HORIZONS = (1, 5, 10, 20, 40)


def load_predictions(root: Path, model: str, year: int, target_name: str) -> pd.DataFrame:
    path = root / f"predictions_test_{year}_test_{model}.parquet"
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_parquet(path)
    if target_name not in frame.columns:
        raise ValueError(f"{path} 缺少标签列 {target_name}")
    required = {"time", "htsc_code", "sector_family", "prediction"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{path} 缺少字段: {sorted(missing)}")
    frame = frame[["time", "htsc_code", "sector_family", target_name, "prediction"]].copy()
    frame["time"] = pd.to_datetime(frame["time"]).dt.floor("D")
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.upper()
    frame = frame.rename(columns={target_name: f"{target_name}_actual", "prediction": f"{target_name}_prediction"})
    if frame.duplicated(["htsc_code", "time"]).any():
        raise ValueError(f"{path} 存在重复主键")
    return frame


def load_market(market_path: Path, codes: set[str], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    glob = str(market_path / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")
    sql = """
        SELECT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
               CAST(time AS DATE) AS time,
               MAX(TRY_CAST(close AS DOUBLE)) AS close
        FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
        WHERE CAST(time AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
          AND (htsc_code LIKE '881%' OR htsc_code LIKE '885%' OR htsc_code LIKE '886%')
        GROUP BY 1, 2 ORDER BY 1, 2
    """
    with duckdb.connect() as con:
        market = con.execute(sql, [glob, start.date(), end.date()]).df()
    market["time"] = pd.to_datetime(market["time"]).dt.floor("D")
    market["htsc_code"] = market["htsc_code"].astype(str).str.upper()
    market["close"] = pd.to_numeric(market["close"], errors="coerce")
    market = market[market["htsc_code"].isin(codes)].dropna(subset=["close"])
    if market.duplicated(["htsc_code", "time"]).any() or market.empty:
        raise ValueError("板块行情为空或存在重复主键")
    market = market.sort_values(["htsc_code", "time"]).reset_index(drop=True)
    close = market.groupby("htsc_code", sort=False)["close"]
    for horizon in HORIZONS:
        market[f"forward_return_{horizon}d"] = close.shift(-horizon) / market["close"] - 1.0
    return market


def assign_groups(frame: pd.DataFrame, group_count: int) -> pd.DataFrame:
    result = frame.copy()
    rank = result.groupby("time", sort=False)["prediction"].rank(method="first", pct=True)
    result["group"] = np.ceil(rank * group_count).astype(int).clip(1, group_count)
    return result


def evaluate_combined_groups(frame: pd.DataFrame, group_count: int, horizon: int) -> tuple[pd.DataFrame, dict[str, float]]:
    grouped = assign_groups(frame.dropna(subset=[f"forward_return_{horizon}d"]), group_count)
    high = grouped[grouped["group"] == group_count]
    low = grouped[grouped["group"] == 1]
    label_group = grouped.groupby("group")[
        ["valley_strength_ex_post_actual", "peak_strength_ex_post_actual"]
    ].mean()
    by_day = grouped.groupby(["time", "group"])[f"forward_return_{horizon}d"].mean().unstack("group")
    if by_day.empty or 1 not in by_day.columns or group_count not in by_day.columns:
        return label_group.reset_index(), {"group_count": group_count, "horizon": horizon, "days": 0}
    spread = by_day[group_count] - by_day[1]
    std = float(spread.std()) if len(spread) > 1 else float("nan")
    return label_group.reset_index(), {
        "group_count": group_count,
        "horizon": horizon,
        "days": int(len(spread)),
        "valley_label_high_minus_low": float(high["valley_strength_ex_post_actual"].mean() - low["valley_strength_ex_post_actual"].mean()),
        "peak_label_high_minus_low": float(high["peak_strength_ex_post_actual"].mean() - low["peak_strength_ex_post_actual"].mean()),
        "long_mean_return": float(by_day[group_count].mean()),
        "short_mean_return": float(by_day[1].mean()),
        "long_short_mean_return": float(spread.mean()),
        "long_short_positive_rate": float((spread > 0).mean()),
        "long_short_sharpe": float(spread.mean() / std * np.sqrt(252)) if std and np.isfinite(std) else float("nan"),
    }


def run_combined(
    *,
    peak_root: Path = DEFAULT_PEAK_ROOT,
    valley_root: Path = DEFAULT_VALLEY_ROOT,
    market_path: Path = DEFAULT_MARKET_PATH,
    report_root: Path = DEFAULT_REPORT_ROOT,
    tracking_root: Path = DEFAULT_TRACKING_ROOT,
    test_years: tuple[int, ...] = (2023, 2024, 2025),
    experiment_name: str = "sector_peak_valley_combined_long_short_v1",
) -> dict[str, object]:
    combined_frames: dict[tuple[int, str], pd.DataFrame] = {}
    for year in test_years:
        for model in MODELS:
            peak = load_predictions(peak_root, model, year, "peak_strength_ex_post")
            valley = load_predictions(valley_root, model, year, "valley_strength_ex_post")
            frame = peak.merge(
                valley,
                on=["time", "htsc_code", "sector_family"],
                how="inner",
                validate="one_to_one",
            )
            frame["prediction"] = frame["valley_strength_ex_post_prediction"] - frame["peak_strength_ex_post_prediction"]
            combined_frames[(year, model)] = frame
    all_codes = set().union(*(set(frame["htsc_code"]) for frame in combined_frames.values()))
    all_times = pd.concat([frame["time"] for frame in combined_frames.values()])
    market = load_market(market_path, all_codes, all_times.min() - pd.Timedelta(days=5), all_times.max() + pd.Timedelta(days=90))
    report_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    group_rows: list[dict[str, object]] = []
    for (year, model), frame in combined_frames.items():
        merged = frame.merge(market, on=["htsc_code", "time"], how="left", validate="one_to_one")
        if merged["close"].isna().any():
            raise ValueError(f"{year}/{model} 无法匹配板块收盘价")
        for group_count in GROUP_COUNTS:
            for horizon in HORIZONS:
                group_frame, metrics = evaluate_combined_groups(merged, group_count, horizon)
                rows.append({"year": year, "model": model, **metrics})
                group_frame["year"] = year
                group_frame["model"] = model
                group_frame["group_count"] = group_count
                group_rows.append(group_frame)
    metrics_frame = pd.DataFrame(rows)
    groups_frame = pd.concat(group_rows, ignore_index=True)
    metrics_frame.to_csv(report_root / "combined_long_short_metrics.csv", index=False, encoding="utf-8-sig")
    groups_frame.to_csv(report_root / "combined_group_means.csv", index=False, encoding="utf-8-sig")
    blend = metrics_frame[metrics_frame["model"] == "blend"]
    summary = blend.groupby(["group_count", "horizon"])[
        ["valley_label_high_minus_low", "peak_label_high_minus_low", "long_mean_return", "short_mean_return", "long_short_mean_return", "long_short_positive_rate", "long_short_sharpe"]
    ].mean().reset_index()
    report = {
        "formula": "valley_prediction - peak_prediction",
        "models": list(MODELS),
        "group_counts": list(GROUP_COUNTS),
        "horizons": list(HORIZONS),
        "test_years": list(test_years),
        "blend_summary": summary.to_dict(orient="records"),
        "notes": [
            "高综合分数代表谷分高、峰分低，按此方向做多；低综合分数做空。",
            "收益为等权板块未来 h 日收盘收益，h>1 存在重叠窗口，未扣交易成本。",
        ],
    }
    (report_root / "combined_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    database_path = tracking_root.parent / "mlflow.db"
    mlflow.set_tracking_uri(f"sqlite:///{database_path.as_posix()}")
    client = MlflowClient()
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        experiment_id = client.create_experiment(experiment_name, artifact_location=tracking_root.as_uri())
    else:
        experiment_id = experiment.experiment_id
    mlflow.set_experiment(experiment_name)
    with mlflow.start_run(run_name="peak_valley_combined_long_short_test", experiment_id=experiment_id) as run:
        mlflow.log_params({"formula": "valley_prediction - peak_prediction", "group_counts": "5,10", "horizons": "1,5,10,20,40", "test_years": ",".join(map(str, test_years)), "portfolio_weight": "equal_weight", "transaction_cost": "not_included"})
        mlflow.log_metrics({f"blend_g{int(row.group_count)}_h{int(row.horizon)}_long_short_mean": float(row.long_short_mean_return) for row in summary.itertuples() if np.isfinite(row.long_short_mean_return)})
        mlflow.log_artifact(str(report_root / "combined_long_short_metrics.csv"), artifact_path="evaluation")
        mlflow.log_artifact(str(report_root / "combined_group_means.csv"), artifact_path="evaluation")
        mlflow.log_artifact(str(report_root / "combined_audit.json"), artifact_path="evaluation")
        mlflow.set_tag("source_peak_experiment", "sector_peak_valley_lgbm_blend_v1")
        mlflow.set_tag("source_valley_experiment", "sector_peak_valley_lgbm_valley_blend_v1")
        report["mlflow_run_id"] = run.info.run_id
    (report_root / "combined_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary.to_string(index=False))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="峰谷综合分数分组与多空测试")
    parser.add_argument("--peak-root", type=Path, default=DEFAULT_PEAK_ROOT)
    parser.add_argument("--valley-root", type=Path, default=DEFAULT_VALLEY_ROOT)
    parser.add_argument("--market-path", type=Path, default=DEFAULT_MARKET_PATH)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--tracking-root", type=Path, default=DEFAULT_TRACKING_ROOT)
    parser.add_argument("--test-years", default="2023,2024,2025")
    parser.add_argument("--experiment-name", default="sector_peak_valley_combined_long_short_v1")
    args = parser.parse_args()
    args.test_years = tuple(int(value.strip()) for value in args.test_years.split(",") if value.strip())
    run_combined(**vars(args))


if __name__ == "__main__":
    main()
