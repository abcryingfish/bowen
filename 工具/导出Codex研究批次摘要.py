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
    parser.add_argument("--size", type=int, default=8)
    args = parser.parse_args()
    queue_path = BASE / "codex_research_queue" / "queue.parquet"
    queue = pl.read_parquet(queue_path)
    targets = queue.filter(pl.col("task_status") == "pending").head(args.size)
    if targets.is_empty():
        raise SystemExit("没有待处理任务")
    codes = targets["sector_code"].to_list()
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    queue = queue.with_columns(
        pl.when(pl.col("sector_code").is_in(codes)).then(pl.lit("in_progress")).otherwise(pl.col("task_status")).alias("task_status"),
        pl.when(pl.col("sector_code").is_in(codes)).then(pl.col("attempt_count") + 1).otherwise(pl.col("attempt_count")).alias("attempt_count"),
        pl.when(pl.col("sector_code").is_in(codes)).then(pl.lit(now)).otherwise(pl.col("claimed_at")).alias("claimed_at"),
    )
    queue.write_parquet(queue_path, compression="zstd")

    assessments = pl.read_parquet(BASE / "current" / "assessments.parquet")
    dimensions = pl.read_parquet(BASE / "current" / "dimension_scores.parquet")
    market = pl.read_parquet(BASE / "market_features" / "analysis_date=*" / "part-*.parquet")
    evidence = pl.read_parquet(BASE / "current" / "evidence.parquet")
    links = pl.read_parquet(BASE / "current" / "claim_evidence_links.parquet")
    rows = []
    metric_names = [
        "return_5d_pct", "return_20d_pct", "return_60d_pct", "return_250d_pct",
        "close_vs_ma20_pct", "close_vs_ma60_pct", "volatility_20d_annualized_pct",
        "max_drawdown_60d_pct", "median_revenue_yoy_pct", "median_profit_yoy_pct",
        "median_roe_pct", "median_net_margin_pct", "profitable_member_pct",
        "median_positive_pe_ttm", "median_pb", "state_regime",
    ]
    for code in codes:
        base_row = assessments.filter(pl.col("sector_code") == code).to_dicts()[0]
        dim = dimensions.filter(pl.col("sector_code") == code).select("dimension_name", "score").to_dicts()
        features = market.filter(pl.col("sector_code") == code).select(metric_names).to_dicts()[0]
        ids = links.filter(pl.col("sector_code") == code).select("evidence_id").unique()
        ev = (
            evidence.join(ids, left_on="content_hash", right_on="evidence_id", how="inner")
            .unique("content_hash")
            .sort("published_at", descending=True)
        )
        selected = []
        for kind, count in (("policy", 4), ("news", 4), ("research_report", 4), ("announcement", 8)):
            selected.extend(ev.filter(pl.col("evidence_type") == kind).head(count).select("evidence_type", "published_at", "source", "title", "url", "content_hash").to_dicts())
        rows.append({
            "sector_code": code, "sector_name": base_row["sector_name"], "analysis_date": str(base_row["analysis_date"]),
            "rule_overall": base_row["overall_score"], "rule_dimensions": {x["dimension_name"]: x["score"] for x in dim},
            "market_features": features, "evidence": selected,
        })
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = BASE / "codex_research_queue" / "batches" / f"batch_{batch_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"batch": str(out), "codes": codes}, ensure_ascii=False))


if __name__ == "__main__":
    main()
