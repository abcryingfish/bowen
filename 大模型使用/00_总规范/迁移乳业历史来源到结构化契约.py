#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Seed machine-readable source knowledge from the completed dairy pilot."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl


BASE = Path(r"D:\database\sector_information\research_knowledge")
REPORT = (
    Path(r"D:\database\sector_information\reports\analysis_date=2026-07-21")
    / "885462.THS__dairy_885462_20260721_20260721T105616586779.json"
)
RUN_ID = "dairy_885462_20260721_20260721T105616586779"
NOW = "2026-07-21T00:00:00+08:00"


SOURCE_MAP = {
    "中国政府网": {
        "source_id": "SRC_GOV_CN_POLICY",
        "domain": "gov.cn",
        "stable_entry": "https://www.gov.cn/zhengce/",
        "status": "active",
        "priority": 1,
        "source_types": ["policy"],
        "objects": ["农业", "养殖", "乳业", "宏观政策"],
        "dimensions": ["policy", "fundamental", "risk"],
        "authority": "official",
        "scores": [1.0, 1.0, 1.0, 0.95, 0.95],
    },
    "农业农村部畜牧兽医局": {
        "source_id": "SRC_MOA_DAIRY",
        "domain": "moa.gov.cn",
        "stable_entry": "https://xmsyj.moa.gov.cn/",
        "status": "active",
        "priority": 1,
        "source_types": ["policy", "industry_data"],
        "objects": ["农业", "畜牧养殖", "乳业"],
        "dimensions": ["policy", "fundamental", "risk"],
        "authority": "official",
        "scores": [1.0, 1.0, 0.9, 0.95, 0.9],
    },
    "国家统计局": {
        "source_id": "SRC_NBS_RELEASE",
        "domain": "stats.gov.cn",
        "stable_entry": "https://www.stats.gov.cn/sj/",
        "status": "active",
        "priority": 1,
        "source_types": ["industry_data", "macro_data"],
        "objects": ["宏观经济", "产业数据", "乳业"],
        "dimensions": ["fundamental", "risk", "valuation"],
        "authority": "official",
        "scores": [1.0, 1.0, 0.95, 0.9, 0.95],
    },
    "东兴证券": {
        "source_id": "SRC_EASTMONEY_REPORT",
        "domain": "data.eastmoney.com",
        "stable_entry": "https://data.eastmoney.com/report/",
        "status": "active",
        "priority": 2,
        "source_types": ["formal_research"],
        "objects": ["行业板块", "个股", "乳业"],
        "dimensions": ["fundamental", "valuation", "risk"],
        "authority": "professional",
        "scores": [0.85, 0.9, 0.7, 0.9, 0.85],
    },
    "华源证券": {
        "source_id": "SRC_EASTMONEY_REPORT",
        "domain": "data.eastmoney.com",
        "stable_entry": "https://data.eastmoney.com/report/",
        "status": "active",
        "priority": 2,
        "source_types": ["formal_research"],
        "objects": ["行业板块", "个股", "乳业"],
        "dimensions": ["fundamental", "valuation", "risk"],
        "authority": "professional",
        "scores": [0.85, 0.9, 0.7, 0.9, 0.85],
    },
    "伊利股份2026年第一季度报告": {
        "source_id": "SRC_SINA_ANNOUNCEMENT_MIRROR",
        "domain": "money.finance.sina.com.cn",
        "stable_entry": "https://money.finance.sina.com.cn/corp/view/",
        "status": "conditional",
        "priority": 2,
        "source_types": ["announcement"],
        "objects": ["A股上市公司", "乳业个股"],
        "dimensions": ["fundamental", "capital", "risk"],
        "authority": "secondary",
        "scores": [0.75, 0.95, 0.95, 0.85, 0.9],
    },
    "新乳业2026年第一季度报告": {
        "source_id": "SRC_SINA_ANNOUNCEMENT_MIRROR",
        "domain": "money.finance.sina.com.cn",
        "stable_entry": "https://money.finance.sina.com.cn/corp/view/",
        "status": "conditional",
        "priority": 2,
        "source_types": ["announcement"],
        "objects": ["A股上市公司", "乳业个股"],
        "dimensions": ["fundamental", "capital", "risk"],
        "authority": "secondary",
        "scores": [0.75, 0.95, 0.95, 0.85, 0.9],
    },
    "光明乳业2026年第一季度报告": {
        "source_id": "SRC_SINA_ANNOUNCEMENT_MIRROR",
        "domain": "money.finance.sina.com.cn",
        "stable_entry": "https://money.finance.sina.com.cn/corp/view/",
        "status": "conditional",
        "priority": 2,
        "source_types": ["announcement"],
        "objects": ["A股上市公司", "乳业个股"],
        "dimensions": ["fundamental", "capital", "risk"],
        "authority": "secondary",
        "scores": [0.75, 0.95, 0.95, 0.85, 0.9],
    },
    "饲料行业信息网转引农业农村部": {
        "source_id": "SRC_FEEDTRADE_INDUSTRY_REPRINT",
        "domain": "m.feedtrade.com.cn",
        "stable_entry": "https://m.feedtrade.com.cn/nav/",
        "status": "conditional",
        "priority": 3,
        "source_types": ["industry_data"],
        "objects": ["农业", "畜牧养殖", "乳业"],
        "dimensions": ["fundamental", "risk"],
        "authority": "secondary",
        "scores": [0.6, 0.75, 0.8, 0.85, 0.75],
    },
    "饲料行业信息网转引经济日报及奶业质量报告2026": {
        "source_id": "SRC_FEEDTRADE_INDUSTRY_REPRINT",
        "domain": "m.feedtrade.com.cn",
        "stable_entry": "https://m.feedtrade.com.cn/nav/",
        "status": "conditional",
        "priority": 3,
        "source_types": ["industry_data"],
        "objects": ["农业", "乳业", "食品"],
        "dimensions": ["fundamental", "risk"],
        "authority": "secondary",
        "scores": [0.6, 0.75, 0.8, 0.85, 0.75],
    },
    "FT食品乳业网经全球婴童网转载": {
        "source_id": "SRC_51NZ_DAIRY_NEWS",
        "domain": "51nz.com.cn",
        "stable_entry": "http://www.51nz.com.cn/data/",
        "status": "conditional",
        "priority": 4,
        "source_types": ["news"],
        "objects": ["乳业", "婴幼儿食品"],
        "dimensions": ["fundamental", "risk"],
        "authority": "secondary",
        "scores": [0.45, 0.65, 0.65, 0.75, 0.65],
    },
    "刘旷频道经全球婴童网转载": {
        "source_id": "SRC_51NZ_DAIRY_NEWS",
        "domain": "51nz.com.cn",
        "stable_entry": "http://www.51nz.com.cn/data/",
        "status": "conditional",
        "priority": 4,
        "source_types": ["news"],
        "objects": ["乳业", "婴幼儿食品"],
        "dimensions": ["fundamental", "risk"],
        "authority": "secondary",
        "scores": [0.45, 0.65, 0.65, 0.75, 0.65],
    },
    "证券之星证星资金流向": {
        "source_id": "SRC_STOCKSTAR_MARGIN",
        "domain": "stockstar.com",
        "stable_entry": "https://4g.stockstar.com/detail/",
        "status": "conditional",
        "priority": 3,
        "source_types": ["capital_data"],
        "objects": ["A股个股"],
        "dimensions": ["capital", "technical"],
        "authority": "secondary",
        "scores": [0.55, 0.8, 0.75, 0.8, 0.7],
    },
}


