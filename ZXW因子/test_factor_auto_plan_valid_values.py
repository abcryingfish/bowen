from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


SCRIPT_PATH = Path(__file__).with_name("ZXW策略技术因子生成.py")
PLANNER_FUNCTIONS = {
    "_sanitize_factor_dir_name",
    "_collect_latest_factor_partition_paths",
    "_load_factor_last_date_map",
    "_get_factor_last_date",
    "_build_factor_scope_execution_plans",
    "_build_execution_code_windows",
    "_prepare_execution_market_long",
    "_build_execution_plan_market_frames",
    "_group_execution_plans_for_compute",
    "_momentum_compute_paths",
    "_select_window_sql",
    "_load_full_history_factor_keys",
    "build_factor_fill_plan",
}


def _load_planner_functions():
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8-sig"), filename=str(SCRIPT_PATH))
    selected = []
    selected_names = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in PLANNER_FUNCTIONS or node.name in selected_names:
            continue
        selected.append(node)
        selected_names.add(node.name)
    module = ast.Module(body=selected, type_ignores=[])
    namespace = {
        "os": os,
        "re": re,
        "Path": Path,
        "pd": pd,
        "con": duckdb.connect(database=":memory:"),
        "SECTOR_MARKET_FACTOR_KEYS": {
            "momentum_20d",
            "momentum_60d",
            "momentum_120d",
            "momentum_252d",
            "pure_momentum",
            "pure_momentum_60d",
            "pure_momentum_252d",
            "close_above_ma60",
            "annual_vol_60d",
        },
        "SECTOR_ONLY_MARKET_FACTOR_KEYS": {
            "sector_volatility_zscore_20d_252d",
            "sector_return_zscore_8d_252d",
            "sector_ewma_rms_zscore_252d",
        },
        "SECTOR_OUTPUT_FACTOR_KEYS": {
            "sector_volatility_zscore_20d_252d",
            "sector_return_zscore_8d_252d",
            "sector_ewma_rms_zscore_252d",
            "industry_pb_percentile_3y_mcap",
            "industry_pb_percentile_3y_median",
            "industry_pb_percentile_mcap",
            "industry_pb_percentile_median",
            "industry_profit_yoy_mcap",
            "industry_profit_yoy_median",
        },
        "SECTOR_AGGREGATE_FACTOR_KEYS": {
            "industry_pb_percentile_3y_mcap",
            "industry_pb_percentile_3y_median",
            "industry_pb_percentile_mcap",
            "industry_pb_percentile_median",
            "industry_profit_yoy_mcap",
            "industry_profit_yoy_median",
        },
        "THS_ONLY_FACTOR_KEYS": {
            "industry_pb_percentile_3y_mcap",
            "industry_pb_percentile_3y_median",
            "industry_pb_percentile_mcap",
            "industry_pb_percentile_median",
            "industry_profit_yoy_mcap",
            "industry_profit_yoy_median",
        },
        "VIEW_NAME": "stock_day_merged",
        "QUERY_START_DATE": "2010-01-01",
        "END_DATE": "2026-07-24",
        "_execution_code_windows_enabled": False,
        "_adj_factor_daily_join_sql": lambda data_sql: None,
    }
    exec(compile(module, str(SCRIPT_PATH), "exec"), namespace)
    return namespace


def _write_factor(tmp_path: Path, factor_name: str, frame: pd.DataFrame) -> None:
    month_dir = tmp_path / f"factor={factor_name}" / "year=2026" / "month=07"
    month_dir.mkdir(parents=True)
    frame.to_parquet(month_dir / "merged.parquet", index=False)


def test_factor_watermark_scan_only_reads_each_factors_latest_month(tmp_path) -> None:
    factor_dir = tmp_path / "factor=测试因子A" / "year=2026"
    for month in ("06", "07"):
        month_dir = factor_dir / f"month={month}"
        month_dir.mkdir(parents=True)
        pd.DataFrame(
            {
                "time": pd.to_datetime([f"2026-{month}-01"]),
                "htsc_code": ["000001.SZ"],
                "value": [1.0],
            }
        ).to_parquet(month_dir / "merged.parquet", index=False)

    staging_dir = factor_dir / "month=08"
    staging_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-08-01"]),
            "htsc_code": ["000001.SZ"],
            "value": [1.0],
        }
    ).to_parquet(staging_dir / "part_interrupted.parquet", index=False)

    paths = _load_planner_functions()["_collect_latest_factor_partition_paths"](str(tmp_path))

    assert len(paths) == 1
    assert "month=07" in paths[0].replace("\\", "/")
    assert paths[0].endswith("merged.parquet")


