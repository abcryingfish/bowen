from datetime import date

import numpy as np
import pandas as pd
import pytest

from models.style_portfolio_monitor.equal_weight_index import (
    _merge_adjusted_month,
    build_equal_weight_index,
    load_adjusted_close,
    select_target_weights,
)


def test_merge_adjusted_month_carries_factor_without_full_history_merge() -> None:
    market = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-01-02", "2026-01-05"]),
            "htsc_code": ["A.SZ", "A.SZ"],
            "close": [10.0, 11.0],
        }
    )
    factors = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-01-02"]),
            "htsc_code": ["A.SZ"],
            "adj_factor": [2.0],
        }
    )

    adjusted, carry = _merge_adjusted_month(market, factors, {})

    assert adjusted.loc[pd.Timestamp("2026-01-02"), "A.SZ"] == pytest.approx(20.0)
    assert adjusted.loc[pd.Timestamp("2026-01-05"), "A.SZ"] == pytest.approx(22.0)
    assert carry == {"A.SZ": pytest.approx(2.0)}


def test_select_target_weights_is_equal_weighted_and_capped() -> None:
    snapshot = pd.DataFrame(
        [
            {"htsc_code": "000001.SZ", "score": 10.0},
            {"htsc_code": "000002.SZ", "score": 20.0},
            {"htsc_code": "000003.SZ", "score": 30.0},
            {"htsc_code": "000004.SZ", "score": 40.0},
            {"htsc_code": "000005.SZ", "score": 50.0},
        ]
    )

    targets = select_target_weights(snapshot, ratio=0.40, max_count=200)

    assert targets["high"] == {
        "000005.SZ": pytest.approx(0.5),
        "000004.SZ": pytest.approx(0.5),
    }
    assert targets["low"] == {
        "000001.SZ": pytest.approx(0.5),
        "000002.SZ": pytest.approx(0.5),
    }
    assert sum(targets["high"].values()) == pytest.approx(1.0)
    assert sum(targets["low"].values()) == pytest.approx(1.0)


def test_equal_weight_index_activates_score_at_next_trading_day() -> None:
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    scores = pd.DataFrame(
        [[20.0, 10.0], [5.0, 30.0], [5.0, 30.0]],
        index=dates,
        columns=["A.SZ", "B.SZ"],
    )
    prices = pd.DataFrame(
        [[100.0, 100.0], [110.0, 100.0], [110.0, 90.0]],
        index=dates,
        columns=scores.columns,
    )
    valid_bar = pd.DataFrame(True, index=dates, columns=scores.columns)

    result = build_equal_weight_index(
        scores,
        prices,
        valid_bar,
        rebalance_dates=set(dates),
        ratio=0.50,
        max_count=200,
    )

    high = result["index_dfs"]["high"]
    low = result["index_dfs"]["low"]
    assert high.loc[dates[0]] == pytest.approx(100.0)
    assert high.loc[dates[1]] == pytest.approx(110.0)
    assert high.loc[dates[2]] == pytest.approx(99.0)
    assert low.loc[dates[1]] == pytest.approx(100.0)
    assert low.loc[dates[2]] == pytest.approx(100.0)
    assert result["weights"]["high"][dates[1].date()] == {"A.SZ": 1.0}
    assert result["weights"]["high"][dates[2].date()] == {"B.SZ": 1.0}
    assert "cash" not in result
    assert "shares" not in result
    assert "commission" not in result


def test_equal_weight_index_lets_weights_drift_between_rebalances() -> None:
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    scores = pd.DataFrame(
        [[30.0, 20.0, 10.0]] * 3,
        index=dates,
        columns=["A.SZ", "B.SZ", "C.SZ"],
    )
    prices = pd.DataFrame(
        [[100.0, 100.0, 100.0], [200.0, 100.0, 100.0], [220.0, 100.0, 100.0]],
        index=dates,
        columns=scores.columns,
    )
    valid_bar = pd.DataFrame(True, index=dates, columns=scores.columns)

    result = build_equal_weight_index(
        scores,
        prices,
        valid_bar,
        rebalance_dates={dates[0]},
        ratio=2 / 3,
        max_count=200,
    )

    high = result["index_dfs"]["high"]
    assert high.loc[dates[1]] == pytest.approx(150.0)
    assert result["weights"]["high"][dates[1].date()] == {
        "A.SZ": pytest.approx(0.5),
        "B.SZ": pytest.approx(0.5),
    }
    assert result["weights"]["high"][dates[2].date()] == {
        "A.SZ": pytest.approx(2 / 3),
        "B.SZ": pytest.approx(1 / 3),
    }
    assert high.loc[dates[2]] == pytest.approx(160.0)


