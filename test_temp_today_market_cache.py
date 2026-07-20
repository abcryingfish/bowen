# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "可视化" / "temp_today_market_cache.py"


def load_module():
    spec = importlib.util.spec_from_file_location("temp_today_market_cache_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_minute_volume_uses_delta_between_cumulative_minute_closes(tmp_path):
    module = load_module()
    db_path = tmp_path / "market_cache.sqlite"
    rows = []
    for ts, price, volume, pvolume, amount in (
        ("2026-07-17 09:30:10", 10.0, 10.0, 1_000.0, 10_000.0),
        ("2026-07-17 09:31:10", 10.1, 25.0, 2_500.0, 25_000.0),
        ("2026-07-17 09:32:10", 10.2, 40.0, 4_000.0, 41_000.0),
    ):
        rows.append({
            "htsc_code": "000001.SZ",
            "ts": ts,
            "last_price": price,
            "amount": amount,
            "volume": volume,
            "pvolume": pvolume,
        })
    module.upsert_tick_snapshots(db_path, rows)

    bars = module.query_today_minute_bars(
        db_path,
        "000001.SZ",
        module._ts_to_epoch("2026-07-17 09:30:00"),
        module._ts_to_epoch("2026-07-17 09:32:59"),
    )

    assert [bar["volume"] for bar in bars] == [0.0, 1_500.0, 1_500.0]
    assert [bar["amount"] for bar in bars] == [0.0, 15_000.0, 16_000.0]

    partial = module.query_today_minute_bars(
        db_path,
        "000001.SZ",
        module._ts_to_epoch("2026-07-17 09:31:00"),
        module._ts_to_epoch("2026-07-17 09:32:59"),
    )
    assert [bar["volume"] for bar in partial] == [1_500.0, 1_500.0]
