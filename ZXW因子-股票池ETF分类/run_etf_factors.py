#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ETF 股票池日线因子计算入口。

本脚本只处理 ETF 日线 OHLCV 因子，不修改原始 ZXW 因子目录。
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import polars as pl


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

DEFAULT_ETF_DAILY_ROOT = Path(r"D:\database\ETF_basic_data_daily")
DEFAULT_OUTPUT_ROOT = Path(r"D:\database\signal_daily_etf")
DEFAULT_START_DATE = "2010-01-01"
MERGED_FILE_NAME = "merged.parquet"
REPORT_DIR_NAME = "_reports"

CODE_COLUMNS = (
    "etf_code",
    "htsc_code",
    "stock_code",
    "code",
    "证券代码",
    "代码",
)

MA_WINDOWS = (5, 10, 15, 20, 30, 40, 50, 60, 70, 120)

BUNDLE_MODULES = {
    "new_hl_ratio": "新HL占比",
    "kdj": "KDJ因子",
    "macd": "MACD因子",
    "obv": "OBV因子",
    "rsi": "RSI",
    "boll_strategy": "布林带策略",
    "dynamic_volatility_channel": "动态波动率通道",
    "volume_drop": "放量下跌因子",
    "hong_bottom_fishing": "洪抄底",
    "moving_average": "均线因子",
    "macd_sell": "卖出MACD",
    "donchian_lower": "唐奇安下通道",
}


class PoolCodesResult:
    def __init__(
        self,
        *,
        codes: list[str],
        code_column: str,
        raw_code_count: int,
        skipped_codes: list[dict[str, str]],
    ) -> None:
        self.codes = codes
        self.code_column = code_column
        self.raw_code_count = raw_code_count
        self.skipped_codes = skipped_codes

    def as_report(self) -> dict[str, Any]:
        return {
            "codes": self.codes,
            "code_column": self.code_column,
            "raw_code_count": self.raw_code_count,
            "valid_code_count": len(self.codes),
            "skipped_codes": self.skipped_codes,
        }


