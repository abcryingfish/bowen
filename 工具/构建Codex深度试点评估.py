#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import polars as pl


BASE = Path(r"D:\database\sector_information")
ANALYSIS_DATE = "2026-07-18"


def main() -> None:
    evidence_path = sorted((BASE / "evidence" / f"analysis_date={ANALYSIS_DATE}").glob("pilot_bundle_*.parquet"))[-1]
    aggregate_path = sorted((BASE / "sector_member_aggregates" / f"analysis_date={ANALYSIS_DATE}").glob("pilot_aggregate_*.parquet"))[-1]
    evidence = pl.read_parquet(evidence_path)
    aggregates = {row["sector_code"]: row for row in pl.read_parquet(aggregate_path).to_dicts()}
    source_assessments = BASE / "codex_assessments" / "analysis_date=2026-07-15"
    output_dir = BASE / "codex_assessments" / f"analysis_date={ANALYSIS_DATE}"
    output_dir.mkdir(parents=True, exist_ok=True)
    for code in sorted(evidence.get_column("sector_code").unique().to_list()):
        old = pl.read_parquet(source_assessments / f"{code}.parquet").to_dicts()[0]
        dimensions = json.loads(old["dimension_scores_json"])
        forecasts = json.loads(old["forecasts_json"])
        refs = evidence.filter(pl.col("sector_code") == code).sort("published_at", descending=True).to_dicts()
        category_counts = {}
        for row in refs:
            category_counts[row["source_type"]] = category_counts.get(row["source_type"], 0) + 1
        aggregate = aggregates[code]
        output = {
            "schema_version": "codex_deep_research_v2.pilot",
            "run_id": f"deep_v2_pilot_{datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')}",
            "analysis_date": ANALYSIS_DATE,
            "sector_code": code,
            "sector_name": old["sector_name"],
            "analysis_archetype": old.get("analysis_archetype"),
            "analysis_archetype_version": old.get("analysis_archetype_version"),
            "overall_score": old["overall_score"],
            "dimension_scores": dimensions,
            "score_status": "baseline_for_pilot_review",
            "review_required": True,
            "verdict": old["verdict"],
            "core_logic": old["core_logic"],
            "key_contradiction": old["key_contradiction"],
            "forecasts": forecasts,
            "source_category_counts": category_counts,
            "evidence_refs": refs,
            "member_aggregate": aggregate,
            "research_method": "codex_deep_research_v2_pilot",
            "is_final_research": False,
            "data_quality": {
                "evidence_count": len(refs),
                "post_date_excluded": 0,
                "financial_coverage_pct": aggregate.get("financial_coverage_pct"),
                "business_purity_status": aggregate.get("business_purity_status"),
                "business_purity_ratio": aggregate.get("business_purity_ratio"),
                "limitations": [
                    "评分沿用上一版本数值，仅用于试点页面检查，未作为正式发布分数",
                    "资金、政策或研报类别缺失时保留no_data，不用其他证据替代",
                    "业务纯度为主营摘要关键词代理指标，需人工抽样复核",
                ],
            },
        }
        (output_dir / f"pilot_{code}.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), "count": len(list(output_dir.glob('pilot_*.json')))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
