import json
from pathlib import Path


REPORT = Path(
    r"D:\database\sector_information\_staging\batch_20260722_rerun5"
    r"\881121.THS\report_candidate.json"
)


def test_semiconductor_report_contains_full_objective_metric_contract() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    metrics = report["objective_metrics"]

    required = {
        "source_member_count",
        "eligible_member_count",
        "excluded_bj_count",
        "excluded_bj_codes",
        "eligible_codes",
        "index_metrics",
        "member_breadth",
        "turnover",
        "member_aggregates",
        "same_period_yoy_rows",
        "member_market_rows",
        "member_valuation_rows",
    }
    assert required <= metrics.keys()
    assert len(metrics["member_market_rows"]) == metrics["eligible_member_count"]
    assert len(metrics["same_period_yoy_rows"]) == metrics["eligible_member_count"]
    assert metrics["member_aggregates"]["financial_coverage_count"] > 0


def test_semiconductor_report_uses_canonical_percentage_fields() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    metrics = report["objective_metrics"]

    for field in (
        "return_5d_pct",
        "return_20d_pct",
        "return_60d_pct",
        "max_drawdown_60d_pct",
        "volatility_20d_annualized_pct",
        "close_vs_ma20_pct",
    ):
        assert field in metrics["index_metrics"]

    for field in ("above_ma20_pct", "above_ma60_pct", "positive_return_20d_pct"):
        assert field in metrics["member_breadth"]