def test_auto_plan_uses_latest_row_dates_including_null_values(tmp_path) -> None:
    _write_factor(
        tmp_path,
        "测试因子A",
        pd.DataFrame(
            {
                "time": pd.to_datetime(["2026-07-23", "2026-07-24", "2026-07-23", "2026-07-24"]),
                "htsc_code": ["A.THS", "A.THS", "B.THS", "B.THS"],
                "value": [1.0, np.nan, np.nan, np.nan],
            }
        ),
    )
    _write_factor(
        tmp_path,
        "测试因子B",
        pd.DataFrame(
            {
                "time": pd.to_datetime(["2026-07-23", "2026-07-24"]),
                "htsc_code": ["A.THS", "A.THS"],
                "value": [np.nan, np.nan],
            }
        ),
    )
    planner = _load_planner_functions()

    last_dates = planner["_load_factor_last_date_map"](str(tmp_path))

    assert last_dates == {
        "测试因子A": pd.Timestamp("2026-07-24"),
        "测试因子B": pd.Timestamp("2026-07-24"),
    }
    assert planner["_get_factor_last_date"](str(tmp_path), "测试因子A") == pd.Timestamp("2026-07-24")
    assert planner["_get_factor_last_date"](str(tmp_path), "测试因子B") == pd.Timestamp("2026-07-24")


def test_execution_plans_keep_factor_scopes_and_start_dates_independent() -> None:
    planner = _load_planner_functions()
    plan_df = pd.DataFrame(
        [
            {
                "factor_en": "dif",
                "status": "stale",
                "plan_start": pd.Timestamp("2026-06-01"),
                "plan_end": pd.Timestamp("2026-07-24"),
            },
            {
                "factor_en": "momentum_120d",
                "status": "missing",
                "plan_start": pd.Timestamp("2020-01-01"),
                "plan_end": pd.Timestamp("2026-07-24"),
            },
            {
                "factor_en": "industry_pb_percentile_mcap",
                "status": "missing",
                "plan_start": pd.Timestamp("2010-01-01"),
                "plan_end": pd.Timestamp("2026-07-24"),
            },
        ]
    )

    plans = planner["_build_factor_scope_execution_plans"](
        factor_plan_df=plan_df,
        bundle_factor_catalog={
            "macd": {"DIF": "dif"},
            "momentum_common": {
                "120日动量": "momentum_120d",
                "板块PB历史分位_5年_整体法": "industry_pb_percentile_mcap",
            },
        },
        selected_bundles=["macd", "momentum_common"],
        standard_market_codes={"000001.SZ", "510300.SH"},
        stock_codes={"000001.SZ"},
        sector_codes={"881001.THS", "885001.THS"},
        factor_lookback_days={
            "dif": 60,
            "momentum_120d": 120,
            "industry_pb_percentile_mcap": 2000,
        },
        buffer_days=20,
    )

    by_factor = {
        plan["target_keys"][0]: plan
        for plan in plans
        if len(plan["target_keys"]) == 1
    }
    all_codes = ["000001.SZ", "510300.SH", "881001.THS", "885001.THS"]
    assert by_factor["dif"]["scope"] == "all_market"
    assert by_factor["dif"]["codes"] == all_codes
    assert by_factor["dif"]["query_start"] == pd.Timestamp("2026-03-13")
    assert by_factor["momentum_120d"]["scope"] == "all_market"
    assert by_factor["momentum_120d"]["codes"] == all_codes
    assert by_factor["industry_pb_percentile_mcap"]["scope"] == "ths_aggregate"
    assert by_factor["industry_pb_percentile_mcap"]["codes"] == ["000001.SZ"]
    assert by_factor["industry_pb_percentile_mcap"]["query_start"] == pd.Timestamp("2004-06-21")


