from __future__ import annotations

import unittest

import pandas as pd

from models.configurable_signal_rules.data import (
    _combine_rule_columns,
    factor_rule_to_payload,
    normalize_rules,
)


class FactorRuleFilterModesTest(unittest.TestCase):
    def test_legacy_threshold_rule_keeps_greater_equal_behavior(self) -> None:
        rule = normalize_rules([{"factor": "动量", "threshold": 1}], "buy")[0]
        frame = pd.DataFrame({rule.column: [0.5, 1.0, 1.5]})

        self.assertEqual(
            _combine_rule_columns(frame, [rule], "and").tolist(),
            [False, True, True],
        )

    def test_value_mode_supports_comparison_and_closed_interval(self) -> None:
        cases = [
            ({"operator": "gt", "value": 1}, [False, False, True]),
            ({"operator": "gte", "value": 1}, [False, True, True]),
            ({"operator": "lt", "value": 1}, [True, False, False]),
            ({"operator": "lte", "value": 1}, [True, True, False]),
            ({"operator": "eq", "value": 1}, [False, True, False]),
            ({"operator": "ne", "value": 1}, [True, False, True]),
            ({"operator": "between", "min": 1, "max": 2}, [False, True, True]),
        ]
        for extra, expected in cases:
            with self.subTest(operator=extra["operator"]):
                raw = {"factor": "动量", "mode": "value", **extra}
                rule = normalize_rules([raw], "buy")[0]
                frame = pd.DataFrame({rule.column: [0.5, 1.0, 1.5]})
                self.assertEqual(
                    _combine_rule_columns(frame, [rule], "and").tolist(),
                    expected,
                )

    def test_cross_section_top_percent_is_daily_and_includes_boundary_ties(self) -> None:
        rule = normalize_rules(
            [{"factor": "动量", "mode": "cross_section_percentile", "direction": "top", "percentile": 0.50}],
            "buy",
        )[0]
        frame = pd.DataFrame(
            {
                "time": pd.to_datetime(["2026-01-02"] * 5 + ["2026-01-03"] * 4),
                "htsc_code": ["A", "B", "C", "D", "E", "A", "B", "C", "D"],
                rule.column: [10, 9, 9, 2, None, 1, 2, 3, 4],
            }
        )

        self.assertEqual(
            _combine_rule_columns(frame, [rule], "and").tolist(),
            [True, True, True, False, False, False, False, True, True],
        )

    def test_cross_section_bottom_percent_keeps_at_least_one_stock(self) -> None:
        rule = normalize_rules(
            [{"factor": "动量", "mode": "cross_section_percentile", "direction": "bottom", "percentile": 0.05}],
            "sell",
        )[0]
        frame = pd.DataFrame(
            {
                "time": pd.to_datetime(["2026-01-02"] * 3),
                "htsc_code": ["A", "B", "C"],
                rule.column: [3, 1, 2],
            }
        )

        self.assertEqual(
            _combine_rule_columns(frame, [rule], "and").tolist(),
            [False, True, False],
        )

    def test_cross_section_percentile_range_uses_high_to_low_rank_position(self) -> None:
        rule = normalize_rules(
            [{
                "factor": "动量",
                "mode": "cross_section_percentile",
                "direction": "range",
                "min_percentile": 0.20,
                "max_percentile": 0.40,
            }],
            "buy",
        )[0]
        frame = pd.DataFrame(
            {
                "time": pd.to_datetime(["2026-01-02"] * 5),
                "htsc_code": ["A", "B", "C", "D", "E"],
                rule.column: [5, 4, 3, 2, 1],
            }
        )

        self.assertEqual(
            _combine_rule_columns(frame, [rule], "and").tolist(),
            [False, True, True, False, False],
        )

    def test_cross_section_top_rank_keeps_exact_count_with_stable_ties(self) -> None:
        rule = normalize_rules(
            [{
                "factor": "momentum",
                "mode": "cross_section_percentile",
                "rank_unit": "rank",
                "direction": "top",
                "rank": 2,
            }],
            "buy",
        )[0]
        frame = pd.DataFrame(
            {
                "time": pd.to_datetime(["2026-01-02"] * 5),
                "htsc_code": ["A", "B", "C", "D", "E"],
                rule.column: [10, 9, 9, 2, None],
            }
        )

        self.assertEqual(
            _combine_rule_columns(frame, [rule], "and").tolist(),
            [True, True, False, False, False],
        )

    def test_cross_section_bottom_rank_keeps_exact_count(self) -> None:
        rule = normalize_rules(
            [{
                "factor": "momentum",
                "mode": "cross_section_percentile",
                "rank_unit": "rank",
                "direction": "bottom",
                "rank": 2,
            }],
            "sell",
        )[0]
        frame = pd.DataFrame(
            {
                "time": pd.to_datetime(["2026-01-02"] * 4),
                "htsc_code": ["A", "B", "C", "D"],
                rule.column: [4, 1, 2, 3],
            }
        )

        self.assertEqual(
            _combine_rule_columns(frame, [rule], "and").tolist(),
            [False, True, True, False],
        )

    def test_cross_section_rank_range_uses_inclusive_one_based_positions(self) -> None:
        rule = normalize_rules(
            [{
                "factor": "momentum",
                "mode": "cross_section_percentile",
                "rank_unit": "rank",
                "direction": "range",
                "min_rank": 2,
                "max_rank": 4,
            }],
            "buy",
        )[0]
        frame = pd.DataFrame(
            {
                "time": pd.to_datetime(["2026-01-02"] * 5),
                "htsc_code": ["A", "B", "C", "D", "E"],
                rule.column: [5, 4, 3, 2, 1],
            }
        )

        self.assertEqual(
            _combine_rule_columns(frame, [rule], "and").tolist(),
            [False, True, True, True, False],
        )
        self.assertEqual(
            factor_rule_to_payload(rule),
            {
                "factor": "momentum",
                "mode": "cross_section_percentile",
                "rank_unit": "rank",
                "direction": "range",
                "min_rank": 2,
                "max_rank": 4,
                "scope": "selected_stock_pool",
                "frequency": "daily",
            },
        )

    def test_cross_section_rank_range_allows_single_position(self) -> None:
        rule = normalize_rules(
            [{
                "factor": "momentum",
                "mode": "cross_section_percentile",
                "rank_unit": "rank",
                "direction": "range",
                "min_rank": 2,
                "max_rank": 2,
            }],
            "buy",
        )[0]
        frame = pd.DataFrame(
            {
                "time": pd.to_datetime(["2026-01-02"] * 3),
                "htsc_code": ["A", "B", "C"],
                rule.column: [3, 2, 1],
            }
        )

        self.assertEqual(
            _combine_rule_columns(frame, [rule], "and").tolist(),
            [False, True, False],
        )

    def test_cross_section_rank_requires_positive_integers(self) -> None:
        invalid_rules = [
            {"direction": "top", "rank": 1.5},
            {"direction": "top", "rank": 0},
            {"direction": "range", "min_rank": 3, "max_rank": 2},
        ]
        for extra in invalid_rules:
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError):
                    normalize_rules(
                        [{
                            "factor": "momentum",
                            "mode": "cross_section_percentile",
                            "rank_unit": "rank",
                            **extra,
                        }],
                        "buy",
                    )

    def test_rule_payload_preserves_filter_mode_for_saved_results(self) -> None:
        rule = normalize_rules(
            [{"factor": "动量", "mode": "cross_section_percentile", "direction": "top", "percentile": 0.05}],
            "buy",
        )[0]

        self.assertEqual(
            factor_rule_to_payload(rule),
            {
                "factor": "动量",
                "mode": "cross_section_percentile",
                "direction": "top",
                "percentile": 0.05,
                "scope": "selected_stock_pool",
                "frequency": "daily",
            },
        )


if __name__ == "__main__":
    unittest.main()
