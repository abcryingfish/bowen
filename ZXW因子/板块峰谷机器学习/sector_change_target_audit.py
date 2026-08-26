"""审计六组板块因子对三周期 V2 峰谷变化目标的横截面关系。

本阶段只输出四类研究指标：
1. 每日横截面 Rank IC；
2. 按自然年的 IC 汇总；
3. 按板块族（881/885/886）汇总的 IC；
4. 每日五分组的目标均值与单调性。

目标列全部来自离线 V2 变化目标文件，不能进入因子面板。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_GROUP_PATH = Path(r"D:\database\sector_peak_valley_ml\factor_groups_v1")
DEFAULT_TARGET_PATH = Path(
    r"D:\database\sector_peak_valley_ml\targets_v1\v2_change_targets.parquet"
)
DEFAULT_CONFIG_PATH = Path(__file__).with_name("sector_factor_groups_v1.json")
DEFAULT_OUTPUT_PATH = Path(
    "outputs/sector_peak_valley_ml/stage_n_factor_group_change_audit"
)

KEYS = ["htsc_code", "time"]
FAMILY_COLUMN = "sector_family"
TARGETS_BY_HORIZON = {
    "ultra_short": ("delta_peak_ultra_short", "delta_valley_ultra_short"),
    "5d": ("delta_peak_5d", "delta_valley_5d"),
    "20d": ("delta_peak_20d", "delta_valley_20d"),
}
GROUP_FILES = (
    "technical_trend",
    "sideways_volatility",
    "relative_strength",
    "constituent_breadth",
    "leader_diffusion",
    "hot_sentiment",
)
MIN_CROSS_SECTION = 20
GENERATOR_VERSION = "v2_hot_rank_change_short_audit"
HOT_RANK_CHANGE_FEATURES = (
    "popularity_rank_improvement_per_day",
    "popularity_rank_improvement_1d_mean",
    "popularity_rank_improvement_3d_mean",
    "popularity_rank_improvement_5d_mean",
)
HOT_SHORT_TARGETS = (
    "delta_peak_ultra_short",
    "delta_valley_ultra_short",
    "delta_peak_5d",
    "delta_valley_5d",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_keys(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["htsc_code"] = result["htsc_code"].astype(str).str.strip().str.upper()
    result["time"] = pd.to_datetime(result["time"], errors="coerce").dt.floor("D")
    if result[KEYS].isna().any().any():
        raise ValueError("审计输入主键包含缺失值")
    if result.duplicated(KEYS).any():
        raise ValueError("审计输入存在重复主键")
    return result


def load_targets(target_path: Path) -> pd.DataFrame:
    target_columns = [column for values in TARGETS_BY_HORIZON.values() for column in values]
    frame = _normalise_keys(pd.read_parquet(target_path, columns=[*KEYS, *target_columns]))
    for column in target_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if np.isinf(frame[target_columns].to_numpy(dtype=float)).any():
        raise ValueError("V2 变化目标包含无穷值")
    return frame.sort_values(["time", "htsc_code"]).reset_index(drop=True)


def load_group(group_path: Path, group_id: str) -> tuple[pd.DataFrame, list[str]]:
    path = group_path / f"{group_id}.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"因子组文件不存在: {path}")
    frame = _normalise_keys(pd.read_parquet(path))
    required = {FAMILY_COLUMN}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{group_id} 缺少字段: {sorted(missing)}")
    frame[FAMILY_COLUMN] = frame[FAMILY_COLUMN].astype(str).str.strip()
    features = [column for column in frame.columns if column not in {*KEYS, FAMILY_COLUMN}]
    if not features:
        raise ValueError(f"{group_id} 没有可审计因子")
    for column in features:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values(["time", "htsc_code"]).reset_index(drop=True), features


def merge_group_targets(
    group: pd.DataFrame, targets: pd.DataFrame
) -> pd.DataFrame:
    merged = group.merge(
        targets,
        on=KEYS,
        how="left",
        validate="one_to_one",
        suffixes=("", "_target"),
    )
    if merged[FAMILY_COLUMN].isna().all():
        raise ValueError("因子组没有板块族字段")
    return merged.sort_values(["time", "htsc_code"]).reset_index(drop=True)


def _rank_ic_for_block(
    block: pd.DataFrame,
    features: list[str],
    targets: list[str],
    min_count: int,
) -> tuple[np.ndarray, np.ndarray]:
    numeric = block[[*features, *targets]].replace([np.inf, -np.inf], np.nan)
    ranks = numeric.rank(method="average", na_option="keep")
    correlation = ranks.corr(method="pearson", min_periods=min_count)
    valid_counts = np.zeros((len(features), len(targets)), dtype=np.int64)
    values = numeric[features].notna().astype(np.int64).T.dot(
        numeric[targets].notna().astype(np.int64)
    )
    valid_counts[:, :] = values.to_numpy(dtype=np.int64)
    return correlation.loc[features, targets].to_numpy(dtype=float), valid_counts


def compute_daily_rank_ic(
    frame: pd.DataFrame,
    features: list[str],
    targets: list[str],
    *,
    min_count: int = MIN_CROSS_SECTION,
    by_family: bool = False,
) -> pd.DataFrame:
    grouping: str | list[str] = ["time", FAMILY_COLUMN] if by_family else "time"
    rows: list[dict[str, object]] = []
    for key, block in frame.groupby(grouping, sort=True, dropna=False):
        correlation, counts = _rank_ic_for_block(block, features, targets, min_count)
        if by_family:
            time, family = key
        else:
            time, family = key, None
        for feature_index, feature in enumerate(features):
            for target_index, target in enumerate(targets):
                rows.append(
                    {
                        "time": time,
                        FAMILY_COLUMN: family,
                        "feature": feature,
                        "target": target,
                        "rank_ic": correlation[feature_index, target_index],
                        "sample_count": int(counts[feature_index, target_index]),
                    }
                )
    return pd.DataFrame(rows)


def _summarise_ic(values: pd.DataFrame, grouping: list[str]) -> pd.DataFrame:
    if values.empty:
        return pd.DataFrame(
            columns=[*grouping, "ic_mean", "ic_median", "valid_days"]
        )
    valid = values.replace([np.inf, -np.inf], np.nan).dropna(subset=["rank_ic"])
    if valid.empty:
        return pd.DataFrame(
            columns=[*grouping, "ic_mean", "ic_median", "valid_days"]
        )
    return (
        valid.groupby(grouping, sort=True)["rank_ic"]
        .agg(ic_mean="mean", ic_median="median", valid_days="count")
        .reset_index()
    )


def summarise_daily_ic(daily_ic: pd.DataFrame) -> pd.DataFrame:
    return _summarise_ic(daily_ic, ["feature", "target"])


def summarise_annual_ic(daily_ic: pd.DataFrame) -> pd.DataFrame:
    values = daily_ic.copy()
    values["year"] = pd.to_datetime(values["time"]).dt.year.astype(int)
    return _summarise_ic(values, ["year", "feature", "target"])


def summarise_family_ic(daily_family_ic: pd.DataFrame) -> pd.DataFrame:
    return _summarise_ic(
        daily_family_ic, [FAMILY_COLUMN, "feature", "target"]
    )


def compute_quintile_monotonicity(
    frame: pd.DataFrame,
    features: list[str],
    targets: list[str],
    *,
    min_count: int = MIN_CROSS_SECTION,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
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
            ranks = factor[valid_factor].rank(method="average", pct=True)
            quintiles = np.ceil(ranks * 5.0).clip(1, 5).astype(int)
            payload = block.loc[valid_factor, targets].copy()
            payload.insert(0, "quintile", quintiles.to_numpy())
            means = payload.groupby("quintile", sort=True)[targets].mean().reindex(range(1, 6))
            for target in targets:
                if means[target].notna().all():
                    daily_means[target].append(means[target].to_numpy(dtype=float))
        for target in targets:
            target_daily_means = daily_means[target]
            values = (
                np.nanmean(np.vstack(target_daily_means), axis=0)
                if target_daily_means
                else np.full(5, np.nan)
            )
            differences = np.diff(values)
            increasing_steps = (
                int(np.sum(differences > 0)) if np.isfinite(values).all() else 0
            )
            decreasing_steps = (
                int(np.sum(differences < 0)) if np.isfinite(values).all() else 0
            )
            direction = (
                "increasing" if increasing_steps >= decreasing_steps else "decreasing"
            )
            rows.append(
                {
                    "feature": feature,
                    "target": target,
                    "q1_mean": values[0],
                    "q2_mean": values[1],
                    "q3_mean": values[2],
                    "q4_mean": values[3],
                    "q5_mean": values[4],
                    "increasing_steps": increasing_steps,
                    "decreasing_steps": decreasing_steps,
                    "best_direction": direction,
                    "monotonicity_ratio": max(increasing_steps, decreasing_steps) / 4.0,
                    "valid_days": len(target_daily_means),
                }
            )
    return pd.DataFrame(rows)


def _hot_train_test_summary(
    daily_ic: pd.DataFrame,
    frame: pd.DataFrame,
    *,
    min_count: int,
) -> pd.DataFrame:
    valid_dates = (
        frame.loc[frame["sentiment_valid_count"].fillna(0) > 0, "time"]
        .drop_duplicates()
        .sort_values()
    )
    if len(valid_dates) < 2:
        return pd.DataFrame()
    split_date = valid_dates.iloc[len(valid_dates) // 2]
    values = daily_ic.copy()
    values["sample"] = np.where(values["time"] < split_date, "train", "test")
    result = _summarise_ic(values, ["sample", "feature", "target"])
    result.insert(0, "split_date", split_date.strftime("%Y-%m-%d"))
    result.attrs["split_date"] = split_date.strftime("%Y-%m-%d")
    result.attrs["train_end"] = (split_date - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    result.attrs["min_count"] = min_count
    return result


def summarise_hot_rank_change_short(
    hot_train_test: pd.DataFrame,
) -> pd.DataFrame:
    """提取热点排名变动因子的短周期 train/test Rank IC。"""

    if hot_train_test.empty:
        return pd.DataFrame()
    required = {"sample", "feature", "target", "ic_mean"}
    missing = required.difference(hot_train_test.columns)
    if missing:
        raise ValueError(f"热点排名变动审计缺少字段: {sorted(missing)}")
    return hot_train_test.loc[
        hot_train_test["feature"].isin(HOT_RANK_CHANGE_FEATURES)
        & hot_train_test["target"].isin(HOT_SHORT_TARGETS)
    ].sort_values(["sample", "feature", "target"]).reset_index(drop=True)


def run_audit(
    *,
    group_path: Path = DEFAULT_GROUP_PATH,
    target_path: Path = DEFAULT_TARGET_PATH,
    config_path: Path = DEFAULT_CONFIG_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    min_count: int = MIN_CROSS_SECTION,
) -> dict[str, object]:
    if min_count < 5:
        raise ValueError("min_count 不能小于 5")
    targets = load_targets(target_path)
    output_path.mkdir(parents=True, exist_ok=True)
    all_overall: list[pd.DataFrame] = []
    all_annual: list[pd.DataFrame] = []
    all_family: list[pd.DataFrame] = []
    all_quintiles: list[pd.DataFrame] = []
    hot_split: pd.DataFrame | None = None
    hot_rank_change_short: pd.DataFrame | None = None
    group_reports: list[dict[str, object]] = []

    for group_id in GROUP_FILES:
        print(f"[审计] {group_id}")
        group, features = load_group(group_path, group_id)
        frame = merge_group_targets(group, targets)
        target_columns = [column for values in TARGETS_BY_HORIZON.values() for column in values]
        daily = compute_daily_rank_ic(frame, features, target_columns, min_count=min_count)
        daily_family = compute_daily_rank_ic(
            frame, features, target_columns, min_count=min_count, by_family=True
        )
        overall = summarise_daily_ic(daily)
        annual = summarise_annual_ic(daily)
        family = summarise_family_ic(daily_family)
        quintiles = compute_quintile_monotonicity(
            frame, features, target_columns, min_count=min_count
        )
        for values in (overall, annual, family, quintiles):
            values.insert(0, "group_id", group_id)
        all_overall.append(overall)
        all_annual.append(annual)
        all_family.append(family)
        all_quintiles.append(quintiles)
        if group_id == "hot_sentiment":
            hot_split = _hot_train_test_summary(daily, frame, min_count=min_count)
            hot_rank_change_short = summarise_hot_rank_change_short(hot_split)
        group_reports.append(
            {
                "group_id": group_id,
                "input_sha256": sha256_file(group_path / f"{group_id}.parquet"),
                "features": len(features),
                "rows": len(frame),
                "valid_feature_rows": int(frame[features].notna().any(axis=1).sum()),
                "min_date": frame["time"].min().strftime("%Y-%m-%d"),
                "max_date": frame["time"].max().strftime("%Y-%m-%d"),
            }
        )

    overall = pd.concat(all_overall, ignore_index=True)
    annual = pd.concat(all_annual, ignore_index=True)
    family = pd.concat(all_family, ignore_index=True)
    quintiles = pd.concat(all_quintiles, ignore_index=True)
    overall.to_csv(output_path / "factor_rank_ic.csv", index=False, encoding="utf-8-sig")
    annual.to_csv(output_path / "factor_rank_ic_annual.csv", index=False, encoding="utf-8-sig")
    family.to_csv(output_path / "factor_rank_ic_sector_family.csv", index=False, encoding="utf-8-sig")
    quintiles.to_csv(
        output_path / "factor_quintile_monotonicity.csv", index=False, encoding="utf-8-sig"
    )
    if hot_split is not None and not hot_split.empty:
        hot_split.to_csv(output_path / "hot_sentiment_train_test.csv", index=False, encoding="utf-8-sig")
    if hot_rank_change_short is not None and not hot_rank_change_short.empty:
        hot_rank_change_short.to_csv(
            output_path / "hot_rank_change_short_train_test.csv",
            index=False,
            encoding="utf-8-sig",
        )

    config_hash = sha256_file(config_path) if config_path.is_file() else None
    output_files = {
        "factor_rank_ic": output_path / "factor_rank_ic.csv",
        "factor_rank_ic_annual": output_path / "factor_rank_ic_annual.csv",
        "factor_rank_ic_sector_family": output_path / "factor_rank_ic_sector_family.csv",
        "factor_quintile_monotonicity": output_path / "factor_quintile_monotonicity.csv",
    }
    if hot_split is not None and not hot_split.empty:
        output_files["hot_sentiment_train_test"] = output_path / "hot_sentiment_train_test.csv"
    if hot_rank_change_short is not None and not hot_rank_change_short.empty:
        output_files["hot_rank_change_short_train_test"] = (
            output_path / "hot_rank_change_short_train_test.csv"
        )
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "group_path": str(group_path),
        "target_path": str(target_path),
        "target_sha256": sha256_file(target_path),
        "config_path": str(config_path),
        "config_sha256": config_hash,
        "min_cross_section": min_count,
        "group_count": len(GROUP_FILES),
        "target_count": sum(len(values) for values in TARGETS_BY_HORIZON.values()),
        "metrics": ["daily_cross_sectional_rank_ic", "annual_ic", "sector_family_ic", "quintile_monotonicity"],
        "hot_sentiment_split": (
            {"split_date": hot_split.attrs.get("split_date")} if hot_split is not None and not hot_split.empty else None
        ),
        "hot_rank_change_policy": "short-cycle audit of stock popularity rank movement; positive prior_rank-current_rank means improving popularity; test targets are ultra_short and 5d",
        "groups": group_reports,
        "outputs": {key: str(path) for key, path in output_files.items()},
        "output_sha256": {key: sha256_file(path) for key, path in output_files.items()},
    }
    (output_path / "audit_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="审计板块六组因子与三周期 V2 变化目标")
    parser.add_argument("--group-path", type=Path, default=DEFAULT_GROUP_PATH)
    parser.add_argument("--target-path", type=Path, default=DEFAULT_TARGET_PATH)
    parser.add_argument("--config-path", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--min-count", type=int, default=MIN_CROSS_SECTION)
    args = parser.parse_args()
    run_audit(**vars(args))


if __name__ == "__main__":
    main()