def test_equal_weight_index_preserves_strategy_specific_target_weights(monkeypatch) -> None:
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    scores = pd.DataFrame(
        [[30.0, 20.0], [30.0, 20.0], [30.0, 20.0]],
        index=dates,
        columns=["A.SZ", "B.SZ"],
    )
    prices = pd.DataFrame(
        [[100.0, 100.0], [200.0, 100.0], [200.0, 100.0]],
        index=dates,
        columns=scores.columns,
    )
    valid_bar = pd.DataFrame(True, index=dates, columns=scores.columns)

    monkeypatch.setattr(
        "models.style_portfolio_monitor.equal_weight_index.select_target_weights",
        lambda *args, **kwargs: {
            "high": {"A.SZ": 0.8, "B.SZ": 0.2},
            "low": {"A.SZ": 0.3, "B.SZ": 0.7},
        },
    )

    result = build_equal_weight_index(
        scores,
        prices,
        valid_bar,
        rebalance_dates={dates[0]},
    )

    assert result["weights"]["high"][dates[1].date()] == {
        "A.SZ": pytest.approx(0.8),
        "B.SZ": pytest.approx(0.2),
    }
    assert result["weights"]["high"][dates[2].date()] == {
        "A.SZ": pytest.approx(8 / 9),
        "B.SZ": pytest.approx(1 / 9),
    }


def test_equal_weight_index_returns_diagnostics_without_money_fields() -> None:
    day = pd.Timestamp("2026-01-01")
    scores = pd.DataFrame([[1.0, 2.0]], index=[day], columns=["A.SZ", "B.SZ"])
    prices = pd.DataFrame([[10.0, 20.0]], index=[day], columns=scores.columns)
    valid_bar = pd.DataFrame(True, index=[day], columns=scores.columns)

    result = build_equal_weight_index(
        scores, prices, valid_bar, rebalance_dates=set(), ratio=0.50
    )

    assert result["diagnostics"]["high"][day.date()]["weight_sum"] == pytest.approx(0.0)
    assert np.isfinite(result["index_dfs"]["high"]).all()


def test_equal_weight_index_rejects_nonpositive_prices_even_when_marked_valid() -> None:
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    scores = pd.DataFrame([[10.0], [10.0], [10.0]], index=dates, columns=["A.SZ"])
    prices = pd.DataFrame([[100.0], [0.0], [110.0]], index=dates, columns=["A.SZ"])
    valid_bar = pd.DataFrame(True, index=dates, columns=["A.SZ"])

    result = build_equal_weight_index(scores, prices, valid_bar, rebalance_dates={dates[0]})

    assert result["index_dfs"]["high"].tolist() == pytest.approx([100.0, 100.0, 100.0])
    assert result["diagnostics"]["high"][dates[1].date()]["valid_count"] == 0


def test_equal_weight_index_does_not_create_trading_days_from_score_only_dates() -> None:
    market_dates = pd.DatetimeIndex(["2026-01-01", "2026-01-05"])
    score_dates = pd.DatetimeIndex(["2026-01-01", "2026-01-02", "2026-01-05"])
    scores = pd.DataFrame([[10.0], [20.0], [30.0]], index=score_dates, columns=["A.SZ"])
    prices = pd.DataFrame([[100.0], [110.0]], index=market_dates, columns=["A.SZ"])
    valid_bar = pd.DataFrame(True, index=market_dates, columns=["A.SZ"])

    result = build_equal_weight_index(scores, prices, valid_bar, rebalance_dates={pd.Timestamp("2026-01-02")})

    assert list(result["index_dfs"]["high"].index) == list(market_dates)


