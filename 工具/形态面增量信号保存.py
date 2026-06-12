import argparse
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import polars as pl


FACTOR_KEY_COLS = ["time", "htsc_code"]
EVENT_KEY_COLS = ["time", "htsc_code", "signal_name"]
DEFAULT_BASE_DIR = r"D:\database\signal_daily_形态\candlestick_no_vol"
EVENTS_DIR_NAME = "events"


def _align_polars_schema(df: pl.DataFrame, columns_order: list[str]) -> pl.DataFrame:
    aligned = df
    for col in columns_order:
        if col not in aligned.columns:
            aligned = aligned.with_columns(pl.lit(None).alias(col))
    return aligned.select(columns_order)


def _merge_with_priority(
    old_df: pl.DataFrame,
    new_df: pl.DataFrame,
    key_cols: list[str],
    *,
    prefer_new: bool,
) -> pl.DataFrame:
    """prefer_new=False 时旧 merged 优先（历史全量）；True 时新 part 优先（增量更新）。"""
    all_cols = list(dict.fromkeys([*old_df.columns, *new_df.columns]))
    value_cols = [c for c in all_cols if c not in key_cols]

    old_prio, new_prio = (1, 0) if prefer_new else (0, 1)
    old_aligned = (
        _align_polars_schema(old_df, all_cols)
        .sort(key_cols)
        .unique(subset=key_cols, keep="last")
        .with_columns(pl.lit(old_prio).alias("__prio"))
    )
    new_aligned = (
        _align_polars_schema(new_df, all_cols)
        .sort(key_cols)
        .unique(subset=key_cols, keep="last")
        .with_columns(pl.lit(new_prio).alias("__prio"))
    )

    agg_exprs = [pl.col(c).drop_nulls().first().alias(c) for c in value_cols]
    merged = (
        pl.concat([old_aligned, new_aligned], how="vertical_relaxed")
        .sort([*key_cols, "__prio"])
        .group_by(key_cols, maintain_order=True)
        .agg(agg_exprs)
        .select(all_cols)
        .sort(key_cols)
    )
    return merged


def _merge_preserve_old_values(
    old_df: pl.DataFrame,
    new_df: pl.DataFrame,
    key_cols: list[str],
) -> pl.DataFrame:
    return _merge_with_priority(old_df, new_df, key_cols, prefer_new=False)


def _cleanup_tmp_file(tmp_path: str) -> None:
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _write_parquet_atomic_with_retry(
    df: pl.DataFrame,
    file_path: str,
    *,
    compression: str = "snappy",
    max_retries: int = 60,
    sleep_seconds: float = 1.0,
) -> None:
    dir_path = os.path.dirname(file_path)
    os.makedirs(dir_path, exist_ok=True)
    tmp_dir = os.path.join(dir_path, ".__tmp_writes__")
    os.makedirs(tmp_dir, exist_ok=True)

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        tmp_path = os.path.join(
            tmp_dir,
            f"tmp_{os.getpid()}_{int(time.time() * 1000)}_{uuid.uuid4().hex}.bin",
        )
        try:
            df.write_parquet(tmp_path, compression=compression)
            os.replace(tmp_path, file_path)
            return
        except OSError as exc:
            last_error = exc
            _cleanup_tmp_file(tmp_path)
            if attempt == 1 or attempt % 5 == 0:
                print(f"[WARN] 写入被占用，等待重试: {file_path} ({attempt}/{max_retries})")
            time.sleep(sleep_seconds)

    raise OSError(f"写入 parquet 失败: {file_path}") from last_error


def _move_corrupt_parquet(file_path: str, reason: str) -> None:
    corrupt_path = f"{file_path}.corrupt.{int(time.time())}"
    print(f"[WARN] 历史分区不可读，已备份: {file_path} -> {corrupt_path}，原因: {reason}")
    try:
        os.replace(file_path, corrupt_path)
    except OSError as exc:
        print(f"[WARN] 备份损坏文件失败: {exc}")


