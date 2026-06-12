#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""季度财报下载（利润表 / 资产负债表 / 现金流量表 / 财务指标）。

每次运行：扫描本地 parquet；登录并用 get_all_stocks_info 拉取 XSHG + XSHE 全市场；
逐只增量请求华泰财报接口，写入 ``D:\\database\\stock_financial_statements`` 下对应子目录。

分区格式：``year=YYYY/month=MM/*.parquet`` + ``merged.parquet``（按 ``end_date`` 分区）。
去重键：``htsc_code + end_date + period``，冲突保留 ``pub_date`` 最新。
"""
from __future__ import annotations

import argparse
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import duckdb
import pandas as pd
import polars as pl
from insight_python.com.insight import common
from insight_python.com.insight.market_service import market_service
from insight_python.com.insight.query import (
    get_all_stocks_info,
    get_balance_sheet,
    get_cashflow_statement,
    get_fin_indicator,
    get_income_statement,
)

BASE_ROOT = r"D:\database\stock_financial_statements"
DEFAULT_START_DATE = "2010-01-01"
DEFAULT_OVERLAP_DAYS = 456
MIN_PARQUET_BYTES = 12
MERGED_FILE_NAME = "merged.parquet"
SLEEP_SEC = 0.0005
DEDUP_COLUMNS = ("htsc_code", "end_date", "period")
PERIOD_VALUES = ("Q1", "Q2", "Q3", "Q4")

STATEMENT_SPECS: dict[str, dict[str, object]] = {
    "income": {
        "label": "利润表",
        "subdir": "income_statements",
        "fetch_fn": get_income_statement,
    },
    "balance": {
        "label": "资产负债表",
        "subdir": "balance_sheet",
        "fetch_fn": get_balance_sheet,
    },
    "cashflow": {
        "label": "现金流量表",
        "subdir": "cash_flow_statement",
        "fetch_fn": get_cashflow_statement,
    },
    "indicator": {
        "label": "财务指标",
        "subdir": "financial_indicators",
        "fetch_fn": get_fin_indicator,
    },
}


class insightmarketservice(market_service):
    def on_query_response(self, result):
        for response in iter(result):
            print(response)


def login() -> None:
    markets = insightmarketservice()
    user = "MDIL1_01042"
    password = "weS._+7atE4Vdr"
    result = common.login(markets, user, password, login_log=False)
    print(result)


def config(open_trace: bool = True, open_file_log: bool = True, open_cout_log: bool = True) -> None:
    common.config(open_trace, open_file_log, open_cout_log)


def get_version() -> None:
    print(common.get_version())


def fini() -> None:
    common.fini()


def normalize_code(code: str) -> str:
    return str(code).strip().upper()


def normalize_period(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip().upper()


def _is_valid_dataframe(result: object) -> bool:
    if result is None or isinstance(result, str):
        return False
    if not hasattr(result, "columns"):
        return False
    return not result.empty


def deduplicate_financial_df(df: pl.DataFrame) -> pl.DataFrame:
    """按 htsc_code + end_date + period 去重，pub_date 较新者优先。"""
    if df.is_empty():
        return df

    subset = [c for c in DEDUP_COLUMNS if c in df.columns]
    if len(subset) < 2:
        return df

    if "pub_date" in df.columns:
        df = df.sort("pub_date")
    return df.unique(subset=subset, keep="last")


def save_partitioned_parquet(df: pl.DataFrame, base_dir: str) -> list[tuple[int, int]]:
    """按 end_date 的 year/month 分区追加写入 parquet。"""
    if df.is_empty():
        return []

    if "end_date" not in df.columns or "htsc_code" not in df.columns:
        raise ValueError("写入数据缺少 end_date 或 htsc_code 列")

    df = (
        df.with_columns(
            pl.col("end_date").cast(pl.Datetime, strict=False).dt.truncate("1d").alias("end_date"),
            pl.col("htsc_code").cast(pl.Utf8).str.to_uppercase().str.strip_chars().alias("htsc_code"),
        )
        .drop_nulls(["end_date", "htsc_code"])
    )
    if "period" in df.columns:
        df = df.with_columns(pl.col("period").map_elements(normalize_period, return_dtype=pl.Utf8).alias("period"))

    df = deduplicate_financial_df(df).sort(["end_date", "htsc_code"])
    df = df.with_columns([
        pl.col("end_date").dt.year().alias("year"),
        pl.col("end_date").dt.month().alias("month"),
    ])

    touched_partitions: list[tuple[int, int]] = []
    for partition_df in df.partition_by(["year", "month"]):
        year = int(partition_df["year"][0])
        month = int(partition_df["month"][0])
        dir_path = os.path.join(base_dir, f"year={year}", f"month={month:02d}")
        os.makedirs(dir_path, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{timestamp}_year_{year}_month_{month:02d}.parquet"
        file_path = os.path.join(dir_path, file_name)

        save_df = partition_df.drop(["year", "month"])
        save_df.write_parquet(file_path)
        touched_partitions.append((year, month))
        print(f"已保存: {file_path} (共 {len(save_df)} 条记录)")

    return touched_partitions


def _transform_financial_merged(df: pl.DataFrame) -> pl.DataFrame:
    return deduplicate_financial_df(df).sort(["end_date", "htsc_code"])


def _is_readable_parquet(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= MIN_PARQUET_BYTES and not pl.read_parquet(str(path), n_rows=1).is_empty()
    except Exception:
        return False


def rebuild_merged_parquets(
    base_dir: str,
    touched_partitions: set[tuple[int, int]],
    transform_merged: Callable[[pl.DataFrame], pl.DataFrame] | None = None,
) -> list[Path]:
    rebuilt_files: list[Path] = []
    for year, month in sorted(touched_partitions):
        partition_dir = Path(base_dir) / f"year={year}" / f"month={month:02d}"
        if not partition_dir.exists():
            continue

        merged_path = partition_dir / MERGED_FILE_NAME
        raw_files = sorted(
            path for path in partition_dir.glob("*.parquet")
            if path.is_file() and path.name != MERGED_FILE_NAME
        )
        input_files = ([merged_path] if merged_path.exists() else []) + raw_files
        input_files = [path for path in input_files if _is_readable_parquet(path)]
        if not input_files:
            print(f"[WARN] 分区 {year}-{month:02d} 无有效 parquet，跳过 merged 重建。")
            continue

        try:
            merged_df = pl.concat(
                [pl.scan_parquet(str(path)) for path in input_files],
                how="diagonal_relaxed",
            ).collect(engine="streaming")
            if transform_merged is not None:
                merged_df = transform_merged(merged_df)
            temp_path = partition_dir / f"{MERGED_FILE_NAME}.{os.getpid()}.{time.time_ns()}.tmp"
            merged_df.write_parquet(str(temp_path), compression="zstd")
            temp_path.replace(merged_path)
            rebuilt_files.append(merged_path)
            print(f"[OK] 已重建 merged: {merged_path}")
        except Exception as exc:
            print(f"[WARN] 分区 {year}-{month:02d} merged 重建失败: {exc}")
            continue

        deleted_count = 0
        for raw_file in raw_files:
            try:
                raw_file.unlink()
                deleted_count += 1
            except OSError as exc:
                print(f"[WARN] 删除原始文件失败，保留到下次合并: {raw_file.name} | {exc}")
        if deleted_count:
            print(f"[OK] 已删除原始 parquet 文件数: {deleted_count} | 分区: {year}-{month:02d}")
    return rebuilt_files


def fetch_market_universe_htsc_codes(
    listing_start: datetime,
    listing_end: datetime,
    listing_state: str = "上市交易",
) -> list[str]:
    codes: set[str] = set()
    for exchange in ("XSHG", "XSHE"):
        result = get_all_stocks_info(
            listing_date=[listing_start, listing_end],
            exchange=exchange,
            listing_state=listing_state,
        )
        if result is None:
            print(f"{exchange} get_all_stocks_info 返回 None，跳过")
            continue
        if not hasattr(result, "columns") or "htsc_code" not in result.columns:
            print(f"{exchange} 结果无 htsc_code 列: {getattr(result, 'columns', None)}")
            continue
        for raw in result["htsc_code"].tolist():
            codes.add(normalize_code(str(raw)))
        print(f"{exchange} 已合并，当前不重复代码数: {len(codes)}")
    return sorted(codes)


def _collect_scan_parquet_paths(base_dir: str) -> list[str]:
    base_path = Path(base_dir)
    merged_files = sorted(base_path.glob("**/merged.parquet"))
    if merged_files:
        return [str(p).replace("\\", "/") for p in merged_files]

    valid_files: list[str] = []
    skipped_small = 0
    for path in sorted(base_path.glob("**/*.parquet")):
        if path.name == MERGED_FILE_NAME:
            continue
        try:
            if path.stat().st_size < MIN_PARQUET_BYTES:
                skipped_small += 1
                continue
        except OSError:
            skipped_small += 1
            continue
        valid_files.append(str(path).replace("\\", "/"))

    if skipped_small:
        print(f"扫描时跳过 {skipped_small} 个无效/损坏 parquet 小文件。")
    return valid_files


