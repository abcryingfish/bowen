#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import polars as pl


BASE = Path(r"D:\database\sector_information")
AS_OF = "2026-07-18 23:59:59"
ANALYSIS_DATE = "2026-07-18"
PILOT_CODES = [
    "881101.THS", "882001.THS", "885462.THS", "886065.THS",
    "886069.THS", "886072.THS", "886086.THS", "886095.THS",
    "886101.THS", "886102.THS", "886109.THS", "886111.THS",
]
DIMENSIONS = ("policy", "fundamental", "capital", "technical", "valuation", "risk")
SOURCE_TYPES = ("policy", "research_report", "announcement", "news", "industry_data", "capital")
POLICY_WORDS = ("政策", "规划", "条例", "指导意见", "国务院", "发改", "财政", "监管", "税收优惠")
CAPITAL_WORDS = ("主力资金", "资金净流入", "资金净流出", "融资余额", "北向资金", "ETF净流入", "成交额")
INDUSTRY_WORDS = ("产量", "价格", "库存", "出货", "订单", "渗透率", "招标", "中标", "产能", "销量", "进出口")
MISMATCH_WORDS = ("上涨", "下跌", "高开", "低开", "涨停", "跌停", "ETF", "主力资金")
PURITY_KEYWORDS = {
    "881101.THS": ("种植", "林业", "林木", "农业", "农产品"),
    "885462.THS": ("乳业", "乳制品", "牛奶", "奶粉", "乳品"),
    "886065.THS": ("核聚变", "核能", "等离子", "超导", "聚变"),
    "886069.THS": ("机器人", "机械臂", "伺服", "减速器", "智能制造"),
    "886086.THS": ("西部大开发", "西部地区", "新疆", "西藏", "青海", "甘肃", "宁夏", "陕西", "四川", "云南", "贵州", "广西", "内蒙古"),
    "886095.THS": ("IP", "版权", "动漫", "游戏", "玩具", "潮玩", "文创"),
    "886111.THS": ("玻璃基板", "电子玻璃", "玻璃基材", "基板"),
}
NOT_APPLICABLE_CODES = {"882001.THS", "886072.THS", "886101.THS", "886102.THS", "886109.THS"}


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
    return parsed


def filter_as_of(rows: list[dict[str, Any]], cutoff: str) -> tuple[list[dict[str, Any]], int]:
    boundary = parse_datetime(cutoff)
    kept: list[dict[str, Any]] = []
    excluded = 0
    for row in rows:
        published = parse_datetime(row.get("published_at"))
        if published is None or boundary is None or published <= boundary:
            kept.append(row)
        else:
            excluded += 1
    return kept, excluded


def classify_evidence(row: dict[str, Any]) -> dict[str, Any]:
    title = str(row.get("title") or "")
    summary = str(row.get("summary") or "")
    text = title + " " + summary
    raw_type = str(row.get("evidence_type") or "news")
    if any(word in text for word in CAPITAL_WORDS):
        source_type = "capital"
    elif any(word in text for word in INDUSTRY_WORDS):
        source_type = "industry_data"
    elif raw_type == "research_report":
        source_type = "research_report"
    elif raw_type == "announcement":
        source_type = "announcement"
    elif raw_type == "policy" and not any(word in text for word in MISMATCH_WORDS):
        source_type = "policy"
    else:
        source_type = "news"
    mismatch = any(word in title for word in MISMATCH_WORDS) and source_type in {"policy", "news"}
    linked = ["capital"] if source_type == "capital" else ["policy"] if source_type == "policy" else ["fundamental"]
    if source_type in {"industry_data", "research_report"}:
        linked = ["fundamental", "valuation"]
    if source_type == "announcement":
        linked = ["fundamental", "risk"]
    if mismatch:
        linked = ["capital"] if any(word in text for word in CAPITAL_WORDS) else []
    return {
        "source_type": source_type,
        "source_type_raw": raw_type,
        "source_tier": "tier1" if source_type in {"policy", "announcement"} else "tier2",
        "linked_dimensions": linked,
        "stance": "adverse" if any(word in text for word in ("下跌", "亏损", "下降", "风险", "诉讼", "问询")) else "supporting",
        "classification_status": "mismatch" if mismatch else "valid",
        "evidence_quality": "medium" if mismatch else "normal",
        "time_validity": "valid_as_of_date",
    }


