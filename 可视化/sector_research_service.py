from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

BASE = Path(r"D:\database\sector_information")
REPORTS = BASE / "reports"
STAGING_PREVIEW_REPORTS = {
    "881140.THS": BASE / "_staging" / "batch_20260722_rerun5" / "881140.THS" / "report.json",
    "881121.THS": BASE / "_staging" / "batch_20260722_rerun5" / "881121.THS" / "report_candidate.json",
    "881105.THS": BASE / "_staging" / "pilot8_20260722_wave1" / "881105.THS" / "report_candidate.json",
    "881155.THS": BASE / "_staging" / "pilot8_20260722_wave1" / "881155.THS" / "report_candidate.json",
    "882030.THS": BASE / "_staging" / "pilot8_20260722_wave1" / "882030.THS" / "report_candidate.json",
    "885699.THS": BASE / "_staging" / "pilot8_20260722_wave1" / "885699.THS" / "report_candidate.json",
    "881160.THS": BASE / "_staging" / "pilot8_20260722_wave2" / "881160.THS" / "report_candidate.json",
    "885842.THS": BASE / "_staging" / "pilot8_20260722_wave2" / "885842.THS" / "report_candidate.json",
    "886069.THS": BASE / "_staging" / "pilot8_20260722_wave2" / "886069.THS" / "report_candidate.json",
    "886110.THS": BASE / "_staging" / "pilot8_20260722_wave2" / "886110.THS" / "report_candidate.json",
}


def _read(name: str, limit: int = 10000) -> list[dict[str, Any]]:
    path = BASE / name / "analysis_date=*" / "part-*.parquet"
    if not path.parent.parent.exists():
        return []
    query = "select * from read_parquet(?, hive_partitioning=true, union_by_name=true) order by analysis_date desc limit ?"
    rows = duckdb.sql(query, params=[str(path), limit]).fetchall()
    cols = duckdb.sql(query, params=[str(path), 1]).columns
    return [dict(zip(cols, row)) for row in rows]


def _jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _decode_json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return _jsonable(value)
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _read_companion_json(directory: Path, name: str, default: Any) -> Any:
    path = directory / name
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _read_companion_parquet(directory: Path, name: str) -> list[dict[str, Any]]:
    path = directory / name
    if not path.is_file():
        return []
    try:
        relation = duckdb.read_parquet(str(path))
        columns = relation.columns
        return [
            {key: _decode_json_value(value) for key, value in zip(columns, row)}
            for row in relation.fetchall()
        ]
    except (duckdb.Error, OSError):
        return []


def _companion_rows(directory: Path, stem: str) -> list[dict[str, Any]]:
    rows = _read_companion_json(directory, f"{stem}.json", [])
    if isinstance(rows, list) and rows:
        return [{key: _decode_json_value(value) for key, value in row.items()} for row in rows if isinstance(row, dict)]
    return _read_companion_parquet(directory, f"{stem}.parquet")


def _confidence_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return {"low": 0.35, "medium": 0.6, "high": 0.85}.get(value.lower(), value)


def _normalize_facets(value: Any) -> dict[str, list[str]]:
    if isinstance(value, dict):
        return {
            str(key): [str(item) for item in (items if isinstance(items, list) else [items]) if item not in (None, "")]
            for key, items in value.items()
            if items not in (None, "", [], {})
        }
    if isinstance(value, list):
        # Early formal reports stored unkeyed tags. Keep them visible under the least
        # assumptive standard facet instead of inventing more specific semantics.
        return {"industry_scope": [str(item) for item in value if item not in (None, "")]}
    if value not in (None, ""):
        return {"industry_scope": [str(value)]}
    return {}


def _normalize_evidence_category_statuses(value: Any) -> dict[str, dict[str, Any]]:
    if isinstance(value, list):
        normalized = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            key = item.get("source_category") or item.get("source_type")
            if not key:
                continue
            normalized[str(key)] = {
                field: _decode_json_value(field_value)
                for field, field_value in item.items()
                if field not in {"source_category", "source_type"}
            }
        return normalized
    if isinstance(value, dict):
        return {
            str(key): (dict(item) if isinstance(item, dict) else {"status": item})
            for key, item in value.items()
        }
    return {}


def _adapter_assessment(directory: Path) -> dict[str, Any]:
    payload = _read_companion_json(directory, "assessment.json", {})
    if not isinstance(payload, dict):
        return {}
    assessments = payload.get("assessments")
    if not isinstance(assessments, list):
        return {}
    return next(
        (
            item
            for item in assessments
            if isinstance(item, dict) and item.get("assessment_type") == "object_adapter"
        ),
        {},
    )


