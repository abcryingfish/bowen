import pytest

from models.style_portfolio_monitor.portfolio import (
    PortfolioState,
    build_target_shares,
    calculate_relative_nav,
    mark_to_market,
    rebalance_at_close,
    select_style_legs,
)


def make_snapshot(count: int):
    import pandas as pd

    return pd.DataFrame(
        [{"htsc_code": f"{i + 1:06d}.SZ", "score": float(i), "close": 10.0, "average_turnover_20d": 30_000_000.0, "history_days": 200} for i in range(count)]
    )


def test_select_high_and_low_uses_ceil_twenty_percent_caps_200_and_is_deterministic():
    selected = select_style_legs(make_snapshot(503), ratio=0.20, max_count=200)
    assert len(selected["high"]) == 101
    assert len(selected["low"]) == 101
    assert selected["high"][0].code == "000503.SZ"
    assert selected["low"][0].code == "000001.SZ"


def test_equal_weight_targets_round_down_to_board_lots_and_keep_cash_non_negative():
    targets = build_target_shares(["600000.SH", "000001.SZ"], {"600000.SH": 10.0, "000001.SZ": 20.0}, 10_000.0, 0.0003, 100)
    assert targets == {"600000.SH": 400, "000001.SZ": 200}


def test_rebalance_sells_before_buys_and_charges_each_trade():
    state = PortfolioState(cash=0.0, positions={"600000.SH": 1000}, last_prices={"600000.SH": 10.0})
    result = rebalance_at_close(state, {"600000.SH": 0, "000001.SZ": 400}, {"600000.SH": 10.0, "000001.SZ": 20.0}, 0.0003)
    assert [trade.side for trade in result.trades] == ["SELL", "BUY"]
    assert result.state.cash >= 0
    assert result.total_commission == pytest.approx((10_000 + 8_000) * 0.0003)


def test_mark_to_market_uses_last_price_and_marks_stale_position():
    result = mark_to_market(PortfolioState(cash=1000, positions={"600000.SH": 100}, last_prices={"600000.SH": 9.8}), {})
    assert result.total_asset == pytest.approx(1980)
    assert result.stale_codes == ["600000.SH"]


def test_relative_nav_is_ratio_not_return_difference():
    assert calculate_relative_nav(110.0, 100.0) == pytest.approx(110.0)
