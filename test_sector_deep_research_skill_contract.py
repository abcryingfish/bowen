from pathlib import Path


SKILL = Path(r"C:\Users\Administrator\.codex\skills\sector-stock-deep-research\SKILL.md")


def test_skill_requires_objective_metric_normalization_and_completeness_audit() -> None:
    text = SKILL.read_text(encoding="utf-8")

    for phrase in (
        "客观指标标准契约",
        "字段归一化",
        "member_market_rows",
        "member_aggregates",
        "same_period_yoy_rows",
        "禁止把字段名不兼容误判为没有数据",
        "objective_metrics_contract_complete",
    ):
        assert phrase in text


def test_skill_requires_rolling_analysis_dates_and_freshness_gating() -> None:
    text = SKILL.read_text(encoding="utf-8")

    for phrase in (
        "滚动分析日",
        "任务启动时",
        "最新完整客观快照",
        "current",
        "7个自然日",
        "退出横向排名",
        "历史报告仍可查看",
    ):
        assert phrase in text

    assert "超过3个自然日" not in text
