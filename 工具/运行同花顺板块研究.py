#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""基于本地同花顺一级快照运行最新板块研究。

只处理最新完整交易日；不回填历史评分。数据不足时保留空值和阻断原因，绝不以中位数填分。
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from sector_type_adapter import classify_sector, semantic_publish_decision


DEFAULT_BASE = Path(r"D:\database\sector_information")
AUDIT_PATH = Path("temp/ths512_full_audit/sector_audit.parquet")
SECTOR_PATH = Path("temp/同花顺软件板块导出/同花顺软件一级板块.csv")
MEMBER_PATH = Path("temp/同花顺软件板块导出/同花顺软件板块成分股.csv")
VALUATION_GLOB = r"D:\database\qmt_company_data\table=factor_fundamental_valuation\year=*\month=*\merged.parquet"
TURNOVER_GLOB = r"D:\database\qmt_turnover_data\year=*\month=*\merged.parquet"


def score_high(value: float, low: float, high: float) -> float:
    if pd.isna(value):
        return np.nan
    return float(np.clip((value - low) / (high - low) * 10, 0, 10))


def score_low(value: float, low: float, high: float) -> float:
    if pd.isna(value):
        return np.nan
    return float(np.clip((high - value) / (high - low) * 10, 0, 10))


def dimension_scores(row: pd.Series) -> dict[str, float]:
    technical_parts = [
        score_high(row.get("return_20d_pct"), -15, 15),
        score_high(row.get("close_vs_ma20_pct"), -10, 10),
        score_high(row.get("close_vs_ma60_pct"), -20, 20),
        score_high(row.get("positive_return_20d_pct"), 0, 100),
    ]
    risk_pressure = [
        score_high(abs(row.get("max_drawdown_60d_pct")), 0, 35),
        score_high(row.get("volatility_20d_annualized_pct"), 10, 60),
        score_high(row.get("max_stock_sector_memberships"), 5, 100),
    ]
    capital_parts = [
        score_high(row.get("market_coverage_pct"), 80, 100),
        score_high(row.get("volume_5d_vs_20d_pct"), -30, 30),
        score_high(row.get("positive_return_20d_pct"), 0, 100),
    ]
    valuation_parts = [
        score_low(row.get("median_positive_pe_ttm"), 5, 100),
        score_low(row.get("median_pb"), 0.5, 10),
        score_low(row.get("loss_or_invalid_pe_pct"), 0, 60),
    ]
    fundamental_parts = [
        score_high(row.get("median_revenue_yoy_pct"), -20, 30),
        score_high(row.get("median_profit_yoy_pct"), -50, 50),
        score_high(row.get("median_roe_pct"), 0, 20),
        score_high(row.get("median_net_margin_pct"), -10, 20),
        score_high(row.get("profitable_member_pct"), 20, 100),
    ]

    def mean(values: list[float]) -> float:
        valid = [v for v in values if not pd.isna(v)]
        return float(np.mean(valid)) if valid else np.nan

    tech = mean(technical_parts)
    pressure = mean(risk_pressure)
    capital = mean(capital_parts)
    valuation = mean(valuation_parts)
    fundamental = mean(fundamental_parts)
    return {
        "technical": tech,
        "risk": 10 - pressure if not pd.isna(pressure) else np.nan,
        "capital": capital,
        "valuation": valuation,
        "fundamental": fundamental,
        "policy": row.get("policy_score", np.nan),
    }