def test_sector_volatility_zscore_executes_only_for_sector_market_codes() -> None:
    planner = _load_planner_functions()
    plan_df = pd.DataFrame(
        [
            {
                "factor_en": "sector_volatility_zscore_20d_252d",
                "status": "missing",
                "plan_start": pd.Timestamp("2020-01-01"),
                "plan_end": pd.Timestamp("2026-07-24"),
            }
        ]
    )

    plans = planner["_build_factor_scope_execution_plans"](
        factor_plan_df=plan_df,
        bundle_factor_catalog={
            "momentum_common": {
                "板块20日波动率ZScore_252日": "sector_volatility_zscore_20d_252d",
            }
        },
        selected_bundles=["momentum_common"],
        standard_market_codes={"000001.SZ", "510300.SH"},
        all_market_codes={"000001.SZ", "510300.SH", "881001.THS", "885001.THS"},
        stock_codes={"000001.SZ"},
        sector_codes={"881001.THS", "885001.THS"},
        factor_lookback_days={"sector_volatility_zscore_20d_252d": 420},
        buffer_days=20,
    )

    assert len(plans) == 1
    assert plans[0]["scope"] == "sector_market"
    assert plans[0]["codes"] == ["881001.THS", "885001.THS"]
    assert plans[0]["query_start"] == pd.Timestamp("2018-10-18")


def test_sector_volatility_target_skips_industry_aggregate_path() -> None:
    planner = _load_planner_functions()
    compute_market, compute_aggregate = planner["_momentum_compute_paths"](
        {"sector_volatility_zscore_20d_252d"}
    )
    assert compute_market is True
    assert compute_aggregate is False


def test_new_sector_short_move_factors_execute_only_for_sector_market_codes() -> None:
    planner = _load_planner_functions()
    factor_catalog = {
        "板块8日涨跌幅ZScore_252日": "sector_return_zscore_8d_252d",
        "板块EWMA_RMS移动强度ZScore_252日": "sector_ewma_rms_zscore_252d",
    }
    factor_keys = set(factor_catalog.values())
    plan_df = pd.DataFrame(
        [
            {
                "factor_en": factor_key,
                "status": "missing",
                "plan_start": pd.Timestamp("2020-01-01"),
                "plan_end": pd.Timestamp("2026-07-24"),
            }
            for factor_key in factor_keys
        ]
    )

    plans = planner["_build_factor_scope_execution_plans"](
        factor_plan_df=plan_df,
        bundle_factor_catalog={"momentum_common": factor_catalog},
        selected_bundles=["momentum_common"],
        standard_market_codes={"000001.SZ", "510300.SH"},
        all_market_codes={"000001.SZ", "510300.SH", "881001.THS", "885001.THS"},
        stock_codes={"000001.SZ"},
        sector_codes={"881001.THS", "885001.THS"},
        factor_lookback_days=dict.fromkeys(factor_keys, 420),
        buffer_days=20,
    )

    assert len(plans) == 1
    assert set(plans[0]["target_keys"]) == factor_keys
    assert plans[0]["scope"] == "sector_market"
    assert plans[0]["codes"] == ["881001.THS", "885001.THS"]
    assert plans[0]["query_start"] == pd.Timestamp("2020-01-01") - pd.Timedelta(days=440)
    assert planner["_momentum_compute_paths"](factor_keys) == (True, False)


def test_unknown_momentum_target_keeps_legacy_dual_path_fallback() -> None:
    planner = _load_planner_functions()
    compute_market, compute_aggregate = planner["_momentum_compute_paths"](
        {"legacy_unknown_factor"}
    )

    assert compute_market is True
    assert compute_aggregate is True


