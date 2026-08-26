"""仅用2016-2022开发期审计纯技术子组因子与V2变化目标。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_SUBGROUP_PATH = Path(
    r"D:\database\sector_peak_valley_ml\technical_subgroups_v1"
)
DEFAULT_TARGET_PATH = Path(
    r"D:\database\sector_peak_valley_ml\targets_v1\v2_change_targets.parquet"
)
DEFAULT_ELIGIBILITY_PATH = Path(
    "outputs/sector_peak_valley_ml/stage_o_technical_subgroups/technical_factor_eligibility.csv"
)
DEFAULT_OUTPUT_PATH = Path(
    "outputs/sector_peak_valley_ml/stage_p_technical_subgroup_audit"
)

KEYS = ["htsc_code", "time"]
FAMILY_COLUMN = "sector_family"
TARGETS = [
    "delta_peak_ultra_short",
    "delta_valley_ultra_short",
    "delta_peak_5d",
    "delta_valley_5d",
    "delta_peak_20d",
    "delta_valley_20d",
]
DEVELOPMENT_START = pd.Timestamp("2016-01-01")
DEVELOPMENT_END_EXCLUSIVE = pd.Timestamp("2023-01-01")
MIN_CROSS_SECTION = 20
GENERATOR_VERSION = "v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_eligible_features(eligibility_path: Path) -> dict[str, list[str]]:
    audit = pd.read_csv(eligibility_path, encoding="utf-8-sig")
    required = {"indicator", "feature", "eligible_for_model"}
    missing = required.difference(audit.columns)
    if missing:
        raise ValueError(f"技术因子资格表缺少字段: {sorted(missing)}")
    eligible = audit["eligible_for_model"].astype(str).str.lower().eq("true")
    return {
        str(indicator): group.loc[eligible.loc[group.index], "feature"].astype(str).tolist()
        for indicator, group in audit.groupby("indicator", sort=True)
    }


def load_development_frame(
    subgroup_path: Path,
    target_path: Path,
    indicator: str,
    features: list[str],
) -> pd.DataFrame:
    group = pd.read_parquet(
        subgroup_path / f"{indicator}.parquet",
        columns=[*KEYS, FAMILY_COLUMN, *features],
    )
    targets = pd.read_parquet(target_path, columns=[*KEYS, *TARGETS])
    for frame in (group, targets):
        frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
        frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
        if frame.duplicated(KEYS).any():
            raise ValueError(f"{indicator} 审计输入存在重复主键")
    merged = group.merge(targets, on=KEYS, how="inner", validate="one_to_one")
    merged = merged[
        (merged["time"] >= DEVELOPMENT_START)
        & (merged["time"] < DEVELOPMENT_END_EXCLUSIVE)
    ].copy()
    for column in [*features, *TARGETS]:
        merged[column] = pd.to_numeric(merged[column], errors="coerce")
    return merged.sort_values(["time", "htsc_code"]).reset_index(drop=True)


def _pairwise_rank_correlation(
    block: pd.DataFrame,
    features: list[str],
    targets: list[str],
    min_count: int,
) -> tuple[np.ndarray, np.ndarray]:
    ranked = block[[*features, *targets]].replace([np.inf, -np.inf], np.nan).rank(
        method="average", na_option="keep"
    )
    x = ranked[features].to_numpy(dtype=float)
    y = ranked[targets].to_numpy(dtype=float)
    mx = np.isfinite(x).astype(float)
    my = np.isfinite(y).astype(float)
    x0 = np.nan_to_num(x, nan=0.0)
    y0 = np.nan_to_num(y, nan=0.0)
    count = mx.T @ my
    sum_x = x0.T @ my
    sum_y = mx.T @ y0
    sum_x2 = (x0 * x0).T @ my
    sum_y2 = mx.T @ (y0 * y0)
    sum_xy = x0.T @ y0
    with np.errstate(divide="ignore", invalid="ignore"):
        covariance = sum_xy - sum_x * sum_y / count
        variance_x = sum_x2 - sum_x * sum_x / count
        variance_y = sum_y2 - sum_y * sum_y / count
        correlation = covariance / np.sqrt(variance_x * variance_y)
    correlation[(count < min_count) | ~np.isfinite(correlation)] = np.nan
    return correlation, count.astype(np.int64)


def compute_daily_ic(
    frame: pd.DataFrame,
    features: list[str],
    targets: list[str],
    *,
    min_count: int = MIN_CROSS_SECTION,
    by_family: bool = False,
) -> pd.DataFrame:
    grouping: str | list[str] = ["time", FAMILY_COLUMN] if by_family else "time"
    pieces = []
    for key, block in frame.groupby(grouping, sort=True):
        correlation, counts = _pairwise_rank_correlation(
            block, features, targets, min_count
        )
        payload = {
            "feature": np.repeat(features, len(targets)),
            "target": np.tile(targets, len(features)),
            "rank_ic": correlation.reshape(-1),
            "sample_count": counts.reshape(-1),
        }
        if by_family:
            time, family = key
            payload["time"] = time
            payload[FAMILY_COLUMN] = family
        else:
            payload["time"] = key
        pieces.append(pd.DataFrame(payload))
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()


def _summarise_ic(values: pd.DataFrame, grouping: list[str]) -> pd.DataFrame:
    valid = values.replace([np.inf, -np.inf], np.nan).dropna(subset=["rank_ic"])
    if valid.empty:
        return pd.DataFrame(columns=[*grouping, "ic_mean", "ic_median", "valid_days"])
    return (
        valid.groupby(grouping, sort=True)["rank_ic"]
        .agg(ic_mean="mean", ic_median="median", valid_days="count")
        .reset_index()
    )


def compute_quintile_monotonicity(
    frame: pd.DataFrame,
    features: list[str],
    targets: list[str],
    *,
    min_count: int = MIN_CROSS_SECTION,
) -> pd.DataFrame:
    total_means = np.zeros((len(features), len(targets), 5), dtype=float)
    valid_days = np.zeros((len(features), len(targets)), dtype=np.int64)
    for _, block in frame.groupby("time", sort=True):
        factor = block[features].replace([np.inf, -np.inf], np.nan)
        ranks = factor.rank(method="average", pct=True)
        quintiles = np.ceil(ranks.to_numpy(dtype=float) * 5.0)
        target = block[targets].to_numpy(dtype=float)
        target_valid = np.isfinite(target).astype(float)
        target_zero = np.nan_to_num(target, nan=0.0)
        day_means = np.full((len(features), len(targets), 5), np.nan)
        for quintile in range(1, 6):
            mask = (quintiles == quintile).astype(float)
            counts = mask.T @ target_valid
            sums = mask.T @ target_zero
            with np.errstate(divide="ignore", invalid="ignore"):
                day_means[:, :, quintile - 1] = sums / counts
        factor_counts = np.isfinite(factor.to_numpy(dtype=float)).sum(axis=0)
        complete = np.isfinite(day_means).all(axis=2) & (factor_counts[:, None] >= min_count)
        total_means += np.where(complete[:, :, None], day_means, 0.0)
        valid_days += complete.astype(np.int64)

    with np.errstate(divide="ignore", invalid="ignore"):
        means = total_means / valid_days[:, :, None]
    rows = []
    for feature_index, feature in enumerate(features):
        for target_index, target in enumerate(targets):
            values = means[feature_index, target_index]
            differences = np.diff(values)
            increasing = int(np.sum(differences > 0)) if np.isfinite(values).all() else 0
            decreasing = int(np.sum(differences < 0)) if np.isfinite(values).all() else 0
            rows.append(
                {
                    "feature": feature,
                    "target": target,
                    **{f"q{index + 1}_mean": values[index] for index in range(5)},
                    "increasing_steps": increasing,
                    "decreasing_steps": decreasing,
                    "best_direction": "increasing" if increasing >= decreasing else "decreasing",
                    "monotonicity_ratio": max(increasing, decreasing) / 4.0,
                    "valid_days": int(valid_days[feature_index, target_index]),
                }
            )
    return pd.DataFrame(rows)


def run_audit(
    *,
    subgroup_path: Path = DEFAULT_SUBGROUP_PATH,
    target_path: Path = DEFAULT_TARGET_PATH,
    eligibility_path: Path = DEFAULT_ELIGIBILITY_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    min_count: int = MIN_CROSS_SECTION,
) -> dict[str, object]:
    eligible_by_indicator = load_eligible_features(eligibility_path)
    output_path.mkdir(parents=True, exist_ok=True)
    overall_parts = []
    annual_parts = []
    family_parts = []
    quintile_parts = []
    source_hashes = {}
    for indicator, features in eligible_by_indicator.items():
        print(f"[技术因子审计] {indicator}: {len(features)}")
        frame = load_development_frame(subgroup_path, target_path, indicator, features)
        development_features = [
            feature for feature in features if frame[feature].nunique(dropna=True) >= 2
        ]
        if not development_features:
            raise RuntimeError(f"{indicator} 开发期没有非恒定因子")
        daily = compute_daily_ic(
            frame, development_features, TARGETS, min_count=min_count
        )
        daily_family = compute_daily_ic(
            frame,
            development_features,
            TARGETS,
            min_count=min_count,
            by_family=True,
        )
        overall = _summarise_ic(daily, ["feature", "target"])
        annual_values = daily.copy()
        annual_values["year"] = pd.to_datetime(annual_values["time"]).dt.year
        annual = _summarise_ic(annual_values, ["year", "feature", "target"])
        family = _summarise_ic(
            daily_family, [FAMILY_COLUMN, "feature", "target"]
        )
        quintile = compute_quintile_monotonicity(
            frame, development_features, TARGETS, min_count=min_count
        )
        for values in (overall, annual, family, quintile):
            values.insert(0, "indicator", indicator)
        overall_parts.append(overall)
        annual_parts.append(annual)
        family_parts.append(family)
        quintile_parts.append(quintile)
        source_hashes[indicator] = sha256_file(subgroup_path / f"{indicator}.parquet")

    overall = pd.concat(overall_parts, ignore_index=True)
    annual = pd.concat(annual_parts, ignore_index=True)
    family = pd.concat(family_parts, ignore_index=True)
    quintile = pd.concat(quintile_parts, ignore_index=True)
    files = {
        "factor_rank_ic_development": output_path / "factor_rank_ic_development.csv",
        "factor_rank_ic_annual_development": output_path / "factor_rank_ic_annual_development.csv",
        "factor_rank_ic_sector_family_development": output_path / "factor_rank_ic_sector_family_development.csv",
        "factor_quintile_development": output_path / "factor_quintile_development.csv",
    }
    for frame, path in zip((overall, annual, family, quintile), files.values()):
        frame.to_csv(path, index=False, encoding="utf-8-sig")
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "development_period": "2016-01-01 <= time < 2023-01-01",
        "test_period_policy": "2023+ sealed and not read for factor selection",
        "metrics": [
            "daily_cross_sectional_rank_ic",
            "annual_ic",
            "sector_family_ic",
            "daily_cross_sectional_quintile_monotonicity",
        ],
        "min_cross_section": min_count,
        "indicators": len(eligible_by_indicator),
        "features": int(overall["feature"].nunique()),
        "factor_target_pairs": int(len(overall)),
        "target_sha256": sha256_file(target_path),
        "eligibility_sha256": sha256_file(eligibility_path),
        "source_sha256": source_hashes,
        "outputs": {key: str(path) for key, path in files.items()},
        "output_sha256": {key: sha256_file(path) for key, path in files.items()},
    }
    (output_path / "technical_subgroup_audit_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="开发期纯技术子组V2变化目标审计")
    parser.add_argument("--subgroup-path", type=Path, default=DEFAULT_SUBGROUP_PATH)
    parser.add_argument("--target-path", type=Path, default=DEFAULT_TARGET_PATH)
    parser.add_argument("--eligibility-path", type=Path, default=DEFAULT_ELIGIBILITY_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--min-count", type=int, default=MIN_CROSS_SECTION)
    args = parser.parse_args()
    run_audit(**vars(args))


if __name__ == "__main__":
    main()
