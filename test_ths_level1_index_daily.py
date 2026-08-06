from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pandas as pd


ROOT = Path(__file__).resolve().parent
SCRIPT_PATH = ROOT / "工具" / "获得同花顺板块和成分股.py"
ENTRY_PATH = ROOT / "工具" / "全量数据更新_合并入口.py"


def load_module():
    assert SCRIPT_PATH.exists(), f"生产脚本尚未创建: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("ths_level1_daily", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_stockname_fixture(path: Path) -> None:
    lines = []
    groups = (("881", 90), ("882", 33), ("885", 293), ("886", 96))
    for prefix, count in groups:
        for number in range(count):
            lines.append(f"{prefix}{number:03d}=板块{prefix}_{number:03d}")
    lines.extend(["883001=不应纳入", "884001=不应纳入"])
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("gb18030"))


def test_load_level1_indices_requires_exact_512_prefix_distribution(tmp_path: Path):
    module = load_module()
    stockname = tmp_path / "stockname_48_0.txt"
    write_stockname_fixture(stockname)

    rows = module.load_level1_indices(stockname)

    assert len(rows) == 512
    assert rows[0]["htsc_code"].endswith(".THS")
    counts = {}
    for row in rows:
        counts[row["security_id"][:3]] = counts.get(row["security_id"][:3], 0) + 1
    assert counts == {"881": 90, "882": 33, "885": 293, "886": 96}


def test_write_level1_universe_saves_names_and_pinyin(tmp_path: Path):
    module = load_module()
    indices = [
        {
            "security_id": "881121",
            "htsc_code": "881121.THS",
            "index_name": "医药",
            "index_prefix": "881",
        }
    ]

    output_path = module.write_level1_universe(indices, tmp_path)

    assert output_path == tmp_path / "_meta" / "ths_level1_universe.parquet"
    frame = pl.read_parquet(output_path)
    assert frame.to_dicts() == [
        {
            "htsc_code": "881121.THS",
            "name": "医药",
            "pinyin_initials": "YY",
            "security_type": "index",
            "security_id": "881121",
            "exchange": "THS",
        }
    ]


def test_parse_year_jsonp_normalizes_existing_index_schema():
    module = load_module()
    payload = {
        "data": (
            "20260714,10.0,12.0,9.0,11.0,100,1000.5,,,,0;"
            "20260715,11.0,13.0,10.0,12.0,120,1200.5,,,,0"
        )
    }
    text = f"callback({json.dumps(payload)})"

    frame = module.parse_year_jsonp(text, security_id="881121")

    assert frame.columns == [
        "htsc_code", "time", "exchange", "security_type", "security_id", "frequency",
        "open", "close", "high", "low", "volume", "value",
    ]
    assert frame["htsc_code"].to_list() == ["881121.THS", "881121.THS"]
    assert frame["close"].to_list() == [11.0, 12.0]
    assert frame["value"].to_list() == [1000.5, 1200.5]


def test_resolve_completed_end_date_uses_1530_boundary():
    module = load_module()

    before = module.resolve_completed_end_date(datetime(2026, 7, 15, 15, 29, 59))
    at_boundary = module.resolve_completed_end_date(datetime(2026, 7, 15, 15, 30, 0))
    monday_before = module.resolve_completed_end_date(datetime(2026, 7, 20, 9, 0, 0))

    assert before.isoformat() == "2026-07-14"
    assert at_boundary.isoformat() == "2026-07-15"
    assert monday_before.isoformat() == "2026-07-17"


def test_resolve_fetch_start_overlaps_last_saved_day():
    module = load_module()

    assert module.resolve_fetch_start(None, "2010-01-01").isoformat() == "2010-01-01"
    assert module.resolve_fetch_start(datetime(2026, 7, 14), "2010-01-01").isoformat() == "2026-07-14"


def test_normalize_repairs_provider_index_ohlc_bounds():
    module = load_module()
    frame = pl.DataFrame(
        {
            "htsc_code": ["885988.THS"],
            "time": [datetime(2022, 4, 12)],
            "exchange": ["THS"],
            "security_type": ["index"],
            "security_id": ["885988"],
            "frequency": ["daily"],
            "open": [1009.889],
            "close": [1199.074],
            "high": [1046.8],
            "low": [993.43],
            "volume": [100.0],
            "value": [1000.0],
        }
    )

    normalized = module._normalize_daily_frame(frame)

    assert normalized["high"].item() == 1199.074
    assert normalized["low"].item() == 993.43