def dedupe_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: str(row.get("published_at") or ""), reverse=True)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in ordered:
        key = str(row.get("content_hash") or hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest())
        if key in seen:
            continue
        seen.add(key)
        enriched = dict(row)
        enriched.update(classify_evidence(row))
        enriched["evidence_id"] = key
        out.append(enriched)
    return out


def business_purity_status(code: str, sector_name: str, texts: list[str], total: int) -> tuple[str, float | None, str]:
    if code in NOT_APPLICABLE_CODES:
        return "not_applicable", None, "该板块是地域、风格、事件或财报样本池，业务纯度不适用"
    keywords = PURITY_KEYWORDS.get(code, tuple(word for word in sector_name if word.strip()))
    matched = sum(1 for text in texts if any(keyword.lower() in text.lower() for keyword in keywords))
    if total <= 0:
        return "no_data", None, "没有可用主营业务摘要"
    return "available", round(matched / total, 4), f"按主营摘要关键词匹配，匹配{matched}/{total}只成分股；仅为主题关联度代理指标"


def build_evidence(codes: list[str]) -> tuple[pl.DataFrame, dict[str, dict[str, int]]]:
    evidence = pl.read_parquet(BASE / "current" / "evidence.parquet")
    links = pl.read_parquet(BASE / "current" / "claim_evidence_links.parquet")
    linked = links.join(evidence, left_on="evidence_id", right_on="content_hash", how="inner").select(
        "sector_code", "evidence_id", "evidence_type", "published_at", "source", "title", "url", "summary"
    )
    direct = evidence.filter(pl.col("entity_id").is_in(codes)).select(
        pl.col("entity_id").alias("sector_code"),
        pl.col("content_hash").alias("evidence_id"),
        "evidence_type", "published_at", "source", "title", "url", "summary",
    )
    network_files = sorted((BASE / "evidence" / f"analysis_date={ANALYSIS_DATE}").glob("pilot_network_*.parquet"))
    network = pl.DataFrame(schema={
        "sector_code": pl.String, "evidence_id": pl.String, "evidence_type": pl.String,
        "published_at": pl.String, "source": pl.String, "title": pl.String, "url": pl.String, "summary": pl.String,
    })
    if network_files:
        raw_network = pl.read_parquet(network_files[-1])
        member_rows = pl.read_parquet(BASE / "constituent_snapshots_eligible" / "analysis_date=2026-07-15" / "part-000.parquet").filter(pl.col("sector_code").is_in(codes)).select("sector_code", "stock_code").to_dicts()
        stock_to_sectors: dict[str, set[str]] = {}
        for member in member_rows:
            stock_to_sectors.setdefault(str(member["stock_code"]), set()).add(str(member["sector_code"]))
        network_rows: list[dict[str, Any]] = []
        for row in raw_network.to_dicts():
            sectors = {str(row["entity_id"])} if row.get("entity_id") else set()
            if row.get("evidence_type") == "announcement":
                try:
                    payload = json.loads(row.get("summary") or "{}")
                    for item in payload.get("codes", []):
                        number = str(item.get("stock_code") or "")
                        suffix = ".SH" if str(item.get("market_code")) == "1" else ".SZ"
                        sectors.update(stock_to_sectors.get(f"{number}{suffix}", set()))
                except (TypeError, json.JSONDecodeError):
                    pass
            for sector in sectors & set(codes):
                network_rows.append({
                    "sector_code": sector, "evidence_id": row["content_hash"], "evidence_type": row["evidence_type"],
                    "published_at": row["published_at"], "source": row["source"], "title": row["title"],
                    "url": row["url"], "summary": row["summary"],
                })
        if network_rows:
            network = pl.DataFrame(network_rows)
    joined = pl.concat([linked, direct, network], how="diagonal_relaxed").unique(
        subset=["sector_code", "evidence_id"]
    )
    all_rows: list[dict[str, Any]] = []
    stats: dict[str, dict[str, int]] = {}
    for code in codes:
        rows = (
            joined.filter(pl.col("sector_code") == code)
            .select(
                pl.col("evidence_id").alias("content_hash"),
                "evidence_type", "published_at", "source", "title", "url", "summary"
            )
            .to_dicts()
        )
        kept, excluded = filter_as_of(rows, AS_OF)
        deduped = dedupe_evidence(kept)
        selected: list[dict[str, Any]] = []
        selected_ids: set[str] = set()
        # Prevent constituent announcements from crowding out reports, policy,
        # industry and capital evidence. Missing categories remain explicit.
        for source_type in SOURCE_TYPES:
            candidates = [row for row in deduped if row["source_type"] == source_type]
            for row in candidates[:4]:
                selected.append(row)
                selected_ids.add(str(row["evidence_id"]))
        for row in deduped:
            if len(selected) >= 20:
                break
            if str(row["evidence_id"]) not in selected_ids:
                selected.append(row)
                selected_ids.add(str(row["evidence_id"]))
        for row in selected:
            row["sector_code"] = code
            row["analysis_date"] = ANALYSIS_DATE
            row["summary"] = str(row.get("summary") or "")[:1200]
            all_rows.append(row)
        counts = {source_type: sum(row["source_type"] == source_type for row in selected) for source_type in SOURCE_TYPES}
        counts.update({"raw_count": len(rows), "deduped_count": len(deduped), "selected_count": len(selected), "post_date_excluded": excluded})
        stats[code] = counts
    return pl.DataFrame(all_rows), stats


