from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parent / "qmt\u83b7\u5f97\u80a1\u7968\u65e5\u9891\u590d\u6743\u56e0\u5b50.py"
SPEC = importlib.util.spec_from_file_location("qmt_adj_factor_daily", MODULE_PATH)
qmt_adj_factor_daily = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(qmt_adj_factor_daily)


def test_qmt_raw_events_convert_to_existing_adj_segments() -> None:
    raw = pd.DataFrame(
        {
            "htsc_code": ["000001.sz", "000001.SZ", "600000.sh"],
            "event_date": ["2025-10-15", "2026-06-12", "2025-07-16"],
            "dr": [1.021505, 1.032846, 1.029927],
            "interest": [0.236, 0.36, 0.41],
        }
    )

    out = qmt_adj_factor_daily.raw_events_to_adj_segments(raw, pd.Timestamp("2026-06-24").date())

    assert out.to_dicts() == [
        {
            "htsc_code": "000001.SZ",
            "begin_date": pd.Timestamp("2025-10-16").date(),
            "end_date": pd.Timestamp("2026-06-12").date(),
            "xdy": 1.021505,
        },
        {
            "htsc_code": "000001.SZ",
            "begin_date": pd.Timestamp("2026-06-13").date(),
            "end_date": pd.Timestamp("2026-06-24").date(),
            "xdy": 1.032846,
        },
        {
            "htsc_code": "600000.SH",
            "begin_date": pd.Timestamp("2025-07-17").date(),
            "end_date": pd.Timestamp("2026-06-24").date(),
            "xdy": 1.029927,
        },
    ]


def test_console_encoding_is_configured_to_utf8_replace() -> None:
    calls: list[dict[str, str]] = []

    class FakeStream:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    fake_sys = SimpleNamespace(stdout=FakeStream(), stderr=FakeStream())

    qmt_adj_factor_daily.configure_console_encoding(fake_sys)

    assert calls == [
        {"encoding": "utf-8", "errors": "replace"},
        {"encoding": "utf-8", "errors": "replace"},
    ]


def test_qmt_event_after_effective_shift_past_adj_end_is_skipped() -> None:
    raw = pd.DataFrame(
        {
            "htsc_code": ["000001.SZ"],
            "event_date": ["2026-06-24"],
            "dr": [1.032846],
        }
    )

    out = qmt_adj_factor_daily.raw_events_to_adj_segments(raw, pd.Timestamp("2026-06-24").date())

    assert out.is_empty()