def test_save_partitioned_replaces_same_key_and_preserves_other_codes(tmp_path: Path):
    module = load_module()
    old = pl.DataFrame(
        {
            "htsc_code": ["881121.THS", "000001.SH"],
            "time": [datetime(2026, 7, 14), datetime(2026, 7, 14)],
            "exchange": ["THS", "DefaultSecurityIDSource"],
            "security_type": ["index", "index"],
            "security_id": ["881121", "000001"],
            "frequency": ["daily", "daily"],
            "open": [10.0, 4000.0],
            "close": [11.0, 4100.0],
            "high": [12.0, 4150.0],
            "low": [9.0, 3990.0],
            "volume": [100.0, 200.0],
            "value": [1000.0, 2000.0],
        }
    )
    month_dir = tmp_path / "year=2026" / "month=07"
    month_dir.mkdir(parents=True)
    old.write_parquet(month_dir / "merged.parquet")
    revised = old.filter(pl.col("htsc_code") == "881121.THS").with_columns(
        pl.lit(11.5).alias("close")
    )

    module.save_partitioned_parquet(revised, tmp_path)

    merged = pl.read_parquet(month_dir / "merged.parquet").sort(["time", "htsc_code"])
    assert len(merged) == 2
    assert merged.filter(pl.col("htsc_code") == "881121.THS")["close"].item() == 11.5
    assert merged.filter(pl.col("htsc_code") == "000001.SH")["close"].item() == 4100.0
    assert not list(month_dir.glob("part_*.parquet"))


def test_purge_existing_ths_rows_preserves_other_indices(tmp_path: Path):
    module = load_module()
    month_dir = tmp_path / "year=2026" / "month=07"
    month_dir.mkdir(parents=True)
    pl.DataFrame(
        {
            "htsc_code": ["881121.THS", "000001.SH"],
            "time": [datetime(2026, 7, 14), datetime(2026, 7, 14)],
        }
    ).write_parquet(month_dir / "merged.parquet")

    result = module.purge_existing_ths_rows(tmp_path)

    remaining = pl.read_parquet(month_dir / "merged.parquet")
    assert result["removed_rows"] == 1
    assert remaining["htsc_code"].to_list() == ["000001.SH"]


def test_pipeline_passes_local_extraction_directly_to_research(monkeypatch, tmp_path: Path):
    module = load_module()
    extracted = {
        "level_rows": {
            "同花顺软件一级": [
                {"指数代码": "881121", "板块名称": "半导体", "软件级别": "同花顺软件一级"}
            ],
            "同花顺软件二级": [],
        },
        "constituent_rows": [
            {
                "指数代码": "881121",
                "板块名称": "半导体",
                "股票代码": "600000.SH",
                "软件级别": "同花顺软件一级",
            }
        ],
        "level1_indices": [
            {
                "security_id": "881121",
                "htsc_code": "881121.THS",
                "index_name": "半导体",
                "index_prefix": "881",
            }
        ],
        "snapshot_date": "2026-07-24",
    }
    calls: dict[str, object] = {}

    monkeypatch.setattr(module, "extract_ths_sector_data", lambda **kwargs: extracted)
    monkeypatch.setattr(
        module,
        "write_sector_exports",
        lambda result, output_dir: calls.setdefault("export", result),
    )
    monkeypatch.setattr(
        module,
        "run_level1_daily_update",
        lambda args, indices: calls.setdefault("daily_indices", indices),
    )

    def capture_research(*, sectors, members, **kwargs):
        calls["research_sectors"] = sectors
        calls["research_members"] = members
        calls["constituent_snapshot_date"] = kwargs["constituent_snapshot_date"]

    monkeypatch.setattr(module, "run_sector_research", capture_research)
    args = SimpleNamespace(
        ths_root=str(tmp_path / "ths"),
        output_dir=str(tmp_path / "export"),
        secondary_export=str(tmp_path / "Table.xlsx"),
        history_workers=1,
        sector_base_dir=str(tmp_path / "sector_information"),
        audit_path=str(tmp_path / "audit.parquet"),
        analysis_date="2026-07-24",
    )

    module.run_pipeline(args)

    assert calls["export"] is extracted
    assert calls["daily_indices"] is extracted["level1_indices"]
    assert calls["research_members"]["股票代码"].tolist() == ["600000.SH"]
    assert calls["research_sectors"]["指数代码"].tolist() == ["881121"]
    assert calls["constituent_snapshot_date"] == "2026-07-24"


