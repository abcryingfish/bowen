from __future__ import annotations

import importlib
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest


VISUAL_DIR = Path(__file__).parent / "可视化"
if str(VISUAL_DIR) not in sys.path:
    sys.path.insert(0, str(VISUAL_DIR))


@pytest.fixture()
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = importlib.import_module("sector_research_service")
    base = tmp_path / "sector_information"
    reports = base / "reports"
    assessment_dir = base / "assessments" / "analysis_date=2026-07-15"
    assessment_dir.mkdir(parents=True)
    reports.mkdir(parents=True)

    pd.DataFrame(
        [
            {
                "sector_code": code,
                "sector_name": name,
                "analysis_date": date(2026, 7, 15),
                "classification_facets_json": "{}",
            }
            for code, name in (
                ("885462.THS", "乳业"),
                ("881140.THS", "化学制药"),
                ("881121.THS", "半导体"),
                ("999998.THS", "无完整报告"),
            )
        ]
    ).to_parquet(assessment_dir / "part-000.parquet", index=False)

    formal_dir = reports / "analysis_date=2026-07-21"
    formal_dir.mkdir(parents=True)
    (formal_dir / "885462.THS__dairy.json").write_text(
        json.dumps(
            {"sector_code": "885462.THS", "sector_name": "乳业", "analysis_date": "2026-07-21"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    preview_files = {}
    for code, name, filename in (
        ("881140.THS", "化学制药", "report.json"),
        ("881121.THS", "半导体", "report_candidate.json"),
    ):
        path = base / "_staging" / "batch" / code / filename
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "sector_code": code,
                    "sector_name": name,
                    "analysis_date": "2026-07-22",
                    "publication": {"status": "ready_for_serial_audit", "officially_published": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        preview_files[code] = path

    monkeypatch.setattr(module, "BASE", base)
    monkeypatch.setattr(module, "REPORTS", reports)
    monkeypatch.setattr(module, "STAGING_PREVIEW_REPORTS", preview_files, raising=False)
    return module


def test_list_entities_merges_allowlisted_staging_previews(service) -> None:
    payload = service.list_entities()
    rows = {row["sector_code"]: row for row in payload["data"]}

    json.dumps(payload, ensure_ascii=False)
    assert set(rows) == {"885462.THS", "881140.THS", "881121.THS"}
    assert rows["885462.THS"]["report_stage"] == "formal"
    assert rows["885462.THS"]["analysis_date"] == "2026-07-21"
    assert rows["881140.THS"]["report_stage"] == "staging"
    assert rows["881121.THS"]["report_stage"] == "staging"


@pytest.mark.parametrize("code", ["881140.THS", "881121.THS"])
def test_report_reads_only_allowlisted_staging_preview(service, code: str) -> None:
    payload = service.report(code)

    assert payload["data"]["sector_code"] == code
    assert payload["data"]["_report_stage"] == "staging"
    assert payload["meta"]["stage"] == "staging"


def test_report_does_not_scan_unlisted_staging_directories(service) -> None:
    hidden = service.BASE / "_staging" / "batch" / "999999.THS" / "report.json"
    hidden.parent.mkdir(parents=True)
    hidden.write_text('{"sector_code":"999999.THS"}', encoding="utf-8")

    payload = service.report("999999.THS")

    assert payload["data"] is None
    assert payload["error"]["code"] == "NOT_FOUND"


def test_pilot8_staging_previews_are_allowlisted() -> None:
    module = importlib.import_module("sector_research_service")

    assert {
        "881105.THS",
        "881155.THS",
        "882030.THS",
        "885699.THS",
        "881160.THS",
        "885842.THS",
        "886069.THS",
        "886110.THS",
    }.issubset(module.STAGING_PREVIEW_REPORTS)


def test_report_normalizes_compact_staging_candidate(service) -> None:
    code = "886110.THS"
    directory = service.BASE / "_staging" / "pilot" / code
    directory.mkdir(parents=True)
    report_path = directory / "report_candidate.json"
    report_path.write_text(
        json.dumps(
            {
                "object_code": code,
                "object_name": "2026中报预增",
                "analysis_date": "2026-07-22",
                "latest_complete_trade_date": "2026-07-21",
                "market_data_cutoff": "2026-07-21",
                "status": "audit_passed_pending_publish",
                "overall_score": 5.185,
                "dimension_scores": [
                    {"dimension": "policy", "score": 5.5, "reason": "披露制度提高透明度"},
                    {"dimension": "risk_pressure", "score": 7.4, "reason": "事件样本波动较高"},
                ],
                "forecasts": [
                    {
                        "horizon_trade_days": 5,
                        "return_range_low_pct": -5.0,
                        "return_range_high_pct": 3.0,
                        "up_probability_pct": 42.0,
                        "confidence": "low",
                        "invalidation": "板块广度快速修复",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (directory / "objective_metrics.json").write_text(
        json.dumps({"eligible_member_count": 445, "excluded_bj_count": 3}, ensure_ascii=False),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "evidence_id": "E01",
                "source_type": "news",
                "title": "板块定义",
                "dimensions": '["fundamental", "risk"]',
                "status": "valid",
            }
        ]
    ).to_parquet(directory / "evidence.parquet", index=False)
    pd.DataFrame(
        [
            {
                "round_id": "R01",
                "query": "板块定义",
                "accepted": '["E01"]',
                "rejected": "[]",
            }
        ]
    ).to_parquet(directory / "search_logs.parquet", index=False)
    service.STAGING_PREVIEW_REPORTS[code] = report_path

    payload = service.report(code)["data"]

    assert payload["sector_code"] == code
    assert payload["sector_name"] == "2026中报预增"
    assert payload["publication"]["status"] == "audit_passed_pending_publish"
    assert payload["objective_metrics"]["eligible_member_count"] == 445
    assert payload["dimension_scores"]["policy"]["explanation"] == "披露制度提高透明度"
    assert payload["dimension_scores"]["risk"]["score"] == 7.4
    assert payload["evidence"][0]["dimensions"] == ["fundamental", "risk"]
    assert payload["search_logs"][0]["accepted"] == ["E01"]
    assert payload["forecasts"][0]["horizon_trading_days"] == 5
    assert payload["forecasts"][0]["return_range_pct"] == [-5.0, 3.0]
    assert payload["forecasts"][0]["up_probability"] == pytest.approx(0.42)
    assert payload["forecasts"][0]["invalidation_conditions"] == ["板块广度快速修复"]


def test_report_normalizes_canonical_semantic_fields_from_legacy_candidate(service) -> None:
    code = "886110.THS"
    directory = service.BASE / "_staging" / "pilot" / code
    directory.mkdir(parents=True)
    report_path = directory / "report_candidate.json"
    report_path.write_text(
        json.dumps(
            {
                "sector_code": code,
                "sector_name": "2026中报预增",
                "sector_adapter": "event_driven",
                "facets": {
                    "event_state": ["earnings_preannouncement"],
                    "universe_role": ["dynamic_positive_earnings_sample"],
                },
                "source_status": [
                    {"source_category": "policy", "status": "valid", "detail": "披露规则可核验"},
                    {
                        "source_category": "industry_data",
                        "status": "not_applicable",
                        "detail": "跨行业动态事件池不适用统一产业指标",
                    },
                ],
                "overall_score_formula": "weighted_formula",
                "analysis_date": "2026-07-22",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (directory / "assessment.json").write_text(
        json.dumps(
            {
                "assessments": [
                    {
                        "assessment_type": "object_adapter",
                        "value": "event_driven",
                        "reason": "成分由中报预告条件动态筛选",
                        "confidence": "high",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {"task_id": "T01", "question": "该对象是否为动态事件样本池？", "status": "closed"},
            {"task_id": "T02", "question": "预增是否由主业驱动？", "status": "closed"},
        ]
    ).to_parquet(directory / "research_tasks.parquet", index=False)
    service.STAGING_PREVIEW_REPORTS[code] = report_path

    payload = service.report(code)["data"]

    assert payload["analysis_archetype"] == "event_driven"
    assert payload["classification_facets"] == {
        "event_state": ["earnings_preannouncement"],
        "universe_role": ["dynamic_positive_earnings_sample"],
    }
    assert payload["classification_confidence"] == pytest.approx(0.85)
    assert payload["classification_reason"] == "成分由中报预告条件动态筛选"
    assert payload["research_questions"] == ["该对象是否为动态事件样本池？", "预增是否由主业驱动？"]
    assert payload["evidence_category_statuses"]["policy"] == {
        "status": "valid",
        "detail": "披露规则可核验",
    }
    assert payload["evidence_category_statuses"]["industry_data"]["status"] == "not_applicable"
    assert payload["overall_formula"] == "weighted_formula"
    assert payload["verdict"] is None
    assert payload["state_regime"] is None
    assert payload["unconfirmed_items"] == []


def test_deep_research_skill_requires_canonical_report_fields() -> None:
    skill_path = Path(r"C:\Users\Administrator\.codex\skills\sector-stock-deep-research\SKILL.md")
    text = skill_path.read_text(encoding="utf-8")

    assert "标准报告字段契约" in text
    assert "新报告禁止输出兼容别名" in text
    assert "sector_adapter -> analysis_archetype" in text
    assert "source_status -> evidence_category_statuses" in text