def registry_rows(evidence: list[dict]) -> list[dict]:
    now = NOW
    rows = []
    for name, item in SOURCE_MAP.items():
        rows.append(
            {
                "schema_version": "1.0",
                "source_id": item["source_id"],
                "source_name": name,
                "domain": item["domain"],
                "stable_entry": item["stable_entry"],
                "status": item["status"],
                "priority": item["priority"],
                "source_types": item["source_types"],
                "applicable_objects": item["objects"],
                "supported_dimensions": item["dimensions"],
                "authority_level": item["authority"],
                "content_access": "full_text",
                "published_at_reliability": "high" if item["authority"] == "official" else "medium",
                "authority_score": item["scores"][0],
                "date_reliability_score": item["scores"][1],
                "content_completeness_score": item["scores"][2],
                "object_match_score": item["scores"][3],
                "reproducibility_score": item["scores"][4],
                "known_limits": [],
                "first_discovered_at": "2026-07-21",
                "last_checked_at": now,
                "last_success_at": now,
                "last_failure_at": None,
                "last_failure_reason": None,
                "success_count": sum(1 for e in evidence if e.get("source") == name),
                "failure_count": 0,
                "superseded_by_source_id": None,
                "example_evidence_ids": [e["evidence_id"] for e in evidence if e.get("source") == name],
                "discovered_by_run_id": RUN_ID,
                "last_checked_by_run_id": RUN_ID,
                "created_at": now,
                "updated_at": now,
            }
        )
    merged: dict[str, dict] = {}
    for row in rows:
        current = merged.get(row["source_id"])
        if current is None:
            merged[row["source_id"]] = row
            continue
        current["source_name"] = f"{current['source_name']} / {row['source_name']}"
        current["source_types"] = sorted(set(current["source_types"] + row["source_types"]))
        current["applicable_objects"] = sorted(set(current["applicable_objects"] + row["applicable_objects"]))
        current["supported_dimensions"] = sorted(set(current["supported_dimensions"] + row["supported_dimensions"]))
        current["example_evidence_ids"] = sorted(set(current["example_evidence_ids"] + row["example_evidence_ids"]))
        current["success_count"] += row["success_count"]
    return list(merged.values())