def scan_latest_end_dates(base_dir: str) -> dict[str, datetime]:
    """扫描本地 parquet，返回每只股票已下载到的最新 end_date。"""
    latest_map: dict[str, datetime] = {}
    if not os.path.exists(base_dir):
        return latest_map

    parquet_paths = _collect_scan_parquet_paths(base_dir)
    if not parquet_paths:
        print("未发现本地 parquet，将按默认起始日处理新股票。")
        return latest_map

    try:
        print(f"正在扫描已下载的数据（{len(parquet_paths)} 个 parquet），请稍候...")
        if len(parquet_paths) == 1:
            from_clause = f"read_parquet('{parquet_paths[0]}', union_by_name=true)"
        else:
            quoted = ", ".join(f"'{path}'" for path in parquet_paths)
            from_clause = f"read_parquet([{quoted}], union_by_name=true)"
        query = f"""
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            MAX(CAST(end_date AS TIMESTAMP)) AS latest_end_date
        FROM {from_clause}
        WHERE htsc_code IS NOT NULL
          AND end_date IS NOT NULL
        GROUP BY 1
        """
        latest_df = duckdb.query(query).df()
        if latest_df.empty:
            print("扫描完成，但未发现有效历史记录。")
            return latest_map

        latest_df["latest_end_date"] = pd.to_datetime(latest_df["latest_end_date"]).dt.floor("D")
        for _, row in latest_df.iterrows():
            latest_map[normalize_code(row["htsc_code"])] = row["latest_end_date"].to_pydatetime()

        print(f"发现已下载 {len(latest_map)} 个股票的历史财报数据。")
    except Exception as exc:
        print(f"扫描本地历史数据失败，将按默认起始日处理: {exc}")

    return latest_map


