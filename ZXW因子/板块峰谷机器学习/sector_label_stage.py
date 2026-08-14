"""构建并审计 881/885/886 板块 V2 波峰波谷标签。"""

from __future__ import annotations

import argparse
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

from peak_valley_expost_annotation_v2 import (  # noqa: E402
    V2_FACTOR_NAME_MAP,
    build_peak_valley_expost_v2_label_bundle,
)


DEFAULT_MARKET_PATH = Path(r"D:\database\index_data_daily")
DEFAULT_OUTPUT_PATH = Path(r"D:\database\sector_peak_valley_ml\labels")
DEFAULT_REPORT_PATH = Path("outputs/sector_peak_valley_ml/stage_a_labels")
SECTOR_PREFIXES = ("881", "885", "886")
MAX_FUTURE_BARS = 40


def _market_glob(base_path: Path) -> str:
    return str(base_path / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")


def load_sector_market(
    base_path: Path,
    *,
    start_date: str,
    end_date: str,
    prefixes: tuple[str, ...] = SECTOR_PREFIXES,
) -> pd.DataFrame:
    """读取同花顺板块 High/Low/Close，并强制主键唯一。"""

    if not prefixes:
        raise ValueError("prefixes 不能为空")
    conditions = " OR ".join("htsc_code LIKE ?" for _ in prefixes)
    params = [_market_glob(base_path), start_date, end_date, *(f"{p}%" for p in prefixes)]
    sql = f"""
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            CAST(time AS DATE) AS time,
            MAX(TRY_CAST(high AS DOUBLE)) AS high,
            MAX(TRY_CAST(low AS DOUBLE)) AS low,
            MAX(TRY_CAST(close AS DOUBLE)) AS close
        FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
        WHERE CAST(time AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
          AND ({conditions})
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    with duckdb.connect() as con:
        frame = con.execute(sql, params).df()
    if frame.empty:
        raise ValueError("没有读取到 881/885/886 板块行情")
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    for column in ("high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["htsc_code", "time", "high", "low", "close"])
    invalid = (frame["high"] < frame[["low", "close"]].max(axis=1)) | (
        frame["low"] > frame[["high", "close"]].min(axis=1)
    )
    if invalid.any():
        raise ValueError(f"发现 {int(invalid.sum())} 行非法 OHLC")
    if frame.duplicated(["htsc_code", "time"]).any():
        raise ValueError("板块行情存在重复主键")
    return frame.sort_values(["htsc_code", "time"]).reset_index(drop=True)


def build_sector_labels(market: pd.DataFrame) -> pd.DataFrame:
    """逐板块计算 V2 标签，返回一行一个板块交易日的宽表。"""

    required = {"htsc_code", "time", "high", "low", "close"}
    missing = required.difference(market.columns)
    if missing:
        raise ValueError(f"行情缺少字段: {sorted(missing)}")
    outputs: list[pd.DataFrame] = []
    factor_keys = list(V2_FACTOR_NAME_MAP.values())
    for code, group in market.groupby("htsc_code", sort=True):
        group = group.sort_values("time").drop_duplicates("time", keep="last")
        index = pd.DatetimeIndex(group["time"])
        wide = {
            field: pd.DataFrame({str(code): group[field].to_numpy()}, index=index)
            for field in ("high", "low", "close")
        }
        bundle = build_peak_valley_expost_v2_label_bundle(
            H=wide["high"], L=wide["low"], C=wide["close"]
        )
        result = pd.DataFrame(
            {key: bundle["factor_dfs"][key][str(code)].to_numpy() for key in factor_keys},
            index=index,
        ).reset_index(names="time")
        result.insert(0, "htsc_code", str(code))
        result["bars_to_end"] = np.arange(len(result) - 1, -1, -1, dtype=np.int32)
        result["label_complete"] = result["bars_to_end"] >= MAX_FUTURE_BARS
        outputs.append(result)
    labels = pd.concat(outputs, ignore_index=True)
    if labels.duplicated(["htsc_code", "time"]).any():
        raise ValueError("V2 板块标签生成后存在重复主键")
    return labels.sort_values(["time", "htsc_code"]).reset_index(drop=True)


def write_partitioned_labels(labels: pd.DataFrame, output_path: Path) -> int:
    """覆盖式写入年月 merged.parquet，避免追加 part 导致重复。"""

    output_path.mkdir(parents=True, exist_ok=True)
    values = labels.copy()
    values["year"] = values["time"].dt.year.astype(int)
    values["month"] = values["time"].dt.month.astype(int)
    written = 0
    for (year, month), group in values.groupby(["year", "month"], sort=True):
        target = output_path / f"year={year}" / f"month={month:02d}"
        target.mkdir(parents=True, exist_ok=True)
        out = target / "merged.parquet"
        payload = group.drop(columns=["year", "month"])
        pl.from_pandas(payload, include_index=False).write_parquet(out, compression="zstd")
        written += len(payload)
    return written


def audit_sector_labels(market: pd.DataFrame, labels: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """检查覆盖、范围、重复、完整区间和分布。"""

    strength_columns = ["peak_strength_ex_post", "valley_strength_ex_post"]
    component_columns = [
        key
        for key in V2_FACTOR_NAME_MAP.values()
        if not key.endswith("confirm_delay")
    ]
    prefix_rows = []
    for prefix in SECTOR_PREFIXES:
        market_codes = set(market.loc[market["htsc_code"].str.startswith(prefix), "htsc_code"])
        label_codes = set(labels.loc[labels["htsc_code"].str.startswith(prefix), "htsc_code"])
        prefix_rows.append(
            {
                "prefix": prefix,
                "market_codes": len(market_codes),
                "label_codes": len(label_codes),
                "coverage": len(market_codes & label_codes) / max(len(market_codes), 1),
                "missing_codes": ",".join(sorted(market_codes - label_codes)),
            }
        )
    coverage = pd.DataFrame(prefix_rows)
    finite_components = labels[component_columns].replace([np.inf, -np.inf], np.nan)
    range_ok = bool(((finite_components >= 0) & (finite_components <= 1)).all().all())
    distribution: dict[str, dict[str, float]] = {}
    complete = labels.loc[labels["label_complete"]]
    for column in strength_columns:
        series = complete[column].dropna()
        distribution[column] = {
            "count": int(series.size),
            "mean": float(series.mean()),
            "std": float(series.std()),
            "zero_rate": float((series == 0).mean()),
            "p10": float(series.quantile(0.10)),
            "p50": float(series.quantile(0.50)),
            "p90": float(series.quantile(0.90)),
            "p99": float(series.quantile(0.99)),
        }
    report = {
        "market_rows": int(len(market)),
        "label_rows": int(len(labels)),
        "codes": int(labels["htsc_code"].nunique()),
        "min_date": labels["time"].min().strftime("%Y-%m-%d"),
        "max_date": labels["time"].max().strftime("%Y-%m-%d"),
        "complete_rows": int(labels["label_complete"].sum()),
        "duplicate_keys": int(labels.duplicated(["htsc_code", "time"]).sum()),
        "range_ok": range_ok,
        "coverage_ok": bool((coverage["coverage"] >= 0.99).all()),
        "nonconstant_ok": bool(all(item["std"] > 0 for item in distribution.values())),
        "distribution": distribution,
        "peak_valley_spearman_complete": float(
            complete[strength_columns].corr(method="spearman").iloc[0, 1]
        ),
    }
    report["passed"] = bool(
        report["duplicate_keys"] == 0
        and report["range_ok"]
        and report["coverage_ok"]
        and report["nonconstant_ok"]
    )
    return report, coverage


def run_stage(
    *,
    market_path: Path,
    output_path: Path,
    report_path: Path,
    start_date: str,
    end_date: str,
) -> dict:
    market = load_sector_market(market_path, start_date=start_date, end_date=end_date)
    print(f"[阶段A] 行情行数={len(market):,}，板块数={market['htsc_code'].nunique()}")
    labels = build_sector_labels(market)
    written = write_partitioned_labels(labels, output_path)
    report, coverage = audit_sector_labels(market, labels)
    report["written_rows"] = written
    report_path.mkdir(parents=True, exist_ok=True)
    (report_path / "label_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    coverage.to_csv(report_path / "label_coverage.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(report["distribution"]).T.to_csv(
        report_path / "label_distribution.csv", encoding="utf-8-sig"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise RuntimeError("阶段 A 标签审计未通过，详见 label_audit.json")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="构建并审计 881/885/886 板块 V2 标签")
    parser.add_argument("--market-path", type=Path, default=DEFAULT_MARKET_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--start-date", default="2016-01-01")
    parser.add_argument("--end-date", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    args = parser.parse_args()
    run_stage(**vars(args))


if __name__ == "__main__":
    main()

