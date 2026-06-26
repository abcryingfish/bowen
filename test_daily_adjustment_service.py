from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent
VIS_DIR = PROJECT_ROOT / "可视化"
if str(VIS_DIR) not in sys.path:
    sys.path.append(str(VIS_DIR))

from daily_adjustment_service import apply_daily_adjustment  # noqa: E402


def _write_raw_events(tmp_path: Path) -> Path:
    rows = [
        ("605020.SH", "2022-06-07", 0.25, 0.0, 0.0, 0.0, 0.0),
        ("605020.SH", "2023-06-16", 0.25, 0.0, 0.4, 0.0, 0.0),
        ("605020.SH", "2024-07-16", 0.15, 0.0, 0.0, 0.0, 0.0),
        ("605020.SH", "2025-06-13", 0.25, 0.0, 0.0, 0.0, 0.0),
        ("605020.SH", "2026-05-29", 0.45, 0.0, 0.0, 0.0, 0.0),
    ]
    df = pd.DataFrame(
        rows,
        columns=[
            "htsc_code",
            "event_date",
            "interest",
            "stockBonus",
            "stockGift",
            "allotNum",
            "allotPrice",
        ],
    )
    df["event_date"] = pd.to_datetime(df["event_date"])
    month_dir = tmp_path / "year=2026" / "month=05"
    month_dir.mkdir(parents=True)
    df.to_parquet(month_dir / "merged.parquet")
    return tmp_path


def test_backward_adjustment_uses_ordinary_corporate_action_events(tmp_path: Path) -> None:
    raw_base = _write_raw_events(tmp_path)
    bars = [
        {
            "time": pd.Timestamp("2026-06-25"),
            "open": 39.86,
            "high": 41.13,
            "low": 38.30,
            "close": 38.88,
        }
    ]

    adjusted = apply_daily_adjustment(
        bars,
        "605020.SH",
        "backward",
        raw_base_path=raw_base,
    )

    assert round(adjusted[0]["close"], 3) == 56.122
    assert round(adjusted[0]["high"], 3) == 59.272


def test_forward_adjustment_uses_inverse_ordinary_events(tmp_path: Path) -> None:
    raw_base = _write_raw_events(tmp_path)
    bars = [
        {
            "time": pd.Timestamp("2021-07-09"),
            "open": 9.98,
            "high": 10.78,
            "low": 9.98,
            "close": 9.98,
        }
    ]

    adjusted = apply_daily_adjustment(
        bars,
        "605020.SH",
        "forward",
        raw_base_path=raw_base,
    )

    assert round(adjusted[0]["close"], 6) == 5.921429
