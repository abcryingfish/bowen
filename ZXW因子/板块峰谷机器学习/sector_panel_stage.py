"""审计板块因子并构建无未来泄漏的训练面板。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import polars as pl

from sector_label_stage import DEFAULT_MARKET_PATH, load_sector_market


DEFAULT_SIGNAL_PATH = Path(r"D:\database\signal_daily")
DEFAULT_LABEL_PATH = Path(r"D:\database\sector_peak_valley_ml\labels")
DEFAULT_PANEL_PATH = Path(r"D:\database\sector_peak_valley_ml\panel\panel.parquet")
DEFAULT_REPORT_PATH = Path("outputs/sector_peak_valley_ml/stage_b_panel")

# 首版按经济含义预先确定，不依据测试期 IC 选取。
FACTOR_WHITELIST = (
    "120日动量",
    "60日动量",
    "20日动量",
    "14日ATR波动率",
    "20日年化波动率",
    "60日年化波动率",
    "20_60日波动率比",
    "60日最大回撤",
    "20日新高占比",
    "20日新低占比",
    "DIF",
    "DEA",
    "MAC",
    "MAC总",
    "RSV",
    "K值",
    "D值",
    "J值",
    "RSI6",
    "RSI12",
    "RSI24",
    "OBV斜率20",
    "OBV动量20",
    "OBV价共振",
    "量比20",
)

TARGET_COLUMNS = ("peak_strength_ex_post", "valley_strength_ex_post")
FORBIDDEN_TOKENS = ("label", "未来", "事后", "peak_strength", "valley_strength", "confirm_delay")


def _partition_glob(path: Path) -> str:
    return str(path / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")


def load_complete_labels(label_path: Path) -> pd.DataFrame:
    with duckdb.connect() as con:
        labels = con.execute(
            """
            SELECT * EXCLUDE (year, month)
            FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
            WHERE label_complete = true
            ORDER BY time, htsc_code
            """,
            [_partition_glob(label_path)],
        ).df()
    labels["time"] = pd.to_datetime(labels["time"]).dt.floor("D")
    if labels.duplicated(["htsc_code", "time"]).any():
        raise ValueError("完整标签存在重复主键")
    return labels


def build_causal_market_features(market: pd.DataFrame) -> pd.DataFrame:
    """只使用 t 及以前数据构造板块基础特征。"""

    pieces = []
    for code, group in market.groupby("htsc_code", sort=True):
        g = group.sort_values("time").copy()
        close = g["close"].astype(float)
        high = g["high"].astype(float)
        low = g["low"].astype(float)
        returns = close.pct_change(fill_method=None)
        features = pd.DataFrame(
            {
                "htsc_code": code,
                "time": g["time"].to_numpy(),
                "mkt_return_1d": returns.to_numpy(),
                "mkt_momentum_5d": close.pct_change(5, fill_method=None).to_numpy(),
                "mkt_momentum_20d": close.pct_change(20, fill_method=None).to_numpy(),
                "mkt_momentum_60d": close.pct_change(60, fill_method=None).to_numpy(),
                "mkt_volatility_20d": returns.rolling(20, min_periods=20).std().to_numpy(),
                "mkt_volatility_60d": returns.rolling(60, min_periods=60).std().to_numpy(),
                "mkt_high_position_20d": (
                    close / high.rolling(20, min_periods=20).max() - 1.0
                ).to_numpy(),
                "mkt_low_position_20d": (
                    close / low.rolling(20, min_periods=20).min() - 1.0
                ).to_numpy(),
                "mkt_high_position_60d": (
                    close / high.rolling(60, min_periods=60).max() - 1.0
                ).to_numpy(),
                "mkt_low_position_60d": (
                    close / low.rolling(60, min_periods=60).min() - 1.0
                ).to_numpy(),
                "mkt_range_atr_20d": (
                    (high - low).rolling(20, min_periods=20).mean() / close
                ).to_numpy(),
            }
        )
        pieces.append(features)
    return pd.concat(pieces, ignore_index=True).sort_values(["time", "htsc_code"])


def load_factor_values(
    signal_path: Path,
    factor_name: str,
    *,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    factor_path = signal_path / f"factor={factor_name}"
    if not factor_path.exists() or not any(factor_path.glob("year=*/month=*/merged.parquet")):
        return pd.DataFrame(columns=["htsc_code", "time", factor_name])
    with duckdb.connect() as con:
        values = con.execute(
            """
            SELECT
                UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                CAST(time AS DATE) AS time,
                MAX(TRY_CAST(value AS DOUBLE)) AS value
            FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
            WHERE CAST(time AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
              AND (
                  htsc_code LIKE '881%'
                  OR htsc_code LIKE '885%'
                  OR htsc_code LIKE '886%'
              )
            GROUP BY 1, 2
            ORDER BY 2, 1
            """,
            [_partition_glob(factor_path), start_date, end_date],
        ).df()
    values["time"] = pd.to_datetime(values["time"]).dt.floor("D")
    values = values.rename(columns={"value": factor_name})
    return values


def _safe_spearman(left: pd.Series, right: pd.Series, min_count: int = 20) -> float:
    valid = pd.concat([left, right], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(valid) < min_count or valid.iloc[:, 0].nunique() < 2 or valid.iloc[:, 1].nunique() < 2:
        return float("nan")
    return float(valid.iloc[:, 0].corr(valid.iloc[:, 1], method="spearman"))


def factor_ic_summary(panel: pd.DataFrame, feature: str, target: str) -> dict[str, float]:
    """同时计算日度横截面与单板块时序 Rank IC。"""

    subset = panel[["time", "htsc_code", feature, target]].replace([np.inf, -np.inf], np.nan)
    daily = subset.groupby("time", sort=True).apply(
        lambda x: _safe_spearman(x[feature], x[target]), include_groups=False
    ).dropna()
    temporal = subset.groupby("htsc_code", sort=True).apply(
        lambda x: _safe_spearman(x[feature], x[target], min_count=60), include_groups=False
    ).dropna()
    return {
        "cross_sectional_ic_mean": float(daily.mean()) if len(daily) else float("nan"),
        "cross_sectional_ic_median": float(daily.median()) if len(daily) else float("nan"),
        "cross_sectional_icir": float(daily.mean() / daily.std()) if len(daily) > 1 and daily.std() else float("nan"),
        "cross_sectional_positive_rate": float((daily > 0).mean()) if len(daily) else float("nan"),
        "cross_sectional_days": int(len(daily)),
        "temporal_ic_mean": float(temporal.mean()) if len(temporal) else float("nan"),
        "temporal_ic_median": float(temporal.median()) if len(temporal) else float("nan"),
        "temporal_positive_rate": float((temporal > 0).mean()) if len(temporal) else float("nan"),
        "temporal_codes": int(len(temporal)),
    }


def audit_feature(panel: pd.DataFrame, feature: str) -> dict[str, object]:
    series = pd.to_numeric(panel[feature], errors="coerce").replace([np.inf, -np.inf], np.nan)
    valid = panel.loc[series.notna(), ["time", "htsc_code"]]
    result: dict[str, object] = {
        "feature": feature,
        "source": "market_causal" if feature.startswith("mkt_") else "signal_daily",
        "rows": int(series.notna().sum()),
        "coverage": float(series.notna().mean()),
        "unique_values": int(series.nunique(dropna=True)),
        "min_date": valid["time"].min().strftime("%Y-%m-%d") if len(valid) else "",
        "max_date": valid["time"].max().strftime("%Y-%m-%d") if len(valid) else "",
        "codes": int(valid["htsc_code"].nunique()),
        "forbidden_name": any(token.lower() in feature.lower() for token in FORBIDDEN_TOKENS),
    }
    result["eligible"] = bool(
        result["coverage"] >= 0.30
        and result["unique_values"] >= 10
        and not result["forbidden_name"]
    )
    for target in TARGET_COLUMNS:
        prefix = "peak" if target.startswith("peak") else "valley"
        for key, value in factor_ic_summary(panel, feature, target).items():
            result[f"{prefix}_{key}"] = value
    return result


def build_panel(
    *,
    market_path: Path,
    signal_path: Path,
    label_path: Path,
    panel_path: Path,
    report_path: Path,
    factor_names: tuple[str, ...] = FACTOR_WHITELIST,
) -> dict:
    labels = load_complete_labels(label_path)
    start_date = labels["time"].min().strftime("%Y-%m-%d")
    end_date = labels["time"].max().strftime("%Y-%m-%d")
    market = load_sector_market(market_path, start_date=start_date, end_date=end_date)
    market_features = build_causal_market_features(market)
    keep_labels = ["htsc_code", "time", *TARGET_COLUMNS, "bars_to_end"]
    panel = labels[keep_labels].merge(
        market_features, on=["htsc_code", "time"], how="left", validate="one_to_one"
    )
    missing_factor_dirs = []
    for index, factor in enumerate(factor_names, start=1):
        values = load_factor_values(
            signal_path, factor, start_date=start_date, end_date=end_date
        )
        if values.empty:
            missing_factor_dirs.append(factor)
            panel[factor] = np.nan
        else:
            panel = panel.merge(
                values, on=["htsc_code", "time"], how="left", validate="one_to_one"
            )
        print(f"[阶段B 因子 {index}/{len(factor_names)}] {factor}，有效行={len(values):,}")

    panel["sector_family"] = panel["htsc_code"].str[:3]
    feature_columns = [
        column
        for column in panel.columns
        if column not in {"htsc_code", "time", "sector_family", "bars_to_end", *TARGET_COLUMNS}
    ]
    audit_rows = [audit_feature(panel, feature) for feature in feature_columns]
    audit = pd.DataFrame(audit_rows).sort_values(
        ["eligible", "coverage", "feature"], ascending=[False, False, True]
    )
    selected = audit.loc[audit["eligible"], "feature"].tolist()
    if not selected:
        raise RuntimeError("没有因子通过阶段 B 审计")
    final_columns = [
        "htsc_code",
        "time",
        "sector_family",
        "bars_to_end",
        *TARGET_COLUMNS,
        *selected,
    ]
    final_panel = panel[final_columns].sort_values(["time", "htsc_code"])
    if final_panel.duplicated(["htsc_code", "time"]).any():
        raise ValueError("训练面板存在重复主键")
    if any(token.lower() in feature.lower() for feature in selected for token in FORBIDDEN_TOKENS):
        raise ValueError("特征列混入疑似未来信息字段")
    panel_path.parent.mkdir(parents=True, exist_ok=True)
    pl.from_pandas(final_panel, include_index=False).write_parquet(panel_path, compression="zstd")
    report_path.mkdir(parents=True, exist_ok=True)
    audit.to_csv(report_path / "factor_audit.csv", index=False, encoding="utf-8-sig")
    report = {
        "rows": int(len(final_panel)),
        "codes": int(final_panel["htsc_code"].nunique()),
        "min_date": start_date,
        "max_date": end_date,
        "candidate_features": len(feature_columns),
        "selected_features": len(selected),
        "selected_feature_names": selected,
        "missing_factor_dirs_or_sector_rows": missing_factor_dirs,
        "duplicate_keys": 0,
        "target_leakage_name_check": True,
        "passed": True,
    }
    (report_path / "panel_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="构建板块峰谷无泄漏训练面板")
    parser.add_argument("--market-path", type=Path, default=DEFAULT_MARKET_PATH)
    parser.add_argument("--signal-path", type=Path, default=DEFAULT_SIGNAL_PATH)
    parser.add_argument("--label-path", type=Path, default=DEFAULT_LABEL_PATH)
    parser.add_argument("--panel-path", type=Path, default=DEFAULT_PANEL_PATH)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    build_panel(**vars(args))


if __name__ == "__main__":
    main()
