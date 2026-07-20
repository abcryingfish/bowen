"""板块类型适配器。

该模块只负责板块语义分类和发布门槛，不计算六维评分，也不读取外部数据。
所有字符串均为 UTF-8；分类结果可直接序列化到 Parquet/JSON。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

ARCHETYPE_VALUES: tuple[str, ...] = (
    "standard_industry",
    "cyclical_resource",
    "regional_basket",
    "industry_chain_theme",
    "policy_driven",
    "technology_growth",
    "event_driven",
    "company_attribute",
    "security_status",
    "universe_sample",
    "style_strategy",
    "general_concept",
)

CLASSIFICATION_FACET_FIELDS: tuple[str, ...] = (
    "industry_scope",
    "region_scope",
    "value_chain_position",
    "driver",
    "technology_stage",
    "policy_relation",
    "ownership",
    "security_status",
    "style",
    "event_state",
    "universe_role",
)

_HIGH_RISK_ARCHETYPES = {"policy_driven", "event_driven", "security_status"}


@dataclass(frozen=True)
class SemanticPublishDecision:
    publish_objective_dimensions: bool
    publish_semantic_dimensions: bool
    publish_overall: bool
    status: str


@dataclass(frozen=True)
class SectorTypeResult:
    analysis_archetype: str
    facets: dict[str, list[str]]
    classification_confidence: float
    runner_up_confidence: float
    review_required: bool
    reason_code: str | None
    type_version: int
    history_policy: str
    evidence_ids: tuple[str, ...]

    def to_record(self) -> dict[str, Any]:
        return {
            "analysis_archetype": self.analysis_archetype,
            "classification_facets": self.facets,
            "classification_confidence": self.classification_confidence,
            "runner_up_confidence": self.runner_up_confidence,
            "review_required": self.review_required,
            "classification_reason_code": self.reason_code,
            "analysis_archetype_version": self.type_version,
            "type_history_policy": self.history_policy,
            "classification_evidence_ids": list(self.evidence_ids),
        }


def _empty_facets() -> dict[str, list[str]]:
    return {field: [] for field in CLASSIFICATION_FACET_FIELDS}


def _evidence_ids(evidence: Sequence[Mapping[str, Any]] | None) -> tuple[str, ...]:
    return tuple(
        str(item["evidence_id"])
        for item in (evidence or [])
        if item.get("evidence_id")
    )


def _keyword_candidate(name: str) -> tuple[str, float, float, dict[str, list[str]]]:
    text = name.strip().lower()
    facets = _empty_facets()
    rules = (
        (("st", "退市", "风险警示"), "security_status", 0.86, 0.18, "security_status", "security_status"),
        (("改革", "监管", "政策", "国企"), "policy_driven", 0.74, 0.60, "policy_relation", "policy_driven"),
        (("人工智能", "芯片", "半导体", "机器人", "算力", "量子", "区块链"), "technology_growth", 0.76, 0.58, "technology_stage", "technology_growth"),
        (("芬太尼",), "industry_chain_theme", 0.74, 0.58, "value_chain_position", "product_theme"),
        (("涨价", "重组", "并购", "事件"), "event_driven", 0.72, 0.61, "event_state", "event_driven"),
        (("资源", "煤炭", "有色", "石油", "钢铁"), "cyclical_resource", 0.73, 0.57, "industry_scope", "resource"),
        (("高股息", "红利", "价值", "成长", "低波"), "style_strategy", 0.73, 0.59, "style", "style_strategy"),
    )
    for keywords, archetype, confidence, runner_up, field, facet in rules:
        if any(keyword in text for keyword in keywords):
            facets[field] = [facet]
            if archetype == "policy_driven":
                facets["driver"] = ["policy"]
            return archetype, confidence, runner_up, facets
    return "general_concept", 0.55, 0.50, facets


def classify_sector(
    source_code: str,
    name: str,
    constituents: Sequence[Mapping[str, Any]] | Sequence[str],
    *,
    evidence: Sequence[Mapping[str, Any]] | None = None,
    previous_archetype: str | None = None,
    previous_type_version: int | None = None,
) -> SectorTypeResult:
    """按来源前缀和名称生成分类结果；不修改历史记录。"""
    if not source_code or not name:
        raise ValueError("source_code and name are required")

    prefix = source_code.split(".", 1)[0][:3]
    facets = _empty_facets()
    if prefix == "881":
        archetype, confidence, runner_up = "standard_industry", 0.99, 0.05
        facets["industry_scope"] = ["industry"]
    elif prefix == "882":
        archetype, confidence, runner_up = "regional_basket", 0.99, 0.05
        facets["region_scope"] = ["regional"]
    else:
        archetype, confidence, runner_up, facets = _keyword_candidate(name)

    ids = _evidence_ids(evidence)
    if archetype == "general_concept" and ids and len(constituents) >= 4:
        confidence, runner_up = 0.72, 0.60
    reason_code: str | None = None
    review_required = confidence < 0.70 or confidence - runner_up < 0.10
    if archetype in _HIGH_RISK_ARCHETYPES and not ids:
        review_required = True
        reason_code = "evidence_required"
    elif review_required:
        reason_code = "classification_threshold_not_met"

    type_version = 1 if previous_type_version is None else previous_type_version
    if previous_archetype is not None and previous_archetype != archetype:
        type_version += 1

    return SectorTypeResult(
        analysis_archetype=archetype,
        facets=facets,
        classification_confidence=confidence,
        runner_up_confidence=runner_up,
        review_required=review_required,
        reason_code=reason_code,
        type_version=type_version,
        history_policy="new_analysis_date_only",
        evidence_ids=ids,
    )


def semantic_publish_decision(result: SectorTypeResult) -> SemanticPublishDecision:
    if result.review_required:
        return SemanticPublishDecision(True, False, False, "needs_review")
    return SemanticPublishDecision(True, True, True, "ready")
