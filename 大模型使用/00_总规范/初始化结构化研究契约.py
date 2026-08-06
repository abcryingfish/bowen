#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Initialize empty Parquet contracts for reusable research knowledge."""
from pathlib import Path

import polars as pl


ROOT = Path(r"D:\database\sector_information\research_knowledge")


SCHEMAS = {
    "source_registry.parquet": {
        "schema_version": pl.String,
        "source_id": pl.String,
        "source_name": pl.String,
        "domain": pl.String,
        "stable_entry": pl.String,
        "status": pl.String,
        "priority": pl.Int8,
        "source_types": pl.List(pl.String),
        "applicable_objects": pl.List(pl.String),
        "supported_dimensions": pl.List(pl.String),
        "authority_level": pl.String,
        "content_access": pl.String,
        "published_at_reliability": pl.String,
        "authority_score": pl.Float64,
        "date_reliability_score": pl.Float64,
        "content_completeness_score": pl.Float64,
        "object_match_score": pl.Float64,
        "reproducibility_score": pl.Float64,
        "known_limits": pl.List(pl.String),
        "first_discovered_at": pl.String,
        "last_checked_at": pl.String,
        "last_success_at": pl.String,
        "last_failure_at": pl.String,
        "last_failure_reason": pl.String,
        "success_count": pl.Int64,
        "failure_count": pl.Int64,
        "superseded_by_source_id": pl.String,
        "example_evidence_ids": pl.List(pl.String),
        "discovered_by_run_id": pl.String,
        "last_checked_by_run_id": pl.String,
        "created_at": pl.String,
        "updated_at": pl.String,
    },
    "source_failures.parquet": {
        "schema_version": pl.String,
        "failure_id": pl.String,
        "source_id": pl.String,
        "url_or_entry": pl.String,
        "domain": pl.String,
        "failure_type": pl.String,
        "first_failed_at": pl.String,
        "last_failed_at": pl.String,
        "affected_source_types": pl.List(pl.String),
        "retry_policy": pl.String,
        "retry_condition": pl.String,
        "alternative_paths": pl.List(pl.String),
        "discovered_by_run_id": pl.String,
        "last_checked_by_run_id": pl.String,
        "notes": pl.String,
        "created_at": pl.String,
        "updated_at": pl.String,
    },
    "source_checks.parquet": {
        "schema_version": pl.String,
        "source_check_id": pl.String,
        "source_id": pl.String,
        "run_id": pl.String,
        "object_type": pl.String,
        "object_code": pl.String,
        "analysis_date": pl.String,
        "checked_at": pl.String,
        "result": pl.String,
        "evidence_id": pl.String,
        "failure_id": pl.String,
        "content_hash": pl.String,
        "published_at": pl.String,
        "notes": pl.String,
    },
    "source_versions.parquet": {
        "schema_version": pl.String,
        "source_version_id": pl.String,
        "source_id": pl.String,
        "content_hash": pl.String,
        "url": pl.String,
        "title": pl.String,
        "published_at": pl.String,
        "retrieved_at": pl.String,
        "content_type": pl.String,
        "evidence_id": pl.String,
        "run_id": pl.String,
        "is_current_version": pl.Boolean,
    },
    "research_context_manifests.parquet": {
        "schema_version": pl.String,
        "research_context_id": pl.String,
        "run_id": pl.String,
        "object_type": pl.String,
        "object_code": pl.String,
        "analysis_date": pl.String,
        "read_documents": pl.List(pl.String),
        "reused_source_ids": pl.List(pl.String),
        "revalidated_evidence_ids": pl.List(pl.String),
        "new_source_ids": pl.List(pl.String),
        "superseded_source_ids": pl.List(pl.String),
        "rejected_source_entries": pl.List(pl.String),
        "old_claims_retested": pl.List(pl.String),
        "claims_invalidated": pl.List(pl.String),
        "constituent_snapshot_id": pl.String,
        "definition_version": pl.String,
        "business_profile_version": pl.String,
        "resource_budget": pl.String,
        "created_at": pl.String,
    },
    "graph_relation_versions.parquet": {
        "schema_version": pl.String,
        "relation_version_id": pl.String,
        "relation_id": pl.String,
        "subject_entity_id": pl.String,
        "predicate": pl.String,
        "object_entity_id": pl.String,
        "object_value": pl.String,
        "relation_status": pl.String,
        "fact_type": pl.String,
        "confidence": pl.Float64,
        "valid_from": pl.String,
        "valid_to": pl.String,
        "evidence_ids": pl.List(pl.String),
        "source_ids": pl.List(pl.String),
        "analysis_date": pl.String,
        "run_id": pl.String,
        "relation_version": pl.Int32,
        "supersedes_relation_id": pl.String,
        "content_hash": pl.String,
        "created_at": pl.String,
    },
}


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, schema in SCHEMAS.items():
        path = ROOT / name
        if not path.exists():
            pl.DataFrame(schema=schema).write_parquet(path, compression="zstd")
            print(f"created {path}")
        else:
            print(f"exists  {path}")


if __name__ == "__main__":
    main()