def main() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    result = json.loads(REPORT.read_text(encoding="utf-8"))
    evidence = [dict(item) for item in result["evidence"]]
    pl.DataFrame(registry_rows(evidence)).write_parquet(BASE / "source_registry.parquet", compression="zstd")

    failures = [
        {"failure_id": "FAIL_CERTIFICATE_PAGE", "failure_type": "certificate_error", "notes": "目标页面证书错误，记为retrieval_failed。"},
        {"failure_id": "FAIL_SEARCH_SNIPPET_ONLY", "failure_type": "search_snippet_only", "notes": "搜索摘要未进入证据。"},
        {"failure_id": "FAIL_BJ_MISMATCH", "failure_type": "excluded_market", "notes": "北交所证据记为mismatch。"},
        {"failure_id": "FAIL_UNCLEAR_INTRADAY_TIME", "failure_type": "analysis_date_time_unknown", "notes": "发布时间不清的分析日内容排除。"},
        {"failure_id": "FAIL_DUPLICATE_REPRINT", "failure_type": "duplicate_or_reprint", "notes": "重复转载不重复计证据。"},
    ]
    failure_rows = []
    for item in failures:
        failure_rows.append({
            "schema_version": "1.0", "failure_id": item["failure_id"], "source_id": None,
            "url_or_entry": None, "domain": None, "failure_type": item["failure_type"],
            "first_failed_at": NOW, "last_failed_at": NOW, "affected_source_types": [],
            "retry_policy": "conditional", "retry_condition": "来源状态变化或出现权威替代入口",
            "alternative_paths": [], "discovered_by_run_id": RUN_ID,
            "last_checked_by_run_id": RUN_ID, "notes": item["notes"],
            "created_at": NOW, "updated_at": NOW,
        })
    pl.DataFrame(failure_rows).write_parquet(BASE / "source_failures.parquet", compression="zstd")

    checks = []
    versions = []
    for item in evidence:
        source = SOURCE_MAP.get(item["source"], {})
        checks.append({
            "schema_version": "1.0", "source_check_id": f"CHECK_{item['evidence_id']}",
            "source_id": source.get("source_id"), "run_id": RUN_ID, "object_type": "sector",
            "object_code": "885462.THS", "analysis_date": "2026-07-21", "checked_at": NOW,
            "result": "valid", "evidence_id": item["evidence_id"], "failure_id": None,
            "content_hash": item.get("content_hash"), "published_at": item.get("published_at"),
            "notes": item.get("title"),
        })
        versions.append({
            "schema_version": "1.0", "source_version_id": f"SV_{item['evidence_id']}",
            "source_id": source.get("source_id"), "content_hash": item.get("content_hash"),
            "url": item.get("url"), "title": item.get("title"),
            "published_at": item.get("published_at"), "retrieved_at": NOW,
            "content_type": item.get("source_type"), "evidence_id": item["evidence_id"],
            "run_id": RUN_ID, "is_current_version": True,
        })
    pl.DataFrame(checks).write_parquet(BASE / "source_checks.parquet", compression="zstd")
    pl.DataFrame(versions).write_parquet(BASE / "source_versions.parquet", compression="zstd")

    context = [{
        "schema_version": "1.0", "research_context_id": f"CTX_{RUN_ID}", "run_id": RUN_ID,
        "object_type": "sector", "object_code": "885462.THS", "analysis_date": "2026-07-21",
        "read_documents": ["AGENTS.md", "CONTEXT.md", "docs/单板块Codex深度研究运行规范.md"],
        "reused_source_ids": sorted({SOURCE_MAP[e["source"]]["source_id"] for e in evidence}),
        "revalidated_evidence_ids": [e["evidence_id"] for e in evidence], "new_source_ids": [],
        "superseded_source_ids": [], "rejected_source_entries": ["FAIL_SEARCH_SNIPPET_ONLY", "FAIL_BJ_MISMATCH"],
        "old_claims_retested": [], "claims_invalidated": [],
        "constituent_snapshot_id": result.get("snapshot_id"), "definition_version": "1.0",
        "business_profile_version": "1.0", "resource_budget": json.dumps({"stop_after_no_new_claim_rounds": 2}, ensure_ascii=False),
        "created_at": NOW,
    }]
    pl.DataFrame(context).write_parquet(BASE / "research_context_manifests.parquet", compression="zstd")


if __name__ == "__main__":
    main()