def _read_existing_partition(file_path: str, key_cols: list[str]) -> pl.DataFrame | None:
    if not os.path.exists(file_path):
        return None

    try:
        if os.path.getsize(file_path) < 12:
            _move_corrupt_parquet(file_path, "文件小于 12 字节")
            return None
        df = pl.read_parquet(file_path)
        casts = [
            pl.col("time").cast(pl.Datetime),
            pl.col("htsc_code").cast(pl.Utf8),
        ]
        if "signal_name" in df.columns:
            casts.append(pl.col("signal_name").cast(pl.Utf8))
        return df.with_columns(casts)
    except Exception as exc:
        _move_corrupt_parquet(file_path, repr(exc))
        return None


def _resolve_factor_month_dirs(
    base_dir: Path,
    factor: str | None,
    year: int | None,
    month: int | None,
) -> list[Path]:
    if factor:
        factor_dirs = [base_dir / f"factor={factor}"]
    else:
        factor_dirs = sorted(base_dir.glob("factor=*"))

    month_dirs: list[Path] = []
    for factor_dir in factor_dirs:
        if not factor_dir.exists():
            continue
        year_dirs = [factor_dir / f"year={int(year)}"] if year else sorted(factor_dir.glob("year=*"))
        for year_dir in year_dirs:
            if not year_dir.exists():
                continue
            cur_month_dirs = (
                [year_dir / f"month={int(month):02d}"]
                if month
                else sorted(year_dir.glob("month=*"))
            )
            for month_dir in cur_month_dirs:
                if month_dir.exists():
                    month_dirs.append(month_dir)
    return month_dirs


def _resolve_events_month_dirs(
    base_dir: Path,
    year: int | None,
    month: int | None,
) -> list[Path]:
    events_base = base_dir / EVENTS_DIR_NAME
    if not events_base.exists():
        return []

    month_dirs: list[Path] = []
    year_dirs = [events_base / f"year={int(year)}"] if year else sorted(events_base.glob("year=*"))
    for year_dir in year_dirs:
        if not year_dir.exists():
            continue
        cur_month_dirs = (
            [year_dir / f"month={int(month):02d}"]
            if month
            else sorted(year_dir.glob("month=*"))
        )
        for month_dir in cur_month_dirs:
            if month_dir.exists():
                month_dirs.append(month_dir)
    return month_dirs


def compact_month_partition(
    month_dir: Path,
    *,
    key_cols: list[str],
    keep_parts: bool = False,
    prefer_new: bool = False,
) -> tuple[int, int]:
    part_paths = sorted(month_dir.glob("part_*.parquet"))
    if not part_paths:
        return 0, 0

    merged_path = month_dir / "merged.parquet"
    new_frames = [pl.read_parquet(str(path)) for path in part_paths if path.stat().st_size >= 12]
    if not new_frames:
        print(f"[SKIP] 无有效 part 文件: {month_dir}")
        return 0, 0

    new_df = (
        pl.concat(new_frames, how="vertical_relaxed", rechunk=True)
        .sort(key_cols)
        .unique(subset=key_cols, keep="last")
        .sort(key_cols)
    )

    old_df = _read_existing_partition(str(merged_path), key_cols)
    if old_df is None:
        save_df = new_df
        print(f"[NEW] {month_dir} 新建 merged (新 {len(new_df)})")
    else:
        save_df = _merge_with_priority(old_df, new_df, key_cols, prefer_new=prefer_new)
        tag = "新优先" if prefer_new else "旧优先"
        print(f"[MERGE/{tag}] {month_dir} (旧 {len(old_df)} + 新 {len(new_df)} => {len(save_df)})")

    _write_parquet_atomic_with_retry(save_df, str(merged_path), compression="snappy")

    if not keep_parts:
        for path in part_paths:
            try:
                path.unlink()
            except OSError as exc:
                print(f"[WARN] 删除 part 文件失败: {path}，原因: {exc}")

    return len(part_paths), len(save_df)


