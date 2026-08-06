from __future__ import annotations

import math

import pandas as pd
import pytest

from 股票市场数据因子 import (
    _resolve_source_paths,
    build_stock_market_data_factor_bundle,
    get_factor_catalog,
    get_factor_lookback_config,
)


EXPECTED_FACTOR_MAP = {
    "总市值": "total_market_value",
    "流通市值": "floating_market_value",
    "自由流通市值": "free_float_market_value",
    "换手率": "turnover_rate",
    "ln_自由流通市值": "ln_free_float_market_value",
}


def _write_source(path) -> None:
    pd.DataFrame(
        {
            "htsc_code": ["000001.SZ", "510300.SH", "881001.THS"],
            "time": pd.to_datetime(["2026-07-30"] * 3),
            "total_market_val": [1000.0, 2000.0, 3000.0],
            "floating_market_val": [800.0, 1600.0, 2400.0],
            "free_float_market_val": [600.0, 1200.0, 1800.0],
            "turnover_rate": [1.25, 2.5, 3.75],
        }
    ).to_parquet(path, index=False)


def test_partitioned_source_only_reads_requested_months(tmp_path) -> None:
    june = tmp_path / "year=2026" / "month=06" / "merged.parquet"
    july = tmp_path / "year=2026" / "month=07" / "merged.parquet"
    june.parent.mkdir(parents=True)
    july.parent.mkdir(parents=True)
    _write_source(june)
    _write_source(july)
    source_glob = str(
        tmp_path / "year=*" / "month=*" / "merged.parquet"
    )

    query_paths, latest_path = _resolve_source_paths(
        source_glob,
        pd.Timestamp("2026-07-01"),
        pd.Timestamp("2026-07-31"),
    )

    assert query_paths == [str(july)]
    assert latest_path == str(july)


def test_catalog_and_lookback_contract() -> None:
    assert get_factor_catalog()["factor_name_map"] == EXPECTED_FACTOR_MAP
    assert get_factor_lookback_config() == {
        "bundle_id": "stock_market_data",
        "bundle_lookback_days": 0,
        "factor_lookback_days": {
            "total_market_value": 0,
            "floating_market_value": 0,
            "free_float_market_value": 0,
            "turnover_rate": 0,
            "ln_free_float_market_value": 0,
        },
    }


def test_bundle_uses_source_values_and_explicit_stock_membership(tmp_path) -> None:
    source = tmp_path / "turnover.parquet"
    _write_source(source)
    close = pd.DataFrame(
        {
            "000001.SZ": [10.0],
            "510300.SH": [4.0],
            "881001.THS": [1.0],
        },
        index=pd.to_datetime(["2026-07-30"]),
    )

    result = build_stock_market_data_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_glob=str(source),
    )

    assert result["bundle_id"] == "stock_market_data"
    assert result["factor_name_map"] == EXPECTED_FACTOR_MAP
    assert list(result["factor_dfs"]["total_market_value"].columns) == ["000001.SZ"]
    assert result["factor_dfs"]["total_market_value"].loc[
        pd.Timestamp("2026-07-30"), "000001.SZ"
    ] == 1000.0
    assert result["factor_dfs"]["floating_market_value"].loc[
        pd.Timestamp("2026-07-30"), "000001.SZ"
    ] == 800.0
    assert result["factor_dfs"]["free_float_market_value"].loc[
        pd.Timestamp("2026-07-30"), "000001.SZ"
    ] == 600.0
    assert result["factor_dfs"]["ln_free_float_market_value"].loc[
        pd.Timestamp("2026-07-30"), "000001.SZ"
    ] == pytest.approx(math.log(600.0))
    assert result["factor_dfs"]["turnover_rate"].loc[
        pd.Timestamp("2026-07-30"), "000001.SZ"
    ] == 1.25


def test_log_market_value_is_nan_for_non_positive_source_value(tmp_path) -> None:
    source = tmp_path / "turnover.parquet"
    pd.DataFrame(
        {
            "htsc_code": ["000001.SZ", "000002.SZ"],
            "time": pd.to_datetime(["2026-07-30"] * 2),
            "total_market_val": [1000.0, 2000.0],
            "floating_market_val": [800.0, 1600.0],
            "free_float_market_val": [600.0, 0.0],
            "turnover_rate": [1.25, 2.5],
        }
    ).to_parquet(source, index=False)

    result = build_stock_market_data_factor_bundle(
        C=pd.DataFrame(
            {"000001.SZ": [10.0], "000002.SZ": [20.0]},
            index=pd.to_datetime(["2026-07-30"]),
        ),
        stock_codes={"000001.SZ", "000002.SZ"},
        source_glob=str(source),
    )

    assert pd.isna(
        result["factor_dfs"]["ln_free_float_market_value"].loc[
            pd.Timestamp("2026-07-30"), "000002.SZ"
        ]
    )