def test_equal_weight_index_handles_empty_and_rejects_duplicate_dates() -> None:
    empty = pd.DataFrame(columns=["A.SZ"])
    result = build_equal_weight_index(empty, empty, empty, rebalance_dates=set())
    assert result["index_dfs"]["high"].empty

    duplicate = pd.DataFrame(
        [[1.0], [2.0]],
        index=[pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-01")],
        columns=["A.SZ"],
    )
    with pytest.raises(ValueError, match="unique"):
        build_equal_weight_index(duplicate, duplicate, duplicate, rebalance_dates=set())


def test_load_adjusted_close_uses_adj_factor_daily(tmp_path) -> None:
    market_dir = tmp_path / "market"
    factor_dir = tmp_path / "adj_factor_daily"
    month_market = market_dir / "year=2026" / "month=01"
    month_factor = factor_dir / "year=2026" / "month=01"
    month_market.mkdir(parents=True)
    month_factor.mkdir(parents=True)
    pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "htsc_code": ["A.SZ", "A.SZ"],
            "close": [10.0, 11.0],
        }
    ).to_parquet(month_market / "merged.parquet")
    pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "htsc_code": ["A.SZ", "A.SZ"],
            "adj_factor": [1.0, 2.0],
        }
    ).to_parquet(month_factor / "merged.parquet")

    result = load_adjusted_close(
        market_base_dir=market_dir,
        adj_factor_daily_dir=factor_dir,
        wide_xdy_dir=tmp_path / "missing-wide",
        start_date="2026-01-01",
        end_date="2026-01-02",
    )

    assert result.loc[pd.Timestamp("2026-01-01"), "A.SZ"] == pytest.approx(10.0)
    assert result.loc[pd.Timestamp("2026-01-02"), "A.SZ"] == pytest.approx(22.0)


def test_load_adjusted_close_carries_factor_from_before_query_start(tmp_path) -> None:
    market_dir = tmp_path / "market"
    factor_dir = tmp_path / "adj_factor_daily"
    month_market = market_dir / "year=2026" / "month=01"
    month_factor = factor_dir / "year=2026" / "month=01"
    previous_factor = factor_dir / "year=2025" / "month=12"
    month_market.mkdir(parents=True)
    month_factor.mkdir(parents=True)
    previous_factor.mkdir(parents=True)
    pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "htsc_code": ["A.SZ", "A.SZ"],
            "close": [10.0, 11.0],
        }
    ).to_parquet(month_market / "merged.parquet")
    pd.DataFrame(
        {"time": [pd.Timestamp("2026-01-02")], "htsc_code": ["A.SZ"], "adj_factor": [3.0]}
    ).to_parquet(month_factor / "merged.parquet")
    pd.DataFrame(
        {"time": [pd.Timestamp("2025-12-31")], "htsc_code": ["A.SZ"], "adj_factor": [2.0]}
    ).to_parquet(previous_factor / "merged.parquet")

    result = load_adjusted_close(
        market_base_dir=market_dir,
        adj_factor_daily_dir=factor_dir,
        wide_xdy_dir=tmp_path / "missing-wide",
        start_date="2026-01-01",
        end_date="2026-01-02",
    )

    assert result.loc[pd.Timestamp("2026-01-01"), "A.SZ"] == pytest.approx(20.0)
    assert result.loc[pd.Timestamp("2026-01-02"), "A.SZ"] == pytest.approx(33.0)


def test_load_adjusted_close_falls_back_to_wide_xdy(tmp_path) -> None:
    market_dir = tmp_path / "market"
    wide_dir = tmp_path / "wide_xdy"
    month_market = market_dir / "year=2026" / "month=01"
    month_wide = wide_dir / "year=2026" / "month=01"
    month_market.mkdir(parents=True)
    month_wide.mkdir(parents=True)
    pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "htsc_code": ["A.SZ", "A.SZ"],
            "close": [10.0, 11.0],
        }
    ).to_parquet(month_market / "merged.parquet")
    pd.DataFrame(
        {
            "htsc_code": ["A.SZ"],
            "2026/01/01": [1.0],
            "2026/01/02": [2.0],
        }
    ).to_parquet(month_wide / "merged.parquet")

    result = load_adjusted_close(
        market_base_dir=market_dir,
        adj_factor_daily_dir=tmp_path / "missing-fast",
        wide_xdy_dir=wide_dir,
        start_date="2026-01-01",
        end_date="2026-01-02",
    )

    assert result.loc[pd.Timestamp("2026-01-01"), "A.SZ"] == pytest.approx(10.0)
    assert result.loc[pd.Timestamp("2026-01-02"), "A.SZ"] == pytest.approx(22.0)


