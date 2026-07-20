#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import polars as pl


BASE = Path(r"D:\database\sector_information")


def main() -> None:
    current_path = BASE / "current" / "assessments.parquet"
    assessments = pl.read_parquet(current_path).with_columns(
        pl.lit("preliminary_rule_score").alias("research_method"),
        pl.lit(False).alias("is_final_research"),
    )
    assessments.write_parquet(current_path, compression="zstd")

    queue_path = BASE / "codex_research_queue" / "queue.parquet"
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    queue = assessments.select(
        "sector_code", "sector_name", "analysis_date", "run_id",
        pl.lit("pending").alias("task_status"),
        pl.lit(0, dtype=pl.Int32).alias("attempt_count"),
        pl.lit(None, dtype=pl.String).alias("claimed_at"),
        pl.lit(None, dtype=pl.String).alias("completed_at"),
        pl.lit(None, dtype=pl.String).alias("last_error"),
        pl.lit(now).alias("created_at"),
    ).sort("sector_code")
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue.write_parquet(queue_path, compression="zstd")
    print({"queue_path": str(queue_path), "tasks": queue.height, "status": queue.group_by("task_status").len().to_dicts()})


if __name__ == "__main__":
    main()