def test_only_pb_and_profit_industry_factors_use_ths_scope() -> None:
    planner = _load_planner_functions()
    plan_df = pd.DataFrame(
        [
            {"factor_en": "dif", "status": "missing", "plan_start": pd.Timestamp("2026-01-01"), "plan_end": pd.Timestamp("2026-07-24")},
            {"factor_en": "momentum_120d", "status": "missing", "plan_start": pd.Timestamp("2026-01-01"), "plan_end": pd.Timestamp("2026-07-24")},
            {"factor_en": "industry_pb_percentile_mcap", "status": "missing", "plan_start": pd.Timestamp("2010-01-01"), "plan_end": pd.Timestamp("2026-07-24")},
            {"factor_en": "industry_profit_yoy_mcap", "status": "missing", "plan_start": pd.Timestamp("2020-01-01"), "plan_end": pd.Timestamp("2026-07-24")},
        ]
    )
    plans = planner["_build_factor_scope_execution_plans"](
        factor_plan_df=plan_df,
        bundle_factor_catalog={
            "macd": {"DIF": "dif"},
            "momentum_common": {
                "120日动量": "momentum_120d",
                "板块PB历史分位_5年_整体法": "industry_pb_percentile_mcap",
                "行业净利润改善率_市值加权": "industry_profit_yoy_mcap",
            },
        },
        selected_bundles=["macd", "momentum_common"],
        standard_market_codes={"000001.SZ"},
        all_market_codes={"000001.SZ", "881001.THS", "510300.SH"},
        stock_codes={"000001.SZ"},
        sector_codes={"881001.THS"},
        factor_lookback_days={"dif": 60, "momentum_120d": 120, "industry_pb_percentile_mcap": 2000, "industry_profit_yoy_mcap": 365},
        buffer_days=20,
    )
    all_market_plans = [plan for plan in plans if plan["scope"] == "all_market"]
    assert all(plan["codes"] == ["000001.SZ", "510300.SH", "881001.THS"] for plan in all_market_plans)
    assert {key for plan in all_market_plans for key in plan["target_keys"]} == {"dif", "momentum_120d"}
    aggregate_plans = [plan for plan in plans if plan["scope"] == "ths_aggregate"]
    assert len(aggregate_plans) == 2
    assert all(plan["codes"] == ["000001.SZ"] for plan in aggregate_plans)
    assert {
        key
        for plan in aggregate_plans
        for key in plan["target_keys"]
    } == {"industry_pb_percentile_mcap", "industry_profit_yoy_mcap"}
def test_execution_code_windows_use_earliest_date_per_code() -> None:
    planner = _load_planner_functions()
    windows = planner["_build_execution_code_windows"](
        [
            {"codes": ["000001.SZ", "510300.SH"], "query_start": pd.Timestamp("2026-03-01")},
            {"codes": ["000001.SZ"], "query_start": pd.Timestamp("2004-06-21")},
            {"codes": ["881001.THS"], "query_start": pd.Timestamp("2019-08-14")},
        ]
    ).set_index("htsc_code")

    assert windows.loc["000001.SZ", "query_start"] == pd.Timestamp("2004-06-21")
    assert windows.loc["510300.SH", "query_start"] == pd.Timestamp("2026-03-01")
    assert windows.loc["881001.THS", "query_start"] == pd.Timestamp("2019-08-14")


def test_market_query_applies_each_codes_own_start_date() -> None:
    planner = _load_planner_functions()
    con = planner["con"]
    con.execute(
        """
        CREATE TABLE stock_day_merged AS
        SELECT * FROM (
            VALUES
                ('000001.SZ', DATE '2026-01-01', 10.0),
                ('000001.SZ', DATE '2026-01-02', 11.0),
                ('881001.THS', DATE '2025-01-01', 20.0)
        ) AS t(htsc_code, time, close)
        """
    )
    windows = pd.DataFrame(
        {
            "htsc_code": ["000001.SZ", "881001.THS"],
            "query_start": pd.to_datetime(["2026-01-02", "2025-01-01"]),
        }
    )
    con.register("_zxw_execution_code_windows", windows)
    planner["_execution_code_windows_enabled"] = True

    result = con.execute(planner["_select_window_sql"]("AND TRUE")).df()

    actual = {
        str(row["htsc_code"]): pd.Timestamp(row["time"])
        for _, row in result.iterrows()
    }
    assert actual == {
        "000001.SZ": pd.Timestamp("2026-01-02"),
        "881001.THS": pd.Timestamp("2025-01-01"),
    }


def test_fill_plan_does_not_compare_every_factor_with_global_code_count() -> None:
    planner = _load_planner_functions()
    planner["_load_lookback_registry"] = lambda bundles: (
        {},
        {"dif": 60, "momentum_120d": 120},
    )
    planner["_get_factor_last_date"] = lambda **kwargs: pd.Timestamp("2026-07-24")

    result = planner["build_factor_fill_plan"](
        factor_dfs_dict={},
        factor_name_map_dict={"DIF": "dif", "120日动量": "momentum_120d"},
        selected_bundles=["macd", "momentum_common"],
        start_date="2010-01-01",
        end_date="2026-07-24",
        base_dir="unused",
        buffer_days=20,
        available_factor_keys={"dif", "momentum_120d"},
    ).set_index("factor_en")

    assert result.loc["dif", "status"] == "up_to_date"
    assert result.loc["momentum_120d", "status"] == "up_to_date"


