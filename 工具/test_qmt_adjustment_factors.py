# -*- coding: utf-8 -*-

from datetime import date

import pandas as pd

from qmt获得股票日频复权因子 import (
    build_monthly_adj_factor_daily_frames,
    raw_events_to_adj_segments,
)


def test_same_multiplier_events_are_both_cumulative():
    raw = pd.DataFrame(
        {
            "htsc_code": ["600415.SH", "600415.SH"],
            "event_date": ["2010-04-26", "2011-06-23"],
            "dr": [2.0, 2.0],
        }
    )
    segments = raw_events_to_adj_segments(raw, date(2012, 1, 1))
    frames = build_monthly_adj_factor_daily_frames(
        segments,
        start_date=date(2010, 1, 1),
        end_date=date(2011, 6, 25),
    )
    daily = pd.concat([frame.to_pandas() for frame in frames.values()], ignore_index=True)
    daily["time"] = pd.to_datetime(daily["time"])

    before_first = daily.loc[daily["time"] == "2010-04-27", "adj_factor"].iloc[0]
    after_second = daily.loc[daily["time"] == "2011-06-24", "adj_factor"].iloc[0]
    assert before_first == 2.0
    assert after_second == 4.0


def test_no_event_before_first_action_is_one():
    raw = pd.DataFrame(
        {
            "htsc_code": ["600000.SH"],
            "event_date": ["2011-01-01"],
            "dr": [1.5],
        }
    )
    segments = raw_events_to_adj_segments(raw, date(2011, 1, 10))
    # The daily table starts at the first effective event; consumers use 1.0
    # before that date when no prior factor exists.
    assert segments["xdy"].to_list() == [1.5]
