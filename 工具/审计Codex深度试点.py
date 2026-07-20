#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl


BASE = Path(r"D:\database\sector_information")
EXPECTED_TYPES = {"policy", "research_report", "announcement", "news", "industry_data", "capital"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    failures: list[dict[str, str]] = []
    evidence_stats = report["evidence_stats"]
    aggregate_path = sorted((BASE / "sector_member_aggregates" / "analysis_date=2026-07-18").glob("pilot_aggregate_*.parquet"))[-1]
    aggregates = pl.read_parquet(aggregate_path).to_dicts()
    aggregate_by_code = {row["sector_code"]: row for row in aggregates}
    rows = []
    for code in report["codes"]:
        stats = evidence_stats[code]
        missing_categories = sorted(EXPECTED_TYPES - {key for key in EXPECTED_TYPES if stats.get(key, 0) > 0})
        aggregate = aggregate_by_code.get(code, {})
        issues = []
        if not 10 <= stats["selected_count"] <= 20:
            issues.append("evidence_count_out_of_range")
        if stats["post_date_excluded"]:
            issues.append("post_date_evidence_found")
        if not aggregate:
            issues.append("missing_member_aggregate")
        if aggregate.get("revenue_distribution_status") != "available":
            issues.append("revenue_distribution_unavailable")
        if aggregate.get("profit_distribution_status") != "available":
            issues.append("profit_distribution_unavailable")
        if aggregate.get("leader_contribution_status") not in {"available", "mixed_or_negative_total_profit"}:
            issues.append("leader_contribution_unavailable")
        if aggregate.get("business_purity_status") not in {"available", "not_applicable"}:
            issues.append("business_purity_unavailable")
        rows.append({
            "sector_code": code,
            "selected_evidence": stats["selected_count"],
            "missing_evidence_categories": missing_categories,
            "financial_coverage_pct": aggregate.get("financial_coverage_pct"),
            "business_purity_status": aggregate.get("business_purity_status"),
            "pilot_status": "needs_rework" if issues else "ready_for_review",
            "issues": issues,
        })
    ready = sum(row["pilot_status"] == "ready_for_review" for row in rows)
    report["pilot_audit"] = {"ready_count": ready, "total_count": len(rows), "rows": rows}
    report["status"] = "pilot_ready_for_review" if ready == len(rows) else "pilot_needs_rework"
    out = Path(args.report).with_name(Path(args.report).stem + "_audited.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(out), "status": report["status"], "ready_count": ready, "total_count": len(rows)}, ensure_ascii=False))
    if ready != len(rows):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
