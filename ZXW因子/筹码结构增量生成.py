# -*- coding: utf-8 -*-
"""筹码结构独立增量入口。

与主ZXW入口分离，保持真实交易日期索引，使筹码状态可以跨批次、跨运行复用。
每批先写29个因子part，全部成功后再提交该批状态；中断不会推进未落盘的状态。
"""

from __future__ import annotations

import argparse
import gc
import os
import sys
import time
import uuid
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from 筹码结构因子 import (  # noqa: E402
    CHIP_STATE_CACHE_PATH,
    CHOUMA_AC,
    CHOUMA_MIN_D,
    FACTOR_NAME_MAP,
    _load_chip_state_cache,
    _save_chip_state_cache,
    _state_usable_for_incremental,
    build_chip_structure_factor_bundle,
)

MARKET_BASE = Path(r"D:\database\stock_basic_data_daily")
TURNOVER_BASE = Path(r"D:\database\qmt_turnover_data")
ADJ_BASE = Path(r"D:\database\stock_adj_daily\adj_factor_daily")
OUTPUT_BASE = Path(r"D:\database\signal_daily")
STATE_PATH = Path(CHIP_STATE_CACHE_PATH)


def _files(base: Path) -> list[str]:
    return [str(p).replace("\\", "/") for p in sorted(base.glob("year=*/month=*/merged.parquet"))]


def _sql_list(paths: list[str]) -> str:
    return "[" + ", ".join("'" + p.replace("'", "''") + "'" for p in paths) + "]"


