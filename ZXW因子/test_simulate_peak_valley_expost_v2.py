from __future__ import annotations

import pandas as pd

from simulate_peak_valley_expost_v2 import run_simulation


def test_simulation_writes_comparison_and_summary(tmp_path):
    dates = pd.date_range("2020-01-01", periods=12, freq="D")
    close = pd.Series([1, 2, 3, 4, 5, 6, 5, 4, 3, 4, 5, 6], index=dates, dtype=float)
    frame = pd.DataFrame(
        {
            "htsc_code": "300265.SZ",
            "time": dates,
            "high": close.to_numpy() + 0.5,
            "low": close.to_numpy() - 0.5,
            "close": close.to_numpy(),
        }
    )
    anchors = {
        "peak": {"positive": [dates[5].strftime("%Y-%m-%d")], "negative": []},
        "valley": {"positive": [dates[8].strftime("%Y-%m-%d")], "negative": []},
    }
    result = run_simulation(frame, anchors, tmp_path)
    assert result["comparison_path"].is_file()
    assert result["summary_path"].is_file()
    comparison = pd.read_csv(result["comparison_path"])
    assert {
        "date",
        "peak_strength_ex_post",
        "valley_strength_ex_post",
    } <= set(comparison)
    assert not {"manual_direction", "manual_peak", "manual_valley"} & set(comparison)
    assert not any(column.startswith("v1_") for column in comparison.columns)
