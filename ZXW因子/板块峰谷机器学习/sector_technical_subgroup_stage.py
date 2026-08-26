"""从板块连续行情构建18个纯技术指标子组面板。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import polars as pl


MODULE_DIR = Path(__file__).resolve().parent
FACTOR_DIR = MODULE_DIR.parent
if str(FACTOR_DIR) not in sys.path:
    sys.path.append(str(FACTOR_DIR))

from 纯技术面因子_bundle import (  # noqa: E402
    INDICATOR_NAMES,
    get_factor_catalog,
    iter_pure_technical_factor_bundles,
)


DEFAULT_MARKET_PATH = Path(r"D:\database\index_data_daily")
DEFAULT_TARGET_PATH = Path(
    r"D:\database\sector_peak_valley_ml\targets_v1\v2_change_targets.parquet"
)
DEFAULT_OUTPUT_PATH = Path(
    r"D:\database\sector_peak_valley_ml\technical_subgroups_v1"
)
DEFAULT_REPORT_PATH = Path(
    "outputs/sector_peak_valley_ml/stage_o_technical_subgroups"
)
DEFAULT_CATALOG_CACHE = Path(
    r"D:\database\signal_daily\_meta\pure_technical_factor_catalog_cache.json"
)

KEYS = ["htsc_code", "time"]
SECTOR_PREFIXES = ("881", "885", "886")
GENERATOR_VERSION = "v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _market_glob(base_path: Path) -> str:
    return str(base_path / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")


def load_target_keys(target_path: Path) -> pd.DataFrame:
    keys = pd.read_parquet(target_path, columns=KEYS)
    keys["htsc_code"] = keys["htsc_code"].astype(str).str.strip().str.upper()
    keys["time"] = pd.to_datetime(keys["time"], errors="coerce").dt.floor("D")
    if keys[KEYS].isna().any().any():
        raise ValueError("目标主键包含缺失值")
    if keys.duplicated(KEYS).any():
        raise ValueError("目标文件存在重复主键")
    keys["sector_family"] = keys["htsc_code"].str[:3]
    return keys.sort_values(["time", "htsc_code"]).reset_index(drop=True)


def load_sector_ohlcv(market_path: Path, end_date: pd.Timestamp) -> pd.DataFrame:
    conditions = " OR ".join("htsc_code LIKE ?" for _ in SECTOR_PREFIXES)
    params = [
        _market_glob(market_path),
        end_date.strftime("%Y-%m-%d"),
        *(f"{prefix}%" for prefix in SECTOR_PREFIXES),
    ]
    with duckdb.connect() as con:
        market = con.execute(
            f"""
            SELECT
                UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                CAST(time AS DATE) AS time,
                MAX(TRY_CAST(open AS DOUBLE)) AS open,
                MAX(TRY_CAST(high AS DOUBLE)) AS high,
                MAX(TRY_CAST(low AS DOUBLE)) AS low,
                MAX(TRY_CAST(close AS DOUBLE)) AS close,
                MAX(TRY_CAST(volume AS DOUBLE)) AS volume
            FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
            WHERE CAST(time AS DATE) <= CAST(? AS DATE)
              AND ({conditions})
            GROUP BY 1, 2
            ORDER BY 1, 2
            """,
            params,
        ).df()
    market["time"] = pd.to_datetime(market["time"], errors="coerce").dt.floor("D")
    for column in ("open", "high", "low", "close", "volume"):
        market[column] = pd.to_numeric(market[column], errors="coerce")
    market = market.dropna(subset=[*KEYS, "open", "high", "low", "close"])
    invalid = (
        (market[["open", "high", "low", "close"]] <= 0).any(axis=1)
        | (market["high"] < market[["open", "close", "low"]].max(axis=1))
        | (market["low"] > market[["open", "close", "high"]].min(axis=1))
    )
    if invalid.any():
        raise ValueError(f"板块行情存在 {int(invalid.sum())} 行非法 OHLC")
    if market.duplicated(KEYS).any():
        raise ValueError("板块行情存在重复主键")
    return market.sort_values(["time", "htsc_code"]).reset_index(drop=True)


def build_market_matrices(
    market: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    dates = pd.DatetimeIndex(sorted(market["time"].unique()))
    codes = pd.Index(sorted(market["htsc_code"].unique()))
    matrices: dict[str, pd.DataFrame] = {}
    for column in ("open", "high", "low", "close", "volume"):
        matrices[column] = (
            market.pivot(index="time", columns="htsc_code", values=column)
            .reindex(index=dates, columns=codes)
            .astype(float)
        )
    valid_bar = matrices["close"].notna()
    for column in ("open", "high", "low"):
        valid_bar &= matrices[column].notna()
    matrices["volume"] = matrices["volume"].fillna(0.0)
    return matrices, valid_bar


def extract_target_rows(
    matrix: pd.DataFrame,
    target_keys: pd.DataFrame,
) -> np.ndarray:
    row_positions = matrix.index.get_indexer(target_keys["time"])
    column_positions = matrix.columns.get_indexer(target_keys["htsc_code"])
    missing = (row_positions < 0) | (column_positions < 0)
    values = np.full(len(target_keys), np.nan, dtype=float)
    if (~missing).any():
        payload = matrix.to_numpy(dtype=float, copy=False)
        values[~missing] = payload[row_positions[~missing], column_positions[~missing]]
    return values


def audit_subgroup(
    frame: pd.DataFrame,
    indicator: str,
    features: list[str],
) -> tuple[pd.DataFrame, dict[str, object]]:
    rows = []
    for feature in features:
        series = pd.to_numeric(frame[feature], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        valid = series.notna()
        unique_values = int(series.nunique(dropna=True))
        forbidden = any(
            token in feature.lower()
            for token in ("label", "future", "未来", "事后", "peak_strength", "valley_strength")
        )
        rows.append(
            {
                "indicator": indicator,
                "feature": feature,
                "rows": int(valid.sum()),
                "coverage": float(valid.mean()),
                "unique_values": unique_values,
                "constant": unique_values < 2,
                "forbidden_name": forbidden,
                "eligible_for_model": bool(unique_values >= 2 and not forbidden),
                "min": float(series.min()) if valid.any() else np.nan,
                "max": float(series.max()) if valid.any() else np.nan,
            }
        )
    audit = pd.DataFrame(rows)
    eligible = audit.loc[audit["eligible_for_model"], "feature"].tolist()
    report = {
        "indicator": indicator,
        "rows": int(len(frame)),
        "features": len(features),
        "eligible_features": len(eligible),
        "eligible_feature_names": eligible,
        "all_missing_or_constant": int(audit["constant"].sum()),
        "forbidden_features": int(audit["forbidden_name"].sum()),
        "valid_rows": int(frame[features].notna().any(axis=1).sum()),
    }
    return audit, report


def build_technical_subgroups(
    *,
    market_path: Path = DEFAULT_MARKET_PATH,
    target_path: Path = DEFAULT_TARGET_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    catalog_cache: Path = DEFAULT_CATALOG_CACHE,
    indicators: tuple[str, ...] = INDICATOR_NAMES,
) -> dict[str, object]:
    target_keys = load_target_keys(target_path)
    market = load_sector_ohlcv(market_path, target_keys["time"].max())
    matrices, valid_bar = build_market_matrices(market)
    catalog = get_factor_catalog(cache_path=catalog_cache)
    catalog_groups = {
        str(group["indicator"]): list(group["children"])
        for group in catalog["groups"]
    }
    unknown = sorted(set(indicators).difference(catalog_groups))
    if unknown:
        raise ValueError(f"目录缺少指标组: {unknown}")

    output_path.mkdir(parents=True, exist_ok=True)
    report_path.mkdir(parents=True, exist_ok=True)
    audit_frames: list[pd.DataFrame] = []
    subgroup_reports: list[dict[str, object]] = []
    for indicator in indicators:
        print(f"[技术子组] {indicator}")
        outputs = list(
            iter_pure_technical_factor_bundles(
                O=matrices["open"],
                H=matrices["high"],
                L=matrices["low"],
                C=matrices["close"],
                V=matrices["volume"],
                H_adj=matrices["high"],
                L_adj=matrices["low"],
                C_adj=matrices["close"],
                valid_bar=valid_bar,
                selected_indicators=[indicator],
            )
        )
        if len(outputs) != 1:
            raise RuntimeError(f"{indicator} 预期1个输出，实际{len(outputs)}个")
        factor_dfs = dict(outputs[0]["factor_dfs"])
        expected = catalog_groups[indicator]
        if set(factor_dfs) != set(expected):
            raise ValueError(
                f"{indicator} 输出与目录不一致: "
                f"缺少={sorted(set(expected).difference(factor_dfs))}, "
                f"多出={sorted(set(factor_dfs).difference(expected))}"
            )
        frame = target_keys[[*KEYS, "sector_family"]].copy()
        for feature in expected:
            frame[feature] = extract_target_rows(factor_dfs[feature], target_keys)
        if frame.duplicated(KEYS).any():
            raise ValueError(f"{indicator} 输出存在重复主键")
        audit, subgroup_report = audit_subgroup(frame, indicator, expected)
        subgroup_path = output_path / f"{indicator}.parquet"
        pl.from_pandas(frame, include_index=False).write_parquet(
            subgroup_path, compression="zstd"
        )
        subgroup_report["output_path"] = str(subgroup_path)
        subgroup_report["output_sha256"] = sha256_file(subgroup_path)
        audit_frames.append(audit)
        subgroup_reports.append(subgroup_report)
        del factor_dfs, frame

    factor_audit = pd.concat(audit_frames, ignore_index=True)
    factor_audit.to_csv(
        report_path / "technical_factor_eligibility.csv",
        index=False,
        encoding="utf-8-sig",
    )
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "source_policy": "compute_from_continuous_ths_sector_ohlcv_with_pure_technical_bundle",
        "price_adjustment": "sector_index_continuous_ohlc_no_stock_adjustment_factor",
        "market_path": str(market_path),
        "market_min_date": market["time"].min().strftime("%Y-%m-%d"),
        "market_max_date": market["time"].max().strftime("%Y-%m-%d"),
        "target_path": str(target_path),
        "target_sha256": sha256_file(target_path),
        "catalog_cache": str(catalog_cache),
        "catalog_cache_sha256": sha256_file(catalog_cache),
        "rows": int(len(target_keys)),
        "codes": int(target_keys["htsc_code"].nunique()),
        "subgroups": len(subgroup_reports),
        "features": int(factor_audit.shape[0]),
        "eligible_features": int(factor_audit["eligible_for_model"].sum()),
        "subgroup_details": subgroup_reports,
    }
    (report_path / "technical_subgroup_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="构建板块纯技术18个指标子组面板")
    parser.add_argument("--market-path", type=Path, default=DEFAULT_MARKET_PATH)
    parser.add_argument("--target-path", type=Path, default=DEFAULT_TARGET_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--catalog-cache", type=Path, default=DEFAULT_CATALOG_CACHE)
    parser.add_argument("--indicators", default=",".join(INDICATOR_NAMES))
    args = parser.parse_args()
    args.indicators = tuple(
        value.strip().upper() for value in args.indicators.split(",") if value.strip()
    )
    build_technical_subgroups(**vars(args))


if __name__ == "__main__":
    main()
