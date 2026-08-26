"""板块波峰混合模型的多空与分组测试。

评估对象是 Stage D 测试期预测，不重新训练模型，不使用测试集调参。
收益采用同花顺板块收盘价的未来 h 个交易日收益，仅用于模型评价。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import mlflow
import numpy as np
import pandas as pd
from mlflow.tracking import MlflowClient


DEFAULT_MARKET_PATH = Path(r"D:\database\index_data_daily")
DEFAULT_PREDICTION_ROOT = Path("outputs/sector_peak_valley_ml/stage_d_lgbm_blend")
DEFAULT_REPORT_ROOT = Path("outputs/sector_peak_valley_ml/stage_e_long_short")
DEFAULT_TRACKING_ROOT = Path(r"D:\database\sector_peak_valley_ml\models\mlflow_artifacts")
PREFIXES = ("881", "885", "886")
MODELS = ("blend", "elastic_net", "lightgbm", "momentum")
GROUP_COUNTS = (5, 10)
HORIZONS = (1, 5, 10, 20, 40)
TARGET = "peak_strength_ex_post"


def load_market_prices(
    market_path: Path,
    codes: set[str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    """读取测试期板块收盘价，并按代码和日期去重。"""

    if not codes:
        raise ValueError("预测文件没有板块代码")
    glob = str(market_path / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")
    sql = """
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            CAST(time AS DATE) AS time,
            MAX(TRY_CAST(close AS DOUBLE)) AS close
        FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
        WHERE CAST(time AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
          AND (htsc_code LIKE '881%' OR htsc_code LIKE '885%' OR htsc_code LIKE '886%')
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    with duckdb.connect() as con:
        market = con.execute(sql, [glob, start_date.date(), end_date.date()]).df()
    market["time"] = pd.to_datetime(market["time"]).dt.floor("D")
    market["htsc_code"] = market["htsc_code"].astype(str).str.strip().str.upper()
    market["close"] = pd.to_numeric(market["close"], errors="coerce")
    market = market[market["htsc_code"].isin(codes)].dropna(subset=["close"])
    if market.empty:
        raise ValueError("未读取到预测板块对应的收盘价")
    if market.duplicated(["htsc_code", "time"]).any():
        raise ValueError("收盘价存在重复主键")
    return market.sort_values(["htsc_code", "time"]).reset_index(drop=True)


def add_forward_returns(market: pd.DataFrame, horizons: tuple[int, ...] = HORIZONS) -> pd.DataFrame:
    result = market.copy()
    grouped_close = result.groupby("htsc_code", sort=False)["close"]
    for horizon in horizons:
        result[f"forward_return_{horizon}d"] = grouped_close.shift(-horizon) / result["close"] - 1.0
    return result


def assign_groups(frame: pd.DataFrame, group_count: int) -> pd.DataFrame:
    """按每个交易日的预测排名分组，1 为最低，group_count 为最高。"""

    if group_count < 2:
        raise ValueError("group_count 必须至少为 2")
    result = frame.copy()
    ranks = result.groupby("time", sort=False)["prediction"].rank(method="first", pct=True)
    result["group"] = np.ceil(ranks * group_count).astype(int).clip(1, group_count)
    return result


def _safe_mean(series: pd.Series) -> float:
    return float(series.mean()) if series.notna().any() else float("nan")


def evaluate_label_groups(predictions: pd.DataFrame, group_count: int) -> tuple[pd.DataFrame, dict[str, float]]:
    grouped = assign_groups(predictions, group_count)
    group_means = (
        grouped.groupby("group", as_index=False)["actual"]
        .agg(["mean", "median", "count"])
        .reset_index()
        .rename(columns={"mean": "actual_mean", "median": "actual_median", "count": "rows"})
    )
    low = grouped.loc[grouped["group"] == 1, "actual"]
    high = grouped.loc[grouped["group"] == group_count, "actual"]
    summary = {
        "group_count": group_count,
        "label_low_group_mean": _safe_mean(low),
        "label_high_group_mean": _safe_mean(high),
        "label_high_minus_low": _safe_mean(high) - _safe_mean(low),
    }
    return group_means, summary


def _max_drawdown(cumulative: pd.Series) -> float:
    drawdown = cumulative - cumulative.cummax()
    return float(drawdown.min()) if len(drawdown) else float("nan")


def evaluate_return_groups(
    predictions: pd.DataFrame,
    group_count: int,
    horizon: int,
) -> tuple[pd.DataFrame, dict[str, float]]:
    return_column = f"forward_return_{horizon}d"
    grouped = assign_groups(predictions.dropna(subset=[return_column]), group_count)
    by_day_group = (
        grouped.groupby(["time", "group"], as_index=False)[return_column]
        .mean()
        .rename(columns={return_column: "group_return"})
    )
    pivot = by_day_group.pivot(index="time", columns="group", values="group_return")
    if pivot.empty or 1 not in pivot.columns or group_count not in pivot.columns:
        return by_day_group, {
            "group_count": group_count,
            "horizon": horizon,
            "days": 0,
            "long_mean_return": float("nan"),
            "short_mean_return": float("nan"),
            "long_short_mean_return": float("nan"),
            "reverse_long_mean_return": float("nan"),
            "reverse_short_mean_return": float("nan"),
            "reverse_long_short_mean_return": float("nan"),
            "long_short_positive_rate": float("nan"),
            "reverse_long_short_positive_rate": float("nan"),
            "long_short_sharpe": float("nan"),
            "reverse_long_short_sharpe": float("nan"),
            "long_short_cumulative_spread": float("nan"),
            "reverse_long_short_cumulative_spread": float("nan"),
            "long_short_max_drawdown": float("nan"),
            "reverse_long_short_max_drawdown": float("nan"),
        }
    spread = pivot[group_count] - pivot[1]
    cumulative = spread.fillna(0.0).cumsum()
    spread_std = float(spread.std()) if len(spread) > 1 else float("nan")
    summary = {
        "group_count": group_count,
        "horizon": horizon,
        "days": int(len(spread)),
        "long_mean_return": float(pivot[group_count].mean()),
        "short_mean_return": float(pivot[1].mean()),
        "long_short_mean_return": float(spread.mean()),
        "reverse_long_mean_return": float(pivot[1].mean()),
        "reverse_short_mean_return": float(pivot[group_count].mean()),
        "reverse_long_short_mean_return": float(-spread.mean()),
        "long_short_positive_rate": float((spread > 0).mean()),
        "reverse_long_short_positive_rate": float((spread < 0).mean()),
        "long_short_sharpe": float(spread.mean() / spread_std * np.sqrt(252))
        if spread_std and np.isfinite(spread_std)
        else float("nan"),
        "reverse_long_short_sharpe": float(-spread.mean() / spread_std * np.sqrt(252))
        if spread_std and np.isfinite(spread_std)
        else float("nan"),
        "long_short_cumulative_spread": float(cumulative.iloc[-1]),
        "reverse_long_short_cumulative_spread": float(-cumulative.iloc[-1]),
        "long_short_max_drawdown": _max_drawdown(cumulative),
        "reverse_long_short_max_drawdown": _max_drawdown(-cumulative),
    }
    daily = pivot.reset_index().rename_axis(None, axis=1)
    daily["spread"] = spread.to_numpy()
    return daily, summary


def load_prediction_files(prediction_root: Path) -> dict[tuple[str, str], pd.DataFrame]:
    loaded: dict[tuple[str, str], pd.DataFrame] = {}
    for model in MODELS:
        for year in (2023, 2024, 2025):
            path = prediction_root / f"predictions_test_{year}_test_{model}.parquet"
            if not path.exists():
                raise FileNotFoundError(path)
            frame = pd.read_parquet(path)
            if "actual" not in frame.columns and TARGET in frame.columns:
                frame = frame.rename(columns={TARGET: "actual"})
            required = {"time", "htsc_code", "sector_family", "actual", "prediction"}
            missing = required.difference(frame.columns)
            if missing:
                raise ValueError(f"{path} 缺少字段: {sorted(missing)}")
            frame["time"] = pd.to_datetime(frame["time"]).dt.floor("D")
            frame["htsc_code"] = frame["htsc_code"].astype(str).str.upper()
            frame["prediction"] = pd.to_numeric(frame["prediction"], errors="coerce")
            frame["actual"] = pd.to_numeric(frame["actual"], errors="coerce")
            frame = frame.dropna(subset=["prediction", "actual"])
            if frame.duplicated(["htsc_code", "time"]).any():
                raise ValueError(f"{path} 存在重复主键")
            loaded[(str(year), model)] = frame
    return loaded


def run_evaluation(
    *,
    market_path: Path = DEFAULT_MARKET_PATH,
    prediction_root: Path = DEFAULT_PREDICTION_ROOT,
    report_root: Path = DEFAULT_REPORT_ROOT,
    tracking_root: Path = DEFAULT_TRACKING_ROOT,
) -> dict[str, object]:
    predictions = load_prediction_files(prediction_root)
    all_codes = set().union(*(set(frame["htsc_code"]) for frame in predictions.values()))
    all_times = pd.concat([frame["time"] for frame in predictions.values()])
    market = add_forward_returns(
        load_market_prices(
            market_path,
            all_codes,
            all_times.min() - pd.Timedelta(days=5),
            all_times.max() + pd.Timedelta(days=90),
        )
    )
    report_root.mkdir(parents=True, exist_ok=True)
    label_rows: list[dict[str, object]] = []
    return_rows: list[dict[str, object]] = []
    for (year, model), frame in predictions.items():
        merged = frame.merge(market, on=["htsc_code", "time"], how="left", validate="one_to_one")
        if merged["close"].isna().any():
            raise ValueError(f"{year}/{model} 存在无法匹配行情的预测行")
        for group_count in GROUP_COUNTS:
            _, label_summary = evaluate_label_groups(merged, group_count)
            label_rows.append({"year": int(year), "model": model, **label_summary})
            for horizon in HORIZONS:
                _, summary = evaluate_return_groups(merged, group_count, horizon)
                return_rows.append({"year": int(year), "model": model, **summary})
    label_frame = pd.DataFrame(label_rows)
    return_frame = pd.DataFrame(return_rows)
    label_frame.to_csv(report_root / "label_group_summary.csv", index=False, encoding="utf-8-sig")
    return_frame.to_csv(report_root / "long_short_metrics.csv", index=False, encoding="utf-8-sig")
    blend_returns = return_frame[return_frame["model"] == "blend"]
    blend_labels = label_frame[label_frame["model"] == "blend"]
    summary = (
        blend_returns.groupby(["group_count", "horizon"])[
            [
                "long_mean_return",
                "short_mean_return",
                "long_short_mean_return",
                "reverse_long_short_mean_return",
                "long_short_positive_rate",
                "reverse_long_short_positive_rate",
                "long_short_sharpe",
                "reverse_long_short_sharpe",
                "long_short_cumulative_spread",
                "reverse_long_short_cumulative_spread",
                "long_short_max_drawdown",
                "reverse_long_short_max_drawdown",
            ]
        ]
        .mean()
        .reset_index()
    )
    report = {
        "prediction_root": str(prediction_root),
        "market_path": str(market_path),
        "models": list(MODELS),
        "group_counts": list(GROUP_COUNTS),
        "horizons": list(HORIZONS),
        "blend_label_summary": blend_labels.to_dict(orient="records"),
        "blend_return_summary": summary.to_dict(orient="records"),
        "notes": [
            "收益为收盘到未来 h 个交易日收盘的板块收益，未扣交易成本。",
            "多空收益为每日最高预测组等权收益减最低预测组等权收益；h>1 为重叠持有期的预测评价，不等同于可直接实盘复利回测。",
        ],
    }
    (report_root / "long_short_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    database_path = tracking_root.parent / "mlflow.db"
    mlflow.set_tracking_uri(f"sqlite:///{database_path.as_posix()}")
    experiment_name = "sector_peak_valley_lgbm_long_short_v1"
    client = MlflowClient()
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        experiment_id = client.create_experiment(experiment_name, artifact_location=tracking_root.as_uri())
    else:
        experiment_id = experiment.experiment_id
    mlflow.set_experiment(experiment_name)
    with mlflow.start_run(run_name="peak_blend_long_short_test", experiment_id=experiment_id) as run:
        mlflow.log_params(
            {
                "target": "peak_strength_ex_post",
                "models": ",".join(MODELS),
                "group_counts": ",".join(map(str, GROUP_COUNTS)),
                "horizons": ",".join(map(str, HORIZONS)),
                "return_definition": "close_t_plus_h / close_t - 1",
                "portfolio_weight": "equal_weight",
                "transaction_cost": "not_included",
            }
        )
        mlflow.log_metrics(
            {
                f"blend_g{int(row.group_count)}_h{int(row.horizon)}_long_short_mean": float(row.long_short_mean_return)
                for row in summary.itertuples()
                if np.isfinite(row.long_short_mean_return)
            }
        )
        mlflow.log_metrics(
            {
                f"blend_g{int(row.group_count)}_h{int(row.horizon)}_reverse_long_short_mean": float(row.reverse_long_short_mean_return)
                for row in summary.itertuples()
                if np.isfinite(row.reverse_long_short_mean_return)
            }
        )
        mlflow.log_artifact(str(report_root / "label_group_summary.csv"), artifact_path="evaluation")
        mlflow.log_artifact(str(report_root / "long_short_metrics.csv"), artifact_path="evaluation")
        mlflow.log_artifact(str(report_root / "long_short_audit.json"), artifact_path="evaluation")
        mlflow.set_tag("source_prediction_experiment", "sector_peak_valley_lgbm_blend_v1")
        mlflow.set_tag("run_id_local", run.info.run_id)
        report["mlflow_run_id"] = run.info.run_id
    (report_root / "long_short_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(summary.to_string(index=False))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="板块波峰混合模型多空与分组测试")
    parser.add_argument("--market-path", type=Path, default=DEFAULT_MARKET_PATH)
    parser.add_argument("--prediction-root", type=Path, default=DEFAULT_PREDICTION_ROOT)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--tracking-root", type=Path, default=DEFAULT_TRACKING_ROOT)
    args = parser.parse_args()
    run_evaluation(**vars(args))


if __name__ == "__main__":
    main()
