from __future__ import annotations

import pandas as pd
import pytest

from models.ths_monthly_threshold.data import normalize_codes, normalize_rules
from models.ths_monthly_threshold.runner import create_ths_cerebro
from models.ths_monthly_threshold.rules import (
    build_monthly_rebalance_frame,
    select_target_codes,
)
from models.ths_monthly_threshold.strategy import (
    ThsEqualWeightBuyHoldStrategy,
    ThsMonthlyThresholdStrategy,
    build_equal_weight_target_sizes,
)


def test_month_end_value_rules_are_executed_on_next_month_first_day():
    frame = pd.DataFrame(
        [
            {"time": "2026-01-30", "htsc_code": "881101.THS", "factor": 2.0},
            {"time": "2026-02-02", "htsc_code": "881101.THS", "factor": 2.1},
            {"time": "2026-01-30", "htsc_code": "881102.THS", "factor": 0.5},
            {"time": "2026-02-02", "htsc_code": "881102.THS", "factor": 0.6},
        ]
    )
    rules = [{"factor": "factor", "mode": "value", "operator": "gte", "value": 1.0}]

    result = build_monthly_rebalance_frame(frame, rules, "and")

    rows = result.set_index(["time", "htsc_code"])
    assert bool(rows.loc[(pd.Timestamp("2026-01-30"), "881101.THS"), "rebalance_due"])
    assert bool(rows.loc[(pd.Timestamp("2026-02-02"), "881101.THS"), "eligible"])
    assert not bool(rows.loc[(pd.Timestamp("2026-02-02"), "881102.THS"), "eligible"])


def test_cross_section_rules_select_top_percentage_and_rebalance_equally():
    frame = pd.DataFrame(
        [
            {"time": "2026-01-30", "htsc_code": "881101.THS", "factor": 3.0},
            {"time": "2026-01-30", "htsc_code": "881102.THS", "factor": 2.0},
            {"time": "2026-01-30", "htsc_code": "881103.THS", "factor": 1.0},
        ]
    )
    rules = [
        {
            "factor": "factor",
            "mode": "cross_section_percentile",
            "direction": "top",
            "percentile": 2 / 3,
        }
    ]

    result = build_monthly_rebalance_frame(frame, rules, "and")
    targets = select_target_codes(result, input_codes=["881101.THS", "881102.THS", "881103.THS"], max_codes=10)

    assert targets == ["881101.THS", "881102.THS"]


def test_target_codes_are_limited_by_input_order_when_more_than_capacity():
    frame = pd.DataFrame(
        [
            {"time": "2026-01-30", "htsc_code": code, "eligible": True}
            for code in ["881101.THS", "881102.THS", "881103.THS"]
        ]
    )
    assert select_target_codes(frame, ["881103.THS", "881101.THS", "881102.THS"], max_codes=2) == [
        "881103.THS",
        "881101.THS",
    ]


def test_monthly_targets_equal_weight_all_eligible_codes_and_round_to_lots():
    targets = build_equal_weight_target_sizes(
        eligible_codes=["881101.THS", "881102.THS"],
        prices={"881101.THS": 100.0, "881102.THS": 200.0},
        portfolio_value=1_000_000.0,
        lot_size=100,
        one_way_cost_rate=0.0015,
    )

    assert targets == {"881101.THS": 4900, "881102.THS": 2400}


def test_monthly_targets_return_zero_for_codes_leaving_the_selection():
    targets = build_equal_weight_target_sizes(
        eligible_codes=["881102.THS"],
        prices={"881101.THS": 100.0, "881102.THS": 200.0},
        portfolio_value=1_000_000.0,
        lot_size=100,
        one_way_cost_rate=0.0015,
        currently_held_codes=["881101.THS", "881102.THS"],
    )

    assert targets["881101.THS"] == 0
    assert targets["881102.THS"] == 4900


def test_only_ths_codes_are_accepted():
    assert normalize_codes(["881101.ths", "881101.THS", "881102.THS"]) == [
        "881101.THS",
        "881102.THS",
    ]
    with pytest.raises(ValueError, match="THS"):
        normalize_codes(["600000.SH"])


def test_cross_section_percentage_and_rank_modes_are_normalized():
    rules = normalize_rules(
        [
            {
                "factor": "120日动量",
                "mode": "cross_section_percentile",
                "direction": "top",
                "percentile": 0.2,
            },
            {
                "factor": "60日年化波动率",
                "mode": "cross_section_percentile",
                "direction": "bottom",
                "rank_unit": "rank",
                "rank": 3,
            },
        ]
    )

    assert rules[0]["percentile"] == 0.2
    assert rules[1]["rank_unit"] == "rank"
    assert rules[1]["rank"] == 3


