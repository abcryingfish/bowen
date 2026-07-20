#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import polars as pl


BASE = Path(r"D:\database\sector_information")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result")
    args = parser.parse_args()
    result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    required = {"sector_code", "sector_name", "analysis_date", "overall_score", "dimension_scores", "verdict", "core_logic", "forecasts", "evidence_refs"}
    missing = required - result.keys()
    if missing:
        raise ValueError(f"缺少字段: {sorted(missing)}")
    if set(result["dimension_scores"]) != {"policy", "fundamental", "capital", "technical", "valuation", "risk"}:
        raise ValueError("dimension_scores必须包含六维")
    if not 0 <= float(result["overall_score"]) <= 10:
        raise ValueError("overall_score越界")

    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    flat = dict(result)
    flat["dimension_scores_json"] = json.dumps(flat.pop("dimension_scores"), ensure_ascii=False)
    flat["forecasts_json"] = json.dumps(flat.pop("forecasts"), ensure_ascii=False)
    flat["evidence_refs_json"] = json.dumps(flat.pop("evidence_refs"), ensure_ascii=False)
    flat["research_method"] = "codex_individual_research"
    flat["is_final_research"] = True
    flat["completed_at"] = now
    frame = pl.from_dicts([flat])
    out = BASE / "codex_assessments" / f"analysis_date={result['analysis_date']}" / f"{result['sector_code']}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(out, compression="zstd")

    queue_path = BASE / "codex_research_queue" / "queue.parquet"
    queue = pl.read_parquet(queue_path).with_columns(
        pl.when(pl.col("sector_code") == result["sector_code"]).then(pl.lit("completed")).otherwise(pl.col("task_status")).alias("task_status"),
        pl.when(pl.col("sector_code") == result["sector_code"]).then(pl.lit(now)).otherwise(pl.col("completed_at")).alias("completed_at"),
        pl.when(pl.col("sector_code") == result["sector_code"]).then(pl.lit(None, dtype=pl.String)).otherwise(pl.col("last_error")).alias("last_error"),
    )
    queue.write_parquet(queue_path, compression="zstd")
    print({"sector_code": result["sector_code"], "output": str(out), "queue": queue.group_by("task_status").len().sort("task_status").to_dicts()})


if __name__ == "__main__":
    main()
