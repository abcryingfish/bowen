#!/usr/bin/python3
# -*- coding: utf-8 -*-
r"""QMT 日频复权因子下载与转换。

原始事件表写入 D:\database\stock_adj_daily_raw，处理后的分段与 wide_xdy 仍写入
D:\database\stock_adj_daily，保持下游读取格式不变。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import polars as pl
from xtquant import xtdata

RAW_BASE_DIR_DEFAULT = r"D:\database\stock_adj_daily_raw"
FINAL_BASE_DIR_DEFAULT = r"D:\database\stock_adj_daily"
RAW_MERGED_FILE_NAME = "merged.parquet"
ADJ_SEGMENTS_PARQUET_NAME = "adj_factor_segments.parquet"
WIDE_XDY_DIR_NAME = "wide_xdy"
RAW_MIN_PARQUET_BYTES = 12
DEFAULT_SECTOR_NAME = "沪深A股"
DEFAULT_START_DATE = "2010-01-01"
DEFAULT_SLEEP_SEC = 0.0005
DEFAULT_OVERLAP_DAYS = 456
RAW_COLUMNS = (
    "htsc_code",
    "event_date",
    "time",
    "interest",
    "stockBonus",
    "stockGift",
    "allotNum",
    "allotPrice",
    "gugai",
    "dr",
    "updated_at",
)


def configure_console_encoding(sys_module=sys) -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys_module, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


configure_console_encoding()


def normalize_code(code: str) -> str:
    return str(code or "").strip().upper()


def _to_py_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


_OPEN_END_SENTINEL = date(1900, 1, 2)


def fix_adj_segment_open_ends_pl(
    df: pl.DataFrame,
    segment_end_cap: date | datetime | None = None,
) -> pl.DataFrame:
    if df.is_empty() or "begin_date" not in df.columns or "end_date" not in df.columns:
        return df
    b = pl.col("begin_date").cast(pl.Date, strict=False)
    e = pl.col("end_date").cast(pl.Date, strict=False)
    bad = e.is_null() | (e <= pl.lit(_OPEN_END_SENTINEL)) | (e < b)
    if segment_end_cap is not None:
        cap_lit = pl.lit(segment_end_cap).cast(pl.Date, strict=False)
        fixed = pl.when(bad).then(pl.max_horizontal(b, cap_lit)).otherwise(e).alias("end_date")
    else:
        fixed = pl.when(bad).then(b).otherwise(e).alias("end_date")
    return df.with_columns(fixed)


def extend_last_segment_end_to_cap(
    merged: pl.DataFrame,
    cap: date,
    *,
    only_htsc_codes: set[str] | None = None,
) -> pl.DataFrame:
    if merged.is_empty() or "htsc_code" not in merged.columns:
        return merged
    cap_lit = pl.lit(cap).cast(pl.Date)
    work = merged.sort(["htsc_code", "begin_date", "end_date"])
    b = pl.col("begin_date").cast(pl.Date, strict=False)
    e = pl.col("end_date").cast(pl.Date, strict=False)
    is_last = (pl.col("htsc_code") != pl.col("htsc_code").shift(-1)).fill_null(True)
    need = is_last & (e < cap_lit)
    if only_htsc_codes:
        codes_upper = [normalize_code(c) for c in only_htsc_codes]
        need = need & pl.col("htsc_code").cast(pl.Utf8).str.strip_chars().str.to_uppercase().is_in(codes_upper)
    new_end = pl.when(need).then(pl.max_horizontal(b, cap_lit)).otherwise(e).alias("end_date")
    return work.with_columns(new_end)


def collapse_adj_segments_same_begin_pl(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty() or not all(c in df.columns for c in ("htsc_code", "begin_date", "end_date", "xdy")):
        return df
    work = df.with_columns(
        [
            pl.col("htsc_code").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("htsc_code"),
            pl.col("begin_date").cast(pl.Date, strict=False),
            pl.col("end_date").cast(pl.Date, strict=False),
            pl.col("xdy").cast(pl.Float64, strict=False),
        ]
    )
    work = work.drop_nulls(subset=["htsc_code", "begin_date", "end_date"])
    return (
        work.sort(["htsc_code", "begin_date", "end_date"])
        .group_by(["htsc_code", "begin_date"], maintain_order=True)
        .last()
    )


def rewrite_adj_segments_extend_last_ends(
    base_dir: str,
    cap: date,
    only_htsc_codes: set[str] | None,
) -> tuple[bool, int]:
    path = Path(base_dir) / ADJ_SEGMENTS_PARQUET_NAME
    if not path.is_file():
        return False, 0
    merged = pl.read_parquet(str(path))
    merged = fix_adj_segment_open_ends_pl(merged, cap)
    merged = merged.drop_nulls(subset=["htsc_code", "begin_date", "end_date"])
    merged = merged.unique(subset=["htsc_code", "begin_date", "end_date", "xdy"], keep="last")
    n0 = len(merged)
    merged = collapse_adj_segments_same_begin_pl(merged)
    if len(merged) < n0:
        print(f"✓ 已按 (htsc_code, begin_date) 合并重复分段 {n0 - len(merged)} 行")
    merged = extend_last_segment_end_to_cap(merged, cap, only_htsc_codes=only_htsc_codes)
    merged = merged.sort(["htsc_code", "begin_date", "end_date"])
    tmp = path.with_name(path.stem + "._writing_.parquet")
    merged.write_parquet(str(tmp), compression="zstd")
    os.replace(str(tmp), str(path))
    who = f"{len(only_htsc_codes)} 只待更新标的" if only_htsc_codes else "全表"
    print(f"✓ 已延长末段 end_date 至 {cap}（{who}），写入 {path} 共 {len(merged)} 行")
    return True, len(merged)


def merge_and_write_adj_segments_parquet(
    new_seg: pl.DataFrame,
    base_dir: str,
    *,
    segment_end_cap: date | datetime | None = None,
) -> tuple[Path, int]:
    os.makedirs(base_dir, exist_ok=True)
    path = Path(base_dir) / ADJ_SEGMENTS_PARQUET_NAME
    if new_seg.is_empty():
        if path.is_file():
            cap_d = _to_py_date(segment_end_cap) if segment_end_cap is not None else None
            if cap_d is not None:
                _, n = rewrite_adj_segments_extend_last_ends(base_dir, cap_d, None)
                return path, n
            cur = pl.read_parquet(str(path))
            return path, len(cur)
        return path, 0

    if path.is_file():
        old = pl.read_parquet(path)
        merged = pl.concat([old, new_seg], how="diagonal_relaxed")
    else:
        merged = new_seg

    std_cols = ["htsc_code", "begin_date", "end_date", "xdy"]
    keep = [c for c in std_cols if c in merged.columns]
    merged = merged.select(keep) if keep else merged
    merged = merged.with_columns(
        pl.col("htsc_code").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("htsc_code")
    )
    merged = merged.with_columns(
        [
            pl.col("begin_date").cast(pl.Date, strict=False),
            pl.col("end_date").cast(pl.Date, strict=False),
            pl.col("xdy").cast(pl.Float64, strict=False),
        ]
    )
    merged = fix_adj_segment_open_ends_pl(merged, segment_end_cap)
    merged = merged.drop_nulls(subset=["htsc_code", "begin_date", "end_date"])
    merged = merged.unique(subset=["htsc_code", "begin_date", "end_date", "xdy"], keep="last")
    n_before_collapse = len(merged)
    merged = collapse_adj_segments_same_begin_pl(merged)
    if len(merged) < n_before_collapse:
        print(f"✓ 已按 (htsc_code, begin_date) 合并重复分段 {n_before_collapse - len(merged)} 行")
    merged = merged.sort(["htsc_code", "begin_date", "end_date"])

    cap_d = _to_py_date(segment_end_cap) if segment_end_cap is not None else None
    if cap_d is not None:
        merged = extend_last_segment_end_to_cap(merged, cap_d, only_htsc_codes=None)

    n = len(merged)
    tmp = path.with_name(path.stem + "._writing_.parquet")
    merged.write_parquet(str(tmp), compression="zstd")
    os.replace(str(tmp), str(path))
    print(f"✓ 已写入复权分段 parquet: {path}  共 {n} 行")
    return path, n


def load_segments_for_codes(base_dir: str, codes: set[str] | None = None) -> pl.DataFrame:
    path = Path(base_dir) / ADJ_SEGMENTS_PARQUET_NAME
    if not path.is_file():
        return pl.DataFrame(schema={"htsc_code": pl.Utf8, "begin_date": pl.Date, "end_date": pl.Date, "xdy": pl.Float64})
    seg = pl.read_parquet(str(path)).with_columns(
        pl.col("htsc_code").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("htsc_code"),
        pl.col("begin_date").cast(pl.Date, strict=False),
        pl.col("end_date").cast(pl.Date, strict=False),
        pl.col("xdy").cast(pl.Float64, strict=False),
    )
    if codes:
        seg = seg.filter(pl.col("htsc_code").is_in(sorted(normalize_code(c) for c in codes)))
    return seg.drop_nulls(subset=["htsc_code", "begin_date", "end_date", "xdy"]).sort(["htsc_code", "begin_date", "end_date"])


def _wide_date_columns_to_slash(wide: pl.DataFrame) -> pl.DataFrame:
    rename = {}
    for c in wide.columns:
        if c == "htsc_code":
            continue
        try:
            d = datetime.strptime(str(c)[:10], "%Y-%m-%d").date()
            rename[c] = f"{d.year}/{d.month}/{d.day}"
        except ValueError:
            pass
    return wide.rename(rename) if rename else wide


def _wide_fill_blank_with_one(wide: pl.DataFrame, *, code_col: str = "htsc_code") -> pl.DataFrame:
    cols = [c for c in wide.columns if c != code_col]
    if not cols:
        return wide
    return wide.with_columns([pl.col(c).fill_null(1.0).fill_nan(1.0).alias(c) for c in cols])


def _seg_parse_dates(seg: pl.DataFrame) -> pl.DataFrame:
    out = seg
    for name in ("begin_date", "end_date"):
        dt = out.schema[name]
        if dt == pl.Utf8 or dt == pl.String:
            out = out.with_columns(
                pl.col(name)
                .str.to_datetime("%Y-%m-%d %H:%M:%S", strict=False)
                .cast(pl.Date)
                .alias(name)
            )
        else:
            out = out.with_columns(pl.col(name).cast(pl.Date).alias(name))
    return out


def build_monthly_xdy_wide_frames(
    seg: pl.DataFrame,
    *,
    only_htsc_codes: set[str] | None = None,
) -> dict[tuple[int, int], pl.DataFrame]:
    if seg.is_empty():
        return {}
    work = seg.select(
        pl.col("htsc_code").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("htsc_code"),
        pl.col("begin_date").cast(pl.Date, strict=False),
        pl.col("end_date").cast(pl.Date, strict=False),
        pl.col("xdy").cast(pl.Float64, strict=False).alias("post_adj_cum"),
    )
    if only_htsc_codes:
        work = work.filter(pl.col("htsc_code").is_in(sorted(normalize_code(c) for c in only_htsc_codes)))
    work = work.drop_nulls(subset=["htsc_code", "begin_date", "end_date", "post_adj_cum"])
    if work.is_empty():
        return {}
    work = _seg_parse_dates(work)
    long_df = (
        work.with_columns(
            pl.date_ranges(
                pl.col("begin_date"),
                pl.col("end_date"),
                interval="1d",
            ).alias("date")
        )
        .explode("date")
        .with_columns(
            pl.col("date").dt.year().alias("_year"),
            pl.col("date").dt.month().alias("_month"),
        )
    )
    result: dict[tuple[int, int], pl.DataFrame] = {}
    for (year_value, month_value), chunk in long_df.group_by(["_year", "_month"], maintain_order=True):
        wide = chunk.pivot(
            on="date",
            index="htsc_code",
            values="post_adj_cum",
            aggregate_function="first",
        )
        wide = _wide_fill_blank_with_one(_wide_date_columns_to_slash(wide))
        result[(int(year_value), int(month_value))] = wide
    return result


def write_monthly_xdy_wide_frames(
    monthly_frames: dict[tuple[int, int], pl.DataFrame],
    *,
    base_dir: str,
    replace_codes: set[str] | None = None,
) -> int:
    wide_root = Path(base_dir) / WIDE_XDY_DIR_NAME
    total_months = 0
    normalized_codes = {normalize_code(c) for c in (replace_codes or set())}
    for (year_value, month_value), frame in monthly_frames.items():
        month_dir = wide_root / f"year={year_value:04d}" / f"month={month_value:02d}"
        month_dir.mkdir(parents=True, exist_ok=True)
        path = month_dir / "merged.parquet"
        merged = frame
        if path.is_file():
            old = pl.read_parquet(str(path))
            if normalized_codes and "htsc_code" in old.columns:
                old = old.filter(~pl.col("htsc_code").cast(pl.Utf8).str.strip_chars().str.to_uppercase().is_in(sorted(normalized_codes)))
            merged = pl.concat([old, frame], how="diagonal_relaxed")
        merged = merged.with_columns(
            pl.col("htsc_code").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("htsc_code")
        )
        merged = merged.unique(subset=["htsc_code"], keep="last").sort("htsc_code")
        tmp = path.with_name(path.stem + "._writing_.parquet")
        merged.write_parquet(str(tmp), compression="zstd")
        os.replace(str(tmp), str(path))
        total_months += 1
    return total_months


def parse_qmt_event_date(value: Any) -> pd.Timestamp | pd.NaT:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NaT
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat"}:
        return pd.NaT
    if text.endswith(".0"):
        text = text[:-2]
    if text.isdigit():
        if len(text) >= 13:
            return pd.to_datetime(int(text), unit="ms", errors="coerce").floor("D")
        if len(text) >= 8:
            return pd.to_datetime(text[:8], format="%Y%m%d", errors="coerce")
    return pd.to_datetime(text, errors="coerce").floor("D")


def parse_raw_factor_tables_arg(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.replace("，", ",").split(",") if part.strip()]


def load_xtquant_sector_universe(sector_name: str) -> list[str]:
    xtdata.download_sector_data()
    stock_list = xtdata.get_stock_list_in_sector(sector_name)
    if not stock_list:
        raise RuntimeError(f"xtquant 板块股票池为空: {sector_name}")
    return sorted({normalize_code(code) for code in stock_list if str(code).strip()})


def resolve_codes(sector_name: str, codes_arg: str | None = None) -> list[str]:
    manual = [normalize_code(part) for part in str(codes_arg or "").replace("，", ",").split(",") if part.strip()]
    if manual:
        return sorted(set(manual))
    return load_xtquant_sector_universe(sector_name)


def format_qmt_day(value: datetime | date) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    return datetime.combine(value, datetime.min.time()).strftime("%Y%m%d")


def normalize_qmt_divid_frame(raw_df: pd.DataFrame, code: str, updated_at: str) -> pd.DataFrame:
    if raw_df is None or raw_df.empty:
        return pd.DataFrame(columns=RAW_COLUMNS)
    out = raw_df.copy()
    if "time" not in out.columns:
        out = out.reset_index()
        if "index" in out.columns:
            out["time"] = out["index"]
    out["htsc_code"] = normalize_code(code)
    out["event_date"] = out["time"].map(parse_qmt_event_date)
    out["updated_at"] = updated_at
    for col in ("interest", "stockBonus", "stockGift", "allotNum", "allotPrice", "gugai", "dr", "time"):
        if col not in out.columns:
            out[col] = pd.NA
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["htsc_code", "event_date", "dr"]).copy()
    out = out.drop_duplicates(subset=["htsc_code", "event_date"], keep="last")
    return out[list(RAW_COLUMNS)].sort_values(["event_date", "htsc_code"]).reset_index(drop=True)


def raw_events_to_adj_segments(raw: pd.DataFrame | pl.DataFrame, adj_end: date) -> pl.DataFrame:
    if isinstance(raw, pl.DataFrame):
        pdf = raw.to_pandas()
    else:
        pdf = raw.copy()
    if pdf.empty:
        return pl.DataFrame(schema={"htsc_code": pl.Utf8, "begin_date": pl.Date, "end_date": pl.Date, "xdy": pl.Float64})
    required = {"htsc_code", "event_date", "dr"}
    missing = sorted(required - set(pdf.columns))
    if missing:
        raise ValueError(f"QMT 原始事件缺少列: {missing}")
    pdf["htsc_code"] = pdf["htsc_code"].map(normalize_code)
    cap = pd.Timestamp(adj_end).normalize()
    # QMT time is aligned to the raw corporate-action event day. The legacy
    # Insight segment starts from the effective ex-right day, one calendar day later.
    pdf["begin_date"] = pd.to_datetime(pdf["event_date"], errors="coerce").dt.normalize() + pd.Timedelta(days=1)
    pdf["xdy"] = pd.to_numeric(pdf["dr"], errors="coerce")
    pdf = pdf.dropna(subset=["htsc_code", "begin_date", "xdy"])
    pdf = pdf[pdf["begin_date"] <= cap].copy()
    pdf = pdf[pdf["xdy"] > 0].copy()
    if pdf.empty:
        return pl.DataFrame(schema={"htsc_code": pl.Utf8, "begin_date": pl.Date, "end_date": pl.Date, "xdy": pl.Float64})
    pdf = pdf.sort_values(["htsc_code", "begin_date"]).drop_duplicates(["htsc_code", "begin_date"], keep="last")
    pdf["next_begin"] = pdf.groupby("htsc_code")["begin_date"].shift(-1)
    pdf["end_date"] = pdf["next_begin"].sub(pd.Timedelta(days=1)).fillna(cap)
    pdf["end_date"] = pdf[["begin_date", "end_date"]].max(axis=1)
    out = pl.from_pandas(pdf[["htsc_code", "begin_date", "end_date", "xdy"]])
    return (
        out.with_columns(
            pl.col("htsc_code").cast(pl.Utf8).str.strip_chars().str.to_uppercase(),
            pl.col("begin_date").cast(pl.Date, strict=False),
            pl.col("end_date").cast(pl.Date, strict=False),
            pl.col("xdy").cast(pl.Float64, strict=False),
        )
        .drop_nulls(["htsc_code", "begin_date", "end_date", "xdy"])
        .sort(["htsc_code", "begin_date"])
    )


def _raw_is_readable_parquet(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= RAW_MIN_PARQUET_BYTES and not pl.read_parquet(str(path), n_rows=1).is_empty()
    except Exception:
        return False


def save_raw_partitioned_parquet(df: pd.DataFrame, raw_base_dir: str) -> list[tuple[int, int]]:
    if df is None or df.empty:
        return []
    pl_df = (
        pl.from_pandas(df)
        .with_columns(
            pl.col("event_date").cast(pl.Datetime, strict=False).dt.truncate("1d").alias("event_date"),
            pl.col("htsc_code").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("htsc_code"),
        )
        .drop_nulls(["htsc_code", "event_date"])
        .unique(subset=["htsc_code", "event_date"], keep="last")
        .sort(["event_date", "htsc_code"])
        .with_columns(
            pl.col("event_date").dt.year().alias("year"),
            pl.col("event_date").dt.month().alias("month"),
        )
    )
    touched: list[tuple[int, int]] = []
    for part in pl_df.partition_by(["year", "month"]):
        year = int(part["year"][0])
        month = int(part["month"][0])
        dir_path = Path(raw_base_dir) / f"year={year}" / f"month={month:02d}"
        dir_path.mkdir(parents=True, exist_ok=True)
        file_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{os.getpid()}_year_{year}_month_{month:02d}.parquet"
        save_df = part.drop(["year", "month"])
        save_df.write_parquet(str(dir_path / file_name), compression="zstd")
        touched.append((year, month))
        print(f"[OK] 已保存 QMT 原始复权事件: {dir_path / file_name} ({len(save_df)} 条)")
    return touched


def rebuild_raw_merged_parquets(raw_base_dir: str, touched: set[tuple[int, int]]) -> None:
    for year, month in sorted(touched):
        month_dir = Path(raw_base_dir) / f"year={year}" / f"month={month:02d}"
        merged_path = month_dir / RAW_MERGED_FILE_NAME
        raw_files = sorted(path for path in month_dir.glob("*.parquet") if path.name != RAW_MERGED_FILE_NAME)
        inputs = ([merged_path] if merged_path.exists() else []) + raw_files
        inputs = [path for path in inputs if _raw_is_readable_parquet(path)]
        if not inputs:
            continue
        merged = pl.concat([pl.scan_parquet(str(path)) for path in inputs], how="diagonal_relaxed").collect(engine="streaming")
        merged = (
            merged.with_columns(
                pl.col("event_date").cast(pl.Datetime, strict=False).dt.truncate("1d").alias("event_date"),
                pl.col("htsc_code").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("htsc_code"),
            )
            .drop_nulls(["htsc_code", "event_date"])
            .unique(subset=["htsc_code", "event_date"], keep="last")
            .sort(["event_date", "htsc_code"])
        )
        tmp = merged_path.with_name(f"{merged_path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        merged.write_parquet(str(tmp), compression="zstd")
        tmp.replace(merged_path)
        for raw_file in raw_files:
            try:
                raw_file.unlink()
            except OSError as exc:
                print(f"[WARN] 删除原始 parquet 失败: {raw_file} | {exc}")
        print(f"[OK] 已重建 QMT 原始事件 merged: {merged_path}")


def scan_raw_latest_event_dates(raw_base_dir: str) -> dict[str, datetime]:
    base = Path(raw_base_dir)
    if not base.exists():
        return {}
    pattern = str(base / "year=*" / "month=*" / RAW_MERGED_FILE_NAME).replace("\\", "/")
    try:
        df = duckdb.query(
            f"""
            SELECT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                   MAX(CAST(event_date AS TIMESTAMP)) AS latest_event_date
            FROM read_parquet('{pattern}', union_by_name=true)
            WHERE htsc_code IS NOT NULL AND event_date IS NOT NULL
            GROUP BY 1
            """
        ).df()
    except Exception:
        return {}
    return {
        normalize_code(row["htsc_code"]): pd.Timestamp(row["latest_event_date"]).to_pydatetime()
        for _, row in df.iterrows()
        if pd.notna(row["latest_event_date"])
    }


def load_raw_events(raw_base_dir: str, codes: set[str] | None = None) -> pl.DataFrame:
    base = Path(raw_base_dir)
    pattern = str(base / "year=*" / "month=*" / RAW_MERGED_FILE_NAME).replace("\\", "/")
    if not base.exists():
        return pl.DataFrame(schema={col: pl.Utf8 for col in RAW_COLUMNS})
    try:
        lf = pl.scan_parquet(pattern)
        if codes:
            normalized = sorted(normalize_code(code) for code in codes)
            lf = lf.filter(pl.col("htsc_code").cast(pl.Utf8).str.strip_chars().str.to_uppercase().is_in(normalized))
        return lf.collect(engine="streaming")
    except Exception:
        return pl.DataFrame(schema={col: pl.Utf8 for col in RAW_COLUMNS})


def fetch_qmt_divid_factors(codes: list[str], start_date: datetime, end_date: datetime, sleep_sec: float) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    failed: list[str] = []
    start_text = format_qmt_day(start_date)
    end_text = format_qmt_day(end_date)
    updated_at = datetime.now().isoformat(timespec="seconds")
    total = len(codes)
    for idx, code in enumerate(codes, start=1):
        if idx == 1 or idx % 200 == 0 or idx == total:
            print(f"QMT 复权事件进度 {idx}/{total} {code}")
        try:
            raw = xtdata.get_divid_factors(code, start_text, end_text)
            frame = normalize_qmt_divid_frame(raw, code, updated_at)
            if not frame.empty:
                parts.append(frame)
            else:
                failed.append(code)
        except Exception as exc:
            failed.append(code)
            print(f"[WARN] {code} get_divid_factors 失败: {exc}")
        time.sleep(sleep_sec)
    if failed:
        preview = ", ".join(failed[:40])
        more = f" ...共{len(failed)}只" if len(failed) > 40 else ""
        print(f"[WARN] 未拉到 QMT 复权事件的代码 {len(failed)} 只: {preview}{more}")
    if not parts:
        return pd.DataFrame(columns=RAW_COLUMNS)
    out = pd.concat(parts, ignore_index=True)
    return out.drop_duplicates(["htsc_code", "event_date"], keep="last").reset_index(drop=True)


def build_codes_to_fetch(all_codes: list[str], latest_map: dict[str, datetime], default_start: datetime, overlap_days: int) -> tuple[list[str], datetime]:
    if not latest_map:
        return all_codes, default_start
    latest = max(latest_map.values())
    start_date = latest - timedelta(days=overlap_days)
    return all_codes, start_date.replace(hour=0, minute=0, second=0, microsecond=0)


def write_final_outputs_from_raw(raw_base_dir: str, final_base_dir: str, adj_end: date, codes: set[str] | None = None) -> None:
    raw_pl = load_raw_events(raw_base_dir, codes)
    if raw_pl.is_empty():
        print("[WARN] 未找到可转换的 QMT 原始复权事件。")
        return
    seg = raw_events_to_adj_segments(raw_pl, adj_end)
    if seg.is_empty():
        print("[WARN] QMT 原始事件转换后无有效分段。")
        return
    merge_and_write_adj_segments_parquet(seg, final_base_dir, segment_end_cap=adj_end)
    affected_codes = set(codes or seg.get_column("htsc_code").unique().to_list())
    affected_seg = load_segments_for_codes(final_base_dir, affected_codes)
    monthly_frames = build_monthly_xdy_wide_frames(affected_seg, only_htsc_codes=affected_codes)
    touched = write_monthly_xdy_wide_frames(monthly_frames, base_dir=final_base_dir, replace_codes=affected_codes)
    print(f"[OK] QMT 复权分段与 wide_xdy 已更新，wide_xdy 分区数: {touched}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QMT 日频复权因子：先保存原始除权除息事件，再转换为现有 xdy 分段和 wide_xdy")
    parser.add_argument("--raw-base-dir", default=RAW_BASE_DIR_DEFAULT, help="QMT 原始除权除息事件输出目录")
    parser.add_argument("--final-base-dir", default=FINAL_BASE_DIR_DEFAULT, help="处理后的 stock_adj_daily 输出目录")
    parser.add_argument("--sector-name", default=DEFAULT_SECTOR_NAME, help="xtquant 板块名称，默认 沪深A股")
    parser.add_argument("--codes", default="", help="逗号分隔手动股票代码；不填则使用板块股票池")
    parser.add_argument("--default-start", default=DEFAULT_START_DATE, help="首次全量起始日，YYYY-MM-DD")
    parser.add_argument("--adj-end", default=datetime.now().strftime("%Y-%m-%d"), help="转换后末段结束日，YYYY-MM-DD")
    parser.add_argument("--overlap-days", type=int, default=DEFAULT_OVERLAP_DAYS, help="增量回溯天数")
    parser.add_argument("--sleep-sec", type=float, default=DEFAULT_SLEEP_SEC, help="逐只请求间隔秒")
    parser.add_argument("--max-codes", type=int, default=0, help="调试用，只处理前 N 只")
    parser.add_argument("--raw-only", action="store_true", help="只拉取并保存 QMT 原始事件，不生成最终分段")
    parser.add_argument("--convert-only", action="store_true", help="只读取已保存 raw 并转换最终分段，不请求 QMT")
    parser.add_argument("--no-incremental", action="store_true", help="忽略 raw 最新事件日期，从 default-start 全量请求")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw_base_dir = str(args.raw_base_dir).strip() or RAW_BASE_DIR_DEFAULT
    final_base_dir = str(args.final_base_dir).strip() or FINAL_BASE_DIR_DEFAULT
    adj_end_dt = datetime.strptime(args.adj_end, "%Y-%m-%d")
    default_start = datetime.strptime(args.default_start, "%Y-%m-%d")
    codes = resolve_codes(args.sector_name, args.codes)
    if args.max_codes > 0:
        codes = codes[: args.max_codes]
    code_set = set(codes)

    if args.convert_only:
        write_final_outputs_from_raw(raw_base_dir, final_base_dir, adj_end_dt.date(), code_set if args.codes or args.max_codes > 0 else None)
        return

    latest_map = {} if args.no_incremental else scan_raw_latest_event_dates(raw_base_dir)
    fetch_codes, start_date = build_codes_to_fetch(codes, latest_map, default_start, args.overlap_days)
    if start_date > adj_end_dt:
        print("[INFO] QMT 原始复权事件已是最新，无需请求。")
    else:
        print(f"QMT 原始复权事件请求: {len(fetch_codes)} 只 | {start_date.date()} ~ {adj_end_dt.date()}")
        raw = fetch_qmt_divid_factors(fetch_codes, start_date, adj_end_dt, args.sleep_sec)
        touched = set(save_raw_partitioned_parquet(raw, raw_base_dir))
        rebuild_raw_merged_parquets(raw_base_dir, touched)

    if not args.raw_only:
        write_final_outputs_from_raw(raw_base_dir, final_base_dir, adj_end_dt.date(), code_set if args.codes or args.max_codes > 0 else None)


if __name__ == "__main__":
    main()