def test_model_registry_exposes_ths_monthly_threshold_model():
    from model_registry import list_models_public, resolve_model_id

    models = {item["id"]: item for item in list_models_public()}
    assert resolve_model_id("ths_monthly_threshold") == "ths_monthly_threshold"
    assert models["ths_monthly_threshold"]["web_runnable"] is True
    assert models["ths_monthly_threshold"]["uses_frontend_buy_sell_rules"] is True


def test_order_log_uses_next_month_execution_date_and_keeps_signal_date():
    rows = []
    for code, prices in {
        "881101.THS": [100.0, 100.0, 101.0],
        "881102.THS": [200.0, 200.0, 202.0],
    }.items():
        for date, price, condition, due in zip(
            ["2026-01-29", "2026-01-30", "2026-02-02"],
            prices,
            [0.0, 1.0, 1.0],
            [0.0, 1.0, 0.0],
        ):
            rows.append(
                {
                    "time": pd.Timestamp(date),
                    "htsc_code": code,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 1_000.0,
                    "mac_total": 0.0,
                    "kdj_signal": 0.0,
                    "obv_bullish": 0.0,
                    "buy_signal": condition,
                    "sell_signal": due,
                }
            )
    frame = pd.DataFrame(rows)
    cerebro = create_ths_cerebro(["881101.THS", "881102.THS"], frame, verbose=False)
    cerebro.addstrategy(ThsMonthlyThresholdStrategy, lot_size=100, one_way_cost_rate=0.0015)

    strategy = cerebro.run()[0]

    assert strategy.order_log
    assert {row["date"] for row in strategy.order_log} == {"2026-02-02"}
    assert {row["signal_date"] for row in strategy.order_log} == {"2026-01-30"}


def test_existing_positions_are_rebalanced_to_equal_weight_each_month():
    rows = []
    price_paths = {
        "881101.THS": [100.0, 100.0, 100.0, 200.0, 200.0],
        "881102.THS": [100.0, 100.0, 100.0, 100.0, 100.0],
    }
    dates = ["2026-01-29", "2026-01-30", "2026-02-02", "2026-02-27", "2026-03-02"]
    for code, prices in price_paths.items():
        for date, price, due in zip(dates, prices, [0.0, 1.0, 0.0, 1.0, 0.0]):
            rows.append(
                {
                    "time": pd.Timestamp(date),
                    "htsc_code": code,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 1_000.0,
                    "mac_total": 0.0,
                    "kdj_signal": 0.0,
                    "obv_bullish": 0.0,
                    "buy_signal": 1.0,
                    "sell_signal": due,
                }
            )
    frame = pd.DataFrame(rows)
    cerebro = create_ths_cerebro(list(price_paths), frame, verbose=False)
    cerebro.addstrategy(ThsMonthlyThresholdStrategy, lot_size=100, one_way_cost_rate=0.0015)

    strategy = cerebro.run()[0]

    march_orders = [row for row in strategy.order_log if row["date"] == "2026-03-02"]
    assert {row["side"] for row in march_orders} == {"BUY", "SELL"}
    values = {
        data._name: strategy.getposition(data).size * float(data.close[0])
        for data in strategy.datas
    }
    assert abs(values["881101.THS"] - values["881102.THS"]) <= 100 * 200.0


def test_buy_hold_benchmark_reserves_cost_and_buys_every_input_code():
    rows = []
    for code in ["881101.THS", "881102.THS"]:
        for date in ["2026-01-29", "2026-01-30"]:
            rows.append(
                {
                    "time": pd.Timestamp(date),
                    "htsc_code": code,
                    "open": 100.0,
                    "high": 100.0,
                    "low": 100.0,
                    "close": 100.0,
                    "volume": 1_000.0,
                    "mac_total": 0.0,
                    "kdj_signal": 0.0,
                    "obv_bullish": 0.0,
                    "buy_signal": 0.0,
                    "sell_signal": 0.0,
                }
            )
    frame = pd.DataFrame(rows)
    cerebro = create_ths_cerebro(["881101.THS", "881102.THS"], frame, verbose=False)
    cerebro.addstrategy(ThsEqualWeightBuyHoldStrategy)

    strategy = cerebro.run()[0]

    assert all(strategy.getposition(data).size > 0 for data in strategy.datas)