def build_member_aggregate(codes: list[str]) -> pl.DataFrame:
    members_path = BASE / "constituent_snapshots_eligible" / "analysis_date=2026-07-15" / "part-000.parquet"
    members = pl.read_parquet(members_path)
    selected = members.filter(pl.col("sector_code").is_in(codes))
    valuation = pl.scan_parquet(str(BASE.parent / "qmt_company_data" / "table=factor_fundamental_valuation" / "year=*" / "month=*" / "merged.parquet")).collect()
    valuation = (
        valuation.filter(pl.col("time") <= datetime(2026, 7, 18))
        .sort("time")
        .unique(subset=["htsc_code"], keep="last")
        .select("htsc_code", "total_market_val", "revenue_ttm", "net_profit_parent_ttm", "roe", "pe_ttm", "pb")
    )
    joined = selected.select("sector_code", "sector_name", "stock_code").unique().join(
        valuation, left_on="stock_code", right_on="htsc_code", how="left"
    )
    profile_path = BASE / "company_business_profiles" / f"analysis_date={ANALYSIS_DATE}" / "pilot_profiles.parquet"
    profiles = pl.read_parquet(profile_path).select("stock_code", "company_summary", "business_scope") if profile_path.exists() else pl.DataFrame({"stock_code": [], "company_summary": [], "business_scope": []})
    joined = joined.join(profiles, on="stock_code", how="left")
    rows: list[dict[str, Any]] = []
    for frame in joined.partition_by("sector_code", as_dict=True).values():
        sector_code = str(frame["sector_code"][0])
        sector_name = str(frame["sector_name"][0])
        n = frame.height
        revenue = [float(v) for v in frame["revenue_ttm"].drop_nulls().to_list()]
        profit = [float(v) for v in frame["net_profit_parent_ttm"].drop_nulls().to_list()]
        market = frame.filter(pl.col("total_market_val").is_not_null()).sort("total_market_val", descending=True)
        top_n = max(1, int(round(n * 0.10)))
        top = market.head(top_n)
        total_market = float(market["total_market_val"].sum()) if market.height else None
        total_revenue = float(frame["revenue_ttm"].drop_nulls().sum()) if revenue else None
        total_profit = float(frame["net_profit_parent_ttm"].drop_nulls().sum()) if profit else None
        profile_texts = [f"{row.get('company_summary') or ''} {row.get('business_scope') or ''}" for row in frame.select("company_summary", "business_scope").to_dicts() if row.get("company_summary") or row.get("business_scope")]
        purity_status, purity_ratio, purity_note = business_purity_status(sector_code, sector_name, profile_texts, n)
        rows.append({
            "sector_code": sector_code, "sector_name": sector_name, "analysis_date": ANALYSIS_DATE,
            "eligible_member_count": n, "financial_coverage_count": len(revenue),
            "financial_coverage_pct": round(len(revenue) / n * 100, 2) if n else None,
            "profitable_member_count": sum(v > 0 for v in profit),
            "profitable_member_pct": round(sum(v > 0 for v in profit) / len(profit) * 100, 2) if profit else None,
            "revenue_median": float(pl.Series(revenue).median()) if revenue else None,
            "revenue_p25": float(pl.Series(revenue).quantile(0.25)) if revenue else None,
            "revenue_p75": float(pl.Series(revenue).quantile(0.75)) if revenue else None,
            "profit_median": float(pl.Series(profit).median()) if profit else None,
            "profit_p25": float(pl.Series(profit).quantile(0.25)) if profit else None,
            "profit_p75": float(pl.Series(profit).quantile(0.75)) if profit else None,
            "leader_top10_market_value_contribution_pct": round(float(top["total_market_val"].sum()) / total_market * 100, 2) if total_market else None,
            "leader_top10_revenue_contribution_pct": round(float(top["revenue_ttm"].drop_nulls().sum()) / total_revenue * 100, 2) if total_revenue else None,
            "leader_top10_profit_contribution_pct": round(float(top["net_profit_parent_ttm"].drop_nulls().sum()) / total_profit * 100, 2) if total_profit and total_profit > 0 else None,
            "revenue_distribution_status": "available" if revenue else "no_data",
            "profit_distribution_status": "available" if profit else "no_data",
            "leader_contribution_status": "available" if market.height and total_profit and total_profit > 0 else "mixed_or_negative_total_profit",
            "business_purity_status": purity_status,
            "business_purity_ratio": purity_ratio,
            "business_purity_note": purity_note,
            "aggregation_limitations": "业务纯度为主营摘要关键词代理指标，需人工抽样复核；财务字段按最新可用记录聚合",
        })
    return pl.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", nargs="*", default=PILOT_CODES)
    args = parser.parse_args()
    codes = args.codes
    evidence_df, evidence_stats = build_evidence(codes)
    aggregate_df = build_member_aggregate(codes)
    run_id = datetime.now(timezone(timedelta(hours=8))).strftime("deep_v2_%Y%m%d_%H%M%S")
    evidence_dir = BASE / "evidence" / f"analysis_date={ANALYSIS_DATE}"
    aggregate_dir = BASE / "sector_member_aggregates" / f"analysis_date={ANALYSIS_DATE}"
    assessment_dir = BASE / "codex_assessments" / f"analysis_date={ANALYSIS_DATE}"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    aggregate_dir.mkdir(parents=True, exist_ok=True)
    assessment_dir.mkdir(parents=True, exist_ok=True)
    evidence_df.write_parquet(evidence_dir / f"pilot_bundle_{run_id}.parquet", compression="zstd")
    aggregate_df.write_parquet(aggregate_dir / f"pilot_aggregate_{run_id}.parquet", compression="zstd")
    report = {
        "schema_version": "codex_deep_research_pilot.v2",
        "run_id": run_id,
        "analysis_date": ANALYSIS_DATE,
        "cutoff": AS_OF,
        "codes": codes,
        "evidence_stats": evidence_stats,
        "aggregation_rows": aggregate_df.height,
        "status": "pilot_evidence_and_aggregation_ready",
        "limitations": ["当前本地证据库没有独立产业数据表时，类别状态保留为no_data", "业务纯度使用东方财富主营摘要关键词代理，仍需人工抽样复核；地域、风格、事件和财报样本池标记为not_applicable"],
    }
    report_path = BASE / "codex_assessments" / f"pilot_quality_report_{run_id}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"run_id": run_id, "report": str(report_path), "evidence": str(evidence_dir), "aggregates": str(aggregate_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