def build_download_plan(
    all_codes: list[str],
    latest_end_date_map: dict[str, datetime],
    default_start_date: datetime,
    end_date: datetime,
    overlap_days: int,
) -> tuple[dict[datetime, list[str]], dict[str, int]]:
    grouped_codes: dict[datetime, list[str]] = defaultdict(list)
    stats = {"up_to_date": 0, "incremental": 0, "full_new": 0}

    for raw_code in all_codes:
        code = normalize_code(raw_code)
        latest_end = latest_end_date_map.get(code)
        if latest_end is None:
            start_date = default_start_date
            stats["full_new"] += 1
        else:
            start_date = latest_end - timedelta(days=overlap_days)
            stats["incremental"] += 1

        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        if start_date > end_date:
            stats["up_to_date"] += 1
            if latest_end is not None:
                stats["incremental"] -= 1
            else:
                stats["full_new"] -= 1
            continue
        grouped_codes[start_date].append(code)

    return dict(sorted(grouped_codes.items(), key=lambda item: item[0])), stats


def flatten_download_plan(download_plan: dict[datetime, list[str]]) -> list[tuple[datetime, str]]:
    tasks: list[tuple[datetime, str]] = []
    for start_date, codes in download_plan.items():
        for code in codes:
            tasks.append((start_date, code))
    return tasks


def should_relogin(error_msg: str) -> bool:
    msg = error_msg.lower()
    return "login" in msg or "connect" in msg or "session" in msg


