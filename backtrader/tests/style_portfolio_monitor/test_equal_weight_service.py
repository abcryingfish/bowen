from datetime import date

import pandas as pd
import pytest

from models.style_portfolio_monitor.equal_weight_service import build_index_day_payloads


def test_build_index_day_payloads_separates_target_and_effective_weights() -> None:
    dates = pd.date_range("2026-01-01", periods=2, freq="D")
    result = {
        "index_dfs": {
            "high": pd.Series([100.0, 110.0], index=dates),
            "low": pd.Series([100.0, 90.0], index=dates),
        },
        "target_weights": {
            "high": {date(2026, 1, 1): {"A.SZ": 1.0}},
            "low": {date(2026, 1, 1): {"B.SZ": 1.0}},
        },
        "weights": {
            "high": {date(2026, 1, 1): {}, date(2026, 1, 2): {"A.SZ": 1.0}},
            "low": {date(2026, 1, 1): {}, date(2026, 1, 2): {"B.SZ": 1.0}},
        },
        "diagnostics": {
            "high": {date(2026, 1, 1): {"valid_count": 2, "valid_price_coverage": 1.0}, date(2026, 1, 2): {"valid_count": 2, "valid_price_coverage": 1.0}},
            "low": {date(2026, 1, 1): {"valid_count": 2, "valid_price_coverage": 1.0}, date(2026, 1, 2): {"valid_count": 2, "valid_price_coverage": 1.0}},
        },
        "signal_dates": {
            date(2026, 1, 1): date(2025, 12, 31),
            date(2026, 1, 2): date(2026, 1, 1),
        },
        "factor_coverage": {
            date(2026, 1, 1): 0.95,
            date(2026, 1, 2): 0.96,
        },
    }
    scores = pd.DataFrame([[90.0, 10.0], [90.0, 10.0]], index=dates, columns=["A.SZ", "B.SZ"])

    payloads = build_index_day_payloads(
        model_version="m-v1",
        model_id="m",
        config_hash="hash",
        result=result,
        score_frame=scores,
    )

    assert payloads[0].legs["high"].rebalanced is True
    assert payloads[0].legs["high"].weights[0]["target_weight"] == pytest.approx(1.0)
    assert payloads[0].legs["high"].weights[0]["effective_weight"] == pytest.approx(0.0)
    assert payloads[0].legs["high"].factor_coverage is None
    assert payloads[1].legs["high"].weights[0]["effective_weight"] == pytest.approx(1.0)
    assert not hasattr(payloads[1].legs["high"], "net_index_value")
    assert not hasattr(payloads[1].legs["high"], "transaction_cost")
    assert payloads[1].legs["high"].signal_date == date(2026, 1, 1)
    assert payloads[1].legs["high"].factor_coverage == pytest.approx(0.95)


def test_build_index_day_payloads_keeps_target_rank_and_marks_old_effective_codes() -> None:
    day = pd.Timestamp("2026-01-01")
    result = {
        "index_dfs": {"high": pd.Series([100.0], index=[day]), "low": pd.Series([100.0], index=[day])},
        "target_weights": {"high": {date(2026, 1, 1): {"A.SZ": 1.0}}, "low": {date(2026, 1, 1): {"A.SZ": 1.0}}},
        "weights": {"high": {date(2026, 1, 1): {"B.SZ": 1.0}}, "low": {date(2026, 1, 1): {"B.SZ": 1.0}}},
        "diagnostics": {"high": {date(2026, 1, 1): {}}, "low": {date(2026, 1, 1): {}}},
        "signal_dates": {},
    }
    scores = pd.DataFrame([[90.0, 80.0]], index=[day], columns=["A.SZ", "B.SZ"])

    payloads = build_index_day_payloads(model_version="m-v1", model_id="m", config_hash="hash", result=result, score_frame=scores)
    by_code = {item["htsc_code"]: item for item in payloads[0].legs["high"].weights}

    assert by_code["A.SZ"]["rank"] == 1
    assert by_code["B.SZ"]["rank"] is None
