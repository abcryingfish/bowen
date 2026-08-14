from __future__ import annotations

import numpy as np
import pandas as pd
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
from sector_label_stage import audit_sector_labels, build_sector_labels


def _market_frame() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=100)
    rows = []
    for offset, code in enumerate(("881001.THS", "885001.THS", "886001.THS")):
        close = 100 + offset + np.sin(np.arange(100) / 6) * 5
        for date, value in zip(dates, close):
            rows.append(
                {
                    "htsc_code": code,
                    "time": date,
                    "high": value + 1,
                    "low": value - 1,
                    "close": value,
                }
            )
    return pd.DataFrame(rows)


def test_build_sector_labels_is_unique_and_marks_incomplete_tail() -> None:
    market = _market_frame()
    labels = build_sector_labels(market)

    assert len(labels) == len(market)
    assert not labels.duplicated(["htsc_code", "time"]).any()
    assert labels.groupby("htsc_code")["label_complete"].sum().eq(60).all()
    assert labels.groupby("htsc_code")["label_complete"].tail(40).eq(False).all()
    assert labels["peak_strength_ex_post"].between(0, 1).all()
    assert labels["valley_strength_ex_post"].between(0, 1).all()


def test_audit_sector_labels_passes_complete_three_prefix_sample() -> None:
    market = _market_frame()
    labels = build_sector_labels(market)

    report, coverage = audit_sector_labels(market, labels)

    assert report["passed"] is True
    assert report["duplicate_keys"] == 0
    assert coverage["coverage"].eq(1.0).all()