def _codes(con: duckdb.DuckDBPyConnection, start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    paths = _files(MARKET_BASE)
    sql = f"""
SELECT DISTINCT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code
FROM read_parquet({_sql_list(paths)}, hive_partitioning=true, union_by_name=true)
WHERE CAST(time AS DATE) BETWEEN DATE '{start:%Y-%m-%d}' AND DATE '{end:%Y-%m-%d}'
  AND htsc_code IS NOT NULL
ORDER BY 1
"""
    return con.execute(sql).df()["htsc_code"].astype(str).tolist()


def _load_batch(
    con: duckdb.DuckDBPyConnection,
    codes: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    code_sql = "(" + ",".join("'" + c.replace("'", "''") + "'" for c in codes) + ")"
    market_paths = _files(MARKET_BASE)
    turnover_paths = _files(TURNOVER_BASE)
    adj_paths = _files(ADJ_BASE)
    market_sql = f"""
WITH d AS (
    SELECT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
           CAST(time AS DATE) AS time,
           TRY_CAST(open AS DOUBLE) AS open,
           TRY_CAST(high AS DOUBLE) AS high,
           TRY_CAST(low AS DOUBLE) AS low,
           TRY_CAST(close AS DOUBLE) AS close,
           TRY_CAST(volume AS DOUBLE) AS volume
    FROM read_parquet({_sql_list(market_paths)}, hive_partitioning=true, union_by_name=true)
    WHERE CAST(time AS DATE) BETWEEN DATE '{start:%Y-%m-%d}' AND DATE '{end:%Y-%m-%d}'
      AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN {code_sql}
), a AS (
    SELECT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
           CAST(time AS DATE) AS time,
           MAX(TRY_CAST(adj_factor AS DOUBLE)) AS adj_factor
    FROM read_parquet({_sql_list(adj_paths)}, hive_partitioning=true, union_by_name=true)
    WHERE CAST(time AS DATE) <= DATE '{end:%Y-%m-%d}'
      AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN {code_sql}
    GROUP BY 1, 2
)
SELECT d.htsc_code, d.time,
       d.open * COALESCE(a.adj_factor, 1.0) AS open,
       d.high * COALESCE(a.adj_factor, 1.0) AS high,
       d.low * COALESCE(a.adj_factor, 1.0) AS low,
       d.close * COALESCE(a.adj_factor, 1.0) AS close,
       d.volume
FROM d ASOF LEFT JOIN a
  ON d.htsc_code = a.htsc_code AND d.time >= a.time
ORDER BY d.time, d.htsc_code
"""
    turnover_sql = f"""
SELECT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
       CAST(time AS DATE) AS time,
       MAX(TRY_CAST(turnover_rate AS DOUBLE)) AS turnover_rate
FROM read_parquet({_sql_list(turnover_paths)}, hive_partitioning=true, union_by_name=true)
WHERE CAST(time AS DATE) BETWEEN DATE '{start:%Y-%m-%d}' AND DATE '{end:%Y-%m-%d}'
  AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN {code_sql}
GROUP BY 1, 2
"""
    market = con.execute(market_sql).df()
    turnover = con.execute(turnover_sql).df() if turnover_paths else pd.DataFrame()
    if market.empty:
        empty = pd.DataFrame()
        return empty, empty, empty, empty, empty
    market["time"] = pd.to_datetime(market["time"]).dt.normalize()
    market = market.drop_duplicates(["time", "htsc_code"], keep="last")
    index = pd.DatetimeIndex(sorted(market["time"].unique()))
    columns = pd.Index(codes, dtype="object")

    def wide(name: str) -> pd.DataFrame:
        frame = market.pivot(index="time", columns="htsc_code", values=name)
        return frame.reindex(index=index, columns=columns).astype(float)

    if turnover.empty:
        t_wide = pd.DataFrame(0.0, index=index, columns=columns)
    else:
        turnover["time"] = pd.to_datetime(turnover["time"]).dt.normalize()
        t_wide = turnover.pivot(index="time", columns="htsc_code", values="turnover_rate")
        t_wide = t_wide.reindex(index=index, columns=columns).fillna(0.0).astype(float)
    return wide("high"), wide("low"), wide("close"), wide("volume"), t_wide


def _write_parts(
    result: dict[str, object],
    output_base: Path,
    write_after: dict[str, dict[str, pd.Timestamp]],
) -> None:
    factor_dfs = result["factor_dfs"]
    for factor_id, frame in factor_dfs.items():
        data = frame.copy()
        data.index = pd.to_datetime(data.index).floor("D")
        factor_watermarks = write_after.get(str(factor_id), {})
        for code in data.columns:
            cutoff = factor_watermarks.get(str(code))
            if cutoff is not None:
                data.loc[data.index <= cutoff, code] = np.nan
        if data.empty:
            continue
        long_df = data.rename_axis("time").reset_index().melt(
            id_vars="time", var_name="htsc_code", value_name="value"
        )
        long_df = long_df.dropna(subset=["value"])
        if long_df.empty:
            continue
        long_df["htsc_code"] = long_df["htsc_code"].astype(str)
        long_df["value"] = long_df["value"].astype("float32")
        for (year, month), chunk in long_df.groupby(
            [long_df["time"].dt.year, long_df["time"].dt.month], sort=True
        ):
            month_dir = output_base / f"factor={factor_id}" / f"year={int(year):04d}" / f"month={int(month):02d}"
            month_dir.mkdir(parents=True, exist_ok=True)
            target = month_dir / (
                f"part_{time.time_ns() // 1_000_000}_{os.getpid()}_{uuid.uuid4().hex}.parquet"
            )
            temp = target.with_suffix(".tmp.parquet")
            chunk[["time", "htsc_code", "value"]].to_parquet(
                temp, index=False, compression="snappy"
            )
            os.replace(temp, target)
        print(f"筹码part写入: {factor_id}，行={len(long_df)}")


def _factor_code_last_dates(
    output_base: Path,
    factor_ids: list[str],
    codes: list[str],
) -> dict[str, dict[str, pd.Timestamp]]:
    """读取每个因子、每只代码的水位，支持股票分批和中断续跑。"""
    con = duckdb.connect(database=":memory:")
    result: dict[str, dict[str, pd.Timestamp]] = {}
    try:
        for factor_id in factor_ids:
            factor_dir = output_base / f"factor={factor_id}"
            month_dirs = sorted(factor_dir.glob("year=*/month=*"), reverse=True)
            pending = set(codes)
            watermarks: dict[str, pd.Timestamp] = {}
            for month_dir in month_dirs:
                paths = [str(p).replace("\\", "/") for p in month_dir.glob("*.parquet")]
                if not paths or not pending:
                    continue
                pending_sql = "(" + ",".join(
                    "'" + code.replace("'", "''") + "'" for code in sorted(pending)
                ) + ")"
                rows = con.execute(
                    f"""
SELECT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
       MAX(CAST(time AS DATE)) AS last_dt
FROM read_parquet({_sql_list(paths)}, union_by_name=true)
WHERE UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN {pending_sql}
GROUP BY 1
"""
                ).fetchall()
                for code, last_dt in rows:
                    if last_dt is not None:
                        watermarks[str(code)] = pd.Timestamp(last_dt)
                        pending.discard(str(code))
                if not pending:
                    break
            result[factor_id] = watermarks
    finally:
        con.close()
    return result


def _validate_existing_overlap(
    result: dict[str, object],
    output_base: Path,
    batch: list[str],
    end: pd.Timestamp,
    valid_close: pd.DataFrame,
) -> None:
    """首批提交前，使用已有最近交易日校验新旧筹码口径。"""
    selected = [
        "absolute_concentration",
        "relative_concentration",
        "concentration_total_score",
        "chip_peak_score",
        "cost_1pct",
        "cost_99pct",
    ]
    factor_dfs = result["factor_dfs"]
    con = duckdb.connect(database=":memory:")
    checked = 0
    eligible_codes_by_date: dict[pd.Timestamp, set[str]] = {}
    try:
        for factor_id in selected:
            frame = factor_dfs[factor_id]
            month_dir = (
                output_base
                / f"factor={factor_id}"
                / f"year={end.year:04d}"
                / f"month={end.month:02d}"
            )
            paths = [
                str(path).replace("\\", "/")
                for path in month_dir.glob("*.parquet")
            ]
            if not paths:
                continue
            existing_end = con.execute(
                f"SELECT MAX(CAST(time AS DATE)) FROM read_parquet({_sql_list(paths)}, union_by_name=true) "
                f"WHERE CAST(time AS DATE) < DATE '{end:%Y-%m-%d}'"
            ).fetchone()[0]
            if existing_end is None:
                continue
            compare_date = pd.Timestamp(existing_end)
            if compare_date not in frame.index:
                raise RuntimeError(f"首批校验缺少计算日期: {factor_id} {compare_date.date()}")
            code_sql = "(" + ",".join("'" + c.replace("'", "''") + "'" for c in batch) + ")"
            if compare_date not in eligible_codes_by_date:
                cost_paths = [
                    str(path).replace("\\", "/")
                    for path in (
                        output_base
                        / "factor=cost_1pct"
                        / f"year={compare_date.year:04d}"
                        / f"month={compare_date.month:02d}"
                    ).glob("*.parquet")
                ]
                eligible_rows = con.execute(
                    f"""
SELECT DISTINCT UPPER(TRIM(CAST(htsc_code AS VARCHAR)))
FROM read_parquet({_sql_list(cost_paths)}, union_by_name=true)
WHERE CAST(time AS DATE) = DATE '{compare_date:%Y-%m-%d}'
  AND TRY_CAST(value AS DOUBLE) > 0
  AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN {code_sql}
"""
                ).fetchall()
                eligible_codes_by_date[compare_date] = {str(row[0]) for row in eligible_rows}
            old = con.execute(
                f"""
SELECT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
       MIN(TRY_CAST(value AS DOUBLE)) AS min_value,
       MAX(TRY_CAST(value AS DOUBLE)) AS max_value
FROM read_parquet({_sql_list(paths)}, union_by_name=true)
WHERE CAST(time AS DATE) = DATE '{compare_date:%Y-%m-%d}'
  AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN {code_sql}
GROUP BY 1
"""
            ).df()
            if old.empty:
                continue
            current = frame.loc[compare_date].rename("current").rename_axis("htsc_code").reset_index()
            current["htsc_code"] = current["htsc_code"].astype(str).str.upper().str.strip()
            current = current[current["htsc_code"].isin(eligible_codes_by_date[compare_date])]
            if compare_date in valid_close.index:
                valid_codes = set(valid_close.columns[valid_close.loc[compare_date].notna()])
                current = current[current["htsc_code"].isin(valid_codes)]
            merged = old.merge(current, on="htsc_code", how="inner").dropna()
            if merged.empty:
                continue
            # 兼容库内重复行：新值只要与该键已有值范围一致即可。
            below = np.maximum(merged["min_value"].to_numpy() - merged["current"].to_numpy(), 0.0)
            above = np.maximum(merged["current"].to_numpy() - merged["max_value"].to_numpy(), 0.0)
            error = np.maximum(below, above)
            scale = np.maximum(np.abs(merged["current"].to_numpy()), 1.0)
            if factor_id.startswith("cost_"):
                tolerance = 0.1
                relative_tolerance = 0.03
            elif factor_id == "absolute_concentration":
                tolerance = 0.5
                relative_tolerance = 1e-5
            elif factor_id == "relative_concentration":
                tolerance = 2.5
                relative_tolerance = 1e-5
            else:
                tolerance = 1.0
                relative_tolerance = 1e-5
            bad = error > (tolerance + relative_tolerance * scale)
            max_error = float(error.max(initial=0.0))
            print(f"首批校验: {factor_id}，日期={compare_date.date()}，样本={len(merged)}，最大误差={max_error:.8g}")
            if bool(bad.any()):
                samples = merged.loc[bad, ["htsc_code", "min_value", "max_value", "current"]].head(5)
                raise RuntimeError(f"筹码口径校验失败: {factor_id}\n{samples.to_string(index=False)}")
            checked += len(merged)
    finally:
        con.close()
    if checked == 0:
        raise RuntimeError("首批校验没有找到可对照的已有筹码数据")


def main() -> None:
    parser = argparse.ArgumentParser(description="筹码结构独立状态增量生成")
    parser.add_argument("--start-date", default="2010-01-04")
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--skip-first-batch-validation", action="store_true")
    parser.add_argument("--max-batches", type=int, default=None, help="仅调试时限制批次数")
    args = parser.parse_args()
    if args.batch_size <= 0:
        raise ValueError("batch-size必须大于0")
    start = pd.Timestamp(args.start_date).floor("D")
    con = duckdb.connect(database=":memory:")
    try:
        codes = _codes(con, start, pd.Timestamp("today"))
        source_end = con.execute(
            f"SELECT MAX(CAST(time AS DATE)) FROM read_parquet({_sql_list(_files(MARKET_BASE))}, hive_partitioning=true, union_by_name=true)"
        ).fetchone()[0]
    finally:
        con.close()
    end = min(pd.Timestamp(args.end_date).floor("D"), pd.Timestamp(source_end)) if args.end_date else pd.Timestamp(source_end)
    if not codes or end < start:
        raise ValueError("没有可用筹码行情范围")
    factor_ids = list(FACTOR_NAME_MAP.values())
    last_dates = _factor_code_last_dates(OUTPUT_BASE, factor_ids, codes)
    os.environ.setdefault("ZXW_CHIP_STATE_CACHE", "1")
    os.environ.setdefault("ZXW_CHIP_STATE_BOOTSTRAP_MAX_CELLS", "10000000")
    os.environ.setdefault("ZXW_CHIP_BUNDLE_CACHE", "0")
    # 个别长期后复权股票会超过100万档；同花顺指数不进入筹码计算。
    os.environ.setdefault("ZXW_CHIP_STATE_MAX_BINS", "5000000")
    state = _load_chip_state_cache(str(STATE_PATH)) if STATE_PATH.is_file() else {}
    print(f"筹码独立更新: {start.date()} ~ {end.date()}，代码={len(codes)}，批次={(len(codes)+args.batch_size-1)//args.batch_size}")

    for batch_no, offset in enumerate(range(0, len(codes), args.batch_size), start=1):
        if args.max_batches is not None and batch_no > args.max_batches:
            break
        batch = codes[offset : offset + args.batch_size]
        complete = all(
            code in state
            and _state_usable_for_incremental(state[code], CHOUMA_MIN_D, CHOUMA_AC)
            and pd.Timestamp(state[code]["last_dt"]).floor("D") >= end
            and all(
                factor_id in last_dates
                and code in last_dates[factor_id]
                and pd.Timestamp(last_dates[factor_id][code]).floor("D") >= end
                for factor_id in factor_ids
            )
            for code in batch
        )
        if complete:
            print(f"筹码批次跳过: {offset + 1}-{offset + len(batch)}，状态已到{end.date()}")
            continue
        query_start = start
        if all(
            code in state and _state_usable_for_incremental(state[code], CHOUMA_MIN_D, CHOUMA_AC)
            for code in batch
        ):
            query_start = min(pd.Timestamp(state[code]["last_dt"]).floor("D") for code in batch)
        con = duckdb.connect(database=":memory:")
        try:
            H, L, C, V, T = _load_batch(con, batch, query_start, end)
        finally:
            con.close()
        if C.empty:
            continue
        stage = STATE_PATH.with_name(f"chip_batch_state_{os.getpid()}_{offset}.parquet")
        import 筹码结构因子 as chip_module
        existing_batch_states = {code: state[code] for code in batch if code in state}
        if existing_batch_states:
            _save_chip_state_cache(existing_batch_states, str(stage))
        chip_module.CHIP_STATE_CACHE_PATH = str(stage)
        result = build_chip_structure_factor_bundle(H=H, L=L, C=C, V=V, T=T)
        if batch_no == 1 and not args.skip_first_batch_validation:
            _validate_existing_overlap(result, OUTPUT_BASE, batch, end, C)
        _write_parts(result, OUTPUT_BASE, last_dates)
        batch_states = _load_chip_state_cache(str(stage))
        incomplete_states = [
            code for code in batch
            if code not in batch_states
            or not _state_usable_for_incremental(batch_states[code], CHOUMA_MIN_D, CHOUMA_AC)
            or pd.Timestamp(batch_states[code]["last_dt"]).floor("D") < end
        ]
        if incomplete_states:
            raise RuntimeError(f"批次状态不完整，样例={incomplete_states[:5]}")
        _save_chip_state_cache(batch_states, str(STATE_PATH))
        state.update(batch_states)
        for factor_id in factor_ids:
            factor_marks = last_dates.setdefault(factor_id, {})
            factor_marks.update({code: end for code in batch})
        stage.unlink(missing_ok=True)
        print(f"筹码批次完成: {offset + 1}-{offset + len(batch)}，状态={len(batch_states)}")
        del result, batch_states, H, L, C, V, T
        gc.collect()


if __name__ == "__main__":
    main()