def test_batch_watermark_unifies_existing_factor_tail_and_keeps_new_factor_full_history() -> None:
    planner = _load_planner_functions()
    planner["_load_lookback_registry"] = lambda bundles: (
        {},
        {"dif": 60, "new_factor": 120},
    )

    result = planner["build_factor_fill_plan"](
        factor_dfs_dict={},
        factor_name_map_dict={"DIF": "dif", "新增因子": "new_factor"},
        selected_bundles=["macd"],
        start_date="2010-01-01",
        end_date="2026-07-29",
        base_dir="unused",
        buffer_days=20,
        available_factor_keys={"dif", "new_factor"},
        factor_last_dt_map={"DIF": pd.Timestamp("2026-07-24")},
        batch_complete_date=pd.Timestamp("2026-07-24"),
    ).set_index("factor_en")

    assert result.loc["dif", "plan_start"] == pd.Timestamp("2026-07-25")
    assert "因子水位" in result.loc["dif", "reason"]
    assert result.loc["new_factor", "plan_start"] == pd.Timestamp("2010-01-01")
    assert result.loc["new_factor", "status"] == "missing"


def test_batch_watermark_does_not_hide_factor_behind_watermark() -> None:
    planner = _load_planner_functions()
    planner["_load_lookback_registry"] = lambda bundles: ({}, {"dif": 60})

    result = planner["build_factor_fill_plan"](
        factor_dfs_dict={},
        factor_name_map_dict={"DIF": "dif"},
        selected_bundles=["macd"],
        start_date="2010-01-01",
        end_date="2026-07-29",
        base_dir="unused",
        buffer_days=20,
        available_factor_keys={"dif"},
        factor_last_dt_map={"DIF": pd.Timestamp("2026-07-20")},
        batch_complete_date=pd.Timestamp("2026-07-24"),
    ).iloc[0]

    assert result["plan_start"] == pd.Timestamp("2026-07-21")


def test_stale_full_history_factor_restarts_from_start_date() -> None:
    planner = _load_planner_functions()
    planner["_load_lookback_registry"] = lambda bundles: (
        {},
        {"ama_golden_cross": 520, "dif": 60},
    )
    planner["_load_full_history_factor_keys"] = lambda bundles: {"ama_golden_cross"}
    planner["_get_factor_last_date"] = lambda **kwargs: pd.Timestamp("2026-07-24")

    result = planner["build_factor_fill_plan"](
        factor_dfs_dict={},
        factor_name_map_dict={"AMA金叉": "ama_golden_cross", "DIF": "dif"},
        selected_bundles=["pure_technical", "macd"],
        start_date="2010-01-01",
        end_date="2026-07-29",
        base_dir="unused",
        buffer_days=20,
        available_factor_keys={"ama_golden_cross", "dif"},
    ).set_index("factor_en")

    assert result.loc["ama_golden_cross", "plan_start"] == pd.Timestamp("2010-01-01")
    assert "全历史因子" in result.loc["ama_golden_cross", "reason"]
    assert result.loc["dif", "plan_start"] == pd.Timestamp("2026-07-25")


def test_load_full_history_factor_keys_unions_selected_bundle_metadata() -> None:
    planner = _load_planner_functions()
    planner["BUNDLE_LOOKBACK_LOADERS"] = {
        "pure_technical": lambda: {
            "full_history_factor_keys": [" AMA_1 ", "AMA_2", ""]
        },
        "macd": lambda: {"full_history_factor_keys": ["MACD_SIGNAL"]},
    }

    result = planner["_load_full_history_factor_keys"](
        ["pure_technical", "macd", "unknown"]
    )

    assert result == {"AMA_1", "AMA_2", "MACD_SIGNAL"}


