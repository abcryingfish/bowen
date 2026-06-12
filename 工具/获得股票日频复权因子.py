#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""日频复权因子（xdy 分段）下载与存储。

默认写入 ``adj_factor_segments.parquet``，并同步增量维护 ``wide_xdy`` 按月宽表。

与已有文件合并后，按 ``(htsc_code, begin_date)`` 只保留 ``end_date`` 最大的一行（避免延长末段与浮点 xdy 导致的重复）。

增量（默认）：全市场时请求 **本地最后一段尚未覆盖到 ``--adj-end``** 的标的；若接口无新分段，

"""
from __future__ import annotations

from insight_python.com.insight import common
from insight_python.com.insight.query import *
from insight_python.com.insight.market_service import market_service
import argparse
import os
import time
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd
import polars as pl


BASE_DIR_DEFAULT = r"D:\database\stock_adj_daily"
ADJ_SEGMENTS_PARQUET_NAME = "adj_factor_segments.parquet"
WIDE_XDY_DIR_NAME = "wide_xdy"


def normalize_htsc_code(code: str) -> str:
    return str(code).strip().upper()


# 接口常见「无结束日」占位：NaT、<= 该哨兵、或早于本段 begin 的 end 一律按开放段处理
_OPEN_END_SENTINEL = date(1900, 1, 2)


def fix_adj_segment_open_ends_pdf(
    raw: pd.DataFrame,
    segment_end_cap: datetime | date | None,
) -> pd.DataFrame:
    """修正缺失或哨兵 ``end_date``，避免下游 ``date_ranges`` 等出现 1900 年等异常。

    判定为缺失：``end_date`` 为 NaT、不晚于 1900-01-02，或早于同段 ``begin_date``。

    - 若提供 ``segment_end_cap``（一般为 ``--adj-end`` 当天），闭合为 ``max(begin_date, cap)``。
    - 若未提供 cap，则退化为 ``begin_date``（单日段）。
    """
    if raw.empty or "begin_date" not in raw.columns or "end_date" not in raw.columns:
        return raw
    out = raw.copy()
    b = pd.to_datetime(out["begin_date"], errors="coerce").dt.normalize()
    e = pd.to_datetime(out["end_date"], errors="coerce").dt.normalize()
    bad = e.isna() | (e <= pd.Timestamp(_OPEN_END_SENTINEL)) | (e < b)
    if segment_end_cap is not None:
        cap = pd.Timestamp(segment_end_cap).normalize()
        fill_e = pd.concat([b, pd.Series(cap, index=out.index)], axis=1).max(axis=1)
    else:
        fill_e = b
    out["begin_date"] = b
    out["end_date"] = e.where(~bad, fill_e)
    return out


def fix_adj_segment_open_ends_pl(
    df: pl.DataFrame,
    segment_end_cap: date | datetime | None = None,
) -> pl.DataFrame:
    """与 :func:`fix_adj_segment_open_ends_pdf` 同语义，用于合并已有 parquet 时清洗历史脏数据。"""
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


def fetch_all_listed_htsc_codes(
    listing_start: datetime,
    listing_end: datetime,
    listing_state: str = "上市交易",
) -> list[str]:
    """
    与 his_get/获得所有的股票代码.py、工具/获得股票日频数据.py 一致：
    上海 XSHG + 深圳 XSHE 各调一次 get_all_stocks_info，合并 htsc_code 并去重。
    """
    codes: set[str] = set()
    for exchange in ("XSHG", "XSHE"):
        result = get_all_stocks_info(
            listing_date=[listing_start, listing_end],
            exchange=exchange,
            listing_state=listing_state,
        )
        if result is None:
            print(f"⚠️ {exchange} get_all_stocks_info 返回 None，跳过")
            continue
        if not hasattr(result, "columns") or "htsc_code" not in result.columns:
            print(f"⚠️ {exchange} 结果无 htsc_code 列: {getattr(result, 'columns', None)}")
            continue
        for raw in result["htsc_code"].tolist():
            codes.add(normalize_htsc_code(str(raw)))
        print(f"✓ {exchange} 已合并，当前不重复代码数: {len(codes)}")
    return sorted(codes)


def scan_local_adj_htsc_codes(base_dir: str) -> set[str]:
    """返回本地已存有分段数据的 ``htsc_code`` 集合。

    优先读 ``{base_dir}/adj_factor_segments.parquet``；若不存在则回退扫描
    ``**/*.parquet``（兼容旧版按年月分区目录）。
    """
    base = Path(base_dir)
    single = base / ADJ_SEGMENTS_PARQUET_NAME
    paths_to_try: list[str] = []
    if single.is_file():
        paths_to_try.append(str(single).replace("\\", "/"))
    if not os.path.isdir(base_dir):
        return set()
    if not paths_to_try:
        pattern = os.path.join(base_dir, "**", "*.parquet").replace("\\", "/")
        paths_to_try.append(pattern)
    try:
        codes: set[str] = set()
        for p in paths_to_try:
            q = f"""
            SELECT DISTINCT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code
            FROM read_parquet('{p}')
            WHERE htsc_code IS NOT NULL
            """
            df = duckdb.query(q).df()
            if not df.empty:
                codes.update(normalize_htsc_code(str(x)) for x in df["htsc_code"].tolist())
        return codes
    except Exception as exc:
        print(f"⚠️ 扫描本地复权 parquet 失败（将按无本地数据全量拉取）: {exc}")
        return set()


def scan_local_adj_max_end_by_code(base_dir: str) -> dict[str, date]:
    """每只标的在本地 parquet 中的「有效最后结束日」``max(end)``（用于判断是否要再拉接口）。

    将 ``end_date <= 1900-01-02`` 视为无效，参与比较时用 ``begin_date`` 代替。
    """
    path = Path(base_dir) / ADJ_SEGMENTS_PARQUET_NAME
    if not path.is_file():
        return {}
    p = str(path).replace("\\", "/")
    try:
        q = f"""
        SELECT
          UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
          max(
            CASE
              WHEN CAST(end_date AS DATE) <= DATE '1900-01-02' THEN CAST(begin_date AS DATE)
              ELSE CAST(end_date AS DATE)
            END
          ) AS mx
        FROM read_parquet('{p}')
        WHERE htsc_code IS NOT NULL
        GROUP BY 1
        """
        df = duckdb.query(q).df()
        if df.empty:
            return {}
        out: dict[str, date] = {}
        for _, row in df.iterrows():
            code = normalize_htsc_code(str(row["htsc_code"]))
            mx = row["mx"]
            if pd.isna(mx):
                continue
            out[code] = pd.Timestamp(mx).date()
        return out
    except Exception as exc:
        print(f"⚠️ 读取本地分段 max(end_date) 失败（将按无本地数据全量拉取）: {exc}")
        return {}


def extend_last_segment_end_to_cap(
    merged: pl.DataFrame,
    cap: date,
    *,
    only_htsc_codes: set[str] | None = None,
) -> pl.DataFrame:
    """对每只标的 **时间序上最后一段**（按 begin_date、end_date 排序后的末行），若 ``end_date < cap`` 则延长为 ``max(begin_date, cap)``。

    ``only_htsc_codes`` 非空时只处理这些代码（用于接口整批无返回时仅延长本次待更新标的）。
    """
    if merged.is_empty() or "htsc_code" not in merged.columns:
        return merged
    cap_lit = pl.lit(cap).cast(pl.Date)
    work = merged.sort(["htsc_code", "begin_date", "end_date"])
    b = pl.col("begin_date").cast(pl.Date, strict=False)
    e = pl.col("end_date").cast(pl.Date, strict=False)
    # 全局最后一行 shift(-1) 为 null，用 fill_null(True) 仍视为「该标的末段」
    is_last = (pl.col("htsc_code") != pl.col("htsc_code").shift(-1)).fill_null(True)
    need = is_last & (e < cap_lit)
    if only_htsc_codes:
        codes_upper = [normalize_htsc_code(c) for c in only_htsc_codes]
        need = need & pl.col("htsc_code").cast(pl.Utf8).str.strip_chars().str.to_uppercase().is_in(codes_upper)
    new_end = pl.when(need).then(pl.max_horizontal(b, cap_lit)).otherwise(e).alias("end_date")
    return work.with_columns(new_end)


def collapse_adj_segments_same_begin_pl(df: pl.DataFrame) -> pl.DataFrame:
    """同 ``(htsc_code, begin_date)`` 只保留 ``end_date`` 最大的一整行（含 ``xdy``）。

    用于清理：延长末段后 API 再带回旧 ``end_date``、或 ``xdy`` 浮点末位不同导致的重复行。
    新除权分段 ``begin_date`` 不同，不会被合并。
    """
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


def rewrite_parquet_extend_last_ends(
    base_dir: str,
    cap: date,
    only_htsc_codes: set[str] | None,
) -> tuple[bool, int]:
    """读已有 ``adj_factor_segments.parquet``，清洗开放段并延长末段 ``end_date`` 至 ``cap`` 后写回。"""
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


def segments_pandas_to_polars_normalized(raw: pd.DataFrame) -> pl.DataFrame:
    """接口 DataFrame -> 标准四列 Polars（Date + xdy）。"""
    cols = ["htsc_code", "begin_date", "end_date", "xdy"]
    missing = [c for c in cols if c not in raw.columns]
    if missing:
        raise ValueError(f"接口结果缺少列: {missing}")
    pdf = raw.loc[:, cols].copy()
    pdf["htsc_code"] = pdf["htsc_code"].map(normalize_htsc_code)
    pdf["begin_date"] = pd.to_datetime(pdf["begin_date"], errors="coerce").dt.normalize()
    pdf["end_date"] = pd.to_datetime(pdf["end_date"], errors="coerce").dt.normalize()
    pdf["xdy"] = pd.to_numeric(pdf["xdy"], errors="coerce")
    pdf = pdf.dropna(subset=["htsc_code", "begin_date", "end_date"])
    pdf = pdf.drop_duplicates(subset=["htsc_code", "begin_date", "end_date"], keep="last")
    out = pl.from_pandas(pdf)
    out = out.with_columns(
        [
            pl.col("begin_date").cast(pl.Date),
            pl.col("end_date").cast(pl.Date),
            pl.col("xdy").cast(pl.Float64),
        ]
    )
    return out.drop_nulls(subset=["begin_date", "end_date"]).sort(["htsc_code", "begin_date"])


def merge_and_write_adj_segments_parquet(
    new_seg: pl.DataFrame,
    base_dir: str,
    *,
    segment_end_cap: date | datetime | None = None,
) -> tuple[Path, int]:
    """与 ``{base_dir}/adj_factor_segments.parquet`` 合并后整表重写（原子替换）。

    先按四元组去重（保留本次拉取），再按 ``(htsc_code, begin_date)`` 只保留 ``end_date`` 最大行。
    """
    os.makedirs(base_dir, exist_ok=True)
    path = Path(base_dir) / ADJ_SEGMENTS_PARQUET_NAME
    if new_seg.is_empty():
        if path.is_file():
            cap_d = _to_py_date(segment_end_cap) if segment_end_cap is not None else None
            if cap_d is not None:
                _, n = rewrite_parquet_extend_last_ends(base_dir, cap_d, None)
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
        seg = seg.filter(pl.col("htsc_code").is_in(sorted(normalize_htsc_code(c) for c in codes)))
    return seg.drop_nulls(subset=["htsc_code", "begin_date", "end_date", "xdy"]).sort(["htsc_code", "begin_date", "end_date"])


def _adj_response_ok(r) -> bool:
    if r is None or isinstance(r, str):
        return False
    return hasattr(r, "columns") and "htsc_code" in r.columns and not r.empty


def fetch_adj_factor_segments_batched(
    codes: list[str],
    begin_date: list[datetime],
    sleep_sec: float = 0.05,
) -> pd.DataFrame:
    """
    对代码列表逐个调用 get_adj_factor（华泰该接口为单标的 HTSC_SECURITY_ID，
    逗号批量不可靠，已取消批量捷径，保证全市场每只都会请求到）。
    """
    parts: list[pd.DataFrame] = []
    failed: list[str] = []
    n = len(codes)
    for i, c in enumerate(codes):
        if i == 0 or (i + 1) % 200 == 0 or i + 1 == n:
            print(f"复权因子进度 {i + 1}/{n}  {c}")
        r = get_adj_factor(htsc_code=c, begin_date=begin_date)
        if _adj_response_ok(r):
            parts.append(r)
        else:
            failed.append(c)
        time.sleep(sleep_sec)

    if failed:
        preview = ", ".join(failed[:40])
        more = f" …共{len(failed)}只" if len(failed) > 40 else ""
        print(f"⚠️ 未拉到复权因子的代码 {len(failed)} 只（控制台预览，不写文件）：{preview}{more}")

    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    nu = out["htsc_code"].map(normalize_htsc_code).nunique() if "htsc_code" in out.columns else 0
    print(f"合并完成：分段行数 {len(out)}，不同标的数 {nu}（请求标的数 {n}）")
    return out


def _to_py_date(d: datetime | date | None) -> date | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    return d


def _wide_date_columns_to_slash(wide: pl.DataFrame) -> pl.DataFrame:
    """将透视列名 2024-01-01 -> 2024/1/1（首列 htsc_code 不变）。"""
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
    """宽表中除代码列外，null / NaN 视为空白，统一填 1.0（乘子为 1 即不复权）。"""
    cols = [c for c in wide.columns if c != code_col]
    if not cols:
        return wide
    return wide.with_columns(
        [pl.col(c).fill_null(1.0).fill_nan(1.0).alias(c) for c in cols]
    )


def _seg_parse_dates(seg: pl.DataFrame) -> pl.DataFrame:
    """begin/end 可能是 API 字符串 'YYYY-MM-DD HH:MM:SS' 或 Datetime。"""
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


def post_adj_segments_to_daily_wide_pl(
    seg: pl.DataFrame,
    *,
    date_min: date | None = None,
    date_max: date | None = None,
) -> pl.DataFrame:
    """
    分段复权因子 -> 按自然日展开的宽表矩阵（Polars）。
    行：htsc_code；列：YYYY/M/D；格：单元值来自上游传入列 `post_adj_cum`（在 xdy_segment 模式下即为该日所在段的 **xdy**）。

    date_min / date_max：仅保留该自然日区间内的列（与行情对齐时可缩小宽表）。
    透视后无分段覆盖的格子为 null/NaN，会填为 1.0（等价于该日乘子为 1）。
    """
    seg = _seg_parse_dates(
        seg.select(
            pl.col("htsc_code"),
            pl.col("begin_date"),
            pl.col("end_date"),
            pl.col("post_adj_cum").cast(pl.Float64),
        )
    )
    long_df = (
        seg.with_columns(
            pl.date_ranges(
                pl.col("begin_date"),
                pl.col("end_date"),
                interval="1d",
            ).alias("date")
        )
        .explode("date")
    )
    if date_min is not None:
        long_df = long_df.filter(pl.col("date") >= pl.lit(date_min).cast(pl.Date))
    if date_max is not None:
        long_df = long_df.filter(pl.col("date") <= pl.lit(date_max).cast(pl.Date))
    wide = long_df.pivot(
        on="date",
        index="htsc_code",
        values="post_adj_cum",
        aggregate_function="first",
    )
    wide = _wide_date_columns_to_slash(wide)
    return _wide_fill_blank_with_one(wide)


def build_monthly_xdy_wide_frames(
    seg: pl.DataFrame,
    *,
    only_htsc_codes: set[str] | None = None,
) -> dict[tuple[int, int], pl.DataFrame]:
    """分段表 -> 按月拆分的 xdy 宽表。"""
    if seg.is_empty():
        return {}
    work = seg.select(
        pl.col("htsc_code").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("htsc_code"),
        pl.col("begin_date").cast(pl.Date, strict=False),
        pl.col("end_date").cast(pl.Date, strict=False),
        pl.col("xdy").cast(pl.Float64, strict=False).alias("post_adj_cum"),
    )
    if only_htsc_codes:
        work = work.filter(pl.col("htsc_code").is_in(sorted(normalize_htsc_code(c) for c in only_htsc_codes)))
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
    """将按月宽表增量写入 ``wide_xdy/year=YYYY/month=MM/merged.parquet``。"""
    wide_root = Path(base_dir) / WIDE_XDY_DIR_NAME
    total_months = 0
    normalized_codes = {normalize_htsc_code(c) for c in (replace_codes or set())}
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


def get_kline_demo():
    """
    :param htsc_code: 华泰证券代码，支持多个code查询，列表类型
    :param time: 时间范围，list类型，开始结束时间为datetime
    :param frequency: 频率，分钟K（‘1min’，’5min’，’15min’，’60min’），日K（‘daily’），周K（‘weekly’），月K（‘monthly’）
    :param fq: 复权，默认前复权”pre”，后复权为”post”，不复权“none”
    :return:pandas.DataFrame
    """

    time_start_date = "2022-01-16 15:10:11"
    time_end_date = "2023-01-18 11:20:50"
    time_start_date = datetime.strptime(time_start_date, '%Y-%m-%d %H:%M:%S')
    time_end_date = datetime.strptime(time_end_date, '%Y-%m-%d %H:%M:%S')

    # time_start_date = "2021-01-14"
    # time_end_date = "2022-10-20"
    # time_start_date = datetime.strptime(time_start_date, '%Y-%m-%d')
    # time_end_date = datetime.strptime(time_end_date, '%Y-%m-%d')

    result = get_kline(htsc_code=["510050.SH", "601688.SH"], time=[time_start_date, time_end_date],
                       frequency="daily", fq="none")
    print(result)




# 查询成交分价
def get_trade_distribution_demo():
    """
    :param htsc_code: 华泰证券代码，支持多个code查询，列表类型
    :param trading_day: 时间范围，list类型，开始结束时间为datetime
    :return: pandas.DataFrame
    """

    start_date = '2021-01-13'
    end_date = '2021-12-11'
    # 转为时间格式
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    result = get_trade_distribution(htsc_code=["601688.SH", "601686.SH"], trading_day=[start_date, end_date])
    print(result)




# ************************************处理查询请求返回结果************************************
class insightmarketservice(market_service):

    def on_query_response(self, result):
        # pass
        for response in iter(result):
            print(response)


# ************************************用户登录************************************
# 登陆
# user 用户名
# password 密码
# login_log 登录日志，默认False
def login():
    
    markets = insightmarketservice()
    # 登陆前 初始化
    user = "MDIL1_01042"
    password = "weS._+7atE4Vdr"
    IP2="153.3.219.107"
    port=9362
    result = common.login(markets, user, password, login_log=False)

    print(result)


# 配置日志打开
# open_trace trace日志开关     True为打开日志False关闭日志
# open_file_log  本地file日志开关     True为打开日志False关闭日志
# open_cout_log  控制台日志开关     True为打开日志False关闭日志
def config(open_trace=True, open_file_log=True, open_cout_log=True):
    common.config(open_trace, open_file_log, open_cout_log)


# 获取当前版本号
def get_version():
    print(common.get_version())


# 释放资源
def fini():
    common.fini()


def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "日频复权因子 xdy 分段：默认写入 ``--base-dir`` 下的 ``adj_factor_segments.parquet``，"
            "并同步增量维护 ``wide_xdy`` 按月宽表。"
        )
    )
    p.add_argument(
        "--base-dir",
        type=str,
        default=BASE_DIR_DEFAULT,
        help=f"复权数据目录，写入 {ADJ_SEGMENTS_PARQUET_NAME}（默认 {BASE_DIR_DEFAULT}）",
    )
    p.add_argument(
        "--no-incremental",
        action="store_true",
        help="全市场时对全部代码重新请求 API（默认：仅当本地末段 end_date 尚未达到 --adj-end 时才请求，并在无新分段时延长末段）",
    )
    p.add_argument(
        "--htsc-code",
        type=str,
        default=None,
        help="若指定则只拉该标的四列；不传则默认全市场（先拉 universe 再对全部代码请求复权因子）",
    )
    p.add_argument(
        "--from-universe",
        action="store_true",
        help="兼容旧命令行（默认已是全市场拉 universe，可不写）",
    )
    p.add_argument(
        "--max-codes",
        type=int,
        default=0,
        help="全市场时只处理前 N 只（调试）；默认 0 表示不截断、一次性全市场",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="已废弃：复权因子仅逐只请求，该参数无效",
    )
    p.add_argument(
        "--skip-universe",
        action="store_true",
        help="全市场时：不调用 get_all_stocks_info，改为从脚本同目录 universe_htsc_codes.csv **只读** 代码表（需自行准备该 CSV）",
    )
    p.add_argument(
        "--adj-begin",
        type=str,
        default="2010-01-01",
        help="get_adj_factor 的 begin_date 区间左端 YYYY-MM-DD",
    )
    p.add_argument(
        "--adj-end",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="get_adj_factor 的 begin_date 区间右端 YYYY-MM-DD（默认：脚本运行当天）",
    )
    p.add_argument(
        "--repair-segments",
        action="store_true",
        help="不请求 API：读取已有 adj_factor_segments.parquet，按 (code,begin) 去重并可选延长末段到 --adj-end 后写回",
    )
    return p.parse_args()


def repair_adj_segments_parquet(
    base_dir: str,
    cap: date | None,
) -> tuple[bool, int]:
    """清洗已有分段 parquet（同 begin 留最长 end），可选延长末段至 cap。"""
    path = Path(base_dir) / ADJ_SEGMENTS_PARQUET_NAME
    if not path.is_file():
        print(f"未找到分段文件: {path}")
        return False, 0
    merged = pl.read_parquet(str(path))
    merged = fix_adj_segment_open_ends_pl(merged, cap)
    merged = merged.drop_nulls(subset=["htsc_code", "begin_date", "end_date"])
    merged = merged.unique(subset=["htsc_code", "begin_date", "end_date", "xdy"], keep="last")
    n0 = len(merged)
    merged = collapse_adj_segments_same_begin_pl(merged)
    if len(merged) < n0:
        print(f"✓ 已按 (htsc_code, begin_date) 合并重复分段 {n0 - len(merged)} 行")
    if cap is not None:
        merged = extend_last_segment_end_to_cap(merged, cap, only_htsc_codes=None)
    merged = merged.sort(["htsc_code", "begin_date", "end_date"])
    tmp = path.with_name(path.stem + "._writing_.parquet")
    merged.write_parquet(str(tmp), compression="zstd")
    os.replace(str(tmp), str(path))
    print(f"✓ 已修复并写回: {path}  共 {len(merged)} 行")
    return True, len(merged)


# 使用指导：登陆 -> 订阅/查询/回放 -> 退出
def main():
    args = parse_args()
    base_dir = str(args.base_dir).strip() or BASE_DIR_DEFAULT
    os.makedirs(base_dir, exist_ok=True)

    if args.repair_segments:
        cap_d = datetime.strptime(args.adj_end, "%Y-%m-%d").date()
        repair_adj_segments_parquet(base_dir, cap_d)
        return

    get_version()
    login()
    config(False, False, False)

    all_codes: list[str] = []
    codes_to_fetch: list[str] = []

    script_dir = Path(__file__).resolve().parent
    universe_path = script_dir / "universe_htsc_codes.csv"

    begin_date_start_date = datetime.strptime(args.adj_begin, "%Y-%m-%d")
    begin_date_end_date = datetime.strptime(args.adj_end, "%Y-%m-%d")

    single = bool(args.htsc_code and str(args.htsc_code).strip())

    if single:
        code = normalize_htsc_code(args.htsc_code)
        raw = get_adj_factor(htsc_code=code, begin_date=[begin_date_start_date, begin_date_end_date])
        if isinstance(raw, str) or raw is None:
            print(f"get_adj_factor 失败: {raw}")
            fini()
            return
        if not hasattr(raw, "columns") or raw.empty:
            print("get_adj_factor 返回空或无列")
            fini()
            return
        all_codes = [code]
        codes_to_fetch = list(all_codes)
    else:
        if args.skip_universe:
            if not universe_path.is_file():
                print(f"错误：已指定 --skip-universe 但未找到 {universe_path}")
                fini()
                return
            all_codes = (
                pd.read_csv(universe_path)["htsc_code"]
                .astype(str)
                .map(normalize_htsc_code)
                .tolist()
            )
            print(f"已从 CSV 读取代码表: {universe_path}  共 {len(all_codes)} 条")
        else:
            listing_start = datetime(1950, 1, 14)
            listing_end = datetime(2030, 12, 31)
            all_codes = fetch_all_listed_htsc_codes(listing_start, listing_end)
            print(f"全市场 htsc_code 已获取: {len(all_codes)} 条（不落盘 CSV，仅内存用于本次拉取）")

        if args.max_codes > 0:
            all_codes = all_codes[: args.max_codes]
            print(f"分段因子仅请求前 {len(all_codes)} 只（--max-codes={args.max_codes}）")
        else:
            print(f"分段因子请求全市场共 {len(all_codes)} 只（--max-codes 0）")

        adj_cap = begin_date_end_date.date()
        local_max_end = scan_local_adj_max_end_by_code(base_dir)
        if local_max_end:
            print(f"本地 parquet 已覆盖 {len(local_max_end)} 只标的的末段结束日（目录: {base_dir}）")

        if args.no_incremental:
            codes_to_fetch = list(all_codes)
            print("已指定 --no-incremental：将对全市场重新请求 API。")
        else:
            codes_to_fetch = [
                c for c in all_codes if local_max_end.get(c) is None or local_max_end[c] < adj_cap
            ]
            skipped = len(all_codes) - len(codes_to_fetch)
            if skipped:
                print(
                    f"增量模式：末段已覆盖至 --adj-end（{adj_cap}）的代码 {skipped} 只无需请求；"
                    f"待请求/刷新 {len(codes_to_fetch)} 只。"
                )
            else:
                print(f"增量模式：待请求/刷新 {len(codes_to_fetch)} 只（本地无数据或末段早于 adj-end）。")

        if not codes_to_fetch:
            print(f"所有标的本地分段末日期已达到或晚于 --adj-end（{adj_cap}），无需请求 API。")
            fini()
            return

        print(f"待请求复权的证券数: {len(codes_to_fetch)}")

        raw = fetch_adj_factor_segments_batched(
            codes_to_fetch,
            [begin_date_start_date, begin_date_end_date],
        )

    if raw.empty:
        print("接口未返回新的分段行（或全部请求失败）。")
        cap_d = begin_date_end_date.date()
        if codes_to_fetch:
            rewrite_parquet_extend_last_ends(base_dir, cap_d, set(codes_to_fetch))
            affected_seg = load_segments_for_codes(base_dir, set(codes_to_fetch))
            monthly_frames = build_monthly_xdy_wide_frames(affected_seg, only_htsc_codes=set(codes_to_fetch))
            touched = write_monthly_xdy_wide_frames(monthly_frames, base_dir=base_dir, replace_codes=set(codes_to_fetch))
            print(f"复权因子按月宽表已更新 {touched} 个月分区（仅受影响标的）")
        fini()
        return

    # 接口缺失 end_date 时常为 NaT 或 1900 占位；先闭合再写 parquet，避免 date_ranges 污染
    raw = fix_adj_segment_open_ends_pdf(raw, begin_date_end_date)

    try:
        seg_pl = segments_pandas_to_polars_normalized(raw)
    except ValueError as exc:
        print(f"数据列校验失败: {exc}")
        fini()
        return

    if seg_pl.is_empty():
        print("规范化后无有效分段行。")
        cap_d = begin_date_end_date.date()
        if codes_to_fetch:
            rewrite_parquet_extend_last_ends(base_dir, cap_d, set(codes_to_fetch))
        fini()
        return

    merge_and_write_adj_segments_parquet(
        seg_pl,
        base_dir,
        segment_end_cap=begin_date_end_date.date(),
    )

    affected_codes = set(codes_to_fetch) if codes_to_fetch else set(all_codes)
    affected_seg = load_segments_for_codes(base_dir, affected_codes)
    monthly_frames = build_monthly_xdy_wide_frames(affected_seg, only_htsc_codes=affected_codes)
    touched = write_monthly_xdy_wide_frames(monthly_frames, base_dir=base_dir, replace_codes=affected_codes)
    print(f"复权因子按月宽表已更新 {touched} 个月分区（仅受影响标的）")

    fini()



if __name__ == '__main__':
    main()
