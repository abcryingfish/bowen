"""Batch writer for V2 ex-post peak/valley labels.

This entry point intentionally does not import the main factor generator. It
keeps the label-only workload bounded so ordinary factor generation cannot
prevent the front end from seeing V2 labels.
"""

from __future__ import annotations

import argparse
import time
import uuid
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import polars as pl

from peak_valley_expost_annotation_v2 import (
V2_FACTOR_NAME_MAP,
    build_peak_valley_expost_v2_label_bundle,
)

V2_FACTOR_DISPLAY_NAMES = {value: key for key, value in V2_FACTOR_NAME_MAP.items()}


MARKET_PATHS = [
    r"D:\database\stock_basic_data_daily",
    r"D:\database\index_data_daily",
    r"D:\database\ETF_basic_data_daily",
]
ADJ_FACTOR_PATH = r"D:\database\stock_adj_daily\adj_factor_daily"
OUTPUT_PATH = r"D:\database\signal_daily_label"


def _glob(path: str) -> str:
    return str(Path(path) / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _load_market_frame(
    con: duckdb.DuckDBPyConnection,
    *,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    paths = ", ".join(_sql_quote(_glob(path)) for path in MARKET_PATHS)
    adj_glob = _glob(ADJ_FACTOR_PATH)
    sql = f"""
    WITH d AS (
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            CAST(time AS DATE) AS time,
            TRY_CAST(high AS DOUBLE) AS high,
            TRY_CAST(low AS DOUBLE) AS low,
            TRY_CAST(close AS DOUBLE) AS close
        FROM read_parquet([{paths}], union_by_name=true, hive_partitioning=1)
        WHERE CAST(time AS DATE) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
          AND htsc_code IS NOT NULL
          AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) NOT LIKE '%.YKRS'
    ),
    a AS (
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            CAST(time AS DATE) AS time,
            MAX(TRY_CAST(adj_factor AS DOUBLE)) AS adj_factor
        FROM read_parquet('{adj_glob}', union_by_name=true, hive_partitioning=1)
        WHERE CAST(time AS DATE) <= DATE '{end_date}'
        GROUP BY 1, 2
    )
    SELECT
        d.htsc_code,
        d.time,
        d.high * COALESCE(a.adj_factor, 1.0) AS high,
        d.low * COALESCE(a.adj_factor, 1.0) AS low,
        d.close * COALESCE(a.adj_factor, 1.0) AS close
    FROM d ASOF LEFT JOIN a
      ON d.htsc_code = a.htsc_code
     AND d.time >= a.time
    WHERE d.high IS NOT NULL AND d.low IS NOT NULL AND d.close IS NOT NULL
    ORDER BY d.time, d.htsc_code
    """
    frame = con.execute(sql).df()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    return frame.dropna(subset=["time", "htsc_code"]).drop_duplicates(
        subset=["time", "htsc_code"], keep="last"
    )


def _write_batch_parts(
    factor_frames: dict[str, pd.DataFrame],
    *,
    output_path: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> int:
    written = 0
    for factor_key, factor_frame in factor_frames.items():
        if factor_frame.empty:
            continue
        values = factor_frame.copy()
        values.index = pd.to_datetime(values.index).floor("D")
        values = values.loc[(values.index >= start_date) & (values.index <= end_date)]
        if values.empty:
            continue
        long_df = (
            values.rename_axis("time")
            .reset_index()
            .melt(id_vars="time", var_name="htsc_code", value_name="value")
        )
        numeric = pd.to_numeric(long_df["value"], errors="coerce")
        long_df = long_df.loc[np.isfinite(numeric)].copy()
        if long_df.empty:
            continue
        long_df["value"] = numeric.loc[long_df.index].astype(np.float32)
        for (year, month), month_df in long_df.groupby(
            [long_df["time"].dt.year, long_df["time"].dt.month], sort=True
        ):
            target = (
                Path(output_path)
                / f"factor={V2_FACTOR_DISPLAY_NAMES[factor_key]}"
                / f"year={int(year)}"
                / f"month={int(month):02d}"
            )
            target.mkdir(parents=True, exist_ok=True)
            out = target / f"part_v2_{int(time.time() * 1000)}_{uuid.uuid4().hex}.parquet"
            pl.from_pandas(
                month_df[["time", "htsc_code", "value"]], include_index=False
            ).sort(["time", "htsc_code"]).write_parquet(out, compression="snappy")
            written += len(month_df)
    return written


def generate_labels(
    *,
    start_date: str,
    end_date: str,
    batch_size: int = 128,
    output_path: str = OUTPUT_PATH,
) -> dict[str, int]:
    start = pd.Timestamp(start_date).floor("D")
    end = pd.Timestamp(end_date).floor("D")
    context_start = start - pd.Timedelta(days=120)
    con = duckdb.connect()
    frame = _load_market_frame(
        con,
        start_date=context_start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
    )
    codes = sorted(frame["htsc_code"].unique().tolist())
    print(f"[V2 label] 行情行数={len(frame)}，标的数={len(codes)}，批大小={batch_size}")
    total_rows = 0
    for offset in range(0, len(codes), max(1, int(batch_size))):
        batch_codes = codes[offset : offset + max(1, int(batch_size))]
        batch = frame.loc[frame["htsc_code"].isin(batch_codes)]
        wide = {
            field: batch.pivot(index="time", columns="htsc_code", values=field).sort_index()
            for field in ("high", "low", "close")
        }
        result = build_peak_valley_expost_v2_label_bundle(
            H=wide["high"], L=wide["low"], C=wide["close"]
        )
        rows = _write_batch_parts(
            result["factor_dfs"], output_path=output_path, start_date=start, end_date=end
        )
        total_rows += rows
        print(f"[V2 label] 批次 {offset + 1}-{offset + len(batch_codes)}/{len(codes)}，写入={rows}")
        del batch, wide, result
    return {"codes": len(codes), "rows": total_rows, "factors": len(V2_FACTOR_NAME_MAP)}


def main() -> None:
    parser = argparse.ArgumentParser(description="分批生成 V2 波峰波谷历史 label")
    parser.add_argument("--start-date", default="2016-01-01")
    parser.add_argument("--end-date", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--output-path", default=OUTPUT_PATH)
    args = parser.parse_args()
    print(generate_labels(**vars(args)))


if __name__ == "__main__":
    main()