def normalize_code(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip().upper()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def _read_csv_with_fallback(path: Path) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "gbk", "utf-8"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return pd.read_csv(path, encoding="utf-8-sig")


def read_pool_file(path: str | Path) -> pd.DataFrame:
    pool_path = Path(path)
    suffix = pool_path.suffix.lower()
    if suffix == ".csv":
        return _read_csv_with_fallback(pool_path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(pool_path)
    raise ValueError(f"不支持的股票池文件类型: {pool_path.suffix}")


def detect_code_column(df: pd.DataFrame) -> str:
    normalized_by_column = {str(column).strip().lower(): column for column in df.columns}
    for candidate in CODE_COLUMNS:
        key = candidate.lower()
        if key in normalized_by_column:
            return str(normalized_by_column[key])
    raise ValueError(f"未找到 ETF 代码列，可识别列: {', '.join(CODE_COLUMNS)}")


def load_pool_codes(path: str | Path, existing_etf_codes: set[str], limit_codes: int | None = None) -> PoolCodesResult:
    df = read_pool_file(path)
    code_column = detect_code_column(df)
    raw_codes = [normalize_code(value) for value in df[code_column].tolist()]
    ordered_codes: list[str] = []
    seen: set[str] = set()
    skipped: list[dict[str, str]] = []

    for code in raw_codes:
        if not code:
            continue
        if code in seen:
            continue
        seen.add(code)
        if code not in existing_etf_codes:
            skipped.append({"code": code, "reason": "not_in_etf_daily_data"})
            continue
        ordered_codes.append(code)
        if limit_codes is not None and len(ordered_codes) >= limit_codes:
            break

    return PoolCodesResult(
        codes=ordered_codes,
        code_column=code_column,
        raw_code_count=len([code for code in raw_codes if code]),
        skipped_codes=skipped,
    )


def _merged_parquet_files(base_dir: Path) -> list[Path]:
    if not base_dir.exists():
        return []
    return sorted(base_dir.glob("year=*/month=*/merged.parquet"))


def list_existing_etf_codes(etf_daily_root: str | Path = DEFAULT_ETF_DAILY_ROOT) -> set[str]:
    files = _merged_parquet_files(Path(etf_daily_root))
    if not files:
        return set()
    frames = [
        pl.scan_parquet(str(path)).select(pl.col("htsc_code").cast(pl.Utf8))
        for path in files
    ]
    return set(pl.concat(frames).unique().collect()["htsc_code"].to_list())


def _partition_months_between(start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[int, int]]:
    cursor = pd.Timestamp(year=start.year, month=start.month, day=1)
    last = pd.Timestamp(year=end.year, month=end.month, day=1)
    months: list[tuple[int, int]] = []
    while cursor <= last:
        months.append((int(cursor.year), int(cursor.month)))
        cursor = cursor + pd.DateOffset(months=1)
    return months


def _daily_files_for_range(base_dir: Path, start: pd.Timestamp, end: pd.Timestamp) -> list[Path]:
    files: list[Path] = []
    for year, month in _partition_months_between(start, end):
        path = base_dir / f"year={year}" / f"month={month:02d}" / MERGED_FILE_NAME
        if path.exists():
            files.append(path)
    return files


def load_etf_daily_data(
    *,
    etf_daily_root: str | Path,
    codes: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    files = _daily_files_for_range(Path(etf_daily_root), start, end)
    if not files:
        return pd.DataFrame(columns=["htsc_code", "time", "open", "high", "low", "close", "volume"])
    scan = pl.scan_parquet([str(path) for path in files])
    df = (
        scan.filter(
            pl.col("htsc_code").is_in(codes)
            & (pl.col("time") >= pl.lit(start.to_pydatetime()))
            & (pl.col("time") <= pl.lit(end.to_pydatetime()))
        )
        .select(["htsc_code", "time", "open", "high", "low", "close", "volume"])
        .collect()
    )
    if df.is_empty():
        return pd.DataFrame(columns=["htsc_code", "time", "open", "high", "low", "close", "volume"])
    out = df.to_pandas()
    out["time"] = pd.to_datetime(out["time"]).dt.floor("D")
    return out.sort_values(["time", "htsc_code"]).reset_index(drop=True)


def get_latest_etf_daily_time(etf_daily_root: str | Path, codes: list[str]) -> pd.Timestamp | None:
    files = _merged_parquet_files(Path(etf_daily_root))
    if not files:
        return None
    scan = pl.scan_parquet([str(path) for path in files])
    df = scan.filter(pl.col("htsc_code").is_in(codes)).select(pl.max("time").alias("max_time")).collect()
    if df.is_empty() or df["max_time"][0] is None:
        return None
    return pd.Timestamp(df["max_time"][0]).floor("D")


def build_wide_ohlcv(daily: pd.DataFrame, codes: list[str]) -> dict[str, pd.DataFrame]:
    if daily.empty:
        empty_index = pd.DatetimeIndex([], name="time")
        return {
            key: pd.DataFrame(index=empty_index, columns=codes, dtype=float)
            for key in ("O", "H", "L", "C", "V")
        } | {"VALID_BAR": pd.DataFrame(index=empty_index, columns=codes, dtype=bool)}

    df = daily.copy()
    df["time"] = pd.to_datetime(df["time"]).dt.floor("D")
    df["htsc_code"] = df["htsc_code"].astype(str).str.upper()

    def pivot(column: str) -> pd.DataFrame:
        wide = (
            df.pivot_table(index="time", columns="htsc_code", values=column, aggfunc="last")
            .sort_index()
            .reindex(columns=codes)
        )
        wide.index = pd.DatetimeIndex(wide.index, name="time")
        return wide.astype(float)

    close = pivot("close")
    return {
        "O": pivot("open"),
        "H": pivot("high"),
        "L": pivot("low"),
        "C": close,
        "V": pivot("volume"),
        "VALID_BAR": close.notna(),
    }


def _import_bundle_modules() -> dict[str, Any]:
    return {bundle: importlib.import_module(module_name) for bundle, module_name in BUNDLE_MODULES.items()}


def get_max_bundle_lookback_days() -> int:
    max_days = 0
    for module in _import_bundle_modules().values():
        getter = getattr(module, "get_factor_lookback_config", None)
        if getter is None:
            continue
        config = getter()
        max_days = max(max_days, int(config.get("bundle_lookback_days") or 0))
    return max_days


def compute_factor_bundles(wide: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    modules = _import_bundle_modules()
    O, H, L, C, V = wide["O"], wide["H"], wide["L"], wide["C"], wide["V"]
    bundle_calls: list[tuple[str, Callable[[], dict[str, Any]]]] = [
        ("new_hl_ratio", lambda: modules["new_hl_ratio"].build_new_hl_ratio_factor_bundle(C=C, window=20)),
        ("kdj", lambda: modules["kdj"].build_kdj_factor_bundle(O=O, H=H, L=L, C=C)),
        ("macd", lambda: modules["macd"].build_d_class_factor_bundle(O=O, H=H, L=L, C=C)),
        ("obv", lambda: modules["obv"].build_obv_factor_bundle(C=C, V=V)),
        ("rsi", lambda: modules["rsi"].build_rsi_factor_bundle(C=C)),
        ("boll_strategy", lambda: modules["boll_strategy"].build_boll_strategy_factor_bundle(C=C, window=20, k=2.0)),
        (
            "dynamic_volatility_channel",
            lambda: modules["dynamic_volatility_channel"].build_dynamic_volatility_channel_factor_bundle(
                H=H,
                L=L,
                C=C,
                high_window=20,
                atr_window=14,
                atr_multiplier=1.5,
            ),
        ),
        ("volume_drop", lambda: modules["volume_drop"].build_volume_drop_factor_bundle(C=C, V=V, volume_window=20)),
        ("hong_bottom_fishing", lambda: modules["hong_bottom_fishing"].build_bottom_fishing_factor_bundle(O=O, H=H, L=L, C=C)),
        ("moving_average", lambda: modules["moving_average"].build_moving_average_factor_bundle(C=C, windows=MA_WINDOWS)),
        ("macd_sell", lambda: modules["macd_sell"].build_macd_sell_factor_bundle(O=O, H=H, L=L, C=C)),
        ("donchian_lower", lambda: modules["donchian_lower"].build_donchian_lower_channel_factor_bundle(C=C, n=10)),
    ]

    factor_frames: dict[str, pd.DataFrame] = {}
    for bundle_name, call in bundle_calls:
        print(f"[BUNDLE] {bundle_name}")
        output = call()
        for factor_name, frame in output.get("factor_dfs", {}).items():
            factor_frames[str(factor_name)] = frame.reindex(index=C.index, columns=C.columns)
    return factor_frames


def _factor_dir(output_root: Path, factor_name: str) -> Path:
    return output_root / f"factor={factor_name}"


def get_factor_latest_time(output_root: str | Path, factor_name: str) -> pd.Timestamp | None:
    files = _merged_parquet_files(_factor_dir(Path(output_root), factor_name))
    if not files:
        return None
    scan = pl.scan_parquet([str(path) for path in files])
    df = scan.select(pl.max("time").alias("max_time")).collect()
    if df.is_empty() or df["max_time"][0] is None:
        return None
    return pd.Timestamp(df["max_time"][0]).floor("D")


def get_output_latest_time(output_root: str | Path) -> pd.Timestamp | None:
    root = Path(output_root)
    if not root.exists():
        return None
    files = sorted(root.glob("factor=*/year=*/month=*/merged.parquet"))
    if not files:
        return None
    scan = pl.scan_parquet([str(path) for path in files])
    df = scan.select(pl.max("time").alias("max_time")).collect()
    if df.is_empty() or df["max_time"][0] is None:
        return None
    return pd.Timestamp(df["max_time"][0]).floor("D")


def _frame_to_long(frame: pd.DataFrame, factor_name: str, save_after: pd.Timestamp | None) -> pl.DataFrame:
    out = frame.copy()
    out.index = pd.to_datetime(out.index).floor("D")
    out.index.name = "time"
    if save_after is not None:
        out = out.loc[out.index > save_after]
    if out.empty:
        return pl.DataFrame(schema={"time": pl.Datetime, "htsc_code": pl.Utf8, "value": pl.Float32})
    long_df = (
        out.reset_index()
        .melt(id_vars="time", var_name="htsc_code", value_name="value")
    )
    long_df["time"] = pd.to_datetime(long_df["time"]).dt.floor("D")
    long_df["htsc_code"] = long_df["htsc_code"].astype(str)
    long_df["value"] = pd.to_numeric(long_df["value"], errors="coerce").astype("float32")
    long_df = long_df[["time", "htsc_code", "value"]]
    return pl.from_pandas(long_df, nan_to_null=True).with_columns(
        [
            pl.col("time").cast(pl.Datetime),
            pl.col("htsc_code").cast(pl.Utf8),
            pl.col("value").cast(pl.Float32),
        ]
    )


def _read_existing_partition(path: Path) -> pl.DataFrame:
    if not path.exists() or path.stat().st_size < 12:
        return pl.DataFrame(schema={"time": pl.Datetime, "htsc_code": pl.Utf8, "value": pl.Float32})
    return pl.read_parquet(str(path)).select(["time", "htsc_code", "value"]).with_columns(
        [
            pl.col("time").cast(pl.Datetime).dt.truncate("1d"),
            pl.col("htsc_code").cast(pl.Utf8),
            pl.col("value").cast(pl.Float32),
        ]
    )


def save_factor_frame_no_overwrite(
    frame: pd.DataFrame,
    *,
    factor_name: str,
    output_root: str | Path,
    save_after: pd.Timestamp | None,
) -> dict[str, int]:
    root = Path(output_root)
    long_df = _frame_to_long(frame, factor_name, save_after)
    if long_df.is_empty():
        return {"rows_written": 0, "partitions_written": 0}

    long_df = long_df.with_columns(
        [
            pl.col("time").dt.year().alias("year"),
            pl.col("time").dt.month().alias("month"),
        ]
    )

    rows_written = int(long_df.height)
    partitions_written = 0
    for part in long_df.partition_by(["year", "month"]):
        year = int(part["year"][0])
        month = int(part["month"][0])
        partition_dir = root / f"factor={factor_name}" / f"year={year}" / f"month={month:02d}"
        partition_dir.mkdir(parents=True, exist_ok=True)
        merged_path = partition_dir / MERGED_FILE_NAME
        existing = _read_existing_partition(merged_path)
        new_rows = part.drop(["year", "month"]).select(["time", "htsc_code", "value"])
        combined = (
            pl.concat([existing, new_rows], how="vertical_relaxed")
            .unique(subset=["time", "htsc_code"], keep="first")
            .sort(["time", "htsc_code"])
        )
        tmp_path = partition_dir / f"{MERGED_FILE_NAME}.{os.getpid()}.{time.time_ns()}.tmp"
        combined.write_parquet(str(tmp_path), compression="zstd")
        tmp_path.replace(merged_path)
        partitions_written += 1

    return {"rows_written": rows_written, "partitions_written": partitions_written}


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def write_run_report(output_root: Path, report: dict[str, Any], report_dir: str | Path | None = None) -> Path:
    out_dir = Path(report_dir) if report_dir else output_root / REPORT_DIR_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"etf_factor_run_{timestamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ETF 股票池日线因子计算")
    parser.add_argument("--pool-file", required=True, help="ETF 股票池 CSV/Excel 文件")
    parser.add_argument("--etf-daily-root", default=str(DEFAULT_ETF_DAILY_ROOT), help="ETF 日线 parquet 根目录")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="ETF 因子输出根目录")
    parser.add_argument("--start", default=DEFAULT_START_DATE, help="首次建库起始日期 YYYY-MM-DD")
    parser.add_argument("--end", default="", help="结束日期 YYYY-MM-DD，默认 ETF 数据最大日期")
    parser.add_argument("--limit-codes", type=int, default=None, help="仅用于测试/试跑：限制有效 ETF 数量")
    parser.add_argument("--report-dir", default="", help="运行报告输出目录，默认 output-root/_reports")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output_root = Path(args.output_root)
    etf_daily_root = Path(args.etf_daily_root)
    default_start = pd.Timestamp(args.start).floor("D")

    existing_etf_codes = list_existing_etf_codes(etf_daily_root)
    pool = load_pool_codes(args.pool_file, existing_etf_codes=existing_etf_codes, limit_codes=args.limit_codes)
    if not pool.codes:
        raise RuntimeError("股票池中没有可用 ETF 代码")

    latest_output = get_output_latest_time(output_root)
    target_start = default_start if latest_output is None else latest_output + pd.Timedelta(days=1)
    latest_daily = get_latest_etf_daily_time(etf_daily_root, pool.codes)
    if latest_daily is None:
        raise RuntimeError("ETF 日线库中没有股票池代码对应数据")
    target_end = pd.Timestamp(args.end).floor("D") if str(args.end or "").strip() else latest_daily

    lookback_days = get_max_bundle_lookback_days()
    lookback_start = max(default_start, target_start - pd.Timedelta(days=lookback_days * 2 + 30))

    report: dict[str, Any] = {
        "pool_file": str(Path(args.pool_file).resolve()),
        "etf_daily_root": str(etf_daily_root),
        "output_root": str(output_root),
        "pool": pool.as_report(),
        "default_start": default_start,
        "latest_output_time": latest_output,
        "target_start": target_start,
        "target_end": target_end,
        "lookback_days": lookback_days,
        "lookback_start": lookback_start,
        "factors_written": 0,
        "rows_written": 0,
        "partitions_written": 0,
        "factor_stats": {},
    }

    if target_start > target_end:
        report["status"] = "up_to_date"
        report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        report_path = write_run_report(output_root, report, args.report_dir or None)
        report["report_path"] = str(report_path)
        print(f"[OK] 已最新，无需更新。报告: {report_path}")
        return report

    daily = load_etf_daily_data(
        etf_daily_root=etf_daily_root,
        codes=pool.codes,
        start=lookback_start,
        end=target_end,
    )
    if daily.empty:
        raise RuntimeError("指定日期范围内没有可计算的 ETF 日线数据")
    wide = build_wide_ohlcv(daily, pool.codes)
    factor_frames = compute_factor_bundles(wide)

    for factor_name, frame in factor_frames.items():
        factor_latest = get_factor_latest_time(output_root, factor_name)
        save_after = factor_latest if factor_latest is not None else default_start - pd.Timedelta(days=1)
        stats = save_factor_frame_no_overwrite(
            frame,
            factor_name=factor_name,
            output_root=output_root,
            save_after=save_after,
        )
        report["factor_stats"][factor_name] = {
            "latest_existing_time": factor_latest,
            **stats,
        }
        if stats["rows_written"] > 0:
            report["factors_written"] += 1
            report["rows_written"] += stats["rows_written"]
            report["partitions_written"] += stats["partitions_written"]

    report["status"] = "ok"
    report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    report_path = write_run_report(output_root, report, args.report_dir or None)
    report["report_path"] = str(report_path)
    print(f"[OK] 写入因子数: {report['factors_written']} | 行数: {report['rows_written']} | 分区: {report['partitions_written']}")
    print(f"[OK] 运行报告: {report_path}")
    return report


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
