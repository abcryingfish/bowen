from __future__ import annotations

from sector_type_adapter import (
    ARCHETYPE_VALUES,
    CLASSIFICATION_FACET_FIELDS,
    classify_sector,
    semantic_publish_decision,
)


def test_archetype_catalog_is_fixed_and_complete():
    assert len(ARCHETYPE_VALUES) == 12
    assert "standard_industry" in ARCHETYPE_VALUES
    assert "policy_driven" in ARCHETYPE_VALUES
    assert "general_concept" in ARCHETYPE_VALUES
    assert len(CLASSIFICATION_FACET_FIELDS) == 11


def test_881_defaults_to_standard_industry():
    result = classify_sector("881101.THS", "种植业", constituents=[])
    assert result.analysis_archetype == "standard_industry"
    assert result.review_required is False
    assert result.classification_confidence >= 0.70
    assert result.facets["industry_scope"] == ["industry"]


def test_882_defaults_to_region():
    result = classify_sector("882101.THS", "北京", constituents=[])
    assert result.analysis_archetype == "regional_basket"
    assert result.review_required is False
    assert result.facets["region_scope"] == ["regional"]


def test_policy_keyword_requires_evidence_when_auto_confirming():
    result = classify_sector("885001.THS", "国企改革", constituents=[])
    assert result.analysis_archetype == "policy_driven"
    assert result.review_required is True
    assert result.reason_code == "evidence_required"

    confirmed = classify_sector(
        "885001.THS",
        "国企改革",
        constituents=[],
        evidence=[{"evidence_id": "ev-1", "kind": "policy", "source": "国务院"}],
    )
    assert confirmed.review_required is False
    assert confirmed.facets["policy_relation"] == ["policy_driven"]


def test_ambiguous_low_confidence_sector_blocks_semantic_publish_only():
    result = classify_sector("885999.THS", "新兴主题", constituents=[])
    assert result.review_required is True
    decision = semantic_publish_decision(result)
    assert decision.publish_objective_dimensions is True
    assert decision.publish_semantic_dimensions is False
    assert decision.publish_overall is False
    assert decision.status == "needs_review"


def test_type_change_is_versioned_without_rewriting_history():
    result = classify_sector(
        "885010.THS",
        "人工智能",
        constituents=[],
        evidence=[{"evidence_id": "ev-2", "kind": "technology", "source": "工信部"}],
        previous_archetype="general_concept",
        previous_type_version=3,
    )
    assert result.analysis_archetype == "technology_growth"
    assert result.type_version == 4
    assert result.history_policy == "new_analysis_date_only"
