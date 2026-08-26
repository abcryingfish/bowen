# -*- coding: utf-8 -*-
"""从筹码因子与筹码状态中移除指数、板块、ETF等非个股代码。

只以 stock_basic_data_daily 的历史代码为白名单。逐文件同目录原子替换，运行中断后可重跑；
不会删除 parquet 文件，也不会修改其他因子。
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

import duckdb

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from 筹码结构因子 import FACTOR_NAME_MAP  # noqa: E402

STOCK_BASE = Path(r"D:\database\stock_basic_data_daily")
OUTPUT_BASE = Path(r"D:\database\signal_daily")
STATE_DIR = OUTPUT_BASE / "_state"


def _sql_list(paths: list[str]) -> str:
    return "[" + ", ".join("'" + path.replace("'", "''") + "'" for path in paths) + "]"


def _stock_paths() -> list[str]:
    return [
        str(path).replace("\\", "/")
        for path in sorted(STOCK_BASE.glob("year=*/month=*/merged.parquet"))
    ]


def _target_files() -> list[Path]:
    paths: list[Path] = []
    for factor_id in FACTOR_NAME_MAP.values():
        paths.extend(sorted((OUTPUT_BASE / f"factor={factor_id}").glob("year=*/month=*/*.parquet")))
    paths.extend(sorted(STATE_DIR.glob("chip_structure_latest_state.parquet")))
    paths.extend(sorted(STATE_DIR.glob("chip_batch_state_*.parquet")))
    return paths


def _prepare_stock_codes(con: duckdb.DuckDBPyConnection) -> int:
    paths = _stock_paths()
    if not paths:
        raise FileNotFoundError(f"没有个股行情分区: {STOCK_BASE}")
    con.execute(
        f"""
CREATE TEMP TABLE stock_codes AS
SELECT DISTINCT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code
FROM read_parquet({_sql_list(paths)}, hive_partitioning=true, union_by_name=true)
WHERE htsc_code IS NOT NULL
"""
    )
    return int(con.execute("SELECT COUNT(*) FROM stock_codes").fetchone()[0])


def _non_stock_count(con: duckdb.DuckDBPyConnection, path: Path) -> tuple[int, int]:
    path_text = str(path).replace("\\", "/").replace("'", "''")
    total, removed = con.execute(
        f"""
SELECT COUNT(*), COUNT(*) FILTER (WHERE s.htsc_code IS NULL)
FROM read_parquet('{path_text}', union_by_name=true) p
LEFT JOIN stock_codes s
  ON UPPER(TRIM(CAST(p.htsc_code AS VARCHAR))) = s.htsc_code
"""
    ).fetchone()
    return int(total), int(removed)


def _rewrite_stock_only(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    total, removed = _non_stock_count(con, path)
    if removed == 0:
        return 0
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp.parquet")
    path_text = str(path).replace("\\", "/").replace("'", "''")
    temp_text = str(temp).replace("\\", "/").replace("'", "''")
    try:
        con.execute(
            f"""
COPY (
    SELECT p.*
    FROM read_parquet('{path_text}', union_by_name=true) p
    INNER JOIN stock_codes s
      ON UPPER(TRIM(CAST(p.htsc_code AS VARCHAR))) = s.htsc_code
) TO '{temp_text}' (FORMAT PARQUET, COMPRESSION SNAPPY)
"""
        )
        kept = int(con.execute(f"SELECT COUNT(*) FROM read_parquet('{temp_text}')").fetchone()[0])
        if kept != total - removed:
            raise RuntimeError(f"清理行数校验失败: {path}，预期={total - removed}，实际={kept}")
        os.replace(temp, path)
        return removed
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="清理筹码因子和状态中的非个股数据")
    parser.add_argument("--apply", action="store_true", help="实际原子重写；默认只统计")
    parser.add_argument("--verbose", action="store_true", help="逐文件打印清理明细")
    args = parser.parse_args()

    con = duckdb.connect(database=":memory:")
    try:
        stock_count = _prepare_stock_codes(con)
        files = _target_files()
        print(f"个股白名单={stock_count}，目标文件={len(files)}，模式={'执行' if args.apply else '检查'}")
        affected_files = 0
        removed_rows = 0
        for index, path in enumerate(files, start=1):
            if args.apply:
                removed = _rewrite_stock_only(con, path)
            else:
                _, removed = _non_stock_count(con, path)
            if removed:
                affected_files += 1
                removed_rows += removed
                if args.verbose or index % 100 == 0 or index == len(files):
                    print(f"[{index}/{len(files)}] {'已清理' if args.apply else '待清理'}: {path}，非个股行={removed}")
            elif index % 500 == 0 or index == len(files):
                print(f"[{index}/{len(files)}] 已检查")
        print(f"完成: 影响文件={affected_files}，非个股行={removed_rows}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
