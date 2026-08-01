from __future__ import annotations

import importlib.util
import sys
import inspect
from datetime import date, datetime
from pathlib import Path

import polars as pl
import pytest


ROOT = Path(__file__).resolve().parent
SCRIPT_PATH = ROOT / "工具" / "获得同花顺板块分钟级数据.py"
ENTRY_PATH = ROOT / "工具" / "全量数据更新_合并入口.py"


def load_module(path: Path = SCRIPT_PATH, name: str = "ths_sector_minute"):
    assert path.exists(), f"生产脚本尚未创建: {path}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def module():
    return load_module()


def test_iter_month_windows_covers_requested_range(module):
    assert module.iter_month_windows(date(2010, 1, 15), date(2010, 3, 2)) == [
        (date(2010, 1, 15), date(2010, 1, 31)),
        (date(2010, 2, 1), date(2010, 2, 28)),
        (date(2010, 3, 1), date(2010, 3, 2)),
    ]


def test_load_client_universe_only_includes_software_level1(module, tmp_path: Path):
    source = tmp_path / "stockname_48_0.txt"
    source.write_bytes(
        (
            "881101=种植业与林业\r\n"
            "882001=安徽\r\n"
            "883300=沪深300\r\n"
            "884001=种子生产\r\n"
            "885311=智能电网\r\n"
            "886999=新增板块\r\n"
        ).encode("gb18030")
    )

    rows = module.load_client_universe(source)

    assert [row["security_id"] for row in rows] == ["881101", "882001", "885311", "886999"]
    assert all(row["htsc_code"].endswith(".THS") for row in rows)


def test_load_client_universe_rejects_duplicate_code(module, tmp_path: Path):
    source = tmp_path / "stockname_48_0.txt"
    source.write_bytes("881101=名称一\n881101=名称二\n".encode("gb18030"))

    with pytest.raises(ValueError, match="重复"):
        module.load_client_universe(source)


def test_merge_universe_snapshot_marks_removed_and_new_codes(module):
    current = [
        {"security_id": "881101", "htsc_code": "881101.THS", "name": "种植业与林业"},
        {"security_id": "886999", "htsc_code": "886999.THS", "name": "新增板块"},
    ]
    previous = pl.DataFrame(
        {
            "htsc_code": ["881101.THS", "881999.THS"],
            "name": ["旧名称", "已移除"],
            "pinyin_initials": ["JM", "YJC"],
            "security_type": ["index", "index"],
            "security_id": ["881101", "881999"],
            "exchange": ["THS", "THS"],
            "is_active": [True, True],
            "first_seen_at": [datetime(2026, 7, 1), datetime(2026, 7, 1)],
            "last_seen_at": [datetime(2026, 7, 1), datetime(2026, 7, 1)],
        }
    )
    observed_at = datetime(2026, 7, 31, 12, 0)

    merged = module.merge_universe_snapshot(current, previous, observed_at)

    by_code = {row["security_id"]: row for row in merged.to_dicts()}
    assert by_code["881101"]["name"] == "种植业与林业"
    assert by_code["881101"]["first_seen_at"] == datetime(2026, 7, 1)
    assert by_code["886999"]["is_active"] is True
    assert by_code["881999"]["is_active"] is False


