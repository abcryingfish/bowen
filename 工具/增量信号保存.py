import argparse
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import polars as pl


KEY_COLS = ["time", "htsc_code"]


def _align_polars_schema(df: pl.DataFrame, columns_order: list[str]) -> pl.DataFrame:
    aligned = df
    for col in columns_order:
        if col not in aligned.columns:
            aligned = aligned.with_columns(pl.lit(None).alias(col))
    return aligned.select(columns_order)


def _merge_preserve_old_values(old_df: pl.DataFrame, new_df: pl.DataFrame) -> pl.DataFrame:
    all_cols = list(dict.fromkeys([*old_df.columns, *new_df.columns]))
    value_cols = [c for c in all_cols if c not in KEY_COLS]

    old_aligned = (
        _align_polars_schema(old_df, all_cols)
        .sort(KEY_COLS)
        .unique(subset=KEY_COLS, keep="last")
        .with_columns(pl.lit(0).alias("__prio"))
    )
    new_aligned = (
        _align_polars_schema(new_df, all_cols)
        .sort(KEY_COLS)
        .unique(subset=KEY_COLS, keep="last")
        .with_columns(pl.lit(1).alias("__prio"))
    )

    agg_exprs = [pl.col(c).drop_nulls().first().alias(c) for c in value_cols]
    merged = (
        pl.concat([old_aligned, new_aligned], how="vertical_relaxed")
        .sort([*KEY_COLS, "__prio"])
        .group_by(KEY_COLS, maintain_order=True)
        .agg(agg_exprs)
        .select(all_cols)
        .sort(KEY_COLS)
    )
    return merged


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


def _read_existing_partition(file_path: str) -> pl.DataFrame | None:
    if not os.path.exists(file_path):
        return None

    try:
        if os.path.getsize(file_path) < 12:
            _move_corrupt_parquet(file_path, "文件小于 12 字节")
            return None
        return pl.read_parquet(file_path).with_columns(
            [
                pl.col("time").cast(pl.Datetime),
                pl.col("htsc_code").cast(pl.Utf8),
            ]
        )
    except Exception as exc:
        _move_corrupt_parquet(file_path, repr(exc))
        return None


def _resolve_target_month_dirs(
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


def compact_month_partition(month_dir: Path, keep_parts: bool = False) -> tuple[int, int]:
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
        .sort(KEY_COLS)
        .unique(subset=KEY_COLS, keep="last")
        .sort(KEY_COLS)
    )

    old_df = _read_existing_partition(str(merged_path))
    if old_df is None:
        save_df = new_df
        print(f"[NEW] {month_dir} 新建 merged (新 {len(new_df)})")
    else:
        save_df = _merge_preserve_old_values(old_df, new_df)
        print(f"[MERGE] {month_dir} (旧 {len(old_df)} + 新 {len(new_df)} => {len(save_df)})")

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


def _compact_month_partition_task(
    month_dir: Path,
    keep_parts: bool,
) -> tuple[Path, int, int]:
    parts, rows = compact_month_partition(month_dir, keep_parts=keep_parts)
    return month_dir, parts, rows


def main() -> None:
    parser = argparse.ArgumentParser(description="按月合并因子增量 part 文件到 merged.parquet")
    parser.add_argument(
        "--base-dir",
        default=r"D:\database\signal_daily",
        help="因子库根目录，如 D:\\database\\signal_daily",
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
        "--workers",
        type=int,
        default=_default_workers(),
        help=f"并行处理的月份目录线程数（默认 {_default_workers()}）",
    )
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    if not base_dir.exists():
        raise FileNotFoundError(f"base_dir 不存在: {base_dir}")

    target_month_dirs = _resolve_target_month_dirs(
        base_dir=base_dir,
        factor=args.factor,
        year=args.year,
        month=args.month,
    )
    if not target_month_dirs:
        print("没有找到需要处理的月份目录。")
        return

    print(f"待处理月份目录数: {len(target_month_dirs)}，workers={max(1, int(args.workers))}")
    total_parts = 0
    touched_months = 0
    workers = max(1, int(args.workers))

    if workers == 1 or len(target_month_dirs) <= 1:
        for month_dir in target_month_dirs:
            parts, _ = compact_month_partition(month_dir, keep_parts=args.keep_parts)
            if parts > 0:
                touched_months += 1
                total_parts += parts
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _compact_month_partition_task,
                    month_dir,
                    args.keep_parts,
                ): month_dir
                for month_dir in target_month_dirs
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

    print(f"处理完成: 命中月份 {touched_months}，合并 part 文件总数 {total_parts}")


if __name__ == "__main__":
    main()
