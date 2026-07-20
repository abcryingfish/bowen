#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import polars as pl


BASE = Path(r"D:\database\sector_information")


def json_default(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sector-code")
    args = parser.parse_args()
    queue_path = BASE / "codex_research_queue" / "queue.parquet"
    queue = pl.read_parquet(queue_path)
    if args.sector_code:
        target = queue.filter(pl.col("sector_code") == args.sector_code)
    else:
        target = queue.filter(pl.col("task_status") == "in_progress").head(1)
        if target.is_empty():
            target = queue.filter(pl.col("task_status") == "pending").head(1)
    if target.is_empty():
        raise SystemExit("没有待处理任务")
    code = target["sector_code"][0]
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    queue = queue.with_columns(
        pl.when(pl.col("sector_code") == code).then(pl.lit("in_progress")).otherwise(pl.col("task_status")).alias("task_status"),
        pl.when((pl.col("sector_code") == code) & (pl.col("task_status") == "pending")).then(pl.col("attempt_count") + 1).otherwise(pl.col("attempt_count")).alias("attempt_count"),
        pl.when(pl.col("sector_code") == code).then(pl.lit(now)).otherwise(pl.col("claimed_at")).alias("claimed_at"),
    )
    queue.write_parquet(queue_path, compression="zstd")

    assessment = pl.read_parquet(BASE / "current" / "assessments.parquet").filter(pl.col("sector_code") == code).to_dicts()[0]
    dimensions = pl.read_parquet(BASE / "current" / "dimension_scores.parquet").filter(pl.col("sector_code") == code).to_dicts()
    market = pl.read_parquet(BASE / "market_features" / "analysis_date=*" / "part-*.parquet").filter(pl.col("sector_code") == code).to_dicts()[0]
    links = pl.read_parquet(BASE / "current" / "claim_evidence_links.parquet").filter(pl.col("sector_code") == code).select("evidence_id").unique()
    evidence = (
        pl.read_parquet(BASE / "current" / "evidence.parquet")
        .join(links, left_on="content_hash", right_on="evidence_id", how="inner")
        .unique("content_hash", keep="first")
        .sort("published_at", descending=True)
        .head(60)
        .to_dicts()
    )
    bundle = {
        "schema_version": "codex_sector_input.v1",
        "sector_code": code,
        "sector_name": assessment["sector_name"],
        "analysis_date": assessment["analysis_date"],
        "rule_baseline": assessment,
        "dimension_baseline": dimensions,
        "market_features": market,
        "evidence": evidence,
        "instructions": {
            "must_verify_sources": True,
            "do_not_invent_missing_values": True,
            "horizons": [5, 20, 60],
            "output_language": "zh-CN",
        },
    }
    out = BASE / "codex_research_queue" / "input_bundles" / f"{code}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    print(json.dumps({"sector_code": code, "sector_name": assessment["sector_name"], "evidence_count": len(evidence), "bundle": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