def test_normalize_rows_matches_stock_minute_schema_and_continuity(module):
    rows = [
        {"time": datetime(2018, 1, 2, 9, 30), "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "volume": None, "amount": None},
        {"time": datetime(2018, 1, 2, 9, 31), "open": 10.5, "high": 11.2, "low": 10.4, "close": 11.0, "volume": 100.0, "amount": 1000.0},
    ]

    frame, last_close, next_index = module.normalize_rows(rows, "881101", prior_close=9.5, index_offset=7)

    assert frame.columns == module.OUTPUT_COLUMNS
    assert frame.schema == module.OUTPUT_SCHEMA
    assert frame["pre_close"].to_list() == pytest.approx([9.5, 10.5])
    assert frame["change"].to_list() == pytest.approx([1.0, 0.5])
    assert frame["__index_level_0__"].to_list() == [7, 8]
    assert frame["date"].to_list() == ["2018-01-02", "2018-01-02"]
    assert last_close == 11.0
    assert next_index == 9


def test_normalize_rows_repairs_invalid_ohlc(module):
    rows = [
        {"time": datetime(2018, 1, 2, 9, 30), "open": 10.0, "high": 9.0, "low": 8.0, "close": 10.5, "volume": 1.0, "amount": 1.0}
    ]
    frame, _, _ = module.normalize_rows(rows, "881101", prior_close=None, index_offset=0)
    assert frame["high"].item() == pytest.approx(10.5)
    assert frame["low"].item() == pytest.approx(8.0)


def test_normalize_rows_repairs_source_ohlc_and_nulls_negative_turnover(module):
    rows = [
        {
            "time": datetime(2022, 11, 9, 9, 44),
            "open": 2586.986,
            "high": 2586.986,
            "low": 2586.986,
            "close": 2590.563,
            "volume": -3680070,
            "amount": -62529620,
        }
    ]

    frame, _, _ = module.normalize_rows(rows, "881102", prior_close=None, index_offset=0)

    assert frame["high"].item() == pytest.approx(2590.563)
    assert frame["low"].item() == pytest.approx(2586.986)
    assert frame["volume"].item() is None
    assert frame["amount"].item() is None


def test_scan_prior_local_values_many_returns_latest_value_per_code(module, tmp_path: Path):
    rows = []
    for code, close, index in [("881101.THS", 10.0, 4), ("881102.THS", 20.0, 9)]:
        rows.append(
            {
                "htsc_code": code,
                "time": datetime(2022, 10, 31, 14, 59),
                "close": close,
                "open": close,
                "high": close,
                "low": close,
                "volume": 1.0,
                "amount": 1.0,
                "date": "2022-10-31",
                "pre_close": close,
                "change": 0.0,
                "pct_chg": 0.0,
                "__index_level_0__": index,
            }
        )
    frame = pl.DataFrame(rows, schema=module.OUTPUT_SCHEMA, strict=False)
    module.write_daily_parts(frame, tmp_path)
    module.rebuild_daily_partitions(tmp_path, module.find_unmerged_partitions(tmp_path))
    result = module.scan_prior_local_values_many(
        tmp_path,
        ["881101.THS", "881102.THS"],
        datetime(2022, 11, 1),
    )
    assert result == {"881101.THS": (10.0, 5), "881102.THS": (20.0, 10)}


def test_daily_partition_merge_is_idempotent(module, tmp_path: Path):
    rows = [
        {"time": datetime(2018, 1, 2, 9, 30), "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1.0, "amount": 10.0}
    ]
    frame, _, _ = module.normalize_rows(rows, "881101", prior_close=None, index_offset=0)

    for _ in range(2):
        touched = module.write_daily_parts(frame, tmp_path)
        module.rebuild_daily_partitions(tmp_path, touched)

    path = tmp_path / "year=2018" / "month=01" / "day=02" / "merged.parquet"
    saved = pl.read_parquet(path)
    assert saved.height == 1
    assert saved.columns == module.OUTPUT_COLUMNS
    assert list(path.parent.glob("part_*.parquet")) == []


def test_download_state_round_trip(module, tmp_path: Path):
    path = tmp_path / "_meta" / "ths_minute_download_state.parquet"
    state_rows = [
        module.DownloadState("881101.THS", "2010-01", "empty", 0, None, None, datetime(2026, 7, 31), ""),
        module.DownloadState("881102.THS", "2010-01", "failed", 0, None, None, datetime(2026, 7, 31), "timeout"),
    ]

    module.write_download_state(state_rows, path)
    loaded = module.read_download_state(path)

    assert loaded[("881101.THS", "2010-01")].status == "empty"
    assert loaded[("881102.THS", "2010-01")].error == "timeout"


def test_should_request_window_can_retry_empty_state(module):
    empty = module.DownloadState(
        "881102.THS",
        "2018-01",
        "empty",
        0,
        None,
        None,
        datetime(2026, 8, 1),
        "",
    )
    success = module.DownloadState(
        "881102.THS",
        "2018-02",
        "success",
        3615,
        datetime(2018, 2, 1, 9, 30),
        datetime(2018, 2, 28, 15, 0),
        datetime(2026, 8, 1),
        "",
    )

    assert module.should_request_window(None, retry_empty=False) is True
    assert module.should_request_window(empty, retry_empty=False) is False
    assert module.should_request_window(empty, retry_empty=True) is True
    assert module.should_request_window(success, retry_empty=True) is False


def test_resolve_end_date_uses_completed_day_boundary(module):
    assert module.resolve_end_date(datetime(2026, 7, 31, 15, 29), False) == date(2026, 7, 30)
    assert module.resolve_end_date(datetime(2026, 7, 31, 15, 30), False) == date(2026, 7, 31)
    assert module.resolve_end_date(datetime(2026, 8, 3, 9, 0), False) == date(2026, 7, 31)
    assert module.resolve_end_date(datetime(2026, 7, 31, 13, 0), True) == date(2026, 7, 31)


def test_combined_entry_registers_independent_ths_minute_stage():
    entry = load_module(ENTRY_PATH, "combined_entry_for_ths_minute")
    stage = next(stage for stage in entry.STAGES if stage.key == "ths_index_mins")
    assert stage.script_name == "获得同花顺板块分钟级数据.py"
    assert entry.STAGE_KEY_ALIASES["ths_mins"] == "ths_index_mins"


def test_client_only_source_has_no_external_quote_request(module):
    source = inspect.getsource(module)
    assert "fuyao" not in source.lower()
    assert "urllib.request" not in source
    assert "http://" not in source.lower()
    assert "https://" not in source.lower()


def test_parse_client_export_decodes_gb18030_and_normalizes_columns(module, tmp_path: Path):
    path = tmp_path / "881102_1分钟.csv"
    path.write_bytes(
        "代码\t时间\t开盘\t最高\t最低\t收盘\t成交量\t成交额\r\n"
        "881102\t2019-04-30 09:30\t3000\t3010\t2990\t3005\t100\t300500\r\n".encode("gb18030")
    )

    frame = module.parse_client_export(path, expected_code="881102.THS")

    assert frame.height == 1
    assert frame["htsc_code"].item() == "881102.THS"
    assert frame["time"].item() == datetime(2019, 4, 30, 9, 30)
    assert frame["close"].item() == pytest.approx(3005)


def test_parse_client_export_rejects_code_mismatch(module, tmp_path: Path):
    path = tmp_path / "wrong.csv"
    path.write_text(
        "code,time,open,high,low,close,volume,amount\n"
        "881101,2019-04-30 09:30,1,1,1,1,1,1\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="代码不匹配"):
        module.parse_client_export(path, expected_code="881102.THS")
