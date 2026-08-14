from datetime import date
import warnings

import pandas as pd

from models.style_portfolio_monitor import equal_weight_runner


class _FakeSource:
    market_root = "unused"

    def __init__(self, dates, codes):
        self._dates = list(dates)
        self._codes = list(codes)

    def available_market_dates(self, start, end):
        return [day.date() for day in self._dates if start <= day.date() <= end]

    def build_eligible_snapshot(self, trade_date, factor_name):
        frame = pd.DataFrame(
            {"htsc_code": self._codes, "score": range(len(self._codes))}
        )
        frame.attrs["factor_coverage"] = 1.0
        return frame


def test_build_model_inputs_does_not_fragment_score_frame(monkeypatch):
    dates = pd.bdate_range("2026-01-01", periods=105)
    codes = [f"{number:06d}.SZ" for number in range(1, 106)]
    source = _FakeSource(dates, codes)
    prices = pd.DataFrame(1.0, index=dates, columns=codes)
    monkeypatch.setattr(equal_weight_runner, "load_adjusted_open_close", lambda **kwargs: (prices, prices))

    with warnings.catch_warnings():
        warnings.simplefilter("error", pd.errors.PerformanceWarning)
        score, _, _, _, _, _ = equal_weight_runner._build_model_inputs(
            definition=type("Definition", (), {"model_id": "test", "factor_name": "factor", "rebalance_frequency": "weekly"})(),
            source=source,
            start=date(2026, 1, 1),
            end=dates[-1].date(),
        )

    assert score.shape == (len(dates), len(codes))
