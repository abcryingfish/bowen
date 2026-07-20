#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import polars as pl


BASE = Path(r"D:\database\sector_information")


def main() -> None:
    evidence = pl.read_parquet(BASE / "current" / "evidence.parquet")
    members = pl.read_parquet(BASE / "constituent_snapshots_eligible" / "analysis_date=*" / "part-*.parquet")
    direct = evidence.filter(pl.col("entity_id").is_not_null()).select(
        pl.col("content_hash").alias("evidence_id"),
        pl.col("entity_id").alias("sector_code"),
        pl.lit("direct_search_match").alias("link_method"),
    )
    announcement_rows: list[dict[str, str]] = []
    for row in evidence.filter(pl.col("evidence_type") == "announcement").select("content_hash", "summary").iter_rows(named=True):
        try:
            codes = json.loads(row["summary"] or "{}").get("stock_codes", [])
        except (json.JSONDecodeError, TypeError):
            codes = []
        announcement_rows.extend({"evidence_id": row["content_hash"], "stock_code": code} for code in codes)
    ann = pl.from_dicts(announcement_rows)
    member_map = members.select("sector_code", "stock_code").unique()
    linked = ann.join(member_map, on="stock_code", how="inner").select(
        "evidence_id", "sector_code", pl.lit("constituent_announcement").alias("link_method")
    )
    links = pl.concat([direct, linked]).unique()
    out = BASE / "current" / "claim_evidence_links.parquet"
    links.write_parquet(out, compression="zstd")
    print({"direct": direct.height, "announcement": linked.height, "total": links.height, "sector_count": links["sector_code"].n_unique()})


if __name__ == "__main__":
    main()