def _normalize_dimension_scores(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = payload.get("dimension_scores") or payload.get("assessment", {}).get("dimension_scores") or {}
    items = raw.items() if isinstance(raw, dict) else (
        (str(item.get("dimension") or item.get("name") or ""), item)
        for item in raw
        if isinstance(item, dict)
    )
    normalized = {}
    for key, value in items:
        if not key:
            continue
        key = "risk" if key == "risk_pressure" else key
        item = dict(value) if isinstance(value, dict) else {"score": value}
        item["score"] = item.get("score", item.get("final_score", item.get("rule_score")))
        item["confidence"] = _confidence_value(item.get("confidence"))
        item["explanation"] = item.get("explanation") or item.get("reason") or "未提供"
        normalized[key] = item
    return normalized


def _normalize_report_payload(payload: dict[str, Any], path: Path) -> dict[str, Any]:
    report = dict(payload)
    directory = path.parent
    assessment = report.get("assessment") if isinstance(report.get("assessment"), dict) else {}

    report["sector_code"] = report.get("sector_code") or report.get("object_code")
    report["sector_name"] = report.get("sector_name") or report.get("object_name") or report.get("sector_code")
    report["overall_score"] = report.get("overall_score", assessment.get("overall_score"))
    report["overall_formula"] = (
        report.get("overall_formula")
        or report.get("overall_score_formula")
        or assessment.get("overall_formula")
    )
    report["overall_explanation"] = report.get("overall_explanation") or report.get("core_conclusion") or assessment.get("verdict")
    report["verdict"] = report.get("verdict") or report.get("core_conclusion") or assessment.get("verdict")
    report["state_regime"] = report.get("state_regime")
    report["dimension_scores"] = _normalize_dimension_scores(report)
    adapter_assessment = _adapter_assessment(directory)
    report["analysis_archetype"] = (
        report.get("analysis_archetype")
        or report.get("sector_adapter")
        or adapter_assessment.get("value")
    )
    report["analysis_archetype_version"] = report.get("analysis_archetype_version")
    report["classification_facets"] = _normalize_facets(
        report.get("classification_facets", report.get("facets"))
    )
    report["classification_confidence"] = _confidence_value(
        report.get(
            "classification_confidence",
            report.get("analysis_archetype_confidence", adapter_assessment.get("confidence")),
        )
    )
    report["type_review_status"] = report.get("type_review_status")
    report["classification_reason"] = report.get("classification_reason") or adapter_assessment.get("reason")
    report["boundary"] = report.get("boundary") if isinstance(report.get("boundary"), dict) else {}
    report["evidence_category_statuses"] = _normalize_evidence_category_statuses(
        report.get("evidence_category_statuses")
        or report.get("source_category_statuses")
        or report.get("source_status")
    )

    research_questions = report.get("research_questions")
    if not isinstance(research_questions, list):
        research_questions = []
    if not research_questions:
        research_questions = [
            row["question"]
            for row in _companion_rows(directory, "research_tasks")
            if isinstance(row.get("question"), str) and row["question"].strip()
        ]
    report["research_questions"] = research_questions
    report["unconfirmed_items"] = (
        report.get("unconfirmed_items") if isinstance(report.get("unconfirmed_items"), list) else []
    )

    objective_metrics = report.get("objective_metrics")
    if not isinstance(objective_metrics, dict) or not objective_metrics:
        objective_metrics = _read_companion_json(directory, "objective_metrics.json", {})
    report["objective_metrics"] = objective_metrics if isinstance(objective_metrics, dict) else {}

    evidence = report.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        evidence = _companion_rows(directory, "evidence")
    report["evidence"] = [
        {
            **item,
            "dimensions": _decode_json_value(item.get("dimensions", item.get("linked_dimensions", []))),
            "linked_dimensions": _decode_json_value(item.get("linked_dimensions", item.get("dimensions", []))),
        }
        for item in evidence
        if isinstance(item, dict)
    ]

    search_logs = report.get("search_logs")
    if not isinstance(search_logs, list) or not search_logs:
        search_logs = _companion_rows(directory, "search_logs")
    report["search_logs"] = [
        {
            **item,
            **{
                key: _decode_json_value(item.get(key, []))
                for key in ("read", "accepted", "rejected", "conflicts")
            },
        }
        for item in search_logs
        if isinstance(item, dict)
    ]

    normalized_claims = []
    for raw_claim in report.get("claims") or []:
        if not isinstance(raw_claim, dict):
            continue
        claim = dict(raw_claim)
        claim["claim_text"] = claim.get("claim_text") or claim.get("claim") or "未提供"
        claim["supporting_evidence_ids"] = _decode_json_value(
            claim.get("supporting_evidence_ids", claim.get("evidence_ids", []))
        )
        claim["confidence"] = _confidence_value(claim.get("confidence"))
        normalized_claims.append(claim)
    report["claims"] = normalized_claims

    normalized_forecasts = []
    for raw_forecast in report.get("forecasts") or []:
        if not isinstance(raw_forecast, dict):
            continue
        forecast = dict(raw_forecast)
        forecast["horizon_trading_days"] = forecast.get("horizon_trading_days", forecast.get("horizon_trade_days"))
        if not isinstance(forecast.get("return_range_pct"), list):
            low = forecast.get("return_range_low_pct", forecast.get("expected_return_low_pct"))
            high = forecast.get("return_range_high_pct", forecast.get("expected_return_high_pct"))
            forecast["return_range_pct"] = [low, high] if low is not None and high is not None else []
        if forecast.get("up_probability") is None and forecast.get("up_probability_pct") is not None:
            forecast["up_probability"] = forecast["up_probability_pct"] / 100
        forecast["confidence"] = _confidence_value(forecast.get("confidence", forecast.get("forecast_confidence")))
        invalidation = forecast.get("invalidation_conditions", forecast.get("invalidation", []))
        forecast["invalidation_conditions"] = invalidation if isinstance(invalidation, list) else [invalidation]
        normalized_forecasts.append(forecast)
    report["forecasts"] = normalized_forecasts

    publication = report.get("publication") if isinstance(report.get("publication"), dict) else {}
    if not publication.get("status"):
        publication["status"] = report.get("publication_status") or report.get("status") or assessment.get("publication_status")
    publication.setdefault("officially_published", False)
    report["publication"] = publication
    return report


def _formal_report_paths(sector_code: str, analysis_date: str | None = None) -> list[Path]:
    paths = []
    for path in REPORTS.glob(f"analysis_date=*/{sector_code}__*.json"):
        if path.name.endswith("__audit.json"):
            continue
        if analysis_date and path.parent.name != f"analysis_date={analysis_date}":
            continue
        paths.append(path)
    return paths


def list_entities(limit: int = 600) -> dict[str, Any]:
    rows = _read("assessments", limit)
    entities = {}
    for row in rows:
        code = str(row.get("sector_code") or "")
        formal_paths = _formal_report_paths(code) if code else []
        if not formal_paths:
            continue
        formal_path = max(formal_paths, key=lambda item: item.stat().st_mtime)
        try:
            formal_payload = json.loads(formal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        formal_payload = _normalize_report_payload(formal_payload, formal_path)
        row["classification_facets"] = json.loads(row.pop("classification_facets_json", "{}"))
        row["sector_name"] = formal_payload.get("sector_name") or row.get("sector_name") or code
        row["analysis_date"] = formal_payload.get("analysis_date") or row.get("analysis_date")
        row["report_stage"] = "formal"
        row["publication_status"] = formal_payload.get("publication", {}).get("status")
        for key, value in list(row.items()):
            row[key] = _jsonable(value)
        entities[code] = row
    for code, path in STAGING_PREVIEW_REPORTS.items():
        if _formal_report_paths(code) or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload = _normalize_report_payload(payload, path)
        if str(payload.get("sector_code")) != code:
            continue
        entities[code] = {
            **entities.get(code, {}),
            "sector_code": code,
            "sector_name": payload.get("sector_name") or code,
            "analysis_date": payload.get("analysis_date"),
            "report_stage": "staging",
            "publication_status": payload.get("publication", {}).get("status"),
        }
    data = list(entities.values())[:limit]
    return {"api_version": "sector_api.v1", "data": data, "meta": {"count": len(data)}}


def dashboard(sector_code: str) -> dict[str, Any]:
    rows = [row for row in _read("assessments", 600) if str(row.get("sector_code")) == sector_code]
    if not rows:
        return {"api_version": "sector_api.v1", "data": None, "error": {"code": "NOT_FOUND", "message": "未找到板块"}}
    dims = [row for row in _read("dimension_scores", 10000) if str(row.get("sector_code")) == sector_code]
    row = rows[0]
    row["classification_facets"] = json.loads(row.pop("classification_facets_json", "{}"))
    row["dimension_scores"] = dims
    return {"api_version": "sector_api.v1", "data": {k: _jsonable(v) for k, v in row.items()}}


def report(sector_code: str, analysis_date: str | None = None) -> dict[str, Any]:
    """读取完整的模型研究 JSON，供统一看板使用。"""
    if not sector_code:
        return {"api_version": "sector_report.v1", "data": None, "error": {"code": "INVALID_ARGUMENT", "message": "缺少sector_code"}}
    candidates = _formal_report_paths(sector_code, analysis_date)
    stage = "formal"
    if candidates:
        path = max(candidates, key=lambda item: item.stat().st_mtime)
    else:
        path = STAGING_PREVIEW_REPORTS.get(sector_code)
        stage = "staging"
        if path is None or not path.is_file():
            return {"api_version": "sector_report.v1", "data": None, "error": {"code": "NOT_FOUND", "message": f"未找到板块研究报告: {sector_code}"}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"api_version": "sector_report.v1", "data": None, "error": {"code": "READ_FAILED", "message": str(exc)}}
    payload = _normalize_report_payload(payload, path)
    if str(payload.get("sector_code")) != sector_code:
        return {"api_version": "sector_report.v1", "data": None, "error": {"code": "READ_FAILED", "message": f"报告代码与请求不一致: {sector_code}"}}
    if analysis_date and str(payload.get("analysis_date")) != analysis_date:
        return {"api_version": "sector_report.v1", "data": None, "error": {"code": "NOT_FOUND", "message": f"未找到指定日期的板块研究报告: {sector_code} / {analysis_date}"}}
    payload["_report_path"] = str(path)
    payload["_report_stage"] = stage
    return {"api_version": "sector_report.v1", "data": payload, "meta": {"path": str(path), "stage": stage}}
