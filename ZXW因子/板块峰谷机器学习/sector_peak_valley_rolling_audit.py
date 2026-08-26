"""峰谷综合分数长窗口滚动回测的市场暴露与显著性审计。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import mlflow
import numpy as np
import pandas as pd
from mlflow.tracking import MlflowClient


DEFAULT_PEAK_ROOT = Path("outputs/sector_peak_valley_ml/stage_g_lgbm_blend_long_peak")
DEFAULT_VALLEY_ROOT = Path("outputs/sector_peak_valley_ml/stage_g_lgbm_blend_long_valley")
DEFAULT_MARKET_PATH = Path(r"D:\database\index_data_daily")
DEFAULT_REPORT_ROOT = Path("outputs/sector_peak_valley_ml/stage_i_rolling_audit")
DEFAULT_TRACKING_ROOT = Path(r"D:\database\sector_peak_valley_ml\models\mlflow_artifacts")
TEST_YEARS = tuple(range(2019, 2027))


def hac_t_stat(values: pd.Series, max_lag: int = 19) -> float:
    array = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if len(array) < 3:
        return float("nan")
    mean = float(array.mean())
    centered = array - mean
    variance = float(np.mean(centered * centered))
    for lag in range(1, min(max_lag, len(array) - 1) + 1):
        weight = 1.0 - lag / (max_lag + 1.0)
        variance += 2.0 * weight * float(np.mean(centered[lag:] * centered[:-lag]))
    standard_error = np.sqrt(max(variance, 0.0) / len(array))
    return float(mean / standard_error) if standard_error > 0 else float("nan")


def load_combined_predictions(peak_root: Path, valley_root: Path, years: tuple[int, ...]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year in years:
        peak = pd.read_parquet(peak_root / f"predictions_test_{year}_test_blend.parquet")
        valley = pd.read_parquet(valley_root / f"predictions_test_{year}_test_blend.parquet")
        for frame in (peak, valley):
            frame["time"] = pd.to_datetime(frame["time"]).dt.floor("D")
            frame["htsc_code"] = frame["htsc_code"].astype(str).str.upper()
        merged = peak[["time", "htsc_code", "prediction"]].rename(columns={"prediction": "peak_prediction"}).merge(
            valley[["time", "htsc_code", "prediction"]].rename(columns={"prediction": "valley_prediction"}),
            on=["time", "htsc_code"],
            how="inner",
            validate="one_to_one",
        )
        merged["prediction"] = merged["valley_prediction"] - merged["peak_prediction"]
        merged["year"] = year
        frames.append(merged)
    return pd.concat(frames, ignore_index=True)


def load_market(market_path: Path, codes: set[str], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    glob = str(market_path / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")
    sql = """
        SELECT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
               CAST(time AS DATE) AS bar_time,
               MAX(TRY_CAST(close AS DOUBLE)) AS close_price
        FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
        WHERE CAST(time AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
          AND (htsc_code LIKE '881%' OR htsc_code LIKE '885%' OR htsc_code LIKE '886%'
               OR htsc_code IN ('000001.SH', '399001.SZ'))
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    with duckdb.connect() as connection:
        market = connection.execute(sql, [glob, start.date(), end.date()]).df()
    market = market.rename(columns={"bar_time": "time", "close_price": "close"})
    market["time"] = pd.to_datetime(market["time"]).dt.floor("D")
    market["htsc_code"] = market["htsc_code"].astype(str).str.upper()
    market["close"] = pd.to_numeric(market["close"], errors="coerce")
    market = market.dropna(subset=["close"]).sort_values(["htsc_code", "time"]).reset_index(drop=True)
    grouped = market.groupby("htsc_code", sort=False)["close"]
    market["forward_return_20d"] = grouped.shift(-20) / market["close"] - 1.0
    market["trailing_return_60d"] = market["close"] / grouped.shift(60) - 1.0
    if market["htsc_code"].isin(codes).sum() == 0:
        raise ValueError("未读取到预测板块行情")
    return market


def build_daily_spreads(predictions: pd.DataFrame, market: pd.DataFrame, group_count: int = 10) -> pd.DataFrame:
    sector_codes = set(predictions["htsc_code"])
    prices = market[market["htsc_code"].isin(sector_codes)]
    merged = predictions.merge(prices, on=["time", "htsc_code"], how="left", validate="one_to_one")
    merged = merged.dropna(subset=["forward_return_20d"])
    rank = merged.groupby(["year", "time"], sort=False)["prediction"].rank(method="first", pct=True)
    merged["group"] = np.ceil(rank * group_count).astype(int).clip(1, group_count)
    daily = merged.groupby(["year", "time", "group"], as_index=False)["forward_return_20d"].mean()
    pivot = daily.pivot(index=["year", "time"], columns="group", values="forward_return_20d")
    spread = (pivot[group_count] - pivot[1]).rename("spread").reset_index()
    broad = market[market["htsc_code"].isin(["000001.SH", "399001.SZ"])]
    broad = broad.pivot(index="time", columns="htsc_code", values=["forward_return_20d", "trailing_return_60d"])
    broad.columns = [f"{left}_{right}" for left, right in broad.columns]
    broad["broad_forward_return_20d"] = broad[["forward_return_20d_000001.SH", "forward_return_20d_399001.SZ"]].mean(axis=1)
    broad["broad_trailing_return_60d"] = broad[["trailing_return_60d_000001.SH", "trailing_return_60d_399001.SZ"]].mean(axis=1)
    sector_benchmark = prices.groupby("time")["forward_return_20d"].mean().rename("sector_forward_return_20d")
    return spread.merge(broad[["broad_forward_return_20d", "broad_trailing_return_60d"]], left_on="time", right_index=True, how="left").merge(
        sector_benchmark, left_on="time", right_index=True, how="left"
    )


def summarize(daily: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for year, group in daily.groupby("year", sort=True):
        sample = group.dropna(subset=["spread", "broad_forward_return_20d", "sector_forward_return_20d"]).copy()
        for benchmark in ("broad_forward_return_20d", "sector_forward_return_20d"):
            variance = float(sample[benchmark].var())
            beta = float(sample["spread"].cov(sample[benchmark]) / variance) if variance > 0 else float("nan")
            residual = sample["spread"] - beta * sample[benchmark]
            spread_std = float(sample["spread"].std())
            naive_t = (
                float(sample["spread"].mean() / spread_std * np.sqrt(len(sample)))
                if spread_std > 0 and np.isfinite(spread_std)
                else float("nan")
            )
            rows.append(
                {
                    "year": int(year),
                    "benchmark": benchmark,
                    "days": int(len(sample)),
                    "spread_mean": float(sample["spread"].mean()),
                    "spread_naive_t": naive_t,
                    "spread_hac_t_lag19": hac_t_stat(sample["spread"], 19),
                    "benchmark_mean": float(sample[benchmark].mean()),
                    "correlation": float(sample["spread"].corr(sample[benchmark])),
                    "beta": beta,
                    "residual_mean": float(residual.mean()),
                    "residual_hac_t_lag19": hac_t_stat(residual, 19),
                    "bull_regime_spread_mean": float(sample.loc[sample["broad_trailing_return_60d"] > 0, "spread"].mean()),
                    "bear_regime_spread_mean": float(sample.loc[sample["broad_trailing_return_60d"] <= 0, "spread"].mean()),
                }
            )
    return pd.DataFrame(rows)


def pooled_summary(sample: pd.DataFrame, *, hac_lag: int) -> dict[str, float | int]:
    values = pd.to_numeric(sample["spread"], errors="coerce").dropna()
    standard_deviation = float(values.std()) if len(values) > 1 else float("nan")
    naive_t = (
        float(values.mean() / standard_deviation * np.sqrt(len(values)))
        if standard_deviation > 0 and np.isfinite(standard_deviation)
        else float("nan")
    )
    return {
        "days": int(len(values)),
        "spread_mean": float(values.mean()) if len(values) else float("nan"),
        "spread_naive_t": naive_t,
        "spread_hac_t": hac_t_stat(values, hac_lag),
    }


def select_non_overlapping_20d(daily: pd.DataFrame) -> pd.DataFrame:
    """每年从首个有效交易日开始每隔20个观测取一个，作为非重叠稳健性检查。"""
    frames = []
    for _, frame in daily.sort_values(["year", "time"]).groupby("year", sort=True):
        frames.append(frame.iloc[::20])
    return pd.concat(frames, ignore_index=True) if frames else daily.iloc[0:0].copy()


def run_audit(
    *,
    peak_root: Path = DEFAULT_PEAK_ROOT,
    valley_root: Path = DEFAULT_VALLEY_ROOT,
    market_path: Path = DEFAULT_MARKET_PATH,
    report_root: Path = DEFAULT_REPORT_ROOT,
    tracking_root: Path = DEFAULT_TRACKING_ROOT,
    test_years: tuple[int, ...] = TEST_YEARS,
    experiment_name: str = "sector_peak_valley_long_market_neutral_audit_v1",
) -> dict[str, object]:
    predictions = load_combined_predictions(peak_root, valley_root, test_years)
    market = load_market(market_path, set(predictions["htsc_code"]), predictions["time"].min() - pd.Timedelta(days=70), predictions["time"].max() + pd.Timedelta(days=90))
    daily = build_daily_spreads(predictions, market, group_count=10)
    summary = summarize(daily)
    report_root.mkdir(parents=True, exist_ok=True)
    daily.to_csv(report_root / "daily_spreads.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(report_root / "market_neutral_summary.csv", index=False, encoding="utf-8-sig")
    pooled = daily.dropna(subset=["spread", "broad_forward_return_20d", "sector_forward_return_20d"])
    full_years_daily = pooled[pooled["year"].isin([year for year in test_years if year != max(test_years)])]
    non_overlapping = select_non_overlapping_20d(pooled)
    pooled_beta_broad = float(pooled["spread"].cov(pooled["broad_forward_return_20d"]) / pooled["broad_forward_return_20d"].var())
    pooled_beta_sector = float(pooled["spread"].cov(pooled["sector_forward_return_20d"]) / pooled["sector_forward_return_20d"].var())
    report = {
        "test_years": list(test_years),
        "full_years": [year for year in test_years if year != max(test_years)],
        "partial_year": max(test_years),
        "group_count": 10,
        "horizon": 20,
        "pooled_days": int(len(pooled)),
        "pooled_spread_mean": float(pooled["spread"].mean()),
        "pooled_spread_hac_t_lag19": hac_t_stat(pooled["spread"], 19),
        "pooled_broad_beta": pooled_beta_broad,
        "pooled_sector_beta": pooled_beta_sector,
        "pooled_broad_correlation": float(pooled["spread"].corr(pooled["broad_forward_return_20d"])),
        "pooled_sector_correlation": float(pooled["spread"].corr(pooled["sector_forward_return_20d"])),
        "full_years_pooled": pooled_summary(full_years_daily, hac_lag=19),
        "non_overlapping_20d": pooled_summary(non_overlapping, hac_lag=0),
        "summary": summary.to_dict(orient="records"),
        "notes": [
            "20日收益窗口重叠，HAC t 使用 Newey-West 风格 lag=19 修正。",
            "2026 为截至 2026-06-15 的部分年度，单独列出，不与完整年度等权解释。",
            "市场 beta 使用未来20日大盘/等权板块收益，仅用于事后评价，不进入模型特征。",
        ],
    }
    (report_root / "rolling_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    database_path = tracking_root.parent / "mlflow.db"
    mlflow.set_tracking_uri(f"sqlite:///{database_path.as_posix()}")
    client = MlflowClient()
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        experiment_id = client.create_experiment(experiment_name, artifact_location=tracking_root.as_uri())
    else:
        experiment_id = experiment.experiment_id
    mlflow.set_experiment(experiment_name)
    with mlflow.start_run(run_name="long_peak_valley_market_neutral_audit", experiment_id=experiment_id) as run:
        mlflow.log_params({"test_years": ",".join(map(str, test_years)), "group_count": 10, "horizon": 20, "hac_lag": 19, "formula": "valley_prediction - peak_prediction"})
        mlflow.log_metrics({"pooled_spread_mean": report["pooled_spread_mean"], "pooled_spread_hac_t_lag19": report["pooled_spread_hac_t_lag19"], "pooled_broad_beta": report["pooled_broad_beta"], "pooled_broad_correlation": report["pooled_broad_correlation"]})
        mlflow.log_metrics({
            "full_years_spread_mean": report["full_years_pooled"]["spread_mean"],
            "full_years_spread_hac_t": report["full_years_pooled"]["spread_hac_t"],
            "non_overlapping_20d_mean": report["non_overlapping_20d"]["spread_mean"],
            "non_overlapping_20d_hac_t": report["non_overlapping_20d"]["spread_hac_t"],
        })
        mlflow.log_artifact(str(report_root / "daily_spreads.csv"), artifact_path="audit")
        mlflow.log_artifact(str(report_root / "market_neutral_summary.csv"), artifact_path="audit")
        mlflow.log_artifact(str(report_root / "rolling_audit.json"), artifact_path="audit")
        report["mlflow_run_id"] = run.info.run_id
    (report_root / "rolling_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary.to_string(index=False))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="峰谷综合分数长窗口滚动市场中性审计")
    parser.add_argument("--peak-root", type=Path, default=DEFAULT_PEAK_ROOT)
    parser.add_argument("--valley-root", type=Path, default=DEFAULT_VALLEY_ROOT)
    parser.add_argument("--market-path", type=Path, default=DEFAULT_MARKET_PATH)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--tracking-root", type=Path, default=DEFAULT_TRACKING_ROOT)
    parser.add_argument("--test-years", default=",".join(map(str, TEST_YEARS)))
    parser.add_argument("--experiment-name", default="sector_peak_valley_long_market_neutral_audit_v1")
    args = parser.parse_args()
    args.test_years = tuple(int(value.strip()) for value in args.test_years.split(",") if value.strip())
    run_audit(**vars(args))


if __name__ == "__main__":
    main()