def test_load_adjusted_close_does_not_reaccumulate_wide_xdy(tmp_path) -> None:
    market_dir = tmp_path / "market"
    wide_dir = tmp_path / "wide_xdy"
    month_market = market_dir / "year=2026" / "month=01"
    month_wide = wide_dir / "year=2026" / "month=01"
    month_market.mkdir(parents=True)
    month_wide.mkdir(parents=True)
    pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "htsc_code": ["A.SZ", "A.SZ", "A.SZ"],
            "close": [10.0, 11.0, 12.0],
        }
    ).to_parquet(month_market / "merged.parquet")
    pd.DataFrame(
        {
            "htsc_code": ["A.SZ"],
            "2026/01/01": [2.0],
            "2026/01/02": [2.0],
            "2026/01/03": [2.0],
        }
    ).to_parquet(month_wide / "merged.parquet")

    result = load_adjusted_close(
        market_base_dir=market_dir,
        adj_factor_daily_dir=tmp_path / "missing-fast",
        wide_xdy_dir=wide_dir,
        start_date="2026-01-01",
        end_date="2026-01-03",
    )

    assert result["A.SZ"].tolist() == pytest.approx([20.0, 22.0, 24.0])


def test_load_adjusted_close_fills_identity_for_missing_factor_rows(tmp_path) -> None:
    market_dir = tmp_path / "market"
    factor_dir = tmp_path / "adj_factor_daily"
    month_market = market_dir / "year=2026" / "month=01"
    month_factor = factor_dir / "year=2026" / "month=01"
    month_market.mkdir(parents=True)
    month_factor.mkdir(parents=True)
    pd.DataFrame({"time": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")], "htsc_code": ["A.SZ", "A.SZ"], "close": [10.0, 11.0]}).to_parquet(month_market / "merged.parquet")
    pd.DataFrame({"time": [pd.Timestamp("2026-01-01")], "htsc_code": ["A.SZ"], "adj_factor": [1.0]}).to_parquet(month_factor / "merged.parquet")

    result = load_adjusted_close(
        market_base_dir=market_dir,
        adj_factor_daily_dir=factor_dir,
        wide_xdy_dir=tmp_path / "missing-wide",
        start_date="2026-01-01",
        end_date="2026-01-02",
    )

    assert result.loc[pd.Timestamp("2026-01-01"), "A.SZ"] == pytest.approx(10.0)
    assert result.loc[pd.Timestamp("2026-01-02"), "A.SZ"] == pytest.approx(11.0)


def test_load_adjusted_close_falls_back_when_first_daily_factor_is_missing(tmp_path) -> None:
    market_dir = tmp_path / "market"
    factor_dir = tmp_path / "adj_factor_daily"
    wide_dir = tmp_path / "wide_xdy"
    month_market = market_dir / "year=2026" / "month=01"
    month_factor = factor_dir / "year=2026" / "month=01"
    month_wide = wide_dir / "year=2026" / "month=01"
    month_market.mkdir(parents=True)
    month_factor.mkdir(parents=True)
    month_wide.mkdir(parents=True)
    pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "htsc_code": ["A.SZ", "A.SZ"],
            "close": [10.0, 11.0],
        }
    ).to_parquet(month_market / "merged.parquet")
    pd.DataFrame(
        {
            "time": [pd.Timestamp("2026-01-02")],
            "htsc_code": ["A.SZ"],
            "adj_factor": [3.0],
        }
    ).to_parquet(month_factor / "merged.parquet")
    pd.DataFrame(
        {
            "htsc_code": ["A.SZ"],
            "2026/01/01": [2.0],
            "2026/01/02": [2.0],
        }
    ).to_parquet(month_wide / "merged.parquet")

    result = load_adjusted_close(
        market_base_dir=market_dir,
        adj_factor_daily_dir=factor_dir,
        wide_xdy_dir=wide_dir,
        start_date="2026-01-01",
        end_date="2026-01-02",
    )

    assert result.loc[pd.Timestamp("2026-01-01"), "A.SZ"] == pytest.approx(20.0)
    assert result.loc[pd.Timestamp("2026-01-02"), "A.SZ"] == pytest.approx(33.0)


