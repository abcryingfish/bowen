# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path

import duckdb
import pandas as pd


SCRIPT_PATH = Path(__file__).resolve().parent / "ZXW因子" / "ZXW策略技术因子生成.py"


def _load_market_source_helpers() -> dict:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8-sig"))
    wanted = {
        "BASE_PATH",
        "INDEX_BASE_PATH",
        "ETF_BASE_PATH",
        "MARKET_DAILY_SOURCE_PATHS",
        "_existing_market_daily_globs",
        "_market_daily_view_sql",
        "_build_factor_save_tasks",
        "_resolve_non_stock_fallback_target_codes",
    }
    selected: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names & wanted:
                selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted:
            selected.append(node)

    namespace: dict = {"Path": Path, "pd": pd}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SCRIPT_PATH), "exec"), namespace)
    return namespace


def _write_month(path: Path, code: str) -> None:
    month_dir = path / "year=2026" / "month=07"
    month_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "htsc_code": code,
                "time": pd.Timestamp("2026-07-01"),
                "open": 1.0,
                "high": 1.2,
                "low": 0.9,
                "close": 1.1,
                "volume": 100.0,
            }
        ]
    ).to_parquet(month_dir / "merged.parquet")


def test_market_daily_view_sql_reads_stock_index_and_etf_sources(tmp_path):
    helpers = _load_market_source_helpers()
    stock_root = tmp_path / "stock_basic_data_daily"
    index_root = tmp_path / "index_data_daily"
    etf_root = tmp_path / "ETF_basic_data_daily"
    missing_root = tmp_path / "missing_daily"
    _write_month(stock_root, "000001.SZ")
    _write_month(index_root, "000001.SH")
    _write_month(etf_root, "510300.SH")

    globs = helpers["_existing_market_daily_globs"](
        [stock_root, index_root, etf_root, missing_root]
    )
    sql = helpers["_market_daily_view_sql"]("market_day_merged", globs)

    con = duckdb.connect()
    con.execute(sql)
    result = con.execute(
        "SELECT htsc_code FROM market_day_merged ORDER BY htsc_code"
    ).df()

    assert result["htsc_code"].tolist() == ["000001.SH", "000001.SZ", "510300.SH"]


def test_build_factor_save_tasks_backfills_only_missing_codes_then_tail():
    helpers = _load_market_source_helpers()
    frame = pd.DataFrame(
        {
            "000001.SZ": [1.0, 2.0, 3.0],
            "510300.SH": [4.0, 5.0, 6.0],
        },
        index=pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-03"]),
    )

    tasks = helpers["_build_factor_save_tasks"](
        ch_name="示例因子",
        eng_name="demo_factor",
        factor_df=frame,
        base_dir=r"D:\database\signal_daily",
        start_dt=pd.Timestamp("2026-07-01"),
        end_dt=pd.Timestamp("2026-07-03"),
        existing_last_dt=pd.Timestamp("2026-07-02"),
        existing_codes={"000001.SZ"},
    )

    assert len(tasks) == 2
    assert tasks[0]["start_dt"] == pd.Timestamp("2026-07-01")
    assert tasks[0]["end_dt"] == pd.Timestamp("2026-07-02")
    assert list(tasks[0]["factor_df"].columns) == ["510300.SH"]
    assert tasks[1]["start_dt"] == pd.Timestamp("2026-07-03")
    assert tasks[1]["end_dt"] == pd.Timestamp("2026-07-03")
    assert list(tasks[1]["factor_df"].columns) == ["000001.SZ", "510300.SH"]


def test_default_auto_target_codes_prefers_non_stock_sources_when_no_precise_gap():
    helpers = _load_market_source_helpers()

    result = helpers["_resolve_non_stock_fallback_target_codes"](
        auto_plan=True,
        target_codes=None,
        prequery_target_codes=[],
        selected_bundles=["macd"],
        non_stock_source_codes={"000001.SH", "510300.SH"},
        needs_all_codes_for_date_tail=False,
    )

    assert result == ["000001.SH", "510300.SH"]


def test_date_tail_update_keeps_all_market_codes():
    helpers = _load_market_source_helpers()

    result = helpers["_resolve_non_stock_fallback_target_codes"](
        auto_plan=True,
        target_codes=None,
        prequery_target_codes=[],
        selected_bundles=["macd"],
        non_stock_source_codes={"000001.SH", "510300.SH"},
        needs_all_codes_for_date_tail=True,
    )

    assert result == []