def test_load_fundamental_features_accepts_null_then_float_parquet_schema(
    monkeypatch,
    tmp_path: Path,
):
    module = load_module()
    first_dir = tmp_path / "year=2025" / "month=03"
    second_dir = tmp_path / "year=2026" / "month=03"
    first_dir.mkdir(parents=True)
    second_dir.mkdir(parents=True)
    common = {
        "htsc_code": ["600000.SH"],
        "income_report_date": [datetime(2024, 12, 31)],
        "income_announce_date": [datetime(2025, 3, 28)],
        "time": [datetime(2025, 3, 28)],
        "roe": [8.0],
        "net_roe": [8.5],
    }
    pl.DataFrame(
        {
            **common,
            "revenue_ttm": pl.Series([None], dtype=pl.Null),
            "net_profit_parent_ttm": pl.Series([None], dtype=pl.Null),
        }
    ).write_parquet(first_dir / "merged.parquet")
    pl.DataFrame(
        {
            **{
                **common,
                "income_report_date": [datetime(2025, 12, 31)],
                "income_announce_date": [datetime(2026, 3, 28)],
                "time": [datetime(2026, 3, 28)],
            },
            "revenue_ttm": [100.0],
            "net_profit_parent_ttm": [10.0],
        }
    ).write_parquet(second_dir / "merged.parquet")
    monkeypatch.setattr(
        module,
        "VALUATION_GLOB",
        str(tmp_path / "year=*" / "month=*" / "merged.parquet"),
    )
    members = pd.DataFrame(
        [{"指数代码": "881121", "股票代码": "600000.SH"}]
    )

    result = module.load_fundamental_features(members, "2026-07-29")

    assert result["sector_id"].tolist() == ["881121"]
    assert result["fundamental_covered_members"].tolist() == [1]
    assert result["median_net_margin_pct"].tolist() == [10.0]


def test_partition_writer_overwrites_same_date_and_keeps_other_dates(tmp_path: Path):
    module = load_module()
    first = pd.DataFrame([{"value": 1}])
    revised = pd.DataFrame([{"value": 2}])
    next_day = pd.DataFrame([{"value": 3}])

    module.write_partition(first, tmp_path, "constituent_snapshots_raw", "2026-07-24")
    module.write_partition(revised, tmp_path, "constituent_snapshots_raw", "2026-07-24")
    module.write_partition(next_day, tmp_path, "constituent_snapshots_raw", "2026-07-25")

    day_one = pl.read_parquet(
        tmp_path / "constituent_snapshots_raw" / "analysis_date=2026-07-24" / "part-000.parquet"
    )
    day_two = pl.read_parquet(
        tmp_path / "constituent_snapshots_raw" / "analysis_date=2026-07-25" / "part-000.parquet"
    )
    assert day_one["value"].to_list() == [2]
    assert day_two["value"].to_list() == [3]


def test_sector_csv_export_overwrites_previous_result(tmp_path: Path):
    module = load_module()

    def result(code: str) -> dict[str, object]:
        level_row = {
            "软件级别": "同花顺软件一级",
            "指数代码": code,
            "板块名称": "测试板块",
            "成分股数量": 1,
            "history_fetch_status": "成功",
        }
        return {
            "level_rows": {
                "同花顺软件一级": [level_row],
                "同花顺软件二级": [],
            },
            "constituent_rows": [
                {
                    "软件级别": "同花顺软件一级",
                    "指数代码": code,
                    "板块名称": "测试板块",
                    "股票代码": "600000.SH",
                }
            ],
        }

    module.write_sector_exports(result("881001"), tmp_path)
    module.write_sector_exports(result("881002"), tmp_path)

    sectors = pd.read_csv(tmp_path / "同花顺软件一级板块.csv", dtype=str, encoding="utf-8-sig")
    members = pd.read_csv(tmp_path / "同花顺软件板块成分股.csv", dtype=str, encoding="utf-8-sig")
    assert sectors["指数代码"].tolist() == ["881002"]
    assert members["指数代码"].tolist() == ["881002"]


def test_combined_entry_exposes_ths_stage_and_argument_passthrough():
    completed = subprocess.run(
        [
            sys.executable,
            str(ENTRY_PATH),
            "--dry-run",
            "--only",
            "ths_level1_index_daily",
            "--ths-level1-index-daily-args",
            "--end 2026-07-14",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "获得同花顺板块和成分股.py" in completed.stdout
    assert "--end 2026-07-14" in completed.stdout