def load_fundamental_features(members: pd.DataFrame, analysis_date: str) -> pd.DataFrame:
    cutoff = pd.Timestamp(analysis_date).date()
    reports = (
        pl.scan_parquet(VALUATION_GLOB)
        .select(
            "htsc_code",
            pl.col("income_report_date").cast(pl.Date, strict=False).alias("report_date"),
            pl.col("income_announce_date").cast(pl.Date, strict=False).alias("announce_date"),
            pl.col("time").cast(pl.Date, strict=False).alias("observation_date"),
            "revenue_ttm", "net_profit_parent_ttm", "roe", "net_roe",
        )
        .filter(pl.col("report_date").is_not_null() & pl.col("announce_date").is_not_null() & (pl.col("announce_date") <= cutoff))
        .collect()
        .sort("observation_date")
        .unique(["htsc_code", "report_date"], keep="last")
    )
    current = reports.sort("report_date").unique("htsc_code", keep="last")
    previous = reports.select(
        "htsc_code",
        pl.col("report_date").dt.offset_by("1y").alias("report_date"),
        pl.col("revenue_ttm").alias("previous_revenue_ttm"),
        pl.col("net_profit_parent_ttm").alias("previous_profit_ttm"),
    )
    stock = current.join(previous, on=["htsc_code", "report_date"], how="left").with_columns(
        pl.when(pl.col("previous_revenue_ttm") > 0).then((pl.col("revenue_ttm") / pl.col("previous_revenue_ttm") - 1) * 100).alias("revenue_yoy_pct"),
        pl.when(pl.col("previous_profit_ttm") > 0).then((pl.col("net_profit_parent_ttm") / pl.col("previous_profit_ttm") - 1) * 100).alias("profit_yoy_pct"),
        pl.when(pl.col("revenue_ttm") != 0).then(pl.col("net_profit_parent_ttm") / pl.col("revenue_ttm") * 100).alias("net_margin_pct"),
        pl.coalesce("net_roe", "roe").alias("roe_pct"),
    ).to_pandas()
    member_map = members[["指数代码", "股票代码"]].rename(columns={"指数代码": "sector_id", "股票代码": "htsc_code"})
    joined = member_map.merge(stock, on="htsc_code", how="left")
    joined["profitable"] = np.where(joined["net_profit_parent_ttm"].notna(), (joined["net_profit_parent_ttm"] > 0) * 100.0, np.nan)
    return joined.groupby("sector_id", as_index=False).agg(
        median_revenue_yoy_pct=("revenue_yoy_pct", "median"),
        median_profit_yoy_pct=("profit_yoy_pct", "median"),
        median_roe_pct=("roe_pct", "median"),
        median_net_margin_pct=("net_margin_pct", "median"),
        profitable_member_pct=("profitable", "mean"),
        fundamental_covered_members=("net_profit_parent_ttm", "count"),
        revenue_yoy_covered_members=("revenue_yoy_pct", "count"),
        profit_yoy_covered_members=("profit_yoy_pct", "count"),
    )


def load_policy_features(base: Path, assessments: pd.DataFrame) -> pd.DataFrame:
    path = base / "current" / "evidence.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["sector_code", "policy_score", "policy_evidence_count"])
    all_evidence = pl.read_parquet(path).filter(pl.col("entity_id").is_not_null())
    direct = all_evidence.group_by("entity_id").agg(
        pl.len().alias("classification_evidence_count"),
        pl.col("content_hash").first().alias("classification_evidence_id"),
    ).rename({"entity_id": "sector_code"}).to_pandas()
    evidence = all_evidence.filter(pl.col("evidence_type") == "policy").to_pandas()
    positive = ("支持", "推动", "鼓励", "规划", "补贴", "加快", "促进", "获批", "落地", "利好", "扩大", "振兴")
    negative = ("限制", "禁止", "收紧", "处罚", "退坡", "下调", "风险", "整治", "取消", "暂停")
    values: list[dict] = []
    for _, row in evidence.iterrows():
        text = f"{row.get('title') or ''} {row.get('summary') or ''}"
        pos = sum(word in text for word in positive)
        neg = sum(word in text for word in negative)
        if pos == neg:
            continue
        values.append({"sector_code": row["entity_id"], "signal": 1.0 if pos > neg else -1.0, "source": row.get("source")})
    if not values:
        return direct.assign(policy_score=np.nan, policy_evidence_count=np.nan)
    frame = pd.DataFrame(values).drop_duplicates(["sector_code", "source", "signal"])
    grouped = frame.groupby("sector_code").agg(policy_signal=("signal", "mean"), policy_evidence_count=("signal", "size")).reset_index()
    grouped["policy_score"] = (5 + 3 * grouped["policy_signal"]).clip(0, 10)
    return direct.merge(grouped, on="sector_code", how="left")