def test_factor_last_date_is_authoritative_when_batch_watermark_lags() -> None:
    planner = _load_planner_functions()
    planner["_load_lookback_registry"] = lambda bundles: ({}, {"dif": 60})

    result = planner["build_factor_fill_plan"](
        factor_dfs_dict={},
        factor_name_map_dict={"DIF": "dif"},
        selected_bundles=["macd"],
        start_date="2010-01-01",
        end_date="2026-07-30",
        base_dir="unused",
        buffer_days=20,
        available_factor_keys={"dif"},
        factor_last_dt_map={"DIF": pd.Timestamp("2026-07-29")},
        batch_complete_date=pd.Timestamp("2026-07-24"),
    ).iloc[0]

    assert result["plan_start"] == pd.Timestamp("2026-07-30")


def test_factor_tail_executes_full_code_scope() -> None:
    planner = _load_planner_functions()
    planner["_load_lookback_registry"] = lambda bundles: ({}, {"dif": 60})
    fill_plan = planner["build_factor_fill_plan"](
        factor_dfs_dict={},
        factor_name_map_dict={"DIF": "dif"},
        selected_bundles=["macd"],
        start_date="2010-01-01",
        end_date="2026-07-29",
        base_dir="unused",
        buffer_days=20,
        available_factor_keys={"dif"},
        factor_last_dt_map={"DIF": pd.Timestamp("2026-07-24")},
        batch_complete_date=pd.Timestamp("2026-07-24"),
    )

    execution_plan = planner["_build_factor_scope_execution_plans"](
        factor_plan_df=fill_plan,
        bundle_factor_catalog={"macd": {"DIF": "dif"}},
        selected_bundles=["macd"],
        standard_market_codes={"000001.SZ", "688825.SH"},
        all_market_codes={"000001.SZ", "688825.SH"},
        stock_codes={"000001.SZ", "688825.SH"},
        sector_codes=set(),
        factor_lookback_days={"dif": 60},
        buffer_days=20,
    )[0]

    assert execution_plan["codes"] == ["000001.SZ", "688825.SH"]
    assert execution_plan["plan_start"] == pd.Timestamp("2026-07-25")
    assert execution_plan["query_start"] == pd.Timestamp("2026-05-06")


def test_sector_aggregate_increment_rewinds_only_in_execution_query() -> None:
    planner = _load_planner_functions()
    planner["_load_lookback_registry"] = lambda bundles: (
        {},
        {"industry_pb_percentile_mcap": 2000},
    )
    planner["_get_factor_last_date"] = lambda **kwargs: pd.Timestamp("2026-07-20")

    fill_plan = planner["build_factor_fill_plan"](
        factor_dfs_dict={},
        factor_name_map_dict={
            "板块PB历史分位_5年_整体法": "industry_pb_percentile_mcap"
        },
        selected_bundles=["momentum_common"],
        start_date="2010-01-01",
        end_date="2026-07-24",
        base_dir="unused",
        buffer_days=20,
        available_factor_keys={"industry_pb_percentile_mcap"},
    )
    row = fill_plan.iloc[0]
    assert row["plan_start"] == pd.Timestamp("2026-07-21")

    execution_plan = planner["_build_factor_scope_execution_plans"](
        factor_plan_df=fill_plan,
        bundle_factor_catalog={
            "momentum_common": {
                "板块PB历史分位_5年_整体法": "industry_pb_percentile_mcap"
            }
        },
        selected_bundles=["momentum_common"],
        standard_market_codes={"000001.SZ"},
        stock_codes={"000001.SZ"},
        sector_codes={"881001.THS"},
        factor_lookback_days={"industry_pb_percentile_mcap": 2000},
        buffer_days=20,
    )[0]
    assert execution_plan["query_start"] == pd.Timestamp("2021-01-08")