def test_load_adjusted_close_uses_identity_factor_when_both_sources_are_missing(tmp_path) -> None:
    market_dir = tmp_path / "market"
    factor_dir = tmp_path / "adj_factor_daily"
    wide_dir = tmp_path / "wide_xdy"
    month_market = market_dir / "year=2026" / "month=01"
    month_factor = factor_dir / "year=2026" / "month=01"
    month_wide = wide_dir / "year=2026" / "month=01"
    month_market.mkdir(parents=True)
    month_factor.mkdir(parents=True)
    month_wide.mkdir(parents=True)
    pd.DataFrame(
        {"time": [pd.Timestamp("2026-01-01")], "htsc_code": ["A.SZ"], "close": [10.0]}
    ).to_parquet(month_market / "merged.parquet")
    pd.DataFrame(
        {"time": [pd.Timestamp("2026-01-01")], "htsc_code": ["B.SZ"], "adj_factor": [2.0]}
    ).to_parquet(month_factor / "merged.parquet")
    pd.DataFrame(
        {"htsc_code": ["B.SZ"], "2026/01/01": [2.0]}
    ).to_parquet(month_wide / "merged.parquet")

    result = load_adjusted_close(
        market_base_dir=market_dir,
        adj_factor_daily_dir=factor_dir,
        wide_xdy_dir=wide_dir,
        start_date="2026-01-01",
        end_date="2026-01-01",
    )

    assert result.loc[pd.Timestamp("2026-01-01"), "A.SZ"] == pytest.approx(10.0)


def test_load_adjusted_close_rejects_invalid_factor_source(tmp_path) -> None:
    market_dir = tmp_path / "market"
    factor_dir = tmp_path / "adj_factor_daily"
    month_market = market_dir / "year=2026" / "month=01"
    month_factor = factor_dir / "year=2026" / "month=01"
    month_market.mkdir(parents=True)
    month_factor.mkdir(parents=True)
    pd.DataFrame(
        {
            "time": [pd.Timestamp("2026-01-01")],
            "htsc_code": ["A.SZ"],
            "close": [10.0],
        }
    ).to_parquet(month_market / "merged.parquet")
    pd.DataFrame(
        {
            "time": [pd.Timestamp("2026-01-01")],
            "htsc_code": ["A.SZ"],
            "adj_factor": [np.nan],
        }
    ).to_parquet(month_factor / "merged.parquet")

    with pytest.raises(RuntimeError, match="复权因子"):
        load_adjusted_close(
            market_base_dir=market_dir,
            adj_factor_daily_dir=factor_dir,
            wide_xdy_dir=tmp_path / "missing-wide",
            start_date="2026-01-01",
            end_date="2026-01-01",
        )


def test_t_plus_one_open_execution_excludes_pre_open_gap() -> None:
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    scores = pd.DataFrame(
        [[100.0, 0.0], [np.nan, np.nan], [np.nan, np.nan]],
        index=dates,
        columns=["A.SZ", "B.SZ"],
    )
    close = pd.DataFrame(
        [[100.0, 100.0], [220.0, 100.0], [242.0, 100.0]],
        index=dates,
        columns=scores.columns,
    )
    open_price = pd.DataFrame(
        [[100.0, 100.0], [200.0, 100.0], [220.0, 100.0]],
        index=dates,
        columns=scores.columns,
    )

    result = build_equal_weight_index(
        scores,
        close,
        close.notna(),
        adjusted_open=open_price,
        rebalance_dates={dates[0]},
        ratio=0.50,
    )

    assert result["index_dfs"]["high"].loc[dates[1]] == pytest.approx(110.0)
    assert "net_index_dfs" not in result
    assert "turnover" not in result
    assert "costs" not in result
    assert result["signal_dates"][dates[1].date()] == dates[0].date()


def test_full_name_switch_applies_the_new_target_at_next_open() -> None:
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    scores = pd.DataFrame(
        [[100.0, 0.0], [0.0, 100.0], [np.nan, np.nan], [np.nan, np.nan]],
        index=dates,
        columns=["A.SZ", "B.SZ"],
    )
    prices = pd.DataFrame(100.0, index=dates, columns=scores.columns)

    result = build_equal_weight_index(
        scores,
        prices,
        prices.notna(),
        adjusted_open=prices,
        rebalance_dates={dates[0], dates[1]},
        ratio=0.50,
    )

    assert result["weights"]["high"][dates[1].date()] == {"A.SZ": 1.0}
    assert result["weights"]["high"][dates[2].date()] == {"B.SZ": 1.0}
    assert result["signal_dates"][dates[2].date()] == dates[1].date()
