from pathlib import Path


TARGET = Path(__file__).parent / "可视化" / "多维度分析" / "index.html"


def test_dashboard_marks_staging_reports_as_candidates() -> None:
    text = TARGET.read_text(encoding="utf-8")

    assert "_report_stage" in text
    assert "staging候选" in text
    assert "正式报告" in text
    assert "此报告仍在 staging" in text


def test_dashboard_adapts_both_research_report_field_variants() -> None:
    text = TARGET.read_text(encoding="utf-8")

    assert "item.evidence_status || item.status" in text
    assert "item.linked_dimensions || item.dimensions" in text
    assert "item.evidence_quality ?? item.quality_score" in text
    assert "item.limitations || item.limitation" in text


def test_dashboard_preserves_two_decimal_overall_scores() -> None:
    text = TARGET.read_text(encoding="utf-8")

    assert "const scoreFmt" in text
    assert "scoreFmt(report.overall_score)" in text


def test_dashboard_normalizes_objective_metric_field_and_unit_variants() -> None:
    text = TARGET.read_text(encoding="utf-8")

    assert "const percentFrom" in text
    assert 'percentFrom(idx, "return_5d_pct", "return_5d")' in text
    assert 'percentFrom(idx, "max_drawdown_60d_pct", "max_drawdown_60d")' in text
    assert 'percentFrom(breadth, "above_ma20_pct", "above_ma20_ratio")' in text
    assert 'percentFrom(breadth, "positive_return_20d_pct", "positive_return_20d_ratio")' in text
    assert "idx.data_cutoff || m.market_data_cutoff || report.market_data_cutoff" in text
