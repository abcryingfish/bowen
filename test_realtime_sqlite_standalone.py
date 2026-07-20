import importlib.util
import sqlite3
import sys
import types
from pathlib import Path


def load_realtime_sqlite_module():
    xtquant = types.ModuleType("xtquant")
    xtquant.xtdata = types.SimpleNamespace()
    sys.modules.setdefault("xtquant", xtquant)
    sys.modules.setdefault("xtquant.xtdata", xtquant.xtdata)

    module_path = Path(__file__).parent / "工具" / "实时行情写入SQLite.py"
    spec = importlib.util.spec_from_file_location("realtime_sqlite_writer", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_realtime_sqlite_writer_does_not_depend_on_visual_cache_module():
    source = (Path(__file__).parent / "工具" / "实时行情写入SQLite.py").read_text(encoding="utf-8")

    assert "temp_today_market_cache" not in source
    assert 'ROOT_DIR / "可视化"' not in source


def test_realtime_sqlite_writer_creates_schema_and_writes_without_external_cache(tmp_path):
    module = load_realtime_sqlite_module()
    db_path = tmp_path / "market_cache.sqlite"

    module.ensure_schema(db_path)
    written, stats = module.upsert_tick_snapshots(
        db_path,
        [
            {
                "htsc_code": "000001.SZ",
                "ts": "2026-07-11 09:31:05",
                "last_price": 10.5,
                "open": 10.0,
                "high": 10.6,
                "low": 9.9,
                "last_close": 10.1,
                "amount": 1000,
                "volume": 200,
                "pvolume": 300,
                "ask_price": [10.51],
                "bid_price": [10.49],
                "ask_vol": [100],
                "bid_vol": [120],
            }
        ],
        collect_stats=True,
    )

    assert written == 1
    assert set(stats) == {"snapshot_sec", "latest_sec", "commit_sec"}
    with sqlite3.connect(db_path) as conn:
        snapshot_count = conn.execute("SELECT COUNT(*) FROM tick_snapshot").fetchone()[0]
        latest = conn.execute(
            "SELECT htsc_code, ts, last_price, ask_price FROM latest_quote WHERE htsc_code = ?",
            ("000001.SZ",),
        ).fetchone()

    assert snapshot_count == 1
    assert latest == ("000001.SZ", "2026-07-11 09:31:05", 10.5, "[10.51]")
