import numpy as np
import pandas as pd

from daily_adjustment_service import _compute_backward_factor_series


def test_backward_factors_do_not_compound_repeated_daily_event_values():
    series = pd.Series(
        [1.10, 1.10, 1.10, 1.05, 1.05],
        index=pd.to_datetime(
            ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]
        ),
    )

    result = _compute_backward_factor_series(series)

    np.testing.assert_allclose(result.to_numpy(), [1.10, 1.10, 1.10, 1.155, 1.155])


def test_backward_factors_accumulate_each_changed_event_once():
    series = pd.Series(
        [1.10, 1.10, 1.20],
        index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
    )

    result = _compute_backward_factor_series(series)

    np.testing.assert_allclose(result.to_numpy(), [1.10, 1.10, 1.32])
