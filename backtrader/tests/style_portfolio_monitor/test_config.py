from datetime import date
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from models.style_portfolio_monitor.config import MODEL_DEFINITIONS, build_config_hash, is_rebalance_day


def test_model_definitions_use_exact_factor_names_and_frequencies():
    actual = [(m.model_id, m.factor_name, m.factor_key, m.rebalance_frequency) for m in MODEL_DEFINITIONS]
    assert actual == [
        ("large_cap_raw", "大市值风格评分（纯市值）", "large_cap_style_score_pure", "weekly"),
        ("small_cap_raw", "小市值风格评分（纯市值）", "small_cap_style_score_pure", "weekly"),
        ("value_raw", "价值模型综合评分", "value_model_composite_score", "monthly"),
        ("value_industry_neutral", "价值模型综合评分(行业标准化)", "value_model_composite_score_industry_normalized", "monthly"),
        ("growth_raw", "成长风格评分", "growth_style_score", "monthly"),
        ("growth_industry_neutral", "成长风格综合评分(行业标准化)", "growth_style_composite_score_industry_normalized", "monthly"),
        ("momentum_raw", "动量风格评分", "momentum_style_score", "weekly"),
        ("low_volatility_raw", "低波风格评分", "low_volatility_style_score", "monthly"),
        ("dividend_raw", "红利基础百分位", "dividend_base_percentile", "quarterly"),
        ("liquidity_raw", "流动性综合评分", "liquidity_composite_score", "weekly"),
    ]


def test_config_hash_is_stable_sha256():
    digest = build_config_hash(MODEL_DEFINITIONS[0])
    assert digest == build_config_hash(MODEL_DEFINITIONS[0])
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_rebalance_day_uses_actual_period_boundaries():
    calendar = [date(2026, 1, 30), date(2026, 2, 2), date(2026, 2, 3), date(2026, 4, 1)]
    assert is_rebalance_day(date(2026, 2, 2), date(2026, 1, 30), "weekly", calendar)
    assert is_rebalance_day(date(2026, 2, 2), date(2026, 1, 30), "monthly", calendar)
    assert not is_rebalance_day(date(2026, 2, 3), date(2026, 2, 2), "monthly", calendar)
    assert is_rebalance_day(date(2026, 4, 1), date(2026, 2, 2), "quarterly", calendar)
    assert is_rebalance_day(date(2026, 1, 30), None, "monthly", calendar)
    with pytest.raises(ValueError):
        is_rebalance_day(date(2026, 2, 2), None, "daily", calendar)