def _default_workers() -> int:
    cpu = os.cpu_count() or 4
    return max(1, min(4, cpu))


def _compact_task(
    month_dir: Path,
    key_cols: list[str],
    keep_parts: bool,
    prefer_new: bool,
) -> tuple[Path, int, int]:
    parts, rows = compact_month_partition(
        month_dir,
        key_cols=key_cols,
        keep_parts=keep_parts,
        prefer_new=prefer_new,
    )
    return month_dir, parts, rows


def _run_compact_jobs(
    month_dirs: list[Path],
    *,
    key_cols: list[str],
    keep_parts: bool,
    workers: int,
    label: str,
    prefer_new: bool = False,
) -> tuple[int, int]:
    if not month_dirs:
        print(f"没有找到需要处理的 {label} 月份目录。")
        return 0, 0

    print(f"待处理 {label} 月份目录数: {len(month_dirs)}，workers={max(1, int(workers))}")
    total_parts = 0
    touched_months = 0
    workers = max(1, int(workers))

    if workers == 1 or len(month_dirs) <= 1:
        for month_dir in month_dirs:
            parts, _ = compact_month_partition(
                month_dir,
                key_cols=key_cols,
                keep_parts=keep_parts,
                prefer_new=prefer_new,
            )
            if parts > 0:
                touched_months += 1
                total_parts += parts
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_compact_task, month_dir, key_cols, keep_parts, prefer_new): month_dir
                for month_dir in month_dirs
            }
            for future in as_completed(futures):
                month_dir = futures[future]
                try:
                    _, parts, _rows = future.result()
                except Exception as exc:
                    print(f"[ERROR] 处理失败: {month_dir}，原因: {exc}")
                    continue
                if parts > 0:
                    touched_months += 1
                    total_parts += parts

    print(f"{label} 处理完成: 命中月份 {touched_months}，合并 part 文件总数 {total_parts}")
    return touched_months, total_parts


def main() -> None:
    parser = argparse.ArgumentParser(description="合并形态面蜡烛信号增量 part 到 merged.parquet")
    parser.add_argument(
        "--base-dir",
        default=DEFAULT_BASE_DIR,
        help=f"形态信号根目录，默认 {DEFAULT_BASE_DIR}",
    )
    parser.add_argument("--factor", default=None, help="仅处理指定因子目录名（factor= 后面的名字）")
    parser.add_argument("--year", type=int, default=None, help="仅处理指定年份，如 2026")
    parser.add_argument("--month", type=int, default=None, help="仅处理指定月份，如 5")
    parser.add_argument(
        "--keep-parts",
        action="store_true",
        help="合并后保留 part 文件（默认会删除）",
    )
    parser.add_argument(
        "--skip-events",
        action="store_true",
        help="跳过 events/ 目录合并",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=_default_workers(),
        help=f"并行处理的月份目录线程数（默认 {_default_workers()}）",
    )
    parser.add_argument(
        "--prefer-new",
        action="store_true",
        help="合并时新 part 覆盖同键旧 merged（增量更新时用）",
    )
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    if not base_dir.exists():
        raise FileNotFoundError(f"base_dir 不存在: {base_dir}")

    factor_month_dirs = _resolve_factor_month_dirs(
        base_dir=base_dir,
        factor=args.factor,
        year=args.year,
        month=args.month,
    )
    _run_compact_jobs(
        factor_month_dirs,
        key_cols=FACTOR_KEY_COLS,
        keep_parts=args.keep_parts,
        workers=args.workers,
        label="factor",
        prefer_new=args.prefer_new,
    )

    if not args.skip_events:
        events_month_dirs = _resolve_events_month_dirs(
            base_dir=base_dir,
            year=args.year,
            month=args.month,
        )
        _run_compact_jobs(
            events_month_dirs,
            key_cols=EVENT_KEY_COLS,
            keep_parts=args.keep_parts,
            workers=args.workers,
            label="events",
            prefer_new=args.prefer_new,
        )


if __name__ == "__main__":
    main()