def normalize_financial_response(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return raw

    if "end_date" not in raw.columns or "htsc_code" not in raw.columns:
        missing = [c for c in ("end_date", "htsc_code") if c not in raw.columns]
        raise ValueError(f"接口结果缺少列: {missing}")

    out = raw.copy()
    out["htsc_code"] = out["htsc_code"].map(normalize_code)
    out["end_date"] = pd.to_datetime(out["end_date"], errors="coerce").dt.floor("D")
    if "period" in out.columns:
        out["period"] = out["period"].map(normalize_period)
    if "pub_date" in out.columns:
        out["pub_date"] = pd.to_datetime(out["pub_date"], errors="coerce")

    out = out.dropna(subset=["htsc_code", "end_date"])
    if "pub_date" in out.columns:
        out = out.sort_values("pub_date")
    dedup_cols = [c for c in DEDUP_COLUMNS if c in out.columns]
    if len(dedup_cols) >= 2:
        out = out.drop_duplicates(subset=dedup_cols, keep="last")

    return out.sort_values(["end_date", "htsc_code"]).reset_index(drop=True)


def _call_fetch_api(
    fetch_fn: Callable[..., pd.DataFrame],
    code: str,
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame | None:
    """优先不传 period 一次拿全；失败则 Q1-Q4 合并。"""
    try:
        result = fetch_fn(htsc_code=code, end_date=[start_date, end_date])
        if _is_valid_dataframe(result):
            return result
    except TypeError:
        pass

    frames: list[pd.DataFrame] = []
    for period in PERIOD_VALUES:
        try:
            result = fetch_fn(htsc_code=code, end_date=[start_date, end_date], period=period)
            if _is_valid_dataframe(result):
                frames.append(result)
        except TypeError:
            break
        except Exception:
            continue

    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def fetch_single_stock_with_retry(
    fetch_fn: Callable[..., pd.DataFrame],
    code: str,
    start_date: datetime,
    end_date: datetime,
    max_retries: int = 3,
) -> pd.DataFrame | None:
    retry_count = 0
    while retry_count < max_retries:
        try:
            result = _call_fetch_api(fetch_fn, code, start_date, end_date)
            if result is None:
                return None
            return normalize_financial_response(result)
        except Exception as exc:
            retry_count += 1
            error_msg = str(exc)
            print(f"  第 {retry_count} 次尝试失败: {error_msg}")
            if retry_count >= max_retries:
                raise

            wait_time = 2 * retry_count
            print(f"  等待 {wait_time} 秒后重试...")
            time.sleep(wait_time)

            if should_relogin(error_msg):
                print("  检测到连接问题，尝试重新登录...")
                login()
                config(False, False, False)
                print("  重新登录成功")

    return None


def resolve_statement_keys(statement_arg: str) -> list[str]:
    key = statement_arg.strip().lower()
    if key == "all":
        return list(STATEMENT_SPECS.keys())
    if key not in STATEMENT_SPECS:
        valid = ", ".join(["all", *STATEMENT_SPECS.keys()])
        raise ValueError(f"未知 --statement: {statement_arg}，可选: {valid}")
    return [key]


def run_statement_download(
    statement_key: str,
    all_codes: list[str],
    default_start_date: datetime,
    end_date: datetime,
    overlap_days: int,
    sleep_sec: float,
) -> None:
    spec = STATEMENT_SPECS[statement_key]
    label = str(spec["label"])
    subdir = str(spec["subdir"])
    fetch_fn = spec["fetch_fn"]
    assert callable(fetch_fn)

    base_dir = os.path.join(BASE_ROOT, subdir)
    os.makedirs(base_dir, exist_ok=True)

    print("\n" + "=" * 60)
    print(f"开始处理: {label} ({statement_key}) -> {base_dir}")
    print("=" * 60)

    latest_end_date_map = scan_latest_end_dates(base_dir)
    download_plan, plan_stats = build_download_plan(
        all_codes, latest_end_date_map, default_start_date, end_date, overlap_days
    )
    tasks = flatten_download_plan(download_plan)
    pending_total = len(tasks)

    print(
        "增量计划: "
        f"已最新 {plan_stats['up_to_date']} 只 | "
        f"增量补拉 {plan_stats['incremental']} 只 | "
        f"首次全量 {plan_stats['full_new']} 只"
    )
    if download_plan:
        plan_preview = ", ".join(
            f"{start.date()}({len(codes)}只)" for start, codes in list(download_plan.items())[:5]
        )
        print(f"下载起点分组(前5): {plan_preview}")

    if pending_total == 0:
        print(f"{label} 无需下载。")
        return

    failed_stocks: list[dict[str, object]] = []
    processed_count = 0
    touched_partitions: set[tuple[int, int]] = set()

    print(f"需更新股票数量: {pending_total}")
    print("-" * 60)

    for stock_num, (start_date, code) in enumerate(tasks, start=1):
        print(f"\n[{label} {stock_num}/{pending_total}] {code}")
        print(f"  下载区间: {start_date.date()} ~ {end_date.date()}")

        try:
            result = fetch_single_stock_with_retry(fetch_fn, code, start_date, end_date)
            if result is None or result.empty:
                print(f"  {code} 返回空数据，已记录")
                failed_stocks.append(
                    {
                        "statement": statement_key,
                        "code": code,
                        "start_date": start_date.strftime("%Y-%m-%d"),
                        "error": "返回空数据",
                        "stock_num": stock_num,
                    }
                )
                time.sleep(sleep_sec)
                continue

            result_pl = pl.from_pandas(result)
            touched = save_partitioned_parquet(result_pl, base_dir)
            touched_partitions.update(touched)

            processed_count += 1
            print(f"  成功处理 {code}，累计 {processed_count}/{pending_total}")
            time.sleep(sleep_sec)
        except Exception as exc:
            error_msg = str(exc)
            print(f"  {code} 最终失败: {error_msg}")
            failed_stocks.append(
                {
                    "statement": statement_key,
                    "code": code,
                    "start_date": start_date.strftime("%Y-%m-%d"),
                    "error": error_msg,
                    "stock_num": stock_num,
                }
            )
            time.sleep(sleep_sec)

    print("\n" + "-" * 60)
    print(f"{label} 执行统计")
    print(f"成功处理: {processed_count}/{pending_total}")
    print(f"更新分区数: {len(touched_partitions)}")
    print(f"失败股票: {len(failed_stocks)}")

    if touched_partitions:
        rebuilt_files = rebuild_merged_parquets(
            base_dir,
            touched_partitions,
            transform_merged=_transform_financial_merged,
            success_prefix="",
        )
        print(f"重建 merged.parquet 数量: {len(rebuilt_files)}")
    else:
        print("本次无新增数据写入，跳过 merged.parquet 重建。")

    if failed_stocks:
        print("\n以下股票失败，可后续补跑:")
        for fail in failed_stocks:
            print(
                f"  - [{fail['statement']}] 序号 {fail['stock_num']}: {fail['code']} | "
                f"起始: {fail['start_date']} | 原因: {fail['error']}"
            )

        fail_file = f"failed_financial_{statement_key}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(fail_file, "w", encoding="utf-8") as f:
            for fail in failed_stocks:
                f.write(
                    f"statement={fail['statement']},stock_num={fail['stock_num']},code={fail['code']},"
                    f"start_date={fail['start_date']},error={fail['error']}\n"
                )
        print(f"失败记录已保存到: {fail_file}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="季度财报下载：get_all_stocks_info 全市场 + 四类财报接口"
    )
    parser.add_argument(
        "--statement",
        default="all",
        choices=["all", *STATEMENT_SPECS.keys()],
        help="下载哪类报表，默认 all",
    )
    parser.add_argument(
        "--listing-start",
        default="1990-01-01",
        help="get_all_stocks_info listing_date 左端（默认 1990-01-01）",
    )
    parser.add_argument(
        "--listing-end",
        default="",
        help="listing_date 右端，默认今天；格式 YYYY-MM-DD",
    )
    parser.add_argument(
        "--listing-state",
        default="上市交易",
        help="get_all_stocks_info listing_state",
    )
    parser.add_argument(
        "--default-start",
        default=DEFAULT_START_DATE,
        help="本地尚无该票时，end_date 从该日起拉（默认 2010-01-01）",
    )
    parser.add_argument(
        "--overlap-days",
        type=int,
        default=DEFAULT_OVERLAP_DAYS,
        help="已有历史时，从 max(end_date) 回溯天数（默认 456）",
    )
    parser.add_argument(
        "--end",
        default="",
        help="end_date 右端，默认今天；格式 YYYY-MM-DD",
    )
    parser.add_argument(
        "--sleep-sec",
        type=float,
        default=SLEEP_SEC,
        help="逐只请求间隔秒数（默认 0.0005）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    statement_keys = resolve_statement_keys(args.statement)
    default_start_date = datetime.strptime(args.default_start, "%Y-%m-%d")
    end_s = (args.end or "").strip()
    end_date = datetime.now() if not end_s else datetime.strptime(end_s, "%Y-%m-%d")
    end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    print("=" * 60)
    print("初始化连接并获取全市场股票池（XSHG + XSHE）...")
    print("=" * 60)
    get_version()
    login()
    config(False, False, False)

    listing_start = datetime.strptime(args.listing_start.strip(), "%Y-%m-%d")
    le_s = (args.listing_end or "").strip()
    listing_end = datetime.now() if not le_s else datetime.strptime(le_s, "%Y-%m-%d")
    all_codes = fetch_market_universe_htsc_codes(listing_start, listing_end, args.listing_state)
    print(f"股票池（API）: {len(all_codes)} 只")
    print(f"待处理报表: {', '.join(statement_keys)}")
    print("=" * 60)

    failed_statements: list[str] = []
    try:
        for statement_key in statement_keys:
            try:
                run_statement_download(
                    statement_key=statement_key,
                    all_codes=all_codes,
                    default_start_date=default_start_date,
                    end_date=end_date,
                    overlap_days=args.overlap_days,
                    sleep_sec=args.sleep_sec,
                )
            except Exception as exc:
                label = str(STATEMENT_SPECS[statement_key]["label"])
                print(f"\n⚠️ {label} ({statement_key}) 处理异常，已跳过继续下一张表: {exc}")
                failed_statements.append(statement_key)
    finally:
        print("\n" + "=" * 60)
        print("处理完成，释放连接...")
        fini()
        print("=" * 60)

    if failed_statements:
        print(f"\n⚠️ 以下报表未完整完成: {', '.join(failed_statements)}")


if __name__ == "__main__":
    main()