def write_partition(df: pd.DataFrame, root: Path, name: str, date_value: str) -> None:
    out = root / name / f"analysis_date={date_value}" / "part-000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pl.from_pandas(df).write_parquet(out, compression="zstd")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE))
    parser.add_argument("--analysis-date", default=None)
    args = parser.parse_args()
    base = Path(args.base_dir)
    audit = pl.read_parquet(AUDIT_PATH).to_pandas()
    sectors = pd.read_csv(SECTOR_PATH, dtype=str)
    members = pd.read_csv(MEMBER_PATH, dtype=str)
    members = members[members["软件级别"].eq("同花顺软件一级")].copy()
    raw_date = args.analysis_date or str(audit["local_end_date"].max())
    analysis_date = pd.Timestamp(raw_date).strftime("%Y-%m-%d")
    run_id = f"run_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"

    fundamentals = load_fundamental_features(members, analysis_date)
    fundamentals["sector_code"] = fundamentals["sector_id"].astype(str).str.zfill(6) + ".THS"
    audit = audit.merge(fundamentals.drop(columns=["sector_id"]), on="sector_code", how="left")
    policies = load_policy_features(base, audit)
    audit = audit.merge(policies, on="sector_code", how="left")

    rows: list[dict] = []
    dim_rows: list[dict] = []
    for _, audit_row in audit.iterrows():
        code = str(audit_row["sector_code"])
        sector_name = str(audit_row["sector_name"])
        members_one = members[members["指数代码"].astype(str).str.zfill(6).eq(code[:6])]
        classification_evidence = []
        if not pd.isna(audit_row.get("classification_evidence_id")):
            classification_evidence = [{"evidence_id": str(audit_row["classification_evidence_id"]), "kind": "direct", "source": "东方财富公开检索"}]
        result = classify_sector(code, sector_name, members_one["股票代码"].tolist(), evidence=classification_evidence)
        scores = dimension_scores(audit_row)
        # policy evidence is not present in the current local evidence store.
        decision = semantic_publish_decision(result)
        required = ("fundamental", "technical", "risk")
        required_valid = all(not pd.isna(scores[name]) for name in required)
        available = {k: v for k, v in scores.items() if not pd.isna(v) and (decision.publish_semantic_dimensions or k not in {"policy", "fundamental", "valuation"})}
        weights = {"policy": .20, "fundamental": .25, "capital": .15, "technical": .15, "valuation": .15, "risk": .10}
        usable_weight = sum(weights[k] for k in available)
        overall = float(sum(available[k] * weights[k] for k in available) / usable_weight) if required_valid and usable_weight >= .80 else np.nan
        status = "needs_review" if result.review_required else ("ready" if required_valid and usable_weight >= .80 else "blocked")
        row = {
            "run_id": run_id, "analysis_date": analysis_date, "sector_code": code,
            "sector_name": sector_name, "analysis_archetype": result.analysis_archetype,
            "analysis_archetype_version": result.type_version,
            "classification_facets_json": json.dumps(result.facets, ensure_ascii=False),
            "classification_confidence": result.classification_confidence,
            "review_required": result.review_required, "status": status,
            "overall_score": overall, "source_member_count": audit_row["source_member_count"],
            "excluded_bj_count": audit_row["excluded_bj_count"], "eligible_member_count": audit_row["eligible_member_count"],
            "market_coverage_pct": audit_row["market_coverage_pct"], "valuation_coverage_pct": audit_row["valuation_coverage_pct"],
            "state_regime": audit_row["state_regime"], "data_freshness_days": audit_row["data_freshness_days"],
        }
        rows.append(row)
        for dim, score in scores.items():
            dim_rows.append({"run_id": run_id, "analysis_date": analysis_date, "sector_code": code, "dimension_name": dim, "score": score, "published": decision.publish_semantic_dimensions or dim in {"technical", "capital", "risk"}, "status": status})

    result_df = pd.DataFrame(rows)
    dim_df = pd.DataFrame(dim_rows)
    write_partition(result_df, base, "assessments", analysis_date)
    write_partition(dim_df, base, "dimension_scores", analysis_date)
    write_partition(audit, base, "market_features", analysis_date)
    member_df = members.rename(columns={"指数代码": "sector_code", "板块名称": "sector_name", "股票代码": "stock_code", "市场": "exchange"}).copy()
    member_df["sector_code"] = member_df["sector_code"].astype(str).str.zfill(6) + ".THS"
    member_df["snapshot_id"] = f"snapshot_{analysis_date.replace('-', '')}_{run_id[-8:]}"
    member_df["analysis_date"] = analysis_date
    member_df["eligible"] = ~member_df["stock_code"].astype(str).str.upper().str.endswith(".BJ")
    member_df["exclusion_reason"] = np.where(member_df["eligible"], None, "北交所强制排除")
    write_partition(member_df, base, "constituent_snapshots_raw", analysis_date)
    write_partition(member_df[member_df["eligible"]].copy(), base, "constituent_snapshots_eligible", analysis_date)
    manifest = pd.DataFrame([{"run_id": run_id, "analysis_date": analysis_date, "sector_count": len(result_df), "ready_count": int((result_df.status == "ready").sum()), "needs_review_count": int((result_df.status == "needs_review").sum()), "blocked_count": int((result_df.status == "blocked").sum())}])
    write_partition(manifest, base, "run_manifest", analysis_date)
    current = base / "current"
    current.mkdir(parents=True, exist_ok=True)
    pl.from_pandas(result_df).write_parquet(current / "assessments.parquet", compression="zstd")
    pl.from_pandas(dim_df).write_parquet(current / "dimension_scores.parquet", compression="zstd")
    print(json.dumps(manifest.iloc[0].to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