def test_sector_volatility_increment_rewinds_only_in_execution_query() -> None:
    planner = _load_planner_functions()
    planner["_load_lookback_registry"] = lambda bundles: (
        {},
        {"sector_volatility_zscore_20d_252d": 420},
    )
    planner["_get_factor_last_date"] = lambda **kwargs: pd.Timestamp("2026-07-20")

    fill_plan = planner["build_factor_fill_plan"](
        factor_dfs_dict={},
        factor_name_map_dict={
            "板块20日波动率ZScore_252日": "sector_volatility_zscore_20d_252d"
        },
        selected_bundles=["momentum_common"],
        start_date="2010-01-01",
        end_date="2026-07-24",
        base_dir="unused",
        buffer_days=20,
        available_factor_keys={"sector_volatility_zscore_20d_252d"},
    )
    row = fill_plan.iloc[0]
    assert row["plan_start"] == pd.Timestamp("2026-07-21")

    execution_plan = planner["_build_factor_scope_execution_plans"](
        factor_plan_df=fill_plan,
        bundle_factor_catalog={
            "momentum_common": {
                "板块20日波动率ZScore_252日": "sector_volatility_zscore_20d_252d"
            }
        },
        selected_bundles=["momentum_common"],
        standard_market_codes={"000001.SZ"},
        stock_codes={"000001.SZ"},
        sector_codes={"881001.THS"},
        factor_lookback_days={"sector_volatility_zscore_20d_252d": 420},
        buffer_days=20,
    )[0]
    assert execution_plan["query_start"] == pd.Timestamp("2026-07-21") - pd.Timedelta(days=440)


def test_standard_market_increment_rewinds_only_in_execution_query() -> None:
    planner = _load_planner_functions()
    planner["_load_lookback_registry"] = lambda bundles: ({}, {"dif": 60})
    planner["_get_factor_last_date"] = lambda **kwargs: pd.Timestamp("2026-07-20")

    fill_plan = planner["build_factor_fill_plan"](
        factor_dfs_dict={},
        factor_name_map_dict={"DIF": "dif"},
        selected_bundles=["macd"],
        start_date="2010-01-01",
        end_date="2026-07-24",
        base_dir="unused",
        buffer_days=20,
        available_factor_keys={"dif"},
    )
    row = fill_plan.iloc[0]
    assert row["plan_start"] == pd.Timestamp("2026-07-21")

    execution_plan = planner["_build_factor_scope_execution_plans"](
        factor_plan_df=fill_plan,
        bundle_factor_catalog={"macd": {"DIF": "dif"}},
        selected_bundles=["macd"],
        standard_market_codes={"000001.SZ"},
        stock_codes={"000001.SZ"},
        sector_codes={"881001.THS"},
        factor_lookback_days={"dif": 60},
        buffer_days=20,
    )[0]
    assert execution_plan["query_start"] == pd.Timestamp("2026-05-02")


def test_factor_tail_execution_plan_keeps_full_scope_without_coverage_filter() -> None:
    planner = _load_planner_functions()
    plan_df = pd.DataFrame(
        [
            {
                "factor_cn": "DIF",
                "factor_en": "dif",
                "status": "stale",
                "reason": "因子水位=2026-07-23，需尾部补到2026-07-24",
                "plan_start": pd.Timestamp("2026-07-24"),
                "plan_end": pd.Timestamp("2026-07-24"),
            }
        ]
    )

    plans = planner["_build_factor_scope_execution_plans"](
        factor_plan_df=plan_df,
        bundle_factor_catalog={"macd": {"DIF": "dif"}},
        selected_bundles=["macd"],
        standard_market_codes={"000001.SZ", "510300.SH"},
        stock_codes={"000001.SZ"},
        sector_codes={"881001.THS"},
        factor_lookback_days={"dif": 60},
        buffer_days=20,
    )

    assert len(plans) == 1
    assert plans[0]["codes"] == ["000001.SZ", "510300.SH", "881001.THS"]


def test_three_and_five_year_pb_share_one_aggregate_execution() -> None:
    planner = _load_planner_functions()
    plan_df = pd.DataFrame(
        [
            {
                "factor_cn": "板块PB历史分位_3年_整体法",
                "factor_en": "industry_pb_percentile_3y_mcap",
                "status": "missing",
                "reason": "因子目录不存在或无历史数据",
                "plan_start": pd.Timestamp("2010-01-01"),
                "plan_end": pd.Timestamp("2026-07-24"),
            },
            {
                "factor_cn": "板块PB历史分位_5年_整体法",
                "factor_en": "industry_pb_percentile_mcap",
                "status": "missing",
                "reason": "因子目录不存在或无历史数据",
                "plan_start": pd.Timestamp("2010-01-01"),
                "plan_end": pd.Timestamp("2026-07-24"),
            },
        ]
    )
    catalog = {
        "momentum_common": {
            "板块PB历史分位_3年_整体法": "industry_pb_percentile_3y_mcap",
            "板块PB历史分位_5年_整体法": "industry_pb_percentile_mcap",
        }
    }

    plans = planner["_build_factor_scope_execution_plans"](
        factor_plan_df=plan_df,
        bundle_factor_catalog=catalog,
        selected_bundles=["momentum_common"],
        standard_market_codes={"000001.SZ"},
        stock_codes={"000001.SZ"},
        sector_codes={"881001.THS"},
        factor_lookback_days={
            "industry_pb_percentile_3y_mcap": 1300,
            "industry_pb_percentile_mcap": 2000,
        },
        buffer_days=20,
    )

    assert len(plans) == 1
    assert set(plans[0]["target_keys"]) == {
        "industry_pb_percentile_3y_mcap",
        "industry_pb_percentile_mcap",
    }
    assert plans[0]["lookback_days"] == 2000
    assert plans[0]["query_start"] == pd.Timestamp("2004-06-21")


