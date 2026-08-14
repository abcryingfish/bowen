from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd

import 板块动量策略常用因子 as momentum_common
from valid_bar_utils import compute_bundles_with_valid_bar
from 板块动量策略常用因子 import (
    build_industry_factor_bundle,
    build_momentum_factor_bundle,
    get_factor_lookback_config,
    select_ths_columns,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOMENTUM_FACTOR_NAMES = {
    "5日动量",
    "20日动量",
    "60日动量",
    "120日动量",
    "252日动量",
    "纯动量",
    "60日纯动量",
    "252日纯动量",
    "收盘价高于MA60",
    "60日年化波动率",
    "板块20日波动率ZScore_252日",
    "板块8日涨跌幅ZScore_252日",
    "板块EWMA_RMS移动强度ZScore_252日",
    "板块PB历史分位_3年_整体法",
    "板块PB历史分位_3年_中位数",
    "板块PB历史分位_5年_整体法",
    "板块PB历史分位_5年_中位数",
    "行业净利润改善率_市值加权",
    "行业净利润改善率_中位数",
}


def test_sector_momentum_module_uses_accurate_filename() -> None:
    factor_dir = Path(__file__).resolve().parent
    assert (factor_dir / "板块动量策略常用因子.py").is_file()
    assert not (factor_dir / "动量策略常用因子.py").exists()


def test_sector_market_factors_select_only_ths_columns() -> None:
    columns = pd.Index([
        "000001.SZ",
        "510300.SH",
        "881101.THS",
        "882001.ths",
        "885001.THS ",
        "886001.THS",
    ])

    assert list(select_ths_columns(columns)) == [
        "881101.THS",
        "882001.ths",
        "885001.THS ",
        "886001.THS",
    ]


def test_industry_bundle_accepts_valid_bar_matrix() -> None:
    assert "valid_bar" in inspect.signature(build_industry_factor_bundle).parameters


def test_pb_only_event_window_starts_at_requested_start_date() -> None:
    start_date = pd.Timestamp("2026-07-21")
    assert momentum_common._industry_event_start(start_date, want_profit=False) == start_date


def test_profit_event_window_keeps_previous_year_reports() -> None:
    start_date = pd.Timestamp("2026-07-21")
    assert momentum_common._industry_event_start(
        start_date, want_profit=True
    ) == start_date - pd.Timedelta(days=550)


def test_momentum_factors_are_registered_in_frontend_catalog() -> None:
    catalog_path = PROJECT_ROOT / "因子分类" / "factor_catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    group = next(item for item in catalog["groups"] if item["group_id"] == "momentum_common")

    assert group["group_name"] == "动量策略常用因子"
    assert group["core_factors"] == ["120日动量"]
    assert set(group["children"]) == MOMENTUM_FACTOR_NAMES
    assert "120日动量" in catalog["core_factors"]


def test_frontend_refreshes_snapshot_after_factor_catalog_loads() -> None:
    source_path = PROJECT_ROOT / "可视化" / "量化因子" / "board_quant.js"
    source = source_path.read_text(encoding="utf-8")
    load_body = source.split("async function loadFactorOptions()", 1)[1].split(
        "async function refreshSignalData", 1
    )[0]

    assert "rightPanelSnapshotCache.clear()" in load_body
    assert "scheduleFactorSnapshotForRightPanel(" in load_body

    index_source = (PROJECT_ROOT / "可视化" / "量化因子" / "index.html").read_text(encoding="utf-8-sig")
    assert "board_quant.js?v=momentum-catalog-refresh-20260727" in index_source


def test_momentum_bundle_calculates_requested_factors() -> None:
    index = pd.date_range("2025-01-01", periods=320, freq="D")
    daily_returns = 0.001 + 0.01 * np.sin(np.arange(len(index), dtype=float) / 7.0)
    close = pd.DataFrame(
        {"881001.THS": 100.0 * np.cumprod(1.0 + daily_returns)},
        index=index,
    )

    result = build_momentum_factor_bundle(C=close)
    factors = result["factor_dfs"]

    expected_momentum = close / close.shift(120) - 1
    expected_pure = expected_momentum - (close / close.shift(20) - 1)
    expected_vol = close.pct_change().rolling(60, min_periods=60).std() * np.sqrt(252)
    expected_vol_20d = close.pct_change().rolling(20, min_periods=20).std() * np.sqrt(252)
    expected_log_vol = np.log(expected_vol_20d.where(expected_vol_20d > 0.0))
    expected_zscore = (
        (expected_log_vol - expected_log_vol.rolling(252, min_periods=120).mean())
        / expected_log_vol.rolling(252, min_periods=120).std().replace(0.0, np.nan)
    ).clip(lower=-3.0, upper=3.0)

    pd.testing.assert_frame_equal(factors["momentum_120d"], expected_momentum)
    pd.testing.assert_frame_equal(factors["pure_momentum"], expected_pure)
    pd.testing.assert_frame_equal(factors["annual_vol_60d"], expected_vol)
    pd.testing.assert_frame_equal(
        factors["sector_volatility_zscore_20d_252d"], expected_zscore
    )
    pd.testing.assert_frame_equal(factors["close_above_ma60"], (close > close.rolling(60).mean()).astype(float))
    assert set(factors) == {
        "momentum_5d",
        "momentum_120d",
        "momentum_20d",
        "momentum_60d",
        "momentum_252d",
        "pure_momentum",
        "pure_momentum_60d",
        "pure_momentum_252d",
        "close_above_ma60",
        "annual_vol_60d",
        "sector_volatility_zscore_20d_252d",
        "sector_return_zscore_8d_252d",
        "sector_ewma_rms_zscore_252d",
    }


def test_multi_period_momentum_uses_requested_lookback_windows() -> None:
    index = pd.date_range("2020-01-01", periods=300, freq="D")
    close = pd.DataFrame(
        {"881001.THS": np.arange(100.0, 400.0)},
        index=index,
    )

    factors = build_momentum_factor_bundle(C=close)["factor_dfs"]
    pd.testing.assert_frame_equal(factors["momentum_5d"], close / close.shift(5) - 1)

    for window in (20, 60, 120, 252):
        pd.testing.assert_frame_equal(
            factors[f"momentum_{window}d"],
            close / close.shift(window) - 1.0,
        )
    pd.testing.assert_frame_equal(
        factors["pure_momentum_60d"],
        (close / close.shift(60) - 1.0) - (close / close.shift(20) - 1.0),
    )
    pd.testing.assert_frame_equal(
        factors["pure_momentum_252d"],
        (close / close.shift(252) - 1.0) - (close / close.shift(20) - 1.0),
    )


def test_sector_short_move_factors_match_vectorized_formulas_and_direction() -> None:
    index = pd.date_range("2024-01-01", periods=360, freq="D")
    phase = np.arange(len(index), dtype=float)
    base_returns = 0.001 + 0.004 * np.sin(phase / 9.0)
    up_returns = base_returns.copy()
    down_returns = base_returns.copy()
    stock_returns = base_returns.copy()
    up_returns[-8:] = 0.018
    down_returns[-8:] = -0.018
    close = pd.DataFrame(
        {
            "881001.THS": 100.0 * np.exp(np.cumsum(up_returns)),
            "881002.THS": 100.0 * np.exp(np.cumsum(down_returns)),
            "000001.SZ": 20.0 * np.exp(np.cumsum(stock_returns)),
        },
        index=index,
    )

    factors = build_momentum_factor_bundle(C=close)["factor_dfs"]
    sector_close = close[["881001.THS", "881002.THS"]]
    sector_price = sector_close.where(sector_close > 0.0)

    move_8d = np.log(sector_price / sector_price.shift(8))
    move_mean = move_8d.rolling(252, min_periods=120).mean()
    move_std = move_8d.rolling(252, min_periods=120).std()
    expected_move = (
        (move_8d - move_mean) / move_std.replace(0.0, np.nan)
    ).clip(-3.0, 3.0).where(sector_close.notna())

    log_return = np.log(sector_price / sector_price.shift(1))
    ewma_rms = np.sqrt(
        252.0
        * log_return.pow(2).ewm(
            halflife=5,
            adjust=False,
            min_periods=1,
        ).mean()
    )
    log_rms = np.log(ewma_rms.where(ewma_rms > 0.0))
    rms_mean = log_rms.rolling(252, min_periods=120).mean()
    rms_std = log_rms.rolling(252, min_periods=120).std()
    expected_rms = (
        (log_rms - rms_mean) / rms_std.replace(0.0, np.nan)
    ).clip(-3.0, 3.0).where(sector_close.notna())

    pd.testing.assert_frame_equal(
        factors["sector_return_zscore_8d_252d"], expected_move
    )
    pd.testing.assert_frame_equal(
        factors["sector_ewma_rms_zscore_252d"], expected_rms
    )
    assert expected_move.iloc[-1, 0] > 0.0
    assert expected_move.iloc[-1, 1] < 0.0
    assert (expected_rms.iloc[-1] > 0.0).all()
    assert not np.isinf(expected_move.to_numpy()).any()
    assert not np.isinf(expected_rms.to_numpy()).any()


def test_sector_volatility_zscore_is_vectorized_and_handles_zero_volatility() -> None:
    index = pd.date_range("2025-01-01", periods=320, freq="D")
    close = pd.DataFrame({"881001.THS": 100.0}, index=index)

    factor = build_momentum_factor_bundle(C=close)["factor_dfs"][
        "sector_volatility_zscore_20d_252d"
    ]

    assert factor.isna().all().all()
    assert not np.isinf(factor.to_numpy()).any()
    function_tree = ast.parse(inspect.getsource(build_momentum_factor_bundle))
    assert not any(isinstance(node, (ast.For, ast.AsyncFor)) for node in ast.walk(function_tree))


def test_sector_volatility_zscore_ignores_non_ths_columns() -> None:
    index = pd.date_range("2025-01-01", periods=320, freq="D")
    phase = np.arange(len(index), dtype=float)
    close = pd.DataFrame(
        {
            "000001.SZ": 100.0 * np.cumprod(1.001 + 0.01 * np.sin(phase / 7.0)),
            "510300.SH": 100.0 * np.cumprod(1.001 + 0.01 * np.cos(phase / 8.0)),
            "881001.THS": 100.0 * np.cumprod(1.001 + 0.01 * np.sin(phase / 9.0)),
        },
        index=index,
    )

    factor = build_momentum_factor_bundle(C=close)["factor_dfs"][
        "sector_volatility_zscore_20d_252d"
    ]

    assert list(factor.columns) == ["881001.THS"]


def test_sector_volatility_merge_preserves_columns_and_nan_without_changing_legacy_fill() -> None:
    index = pd.date_range("2025-01-01", periods=320, freq="D")
    phase = np.arange(len(index), dtype=float)
    base = 100.0 * np.cumprod(1.001 + 0.01 * np.sin(phase / 7.0))
    close = pd.DataFrame(
        {
            "880001.THS": base * 0.99,
            "000001.SZ": base,
            "881001.THS": base * 1.01,
        },
        index=index,
    )
    valid_bar = pd.DataFrame(True, index=index, columns=close.columns)
    gap_date = index[200]
    valid_bar.loc[gap_date, "880001.THS"] = False
    close.loc[gap_date, "880001.THS"] = np.nan
    filled_close = close.ffill()

    def raw_compute(**kwargs):
        return {"momentum_common"}, [build_momentum_factor_bundle(C=kwargs["C"])]

    _, bundles = compute_bundles_with_valid_bar(
        raw_compute,
        O=filled_close,
        H=filled_close,
        L=filled_close,
        C=filled_close,
        V=filled_close,
        selected_bundles=["momentum_common"],
        valid_bar=valid_bar,
    )
    factors = bundles[0]["factor_dfs"]
    zscore = factors["sector_volatility_zscore_20d_252d"]
    move_zscore = factors["sector_return_zscore_8d_252d"]
    rms_zscore = factors["sector_ewma_rms_zscore_252d"]

    assert list(zscore.columns) == ["880001.THS", "881001.THS"]
    assert list(move_zscore.columns) == ["880001.THS", "881001.THS"]
    assert list(rms_zscore.columns) == ["880001.THS", "881001.THS"]
    assert zscore.iloc[:139].isna().all().all()
    assert np.isnan(zscore.loc[gap_date, "880001.THS"])
    assert np.isnan(move_zscore.loc[gap_date, "880001.THS"])
    assert np.isnan(rms_zscore.loc[gap_date, "880001.THS"])

    legacy_momentum = factors["momentum_120d"]
    assert list(legacy_momentum.columns) == ["880001.THS", "000001.SZ", "881001.THS"]
    assert legacy_momentum.loc[index[50], "000001.SZ"] == 0.0
    assert legacy_momentum.loc[gap_date, "880001.THS"] == 0.0


def test_momentum_bundle_exposes_lookback_and_names() -> None:
    config = get_factor_lookback_config()
    assert config["bundle_id"] == "momentum_common"
    assert config["bundle_lookback_days"] == 2000
    assert config["factor_lookback_days"]["momentum_120d"] == 120
    assert config["factor_lookback_days"]["sector_volatility_zscore_20d_252d"] == 420
    assert config["factor_lookback_days"]["sector_return_zscore_8d_252d"] == 420
    assert config["factor_lookback_days"]["sector_ewma_rms_zscore_252d"] == 420
    assert config["factor_lookback_days"]["industry_pb_percentile_3y_mcap"] == 1300
    assert config["factor_lookback_days"]["industry_pb_percentile_3y_median"] == 1300
    assert config["factor_lookback_days"]["industry_pb_percentile_mcap"] == 2000
    assert config["factor_lookback_days"]["industry_pb_percentile_median"] == 2000


def test_industry_aggregation_counts_each_stock_once_per_sector(tmp_path) -> None:
    snapshot_path = tmp_path / "snapshot.parquet"
    valuation_path = tmp_path / "valuation.parquet"

    pd.DataFrame(
        {
            "sector_code": ["S1.THS", "S2.THS", "S1.THS"],
            "stock_code": ["A.SZ", "A.SZ", "B.SZ"],
            "eligible": [True, True, True],
        }
    ).to_parquet(snapshot_path, index=False)

    pd.DataFrame(
        {
            "htsc_code": ["A.SZ", "A.SZ", "B.SZ", "B.SZ"],
            "time": pd.to_datetime(["2025-01-10", "2026-01-12", "2025-01-10", "2026-01-12"]),
            "income_report_date": pd.to_datetime(["2024-12-31", "2025-12-31", "2024-12-31", "2025-12-31"]),
            "income_announce_date": pd.to_datetime(["2025-01-10", "2026-01-10", "2025-01-10", "2026-01-10"]),
            "pb": [1.0, 1.0, 1.0, 1.0],
            "total_market_val": [100.0, 100.0, 100.0, 100.0],
            "net_profit_parent_ttm": [100.0, 200.0, 100.0, 100.0],
        }
    ).to_parquet(valuation_path, index=False)

    result = build_industry_factor_bundle(
        dates=pd.DatetimeIndex(["2026-01-12"]),
        stock_codes=pd.Index(["A.SZ", "B.SZ"]),
        snapshot_path=snapshot_path,
        valuation_glob=valuation_path.as_posix(),
    )

    actual = result["factor_dfs"]["industry_profit_yoy_mcap"].loc[pd.Timestamp("2026-01-12"), "S1.THS"]
    assert np.isclose(actual, 1.0 / 3.0)


def test_industry_profit_factor_uses_improvement_rate_for_negative_base(tmp_path) -> None:
    snapshot_path = tmp_path / "snapshot.parquet"
    valuation_path = tmp_path / "valuation.parquet"
    stocks = ["TURN.SZ", "NARROW.SZ", "WIDEN.SZ", "LOSS.SZ"]
    sectors = ["TURN.THS", "NARROW.THS", "WIDEN.THS", "LOSS.THS"]

    pd.DataFrame(
        {
            "sector_code": sectors,
            "stock_code": stocks,
            "eligible": [True] * 4,
        }
    ).to_parquet(snapshot_path, index=False)

    previous_profit = [-10.0, -10.0, -5.0, 10.0]
    current_profit = [2.0, -5.0, -10.0, -2.0]
    rows = []
    for stock, previous, current in zip(stocks, previous_profit, current_profit, strict=True):
        rows.extend(
            [
                {
                    "htsc_code": stock,
                    "time": pd.Timestamp("2025-01-10"),
                    "income_report_date": pd.Timestamp("2024-12-31"),
                    "income_announce_date": pd.Timestamp("2025-01-10"),
                    "pb": 1.0,
                    "total_market_val": 100.0,
                    "net_profit_parent_ttm": previous,
                },
                {
                    "htsc_code": stock,
                    "time": pd.Timestamp("2026-01-12"),
                    "income_report_date": pd.Timestamp("2025-12-31"),
                    "income_announce_date": pd.Timestamp("2026-01-10"),
                    "pb": 1.0,
                    "total_market_val": 100.0,
                    "net_profit_parent_ttm": current,
                },
            ]
        )
    pd.DataFrame(rows).to_parquet(valuation_path, index=False)

    result = build_industry_factor_bundle(
        dates=pd.DatetimeIndex(["2026-01-12"]),
        stock_codes=pd.Index(stocks),
        snapshot_path=snapshot_path,
        valuation_glob=valuation_path.as_posix(),
    )
    factor = result["factor_dfs"]["industry_profit_yoy_mcap"].loc[pd.Timestamp("2026-01-12")]

    expected = {
        "TURN.THS": 2.0,
        "NARROW.THS": 2.0 / 3.0,
        "WIDEN.THS": -2.0 / 3.0,
        "LOSS.THS": -2.0,
    }
    for sector, value in expected.items():
        assert np.isclose(factor[sector], value)


def test_industry_aggregation_keeps_suspended_stock_in_constituent_scope(tmp_path) -> None:
    snapshot_path = tmp_path / "snapshot.parquet"
    valuation_path = tmp_path / "valuation.parquet"
    dates = pd.DatetimeIndex(["2026-01-12", "2026-01-13"])

    pd.DataFrame(
        {
            "sector_code": ["S1.THS", "S1.THS"],
            "stock_code": ["A.SZ", "B.SZ"],
            "eligible": [True, True],
        }
    ).to_parquet(snapshot_path, index=False)

    rows = []
    for stock, current_profit in (("A.SZ", 200.0), ("B.SZ", 100.0)):
        rows.append(
            {
                "htsc_code": stock,
                "time": pd.Timestamp("2025-01-10"),
                "income_report_date": pd.Timestamp("2024-12-31"),
                "income_announce_date": pd.Timestamp("2025-01-10"),
                "pb": 1.0,
                "total_market_val": 100.0,
                "net_profit_parent_ttm": 100.0,
            }
        )
        for trade_date in dates:
            rows.append(
                {
                    "htsc_code": stock,
                    "time": trade_date,
                    "income_report_date": pd.Timestamp("2025-12-31"),
                    "income_announce_date": pd.Timestamp("2026-01-10"),
                    "pb": 1.0,
                    "total_market_val": 100.0,
                    "net_profit_parent_ttm": current_profit,
                }
            )
    pd.DataFrame(rows).to_parquet(valuation_path, index=False)

    valid_bar = pd.DataFrame(
        {
            "A.SZ": [False, True],
            "B.SZ": [True, True],
        },
        index=dates,
    )
    result = build_industry_factor_bundle(
        dates=dates,
        stock_codes=pd.Index(["A.SZ", "B.SZ"]),
        valid_bar=valid_bar,
        snapshot_path=snapshot_path,
        valuation_glob=valuation_path.as_posix(),
    )
    factor = result["factor_dfs"]["industry_profit_yoy_mcap"]["S1.THS"]

    assert np.isclose(factor.loc[pd.Timestamp("2026-01-12")], 1.0 / 3.0)
    assert np.isclose(factor.loc[pd.Timestamp("2026-01-13")], 1.0 / 3.0)


def test_industry_pb_window_carries_latest_value_across_missing_valuation_day(tmp_path, monkeypatch) -> None:
    snapshot_path = tmp_path / "snapshot.parquet"
    valuation_path = tmp_path / "valuation.parquet"
    valuation_dates = pd.to_datetime([
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
        "2026-01-09",
    ])
    requested_dates = pd.to_datetime([
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
        "2026-01-08",
        "2026-01-09",
    ])

    pd.DataFrame(
        {
            "sector_code": ["S1.THS"],
            "stock_code": ["A.SZ"],
            "eligible": [True],
        }
    ).to_parquet(snapshot_path, index=False)
    pd.DataFrame(
        {
            "htsc_code": ["A.SZ"] * len(valuation_dates),
            "time": valuation_dates,
            "income_report_date": pd.to_datetime(["2025-09-30"] * len(valuation_dates)),
            "income_announce_date": pd.to_datetime(["2025-10-30"] * len(valuation_dates)),
            "pb": [1.0, 2.0, 3.0, 4.0],
            "total_market_val": [100.0] * len(valuation_dates),
            "net_profit_parent_ttm": [10.0] * len(valuation_dates),
        }
    ).to_parquet(valuation_path, index=False)
    monkeypatch.setattr(momentum_common, "_INDUSTRY_PB_PERCENTILE_WINDOW_5Y", 3)

    result = build_industry_factor_bundle(
        dates=requested_dates,
        stock_codes=pd.Index(["A.SZ"]),
        snapshot_path=snapshot_path,
        valuation_glob=valuation_path.as_posix(),
    )
    factor = result["factor_dfs"]["industry_pb_percentile_median"]["S1.THS"]

    assert np.isclose(factor.loc[pd.Timestamp("2026-01-08")], 5.0 / 6.0)
    assert np.isclose(factor.loc[pd.Timestamp("2026-01-09")], 1.0)


def test_industry_pb_does_not_fill_from_future_valuation_row(tmp_path, monkeypatch) -> None:
    snapshot_path = tmp_path / "snapshot.parquet"
    valuation_path = tmp_path / "valuation.parquet"
    requested_dates = pd.to_datetime(["2026-01-05", "2026-01-06"])

    pd.DataFrame(
        {
            "sector_code": ["S1.THS"],
            "stock_code": ["A.SZ"],
            "eligible": [True],
        }
    ).to_parquet(snapshot_path, index=False)
    pd.DataFrame(
        {
            "htsc_code": ["A.SZ"],
            "time": pd.to_datetime(["2026-01-06"]),
            "income_report_date": pd.to_datetime(["2025-09-30"]),
            "income_announce_date": pd.to_datetime(["2025-10-30"]),
            "pb": [2.0],
            "total_market_val": [100.0],
            "net_profit_parent_ttm": [10.0],
        }
    ).to_parquet(valuation_path, index=False)
    monkeypatch.setattr(momentum_common, "_INDUSTRY_PB_PERCENTILE_WINDOW_5Y", 1)

    result = build_industry_factor_bundle(
        dates=requested_dates,
        stock_codes=pd.Index(["A.SZ"]),
        snapshot_path=snapshot_path,
        valuation_glob=valuation_path.as_posix(),
        target_factor_keys={"industry_pb_percentile_median"},
    )
    factor = result["factor_dfs"]["industry_pb_percentile_median"]["S1.THS"]

    assert np.isnan(factor.loc[pd.Timestamp("2026-01-05")])
    assert np.isclose(factor.loc[pd.Timestamp("2026-01-06")], 1.0)


def test_industry_pb_mcap_uses_aggregate_market_value_to_book_equity(tmp_path, monkeypatch) -> None:
    snapshot_path = tmp_path / "snapshot.parquet"
    valuation_path = tmp_path / "valuation.parquet"
    dates = pd.to_datetime(["2026-01-05", "2026-01-06"])

    pd.DataFrame(
        {
            "sector_code": ["S1.THS", "S1.THS"],
            "stock_code": ["A.SZ", "B.SZ"],
            "eligible": [True, True],
        }
    ).to_parquet(snapshot_path, index=False)
    pd.DataFrame(
        {
            "htsc_code": ["A.SZ", "B.SZ", "A.SZ", "B.SZ"],
            "time": [dates[0], dates[0], dates[1], dates[1]],
            "income_report_date": pd.to_datetime(["2025-09-30"] * 4),
            "income_announce_date": pd.to_datetime(["2025-10-30"] * 4),
            "pb": [100.0, 1.0, 2.0, 1.2],
            "total_market_val": [100.0, 900.0, 100.0, 900.0],
            "net_profit_parent_ttm": [10.0] * 4,
        }
    ).to_parquet(valuation_path, index=False)
    monkeypatch.setattr(momentum_common, "_INDUSTRY_PB_PERCENTILE_WINDOW_5Y", 2)

    result = build_industry_factor_bundle(
        dates=dates,
        stock_codes=pd.Index(["A.SZ", "B.SZ"]),
        snapshot_path=snapshot_path,
        valuation_glob=valuation_path.as_posix(),
    )
    factor = result["factor_dfs"]["industry_pb_percentile_mcap"]["S1.THS"]

    # 整体法：第1日 PB=1000/(100/100+900/1)，第2日 PB=1000/(100/2+900/1.2)。
    # 第2日整体PB更高，因此两日窗口中的历史分位应为1；算术市值加权会错误得到0.5。
    assert np.isclose(factor.loc[dates[1]], 1.0)


def test_industry_pb_bundle_generates_distinct_three_and_five_year_percentiles(tmp_path, monkeypatch) -> None:
    snapshot_path = tmp_path / "snapshot.parquet"
    valuation_path = tmp_path / "valuation.parquet"
    dates = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"])

    pd.DataFrame(
        {
            "sector_code": ["S1.THS"],
            "stock_code": ["A.SZ"],
            "eligible": [True],
        }
    ).to_parquet(snapshot_path, index=False)
    pd.DataFrame(
        {
            "htsc_code": ["A.SZ"] * 3,
            "time": dates,
            "income_report_date": pd.to_datetime(["2025-09-30"] * 3),
            "income_announce_date": pd.to_datetime(["2025-10-30"] * 3),
            "pb": [1.0, 3.0, 2.0],
            "total_market_val": [100.0] * 3,
            "net_profit_parent_ttm": [10.0] * 3,
        }
    ).to_parquet(valuation_path, index=False)
    monkeypatch.setattr(momentum_common, "_INDUSTRY_PB_PERCENTILE_WINDOW_3Y", 2)
    monkeypatch.setattr(momentum_common, "_INDUSTRY_PB_PERCENTILE_WINDOW_5Y", 3)

    result = build_industry_factor_bundle(
        dates=dates,
        stock_codes=pd.Index(["A.SZ"]),
        snapshot_path=snapshot_path,
        valuation_glob=valuation_path.as_posix(),
    )
    factors = result["factor_dfs"]

    assert np.isclose(factors["industry_pb_percentile_3y_mcap"].loc[dates[-1], "S1.THS"], 0.5)
    assert np.isclose(factors["industry_pb_percentile_mcap"].loc[dates[-1], "S1.THS"], 2.0 / 3.0)
    assert result["factor_name_map"]["板块PB历史分位_3年_整体法"] == "industry_pb_percentile_3y_mcap"
    assert result["factor_name_map"]["板块PB历史分位_5年_整体法"] == "industry_pb_percentile_mcap"


def test_industry_profit_mcap_uses_previous_day_market_cap_weighted_symmetric_rate(
    tmp_path,
) -> None:
    snapshot_path = tmp_path / "snapshot.parquet"
    valuation_path = tmp_path / "valuation.parquet"

    pd.DataFrame(
        {
            "sector_code": ["S1.THS", "S1.THS"],
            "stock_code": ["A.SZ", "B.SZ"],
            "eligible": [True, True],
        }
    ).to_parquet(snapshot_path, index=False)
    pd.DataFrame(
        {
            "htsc_code": ["A.SZ", "B.SZ", "A.SZ", "B.SZ", "A.SZ", "B.SZ"],
            "time": pd.to_datetime(
                [
                    "2025-01-10",
                    "2025-01-10",
                    "2026-01-09",
                    "2026-01-09",
                    "2026-01-12",
                    "2026-01-12",
                ]
            ),
            "income_report_date": pd.to_datetime(
                [
                    "2024-12-31",
                    "2024-12-31",
                    "2024-12-31",
                    "2024-12-31",
                    "2025-12-31",
                    "2025-12-31",
                ]
            ),
            "income_announce_date": pd.to_datetime(
                [
                    "2025-01-10",
                    "2025-01-10",
                    "2025-01-10",
                    "2025-01-10",
                    "2026-01-10",
                    "2026-01-10",
                ]
            ),
            "pb": [1.0] * 6,
            # 当日市值与上一交易日市值反转，确保权重没有错误使用当日值。
            "total_market_val": [900.0, 100.0, 900.0, 100.0, 100.0, 900.0],
            "net_profit_parent_ttm": [1.0, 999.0, 1.0, 999.0, 101.0, 999.0],
        }
    ).to_parquet(valuation_path, index=False)

    result = build_industry_factor_bundle(
        dates=pd.DatetimeIndex(["2026-01-12"]),
        stock_codes=pd.Index(["A.SZ", "B.SZ"]),
        snapshot_path=snapshot_path,
        valuation_glob=valuation_path.as_posix(),
    )
    factor = result["factor_dfs"]["industry_profit_yoy_mcap"]

    a_improvement = 2.0 * (101.0 - 1.0) / (abs(101.0) + abs(1.0))
    expected = (900.0 * a_improvement + 100.0 * 0.0) / 1000.0
    assert np.isclose(factor.loc[pd.Timestamp("2026-01-12"), "S1.THS"], expected)


def test_industry_profit_mcap_averages_symmetric_rates_for_equal_weights(tmp_path) -> None:
    snapshot_path = tmp_path / "snapshot.parquet"
    valuation_path = tmp_path / "valuation.parquet"

    pd.DataFrame(
        {
            "sector_code": ["S1.THS", "S1.THS"],
            "stock_code": ["A.SZ", "B.SZ"],
            "eligible": [True, True],
        }
    ).to_parquet(snapshot_path, index=False)
    pd.DataFrame(
        {
            "htsc_code": ["A.SZ", "B.SZ", "A.SZ", "B.SZ"],
            "time": pd.to_datetime(["2025-01-10", "2025-01-10", "2026-01-12", "2026-01-12"]),
            "income_report_date": pd.to_datetime(["2024-12-31", "2024-12-31", "2025-12-31", "2025-12-31"]),
            "income_announce_date": pd.to_datetime(["2025-01-10", "2025-01-10", "2026-01-10", "2026-01-10"]),
            "pb": [1.0] * 4,
            "total_market_val": [100.0] * 4,
            "net_profit_parent_ttm": [100.0, -99.0, 110.0, -95.0],
        }
    ).to_parquet(valuation_path, index=False)

    result = build_industry_factor_bundle(
        dates=pd.DatetimeIndex(["2026-01-12"]),
        stock_codes=pd.Index(["A.SZ", "B.SZ"]),
        snapshot_path=snapshot_path,
        valuation_glob=valuation_path.as_posix(),
    )
    factor = result["factor_dfs"]["industry_profit_yoy_mcap"]

    a_improvement = 2.0 * (110.0 - 100.0) / (abs(110.0) + abs(100.0))
    b_improvement = 2.0 * (-95.0 - -99.0) / (abs(-95.0) + abs(-99.0))
    assert np.isclose(
        factor.loc[pd.Timestamp("2026-01-12"), "S1.THS"],
        (a_improvement + b_improvement) / 2.0,
    )


def test_industry_bundle_profit_only_does_not_require_pb_columns(tmp_path) -> None:
    snapshot_path = tmp_path / "snapshot.parquet"
    valuation_path = tmp_path / "valuation.parquet"
    pd.DataFrame(
        {"sector_code": ["S1.THS"], "stock_code": ["A.SZ"], "eligible": [True]}
    ).to_parquet(snapshot_path, index=False)
    pd.DataFrame(
        {
            "htsc_code": ["A.SZ", "A.SZ"],
            "time": pd.to_datetime(["2025-01-10", "2026-01-12"]),
            "income_report_date": pd.to_datetime(["2024-12-31", "2025-12-31"]),
            "income_announce_date": pd.to_datetime(["2025-01-10", "2026-01-10"]),
            "total_market_val": [100.0, 100.0],
            "net_profit_parent_ttm": [100.0, 120.0],
        }
    ).to_parquet(valuation_path, index=False)

    result = build_industry_factor_bundle(
        dates=pd.DatetimeIndex(["2026-01-12"]),
        stock_codes=pd.Index(["A.SZ"]),
        snapshot_path=snapshot_path,
        valuation_glob=valuation_path.as_posix(),
        target_factor_keys={"industry_profit_yoy_mcap"},
    )

    assert set(result["factor_dfs"]) == {"industry_profit_yoy_mcap"}
    assert result["factor_name_map"] == {
        "行业净利润改善率_市值加权": "industry_profit_yoy_mcap"
    }
    assert np.isclose(
        result["factor_dfs"]["industry_profit_yoy_mcap"].loc[
            pd.Timestamp("2026-01-12"), "S1.THS"
        ],
        2.0 / 11.0,
    )


def test_industry_bundle_pb_only_does_not_require_profit_columns(tmp_path, monkeypatch) -> None:
    snapshot_path = tmp_path / "snapshot.parquet"
    valuation_path = tmp_path / "valuation.parquet"
    dates = pd.to_datetime(["2026-01-05", "2026-01-06"])
    pd.DataFrame(
        {"sector_code": ["S1.THS"], "stock_code": ["A.SZ"], "eligible": [True]}
    ).to_parquet(snapshot_path, index=False)
    pd.DataFrame(
        {
            "htsc_code": ["A.SZ", "A.SZ"],
            "time": dates,
            "income_announce_date": pd.to_datetime(["2025-10-30", "2025-10-30"]),
            "pb": [1.0, 2.0],
            "total_market_val": [100.0, 100.0],
        }
    ).to_parquet(valuation_path, index=False)
    monkeypatch.setattr(momentum_common, "_INDUSTRY_PB_PERCENTILE_WINDOW_3Y", 2)

    result = build_industry_factor_bundle(
        dates=dates,
        stock_codes=pd.Index(["A.SZ"]),
        snapshot_path=snapshot_path,
        valuation_glob=valuation_path.as_posix(),
        target_factor_keys={"industry_pb_percentile_3y_mcap"},
    )

    assert set(result["factor_dfs"]) == {"industry_pb_percentile_3y_mcap"}
    assert result["factor_name_map"] == {
        "板块PB历史分位_3年_整体法": "industry_pb_percentile_3y_mcap"
    }
    assert np.isclose(
        result["factor_dfs"]["industry_pb_percentile_3y_mcap"].loc[dates[-1], "S1.THS"],
        1.0,
    )
