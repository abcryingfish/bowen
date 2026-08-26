"""构建市场状态条件化板块因子组。

纯大盘状态对同一交易日所有板块相同，不能直接作为横截面因子。
本模块将历史可得的指数/板块市场状态与板块自身特征相乘，形成每日
仍具备板块间差异的条件化因子，供独立模型审计。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import polars as pl


INDEX_PATH = Path(r"D:\database\index_data_daily")
TECH_PATH = Path(r"D:\database\sector_peak_valley_ml\factor_groups_v1\technical_trend.parquet")
SIDEWAYS_PATH = Path(r"D:\database\sector_peak_valley_ml\factor_groups_v1\sideways_volatility.parquet")
RS_PATH = Path(r"D:\database\sector_peak_valley_ml\factor_groups_v1\relative_strength.parquet")
BREADTH_PATH = Path(r"D:\database\sector_peak_valley_ml\factor_groups_v1\constituent_breadth.parquet")
OUTPUT_PATH = Path(r"D:\database\sector_peak_valley_ml\factor_groups_v1\market_state_conditioned.parquet")
KEYS = ["htsc_code", "time"]
FAMILY = "sector_family"
INDEX_CODES = ("000001.SH", "399001.SZ")
SECTOR_PREFIXES = ("881", "885", "886")
GENERATOR_VERSION = "v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_prices(index_path: Path) -> pd.DataFrame:
    glob = str(index_path / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")
    codes = list(INDEX_CODES)
    with duckdb.connect() as con:
        frame = con.execute(
            """
            SELECT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                   CAST(time AS DATE) AS time,
                   TRY_CAST(close AS DOUBLE) AS close
            FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
            WHERE (htsc_code IN (?, ?) OR htsc_code LIKE '881%' OR htsc_code LIKE '885%' OR htsc_code LIKE '886%')
              AND TRY_CAST(close AS DOUBLE) > 0
            """,
            [glob, *codes],
        ).df()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    if frame.duplicated(KEYS).any():
        raise ValueError("指数/板块行情存在重复主键")
    return frame.dropna(subset=[*KEYS, "close"]).sort_values(["htsc_code", "time"]).reset_index(drop=True)


def build_market_state(prices: pd.DataFrame) -> pd.DataFrame:
    indices = prices[prices["htsc_code"].isin(INDEX_CODES)].pivot(index="time", columns="htsc_code", values="close").sort_index()
    indices = indices.ffill()
    returns_1d = indices.pct_change()
    state = pd.DataFrame(index=indices.index)
    for days in (1, 5, 20, 60):
        state[f"market_return_{days}d"] = indices.pct_change(days).mean(axis=1)
    state["market_volatility_20d"] = returns_1d.rolling(20, min_periods=20).std().mean(axis=1) * np.sqrt(252.0)
    state["market_volatility_60d"] = returns_1d.rolling(60, min_periods=60).std().mean(axis=1) * np.sqrt(252.0)
    ma20 = indices.rolling(20, min_periods=20).mean()
    ma60 = indices.rolling(60, min_periods=60).mean()
    state["market_trend_ma20_ma60"] = (ma20 / ma60 - 1.0).mean(axis=1)
    state["market_above_ma20_ratio"] = (indices > ma20).mean(axis=1)

    sectors = prices[prices["htsc_code"].str.startswith(SECTOR_PREFIXES)].copy()
    grouped = sectors.groupby("htsc_code", sort=False)["close"]
    sectors["return_1d"] = grouped.pct_change()
    sectors["return_5d"] = grouped.pct_change(5)
    sectors["return_20d"] = grouped.pct_change(20)
    sectors["ma20"] = grouped.transform(lambda values: values.rolling(20, min_periods=20).mean())
    sectors["high20"] = grouped.transform(lambda values: values.rolling(20, min_periods=20).max())
    sectors["low20"] = grouped.transform(lambda values: values.rolling(20, min_periods=20).min())
    breadth = sectors.groupby("time", sort=True).agg(
        market_breadth_up_1d=("return_1d", lambda values: float((values > 0).mean())),
        market_breadth_positive_5d=("return_5d", lambda values: float((values > 0).mean())),
        market_breadth_above_ma20=("close", lambda values: np.nan),
        market_new_high_ratio_20d=("close", lambda values: np.nan),
        market_new_low_ratio_20d=("close", lambda values: np.nan),
        market_return_dispersion_20d=("return_20d", "std"),
    )
    for name, expression in (
        ("market_breadth_above_ma20", sectors["close"] > sectors["ma20"]),
        ("market_new_high_ratio_20d", sectors["close"] >= sectors["high20"]),
        ("market_new_low_ratio_20d", sectors["close"] <= sectors["low20"]),
    ):
        breadth[name] = expression.groupby(sectors["time"]).mean()
    state = state.join(breadth, how="left").reset_index()
    state["time"] = pd.to_datetime(state["time"]).dt.floor("D")
    return state


def build_conditioned_group(tech_path: Path, sideways_path: Path, rs_path: Path, breadth_path: Path, prices: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    tech_cols = ["120日动量", "60日动量", "mkt_momentum_20d", "mkt_momentum_60d"]
    sideways_cols = ["60日年化波动率", "20日新高占比", "20日新低占比"]
    rs_cols = ["rs_vs_all_20d", "strength_pct_all_20d", "residual_strength_20d"]
    breadth_cols = ["constituent_up_ratio_1d", "constituent_positive_return_ratio_5d", "constituent_above_ma20_ratio"]
    tech = pd.read_parquet(tech_path, columns=[*KEYS, FAMILY, *tech_cols])
    sideways = pd.read_parquet(sideways_path, columns=[*KEYS, *sideways_cols])
    relative = pd.read_parquet(rs_path, columns=[*KEYS, *rs_cols])
    breadth = pd.read_parquet(breadth_path, columns=[*KEYS, *breadth_cols])
    frame = tech.merge(sideways, on=KEYS, how="inner", validate="one_to_one").merge(relative, on=KEYS, how="inner", validate="one_to_one").merge(breadth, on=KEYS, how="inner", validate="one_to_one")
    state = build_market_state(prices)
    frame["time"] = pd.to_datetime(frame["time"]).dt.floor("D")
    frame = frame.merge(state, on="time", how="left", validate="many_to_one")
    sources = {
        "sector_momentum_20d": "mkt_momentum_20d",
        "sector_momentum_60d": "mkt_momentum_60d",
        "sector_relative_strength_20d": "rs_vs_all_20d",
        "sector_volatility_60d": "60日年化波动率",
        "sector_new_high_ratio_20d": "20日新高占比",
        "sector_new_low_ratio_20d": "20日新低占比",
        "sector_constituent_up_ratio_1d": "constituent_up_ratio_1d",
        "sector_constituent_positive_5d": "constituent_positive_return_ratio_5d",
        "sector_constituent_above_ma20": "constituent_above_ma20_ratio",
    }
    global_states = ["market_return_20d", "market_return_60d", "market_volatility_20d", "market_breadth_up_1d", "market_breadth_above_ma20", "market_return_dispersion_20d"]
    features = []
    for output_name, source_name in sources.items():
        for state_name in global_states:
            feature = f"{output_name}_x_{state_name}"
            frame[feature] = pd.to_numeric(frame[source_name], errors="coerce") * pd.to_numeric(frame[state_name], errors="coerce")
            features.append(feature)
    result = frame[[*KEYS, FAMILY, *features]].copy()
    result["sector_family"] = result["sector_family"].astype(str).str.strip()
    result = result.sort_values(["time", "htsc_code"]).reset_index(drop=True)
    if result.duplicated(KEYS).any():
        raise ValueError("市场状态条件化因子存在重复主键")
    return result, features


def run(*, index_path: Path = INDEX_PATH, tech_path: Path = TECH_PATH, sideways_path: Path = SIDEWAYS_PATH, rs_path: Path = RS_PATH, breadth_path: Path = BREADTH_PATH, output_path: Path = OUTPUT_PATH) -> dict[str, object]:
    prices = load_prices(index_path)
    result, features = build_conditioned_group(tech_path, sideways_path, rs_path, breadth_path, prices)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pl.from_pandas(result, include_index=False).write_parquet(output_path, compression="zstd")
    valid_rows = int(result[features].notna().any(axis=1).sum())
    manifest = {
        "version": GENERATOR_VERSION,
        "group_id": "market_state_conditioned",
        "features": features,
        "feature_count": len(features),
        "rows": len(result),
        "valid_rows": valid_rows,
        "date_start": result["time"].min().strftime("%Y-%m-%d"),
        "date_end": result["time"].max().strftime("%Y-%m-%d"),
        "global_state_policy": "index and sector-universe trailing-only statistics",
        "conditioning_policy": "sector-specific features multiplied by same-day market state",
        "source_sha256": {"technical_trend": sha256_file(tech_path), "sideways_volatility": sha256_file(sideways_path), "relative_strength": sha256_file(rs_path), "constituent_breadth": sha256_file(breadth_path)},
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
    }
    output_path.with_name("market_state_conditioned_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="构建市场状态条件化板块因子组")
    parser.add_argument("--index-path", type=Path, default=INDEX_PATH)
    parser.add_argument("--tech-path", type=Path, default=TECH_PATH)
    parser.add_argument("--sideways-path", type=Path, default=SIDEWAYS_PATH)
    parser.add_argument("--rs-path", type=Path, default=RS_PATH)
    parser.add_argument("--breadth-path", type=Path, default=BREADTH_PATH)
    parser.add_argument("--output-path", type=Path, default=OUTPUT_PATH)
    run(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
