# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "实盘环境" / "实时因子" / "intraday_signal_service.py"
RUNNER_PATH = ROOT / "实盘环境" / "实时因子" / "获得实时数据且计算_落盘盘中信号.py"


def load_module():
    spec = importlib.util.spec_from_file_location("intraday_signal_service_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_runner_module():
    module_dir = str(RUNNER_PATH.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    spec = importlib.util.spec_from_file_location("intraday_signal_runner_test", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_snapshot_replacement_keeps_only_last_successful_round(tmp_path):
    module = load_module()
    db = tmp_path / "snapshot.sqlite"
    module.ensure_snapshot_schema(db)
    module.replace_snapshot(
        db,
        trading_day="2026-07-16",
        round_id=1,
        quote_cutoff_time="2026-07-16 10:00:00",
        values=[{"htsc_code": "000001.SZ", "factor_name": "总买入信号", "value": 1.0}],
    )
    module.replace_snapshot(
        db,
        trading_day="2026-07-16",
        round_id=2,
        quote_cutoff_time="2026-07-16 10:01:00",
        values=[{"htsc_code": "000002.SZ", "factor_name": "总买入信号", "value": 0.0}],
    )
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM snapshot_values").fetchone()[0] == 1
        assert conn.execute("SELECT round_id FROM snapshot_meta WHERE id=1").fetchone()[0] == 2
        assert conn.execute("SELECT htsc_code FROM snapshot_values").fetchone()[0] == "000002.SZ"
    assert module.read_last_round_id(db) == 2


def test_event_writer_only_records_state_transitions(tmp_path):
    module = load_module()
    db = tmp_path / "event.sqlite"
    module.ensure_event_schema(db)
    previous = {("000001.SZ", "总买入信号"): 0.0}
    current = {("000001.SZ", "总买入信号"): 1.0}
    assert module.append_signal_transitions(db, "2026-07-16", 1, previous, current) == 1
    assert module.append_signal_transitions(db, "2026-07-16", 2, current, current) == 0
    assert module.append_signal_transitions(db, "2026-07-16", 3, current, {("000001.SZ", "总买入信号"): 0.0}) == 1
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT event_type FROM signal_events ORDER BY id").fetchall()
    assert [row[0] for row in rows] == ["triggered", "cleared"]


def test_empty_existing_event_db_is_a_real_zero_state(tmp_path):
    module = load_module()
    db = tmp_path / "event.sqlite"
    module.ensure_event_schema(db)
    assert module.read_event_signal_state(db) == {}
    assert module.read_event_signal_state(tmp_path / "missing.sqlite") is None


def test_factor_registry_exposes_only_configured_final_signals():
    module = load_module()
    registry = module.build_default_factor_registry()
    finals = {item.key for item in registry if item.is_final_signal}
    assert finals == {"tdx_five_day_level6_no_concentration", "total_buy_signal", "sell_factor_1_5_120"}


def test_runner_imports_registry_and_stops_after_1505():
    from datetime import datetime

    runner = load_runner_module()
    assert runner.build_default_factor_registry()
    assert runner._after_realtime_stop(datetime(2026, 7, 17, 15, 5), "2026-07-17") is True
    assert runner._after_realtime_stop(datetime(2026, 7, 17, 15, 4), "2026-07-17") is False


def test_market_signal_fallback_reads_only_today_snapshot(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "可视化"))
    import 可视化.market_data_service as market

    day = datetime.now().strftime("%Y-%m-%d")
    snapshot = tmp_path / f"intraday_signal_snapshot_{day}.sqlite"
    module = load_module()
    module.replace_snapshot(
        snapshot,
        trading_day=day,
        round_id=7,
        quote_cutoff_time=f"{day} 14:50:00",
        values=[{"htsc_code": "000001.SZ", "factor_name": "total_buy_signal", "value": 1.0, "is_final_signal": 1}],
    )
    monkeypatch.setattr(market, "INTRADAY_SIGNAL_SNAPSHOT_BASE_PATH", str(tmp_path))
    monkeypatch.setattr(market, "datetime", __import__("datetime").datetime)
    ts = int(time.mktime(__import__("datetime").datetime.strptime(f"{day} 14:50:00", "%Y-%m-%d %H:%M:%S").timetuple()))
    result = market._query_intraday_signal_fallback("000001.SZ", "总买入信号", ts)
    assert result is not None
    assert result["meta"]["source"] == "intraday_snapshot"
    assert result["meta"]["resolved_factor"] == "total_buy_signal"
    assert result["meta"]["provisional"] is True
    assert result["meta"]["round_id"] == 7
    public_result = market.query_market_signal(
        code="000001.SZ",
        interval="1day",
        factor="总买入信号",
        from_ts=ts - 86400,
        to_ts=ts,
        base_path=str(tmp_path / "missing_formal"),
    )
    assert public_result["meta"]["source"] == "intraday_snapshot"
    snapshot_result = market._query_intraday_factor_snapshot_fallback("000001.SZ", ts)
    assert snapshot_result is not None
    assert snapshot_result["factors"]["总买入信号"] == 1.0


def test_market_signal_appends_today_snapshot_to_formal_history(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "可视化"))
    import 可视化.market_data_service as market

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    formal_root = tmp_path / "formal"
    formal_path = (
        formal_root
        / "factor=总买入信号"
        / f"year={yesterday:%Y}"
        / f"month={yesterday:%m}"
        / "merged.parquet"
    )
    formal_path.parent.mkdir(parents=True)
    pd.DataFrame({
        "htsc_code": ["000001.SZ"],
        "time": [yesterday],
        "value": [0.0],
    }).to_parquet(formal_path, index=False)

    snapshot = tmp_path / f"intraday_signal_snapshot_{today:%Y-%m-%d}.sqlite"
    module = load_module()
    module.replace_snapshot(
        snapshot,
        trading_day=f"{today:%Y-%m-%d}",
        round_id=9,
        quote_cutoff_time=f"{today:%Y-%m-%d} 14:50:00",
        values=[{
            "htsc_code": "000001.SZ",
            "factor_name": "total_buy_signal",
            "value": 1.0,
            "is_final_signal": 1,
        }],
    )
    monkeypatch.setattr(market, "INTRADAY_SIGNAL_SNAPSHOT_BASE_PATH", str(tmp_path))

    daily_time = int(today.replace(tzinfo=timezone.utc).timestamp())
    result = market.query_market_signal(
        code="000001.SZ",
        interval="1day",
        factor="总买入信号",
        from_ts=int(time.mktime(yesterday.timetuple())),
        to_ts=daily_time,
        base_path=str(formal_root),
    )

    assert [point["value"] for point in result["signals"]] == [0.0, 1.0]
    assert result["signals"][-1]["time"] == daily_time
    assert datetime.fromtimestamp(result["signals"][-1]["time"]).date() == today.date()
    assert result["meta"]["source"] == "formal_with_intraday"
    assert result["meta"]["provisional"] is True
    assert result["meta"]["round_id"] == 9