def test_execution_plan_market_frames_only_expand_requested_window() -> None:
    planner = _load_planner_functions()
    source = pd.DataFrame(
        {
            "time": pd.to_datetime([
                "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-01", "2026-01-02"
            ]),
            "htsc_code": ["A.SZ", "A.SZ", "A.SZ", "B.SZ", "B.SZ"],
            "open": [1.0, 2.0, 3.0, 10.0, 20.0],
            "high": [1.1, 2.1, 3.1, 10.1, 20.1],
            "low": [0.9, 1.9, 2.9, 9.9, 19.9],
            "close": [1.0, 2.0, 3.0, 10.0, 20.0],
            "volume": [100.0, 200.0, 300.0, 1000.0, 2000.0],
        }
    )

    prepared = planner["_prepare_execution_market_long"](source)
    assert prepared.index.names == ["htsc_code", "time"]
    assert prepared.index.is_monotonic_increasing

    frames = planner["_build_execution_plan_market_frames"](
        prepared,
        codes=["A.SZ"],
        query_start=pd.Timestamp("2026-01-02"),
        plan_end=pd.Timestamp("2026-01-03"),
    )

    assert frames is not None
    assert list(frames["C"].columns) == ["A.SZ"]
    assert list(frames["C"].index) == [
        pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-03")
    ]


def test_execution_market_long_normalizes_codes_and_dates_once() -> None:
    planner = _load_planner_functions()
    source = pd.DataFrame(
        {
            "time": ["2026-01-02 15:00:00", "2026-01-01 09:30:00"],
            "htsc_code": [" a.sz ", "B.sz"],
            "open": [2.0, 10.0],
            "high": [2.1, 10.1],
            "low": [1.9, 9.9],
            "close": [2.0, 10.0],
            "volume": [200.0, 1000.0],
        }
    )

    prepared = planner["_prepare_execution_market_long"](source)

    assert list(prepared.index) == [
        ("A.SZ", pd.Timestamp("2026-01-02")),
        ("B.SZ", pd.Timestamp("2026-01-01")),
    ]


def test_same_scope_execution_plans_share_one_compute_batch() -> None:
    planner = _load_planner_functions()
    plans = [
        {
            "bundle": "chip_structure",
            "scope": "standard_market",
            "target_keys": ["chip_peak_score"],
            "codes": ["A.SZ", "B.SZ"],
            "query_start": pd.Timestamp("2025-01-01"),
            "plan_start": pd.Timestamp("2025-06-01"),
            "plan_end": pd.Timestamp("2026-01-01"),
        },
        {
            "bundle": "total_buy_signal",
            "scope": "standard_market",
            "target_keys": ["total_buy_signal"],
            "codes": ["A.SZ", "B.SZ"],
            "query_start": pd.Timestamp("2025-03-01"),
            "plan_start": pd.Timestamp("2025-07-01"),
            "plan_end": pd.Timestamp("2026-01-01"),
        },
    ]

    batches = planner["_group_execution_plans_for_compute"](plans)

    assert len(batches) == 1
    assert batches[0]["bundles"] == ["chip_structure", "total_buy_signal"]
    assert batches[0]["query_start"] == pd.Timestamp("2025-01-01")
    assert batches[0]["plan_start"] == pd.Timestamp("2025-06-01")
    assert set(batches[0]["target_keys"]) == {"chip_peak_score", "total_buy_signal"}
