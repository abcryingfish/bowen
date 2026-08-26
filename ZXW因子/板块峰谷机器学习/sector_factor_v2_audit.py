"""审计板块因子与 V2 峰谷标签、未来收益的横截面排序关系。"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


DEFAULT_PANEL_PATH = Path(r"D:\database\sector_peak_valley_ml\panel\panel.parquet")
DEFAULT_MARKET_PATH = Path(r"D:\database\index_data_daily")
DEFAULT_OUTPUT_PATH = Path("outputs/sector_peak_valley_ml/stage_k_factor_v2_audit")

ID_COLUMNS = {"htsc_code", "time", "sector_family", "bars_to_end"}
V2_TARGETS = ("peak_strength_ex_post", "valley_strength_ex_post")
FORWARD_HORIZONS = (5, 10, 20)
MIN_CROSS_SECTION = 20


def _market_glob(base_path: Path) -> str:
    return str(base_path / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")


def load_panel(panel_path: Path) -> tuple[pd.DataFrame, list[str]]:
    frame = pd.read_parquet(panel_path)
    required = {*ID_COLUMNS, *V2_TARGETS}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"训练面板缺少字段: {sorted(missing)}")
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    frame["sector_family"] = frame["sector_family"].astype(str).str.strip()
    if frame[["htsc_code", "time"]].isna().any().any():
        raise ValueError("训练面板主键包含缺失值")
    if frame.duplicated(["htsc_code", "time"]).any():
        raise ValueError("训练面板存在重复主键")
    features = [
        column
        for column in frame.columns
        if column not in ID_COLUMNS and column not in V2_TARGETS
    ]
    if not features:
        raise ValueError("训练面板没有可审计因子")
    for column in [*features, *V2_TARGETS]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values(["time", "htsc_code"]).reset_index(drop=True), features


def load_market_close(market_path: Path, start_date: pd.Timestamp) -> pd.DataFrame:
    with duckdb.connect() as con:
        market = con.execute(
            """
            SELECT
                UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                CAST(time AS DATE) AS time,
                MAX(TRY_CAST(close AS DOUBLE)) AS close
            FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
            WHERE CAST(time AS DATE) >= CAST(? AS DATE)
              AND (htsc_code LIKE '881%' OR htsc_code LIKE '885%' OR htsc_code LIKE '886%')
            GROUP BY 1, 2
            ORDER BY 1, 2
            """,
            [_market_glob(market_path), start_date.strftime("%Y-%m-%d")],
        ).df()
    if market.empty:
        raise ValueError("没有读取到板块收盘价")
    market["time"] = pd.to_datetime(market["time"], errors="coerce").dt.floor("D")
    market["close"] = pd.to_numeric(market["close"], errors="coerce")
    market = market.dropna(subset=["htsc_code", "time", "close"])
    if market.duplicated(["htsc_code", "time"]).any():
        raise ValueError("板块行情存在重复主键")
    return market.sort_values(["htsc_code", "time"]).reset_index(drop=True)


def add_forward_returns(
    panel: pd.DataFrame,
    market: pd.DataFrame,
    horizons: tuple[int, ...] = FORWARD_HORIZONS,
) -> tuple[pd.DataFrame, list[str]]:
    values = market[["htsc_code", "time", "close"]].copy()
    grouped_close = values.groupby("htsc_code", sort=False)["close"]
    targets = []
    for horizon in horizons:
        target = f"forward_return_{horizon}d"
        values[target] = grouped_close.shift(-horizon) / values["close"] - 1.0
        targets.append(target)
    merged = panel.merge(
        values[["htsc_code", "time", *targets]],
        on=["htsc_code", "time"],
        how="left",
        validate="one_to_one",
    )
    return merged, targets


def _rank_ic_block(
    block: pd.DataFrame,
    features: list[str],
    targets: list[str],
    min_count: int,
) -> np.ndarray:
    numeric = block[[*features, *targets]].replace([np.inf, -np.inf], np.nan)
    ranks = numeric.rank(method="average", na_option="keep")
    correlations = ranks.corr(method="pearson", min_periods=min_count)
    return correlations.loc[features, targets].to_numpy().reshape(-1)


def compute_daily_ic(
    frame: pd.DataFrame,
    features: list[str],
    targets: list[str],
    *,
    min_count: int = MIN_CROSS_SECTION,
    by_family: bool = False,
) -> pd.DataFrame:
    group_columns = ["time", "sector_family"] if by_family else ["time"]
    pair_index = pd.MultiIndex.from_product(
        [features, targets], names=["feature", "target"]
    )
    rows = []
    grouper = group_columns if len(group_columns) > 1 else group_columns[0]
    for key, block in frame.groupby(grouper, sort=True):
        values = _rank_ic_block(block, features, targets, min_count)
        if by_family:
            time, family = key
            prefix = {"time": time, "sector_family": family}
        else:
            prefix = {"time": key}
        result = pd.DataFrame(
            {
                **{column: value for column, value in prefix.items()},
                "feature": pair_index.get_level_values("feature"),
                "target": pair_index.get_level_values("target"),
                "rank_ic": values,
            }
        )
        rows.append(result)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _summarize_ic(values: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    valid = values.replace([np.inf, -np.inf], np.nan).dropna(subset=["rank_ic"])
    if valid.empty:
        return pd.DataFrame(columns=[*group_columns, "ic_mean", "ic_median", "valid_days"])
    return (
        valid.groupby(group_columns, sort=True)["rank_ic"]
        .agg(ic_mean="mean", ic_median="median", valid_days="count")
        .reset_index()
    )


def summarize_overall_ic(daily_ic: pd.DataFrame) -> pd.DataFrame:
    return _summarize_ic(daily_ic, ["feature", "target"])


def summarize_ic_breakdown(
    daily_ic: pd.DataFrame,
    family_daily_ic: pd.DataFrame,
) -> pd.DataFrame:
    annual = daily_ic.copy()
    annual["breakdown_type"] = "year"
    annual["breakdown_value"] = annual["time"].dt.year.astype(str)
    annual = _summarize_ic(
        annual,
        ["breakdown_type", "breakdown_value", "feature", "target"],
    )

    family = family_daily_ic.copy()
    family["breakdown_type"] = "sector_family"
    family["breakdown_value"] = family["sector_family"].astype(str)
    family = _summarize_ic(
        family,
        ["breakdown_type", "breakdown_value", "feature", "target"],
    )
    return pd.concat([annual, family], ignore_index=True)


def compute_quintile_monotonicity(
    frame: pd.DataFrame,
    features: list[str],
    targets: list[str],
    *,
    min_count: int = MIN_CROSS_SECTION,
) -> pd.DataFrame:
    rows = []
    date_indices = frame.groupby("time", sort=True).indices
    for feature in features:
        daily_means: dict[str, list[np.ndarray]] = {target: [] for target in targets}
        for indices in date_indices.values():
            block = frame.iloc[indices]
            factor = pd.to_numeric(block[feature], errors="coerce").replace(
                [np.inf, -np.inf], np.nan
            )
            valid_factor = factor.notna()
            if valid_factor.sum() < min_count or factor[valid_factor].nunique() < 5:
                continue
            percentile = factor[valid_factor].rank(method="average", pct=True)
            quintile = np.ceil(percentile * 5.0).clip(1, 5).astype(int)
            payload = block.loc[valid_factor, targets].copy()
            payload["quintile"] = quintile.to_numpy()
            means = payload.groupby("quintile", sort=True)[targets].mean().reindex(range(1, 6))
            for target in targets:
                if means[target].notna().all():
                    daily_means[target].append(means[target].to_numpy(dtype=float))
        for target in targets:
            arrays = daily_means[target]
            means = np.nanmean(np.vstack(arrays), axis=0) if arrays else np.full(5, np.nan)
            differences = np.diff(means)
            increasing_steps = int(np.sum(differences > 0)) if np.isfinite(means).all() else 0
            decreasing_steps = int(np.sum(differences < 0)) if np.isfinite(means).all() else 0
            best_steps = max(increasing_steps, decreasing_steps)
            direction = "increasing" if increasing_steps >= decreasing_steps else "decreasing"
            rows.append(
                {
                    "feature": feature,
                    "target": target,
                    "q1_mean": means[0],
                    "q2_mean": means[1],
                    "q3_mean": means[2],
                    "q4_mean": means[3],
                    "q5_mean": means[4],
                    "increasing_steps": increasing_steps,
                    "decreasing_steps": decreasing_steps,
                    "best_direction": direction,
                    "monotonicity_ratio": best_steps / 4.0,
                    "valid_days": len(arrays),
                }
            )
    return pd.DataFrame(rows)


def run_audit(
    *,
    panel_path: Path = DEFAULT_PANEL_PATH,
    market_path: Path = DEFAULT_MARKET_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    min_count: int = MIN_CROSS_SECTION,
) -> dict[str, object]:
    panel, features = load_panel(panel_path)
    market = load_market_close(market_path, panel["time"].min())
    frame, forward_targets = add_forward_returns(panel, market)
    targets = [*V2_TARGETS, *forward_targets]

    print(f"开始计算横截面 Rank IC：{len(features)} 个因子，{len(targets)} 个目标")
    daily_ic = compute_daily_ic(frame, features, targets, min_count=min_count)
    family_daily_ic = compute_daily_ic(
        frame, features, targets, min_count=min_count, by_family=True
    )
    overall = summarize_overall_ic(daily_ic)
    breakdown = summarize_ic_breakdown(daily_ic, family_daily_ic)

    print("开始计算五分组单调性")
    quintiles = compute_quintile_monotonicity(
        frame, features, targets, min_count=min_count
    )

    output_path.mkdir(parents=True, exist_ok=True)
    overall.to_csv(output_path / "factor_rank_ic.csv", index=False, encoding="utf-8-sig")
    breakdown.to_csv(output_path / "factor_ic_breakdown.csv", index=False, encoding="utf-8-sig")
    quintiles.to_csv(
        output_path / "factor_quintile_monotonicity.csv", index=False, encoding="utf-8-sig"
    )
    report = {
        "features": len(features),
        "targets": targets,
        "rows": len(frame),
        "min_date": frame["time"].min().strftime("%Y-%m-%d"),
        "max_date": frame["time"].max().strftime("%Y-%m-%d"),
        "overall_rows": len(overall),
        "breakdown_rows": len(breakdown),
        "quintile_rows": len(quintiles),
    }
    print(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="板块因子 V2 与未来收益 Rank IC 审计")
    parser.add_argument("--panel-path", type=Path, default=DEFAULT_PANEL_PATH)
    parser.add_argument("--market-path", type=Path, default=DEFAULT_MARKET_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--min-count", type=int, default=MIN_CROSS_SECTION)
    args = parser.parse_args()
    run_audit(**vars(args))


if __name__ == "__main__":
    main()