def test_bundle_preserves_missing_dates_instead_of_filling(tmp_path) -> None:
    source = tmp_path / "turnover.parquet"
    pd.DataFrame(
        {
            "htsc_code": ["000001.SZ", "000002.SZ"],
            "time": pd.to_datetime(["2026-07-30", "2026-07-31"]),
            "total_market_val": [1000.0, 2000.0],
            "floating_market_val": [800.0, 1600.0],
            "free_float_market_val": [600.0, 1200.0],
            "turnover_rate": [1.25, 2.5],
        }
    ).to_parquet(source, index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0, 10.1]},
        index=pd.to_datetime(["2026-07-30", "2026-07-31"]),
    )

    result = build_stock_market_data_factor_bundle(
        C=close,
        stock_codes={"000001.SZ"},
        source_glob=str(source),
    )

    assert pd.isna(
        result["factor_dfs"]["turnover_rate"].loc[
            pd.Timestamp("2026-07-31"), "000001.SZ"
        ]
    )


def test_bundle_rejects_stale_turnover_source(tmp_path) -> None:
    source = tmp_path / "turnover.parquet"
    _write_source(source)
    close = pd.DataFrame(
        {"000001.SZ": [10.0, 10.1]},
        index=pd.to_datetime(["2026-07-30", "2026-07-31"]),
    )

    try:
        build_stock_market_data_factor_bundle(
            C=close,
            stock_codes={"000001.SZ"},
            source_glob=str(source),
        )
    except ValueError as exc:
        assert "尚未更新到 2026-07-31" in str(exc)
    else:
        raise AssertionError("换手率源数据落后时必须停止生成，不能写入空值并推进水位")


def test_bundle_rejects_missing_requested_month_partition(tmp_path) -> None:
    june = tmp_path / "year=2026" / "month=06" / "merged.parquet"
    august = tmp_path / "year=2026" / "month=08" / "merged.parquet"
    june.parent.mkdir(parents=True)
    august.parent.mkdir(parents=True)
    _write_source(june)
    pd.DataFrame(
        {
            "htsc_code": ["000001.SZ"],
            "time": pd.to_datetime(["2026-08-01"]),
            "total_market_val": [1000.0],
            "floating_market_val": [800.0],
            "free_float_market_val": [600.0],
            "turnover_rate": [1.25],
        }
    ).to_parquet(august, index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0]},
        index=pd.to_datetime(["2026-07-30"]),
    )

    try:
        build_stock_market_data_factor_bundle(
            C=close,
            stock_codes={"000001.SZ"},
            source_glob=str(tmp_path / "year=*" / "month=*" / "merged.parquet"),
        )
    except ValueError as exc:
        assert "请求区间没有可读取的年月分区" in str(exc)
    else:
        raise AssertionError("请求月份缺失时必须停止生成，不能用整批空值推进水位")


def test_bundle_rejects_globally_missing_active_trading_day(tmp_path) -> None:
    source = tmp_path / "turnover.parquet"
    pd.DataFrame(
        {
            "htsc_code": ["000001.SZ"],
            "time": pd.to_datetime(["2026-07-31"]),
            "total_market_val": [1000.0],
            "floating_market_val": [800.0],
            "free_float_market_val": [600.0],
            "turnover_rate": [1.25],
        }
    ).to_parquet(source, index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0, 10.1]},
        index=pd.to_datetime(["2026-07-30", "2026-07-31"]),
    )

    try:
        build_stock_market_data_factor_bundle(
            C=close,
            stock_codes={"000001.SZ"},
            source_glob=str(source),
        )
    except ValueError as exc:
        assert "缺少有股票行情的交易日" in str(exc)
        assert "2026-07-30" in str(exc)
    else:
        raise AssertionError("交易日全市场源记录缺失时必须停止生成")


def test_bundle_reports_missing_required_source_column(tmp_path) -> None:
    source = tmp_path / "turnover.parquet"
    pd.DataFrame(
        {
            "htsc_code": ["000001.SZ"],
            "time": pd.to_datetime(["2026-07-30"]),
            "total_market_val": [1000.0],
            "floating_market_val": [800.0],
            "turnover_rate": [1.25],
        }
    ).to_parquet(source, index=False)
    close = pd.DataFrame(
        {"000001.SZ": [10.0]},
        index=pd.to_datetime(["2026-07-30"]),
    )

    with pytest.raises(
        ValueError,
        match="qmt_turnover_data 缺少字段.*free_float_market_val",
    ):
        build_stock_market_data_factor_bundle(
            C=close,
            stock_codes={"000001.SZ"},
            source_glob=str(source),
        )
