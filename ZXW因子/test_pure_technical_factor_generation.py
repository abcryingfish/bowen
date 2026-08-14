# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
import re
import sys
import importlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ZXW_DIR = Path(__file__).resolve().parent
if str(ZXW_DIR) not in sys.path:
    sys.path.append(str(ZXW_DIR))


def _load_runner():
    return importlib.import_module("纯技术面因子.将所有的技术面进行使用")


@pytest.fixture(scope="module")
def price_matrices() -> tuple[pd.DataFrame, ...]:
    index = pd.date_range("2025-01-01", periods=160, freq="B")
    columns = ["000001.SZ", "600000.SH", "000300.SH"]
    rng = np.random.default_rng(20260722)
    close = pd.DataFrame(
        100.0 + np.cumsum(rng.normal(0.0, 1.0, (len(index), len(columns))), axis=0),
        index=index,
        columns=columns,
    )
    open_ = close + rng.normal(0.0, 0.4, close.shape)
    high = pd.DataFrame(np.maximum(open_, close), index=index, columns=columns) + 1.0
    low = pd.DataFrame(np.minimum(open_, close), index=index, columns=columns) - 1.0
    volume = pd.DataFrame(
        rng.integers(10_000, 1_000_000, close.shape),
        index=index,
        columns=columns,
    ).astype(float)
    return open_, high, low, close, volume


def test_catalog_contains_401_unique_safe_factor_ids(tmp_path: Path) -> None:
    from 纯技术面因子_bundle import (
        INDICATOR_NAMES,
        get_factor_catalog,
        get_factor_lookback_config,
    )

    catalog = get_factor_catalog(
        force_refresh=True,
        cache_path=tmp_path / "pure_technical_factor_catalog_cache.json",
    )
    factor_map = catalog["factor_name_map"]
    factor_labels = catalog["factor_labels"]
    groups = catalog["groups"]

    assert catalog["bundle_id"] == "pure_technical"
    assert len(factor_map) == 401
    assert len(set(factor_map.values())) == 401
    assert len(set(factor_map)) == 401
    assert all(re.fullmatch(r"[A-Z0-9]+_[a-z0-9_]+", name) for name in factor_map.values())
    assert set(factor_labels) == set(factor_map.values())
    assert set(factor_labels.values()) == set(factor_map)
    assert all(re.fullmatch(r"[A-Z0-9]+_.+", label) for label in factor_labels.values())
    assert all(re.search(r"[\u4e00-\u9fff]", label) for label in factor_labels.values())
    assert factor_labels["MACD_golden_cross"] == "MACD_金叉"
    assert factor_labels["RSI_oversold_signal"] == "RSI_超卖信号"
    assert len(groups) == 18
    assert {group["indicator"] for group in groups} == set(INDICATOR_NAMES)
    assert sum(len(group["children"]) for group in groups) == 401

    lookback = get_factor_lookback_config()
    assert lookback["bundle_id"] == "pure_technical"
    assert set(lookback["factor_lookback_days"]) == set(factor_map.values())
    assert all(days == 520 for days in lookback["factor_lookback_days"].values())
    assert lookback["full_history_factor_keys"] == sorted(
        name for name in factor_map.values() if name.startswith("AMA_")
    )


def test_main_generator_preserves_pure_technical_display_mapping() -> None:
    source_path = Path(__file__).with_name("ZXW策略技术因子生成.py")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    mapper_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_factor_storage_name_map"
    )
    namespace: dict[str, object] = {}
    exec(
        compile(
            ast.Module(body=[mapper_node], type_ignores=[]),
            filename=str(source_path),
            mode="exec",
        ),
        namespace,
    )
    mapper = namespace["_factor_storage_name_map"]

    raw_map = {
        "ADX_金叉": "ADX_golden_cross",
        "RSI_超卖信号": "RSI_oversold_signal",
    }
    assert mapper("pure_technical", raw_map) == raw_map
    assert mapper("macd", raw_map) == raw_map
    compute_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "compute_selected_bundles"
    )
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_factor_storage_name_map"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "pure_technical"
        for node in ast.walk(compute_node)
    )


def test_iterator_runs_all_indicators_with_aligned_outputs(price_matrices) -> None:
    from 纯技术面因子_bundle import INDICATOR_NAMES, iter_pure_technical_factor_bundles

    open_, high, low, close, volume = price_matrices
    outputs = list(
        iter_pure_technical_factor_bundles(
            O=open_,
            H=high,
            L=low,
            C=close,
            V=volume,
        )
    )

    assert [output["indicator"] for output in outputs] == list(INDICATOR_NAMES)
    factor_ids: list[str] = []
    for output in outputs:
        assert output["factor_dfs"]
        assert set(output["factor_name_map"].values()) == set(output["factor_dfs"])
        for factor_id, frame in output["factor_dfs"].items():
            factor_ids.append(factor_id)
            assert frame.index.equals(close.index)
            assert frame.columns.equals(close.columns)
    assert len(factor_ids) == 401
    assert len(set(factor_ids)) == 401


@pytest.mark.parametrize("indicator", ["MACD", "RSI"])
def test_adjusted_matrix_adapter_matches_direct_special_interface(price_matrices, indicator: str) -> None:
    from 纯技术面因子_bundle import iter_pure_technical_factor_bundles

    module = __import__(f"纯技术面因子.{indicator}", fromlist=[indicator])
    indicator_class = getattr(module, indicator)
    open_, high, low, close, volume = price_matrices
    adjusted_high = high * 1.17
    adjusted_low = low * 1.17
    adjusted_close = close * 1.17

    output = next(
        iter_pure_technical_factor_bundles(
            O=open_,
            H=high,
            L=low,
            C=close,
            V=volume,
            H_adj=adjusted_high,
            L_adj=adjusted_low,
            C_adj=adjusted_close,
            selected_indicators=[indicator],
        )
    )
    direct = indicator_class().get_factor_matrices(
        open_, high, low, close, volume, adjusted_high, adjusted_low, adjusted_close
    )

    for signal_key, expected in direct.items():
        pd.testing.assert_frame_equal(output["factor_dfs"][f"{indicator}_{signal_key}"], expected)


def test_valid_bar_mask_restores_invalid_rows_as_zero(price_matrices) -> None:
    from 纯技术面因子_bundle import iter_pure_technical_factor_bundles

    open_, high, low, close, volume = price_matrices
    valid_bar = close.notna()
    invalid_day = close.index[80]
    valid_bar.loc[invalid_day, "000001.SZ"] = False

    output = next(
        iter_pure_technical_factor_bundles(
            O=open_,
            H=high,
            L=low,
            C=close,
            V=volume,
            valid_bar=valid_bar,
            selected_indicators=["MACD"],
        )
    )

    assert all(frame.loc[invalid_day, "000001.SZ"] == 0.0 for frame in output["factor_dfs"].values())


def test_market_loader_carries_last_backward_factor_for_missing_day(tmp_path: Path) -> None:
    runner = _load_runner()
    market_root = tmp_path / "market"
    duplicate_market_root = tmp_path / "duplicate_market"
    adj_root = tmp_path / "adj"
    market_dir = market_root / "year=2025" / "month=01"
    duplicate_market_dir = duplicate_market_root / "year=2025" / "month=01"
    adj_dir = adj_root / "year=2025" / "month=01"
    market_dir.mkdir(parents=True)
    duplicate_market_dir.mkdir(parents=True)
    adj_dir.mkdir(parents=True)

    market = pd.DataFrame(
        {
            "time": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "htsc_code": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 20.0],
            "high": [11.0, 21.0],
            "low": [9.0, 19.0],
            "close": [10.5, 20.5],
            "volume": [1000.0, 2000.0],
        }
    )
    adjustment = pd.DataFrame(
        {
            "time": pd.to_datetime(["2025-01-02"]),
            "htsc_code": ["000001.SZ"],
            "adj_factor": [2.0],
        }
    )
    market.to_parquet(market_dir / "merged.parquet", index=False)
    market.to_parquet(duplicate_market_dir / "merged.parquet", index=False)
    adjustment.to_parquet(adj_dir / "merged.parquet", index=False)

    loaded, stats = runner.load_adjusted_market_data(
        market_base_paths=[market_root, duplicate_market_root],
        adj_factor_base_path=adj_root,
        start_date="2025-01-01",
        end_date="2025-01-31",
    )

    loaded = loaded.set_index("time")
    assert loaded.loc[pd.Timestamp("2025-01-02"), "close"] == pytest.approx(21.0)
    assert loaded.loc[pd.Timestamp("2025-01-03"), "close"] == pytest.approx(41.0)
    assert stats == {"rows": 2, "matched_adj_rows": 2, "missing_adj_rows": 0}


def test_market_loader_falls_back_to_wide_xdy(tmp_path: Path) -> None:
    runner = _load_runner()
    market_root = tmp_path / "market"
    wide_root = tmp_path / "wide_xdy"
    market_dir = market_root / "year=2025" / "month=01"
    wide_dir = wide_root / "year=2025" / "month=01"
    market_dir.mkdir(parents=True)
    wide_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "time": pd.to_datetime(["2025-01-02"]),
            "htsc_code": ["000001.SZ"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
        }
    ).to_parquet(market_dir / "merged.parquet", index=False)
    pd.DataFrame(
        {"htsc_code": ["000001.SZ"], "2025/01/02": [2.0]}
    ).to_parquet(wide_dir / "merged.parquet", index=False)

    loaded, stats = runner.load_adjusted_market_data(
        market_base_paths=[market_root],
        adj_factor_base_path=tmp_path / "missing_adj",
        wide_xdy_base_path=wide_root,
        start_date="2025-01-01",
        end_date="2025-01-31",
    )

    assert loaded["close"].iloc[0] == pytest.approx(21.0)
    assert stats == {"rows": 1, "matched_adj_rows": 1, "missing_adj_rows": 0}


def test_wide_xdy_fallback_carries_previous_factor_across_date_gap(tmp_path: Path) -> None:
    runner = _load_runner()
    market = pd.DataFrame(
        {
            "time": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
            "htsc_code": ["000001.SZ"] * 3,
            "open": [10.0] * 3,
            "high": [10.0] * 3,
            "low": [10.0] * 3,
            "close": [10.0] * 3,
            "volume": [1000.0] * 3,
        }
    )
    wide_dir = tmp_path / "wide_xdy" / "year=2025" / "month=01"
    wide_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "htsc_code": ["000001.SZ"],
            "2025/01/02": [2.0],
            "2025/01/06": [2.0],
        }
    ).to_parquet(wide_dir / "merged.parquet", index=False)

    adjusted, matched = runner._apply_wide_xdy_backward(
        market,
        tmp_path / "wide_xdy",
        pd.Timestamp("2025-01-01"),
        pd.Timestamp("2025-01-31"),
    )

    assert adjusted["close"].tolist() == pytest.approx([20.0, 20.0, 20.0])
    assert matched == 3


def test_incremental_plan_handles_tail_new_codes_and_full_history() -> None:
    runner = _load_runner()
    factor_ids = ["ADX_golden_cross", "AMA_golden_cross", "RSI_golden_cross"]
    storage_summary = {
        "ADX_golden_cross": {
            "last_dt": pd.Timestamp("2025-01-08"),
            "codes": {"000001.SZ", "600000.SH"},
        },
        "AMA_golden_cross": {
            "last_dt": pd.Timestamp("2025-01-10"),
            "codes": {"000001.SZ"},
        },
        "RSI_golden_cross": {
            "last_dt": pd.Timestamp("2025-01-10"),
            "codes": {"000001.SZ", "600000.SH"},
        },
    }
    lookback = {
        "factor_lookback_days": {factor_id: 520 for factor_id in factor_ids},
        "full_history_factor_keys": ["AMA_golden_cross"],
    }

    plan = runner.build_incremental_plan(
        factor_ids=factor_ids,
        storage_summary=storage_summary,
        available_codes={"000001.SZ", "600000.SH"},
        start_date="2020-01-01",
        end_date="2025-01-10",
        lookback_config=lookback,
    ).set_index("factor_id")

    assert plan.loc["ADX_golden_cross", "status"] == "stale"
    assert plan.loc["ADX_golden_cross", "compute_start"] == pd.Timestamp("2023-08-07")
    assert plan.loc["ADX_golden_cross", "save_start"] == pd.Timestamp("2025-01-09")
    assert plan.loc["AMA_golden_cross", "status"] == "stale"
    assert plan.loc["AMA_golden_cross", "compute_start"] == pd.Timestamp("2020-01-01")
    assert plan.loc["AMA_golden_cross", "missing_codes"] == ("600000.SH",)
    assert plan.loc["RSI_golden_cross", "status"] == "up_to_date"
    assert pd.isna(plan.loc["RSI_golden_cross", "compute_start"])


def test_storage_summary_keeps_codes_from_earlier_months(tmp_path: Path) -> None:
    runner = _load_runner()
    factor_name = "ADX_golden_cross"
    factor_root = tmp_path / f"factor={factor_name}"
    frames = {
        (2025, 1): pd.DataFrame(
            {
                "time": pd.to_datetime(["2025-01-31"]),
                "htsc_code": ["000001.SZ"],
                "value": pd.Series([0.0], dtype="float32"),
            }
        ),
        (2025, 2): pd.DataFrame(
            {
                "time": pd.to_datetime(["2025-02-28"]),
                "htsc_code": ["600000.SH"],
                "value": pd.Series([1.0], dtype="float32"),
            }
        ),
    }
    for (year, month), frame in frames.items():
        month_dir = factor_root / f"year={year:04d}" / f"month={month:02d}"
        month_dir.mkdir(parents=True)
        frame.to_parquet(month_dir / "merged.parquet", index=False)

    summary = runner.load_factor_storage_summary(tmp_path, [factor_name])[factor_name]

    assert summary["last_dt"] == pd.Timestamp("2025-02-28")
    assert summary["codes"] == {"000001.SZ", "600000.SH"}


def test_dense_month_parts_compact_with_old_value_priority(tmp_path: Path) -> None:
    runner = _load_runner()
    factor_name = "ADX_golden_cross"
    index = pd.to_datetime(["2025-01-02", "2025-01-03"])
    first = pd.DataFrame(
        [[0.0, 0.5], [0.0, -0.5]],
        index=index,
        columns=["000001.SZ", "600000.SH"],
    )

    runner.write_factor_parts(
        factor_dfs={factor_name: first},
        output_base_dir=tmp_path,
        save_ranges={factor_name: (pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03"))},
        max_workers=1,
    )
    runner.compact_signal_daily_parts(tmp_path, factor_names=[factor_name], workers=1)

    merged_path = tmp_path / f"factor={factor_name}" / "year=2025" / "month=01" / "merged.parquet"
    merged = pd.read_parquet(merged_path).sort_values(["time", "htsc_code"]).reset_index(drop=True)
    assert list(merged.columns) == ["time", "htsc_code", "value"]
    assert len(merged) == 4
    assert merged["value"].dtype == np.float32
    assert (merged["value"] == 0.0).sum() == 2

    second = pd.DataFrame(
        [[9.0], [0.7]],
        index=pd.to_datetime(["2025-01-02", "2025-01-06"]),
        columns=["000001.SZ"],
    )
    runner.write_factor_parts(
        factor_dfs={factor_name: second},
        output_base_dir=tmp_path,
        save_ranges={factor_name: (pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-06"))},
        max_workers=1,
    )
    runner.compact_signal_daily_parts(tmp_path, factor_names=[factor_name], workers=1)

    merged = pd.read_parquet(merged_path)
    duplicate_key = merged[
        (pd.to_datetime(merged["time"]).dt.normalize() == pd.Timestamp("2025-01-02"))
        & (merged["htsc_code"] == "000001.SZ")
    ]
    assert duplicate_key["value"].iloc[0] == pytest.approx(0.0)
    assert len(merged) == 5


def test_atomic_writer_retries_replace_without_rewriting_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    frame = runner.pl.DataFrame(
        {
            "time": [pd.Timestamp("2025-01-02")],
            "htsc_code": ["000001.SZ"],
            "value": [np.float32(1.0)],
        }
    )
    target = tmp_path / "factor=TEST" / "year=2025" / "month=01" / "part_test.parquet"
    original_write = runner.pl.DataFrame.write_parquet
    original_replace = runner.os.replace
    write_count = 0
    replace_count = 0

    def recording_write(self, *args, **kwargs):
        nonlocal write_count
        write_count += 1
        return original_write(self, *args, **kwargs)

    def transient_replace(source, destination):
        nonlocal replace_count
        replace_count += 1
        if replace_count <= 3:
            raise PermissionError("simulated Windows scanner lock")
        return original_replace(source, destination)

    monkeypatch.setattr(runner.pl.DataFrame, "write_parquet", recording_write)
    monkeypatch.setattr(runner.os, "replace", transient_replace)
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)

    runner._write_parquet_atomic(frame, target, max_retries=5)

    assert target.is_file()
    assert write_count == 1
    assert replace_count == 4
    assert not (target.parent / ".__tmp_writes__").exists()


def test_atomic_writer_retries_transient_parquet_write_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    frame = runner.pl.DataFrame(
        {
            "time": [pd.Timestamp("2025-01-02")],
            "htsc_code": ["000001.SZ"],
            "value": [np.float32(1.0)],
        }
    )
    target = tmp_path / "factor=TEST" / "year=2025" / "month=01" / "part_test.parquet"
    original_write = runner.pl.DataFrame.write_parquet
    write_count = 0

    def transient_write(self, *args, **kwargs):
        nonlocal write_count
        write_count += 1
        if write_count <= 3:
            raise OSError("simulated Polars sink_parquet Windows lock")
        return original_write(self, *args, **kwargs)

    monkeypatch.setattr(runner.pl.DataFrame, "write_parquet", transient_write)
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)

    runner._write_parquet_atomic(frame, target, max_retries=5)

    assert target.is_file()
    assert write_count == 4
    assert not (target.parent / ".__tmp_writes__").exists()


def test_two_indicator_end_to_end_incremental_run(
    tmp_path: Path, price_matrices, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    open_, high, low, close, volume = price_matrices
    market_root = tmp_path / "market"
    adj_root = tmp_path / "adj"
    output_root = tmp_path / "signal_daily"

    records = []
    adjustment_records = []
    for date_value in close.index:
        for code in close.columns[:2]:
            records.append(
                {
                    "time": date_value,
                    "htsc_code": code,
                    "open": open_.loc[date_value, code],
                    "high": high.loc[date_value, code],
                    "low": low.loc[date_value, code],
                    "close": close.loc[date_value, code],
                    "volume": volume.loc[date_value, code],
                }
            )
            adjustment_records.append(
                {"time": date_value, "htsc_code": code, "adj_factor": 1.1}
            )
    market = pd.DataFrame(records)
    adjustment = pd.DataFrame(adjustment_records)
    for (year, month), group in market.groupby([market["time"].dt.year, market["time"].dt.month]):
        path = market_root / f"year={year:04d}" / f"month={month:02d}"
        path.mkdir(parents=True)
        group.to_parquet(path / "merged.parquet", index=False)
    for (year, month), group in adjustment.groupby(
        [adjustment["time"].dt.year, adjustment["time"].dt.month]
    ):
        path = adj_root / f"year={year:04d}" / f"month={month:02d}"
        path.mkdir(parents=True)
        group.to_parquet(path / "merged.parquet", index=False)

    observed_save_workers: list[int] = []
    market_load_count = 0
    matrix_build_count = 0
    original_write_factor_parts = runner.write_factor_parts
    original_load_adjusted_market_data = runner.load_adjusted_market_data
    original_build_price_matrices = runner._build_price_matrices

    def recording_write_factor_parts(**kwargs):
        observed_save_workers.append(int(kwargs["max_workers"]))
        return original_write_factor_parts(**kwargs)

    def recording_load_adjusted_market_data(**kwargs):
        nonlocal market_load_count
        market_load_count += 1
        return original_load_adjusted_market_data(**kwargs)

    def recording_build_price_matrices(frame):
        nonlocal matrix_build_count
        matrix_build_count += 1
        return original_build_price_matrices(frame)

    monkeypatch.setattr(runner, "write_factor_parts", recording_write_factor_parts)
    monkeypatch.setattr(runner, "load_adjusted_market_data", recording_load_adjusted_market_data)
    monkeypatch.setattr(runner, "_build_price_matrices", recording_build_price_matrices)
    args = runner.parse_args(
        [
            "--start-date",
            close.index.min().strftime("%Y-%m-%d"),
            "--end-date",
            close.index.max().strftime("%Y-%m-%d"),
            "--stock-base-path",
            str(market_root),
            "--index-base-path",
            str(tmp_path / "missing_index"),
            "--etf-base-path",
            str(tmp_path / "missing_etf"),
            "--adj-factor-base-path",
            str(adj_root),
            "--wide-xdy-base-path",
            str(tmp_path / "missing_wide"),
            "--output-base-dir",
            str(output_root),
            "--selected-indicators",
            "MACD",
            "RSI",
            "--target-factors",
            "MACD_golden_cross",
            "RSI_golden_cross",
            "--max-save-workers",
            "2",
            "--compact-workers",
            "1",
            "--code-batch-size",
            "1",
        ]
    )
    runner.run(args)
    assert 2 in observed_save_workers
    assert market_load_count == 2
    assert matrix_build_count == 2
    metadata_path = output_root / "_meta" / "pure_technical_factor_catalog_cache.json"
    assert metadata_path.is_file()
    metadata = __import__("json").loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["factor_labels"]["MACD_golden_cross"] == "MACD_金叉"

    for factor_name in ("MACD_golden_cross", "RSI_golden_cross"):
        paths = sorted((output_root / f"factor={factor_name}").glob("year=*/month=*/merged.parquet"))
        assert paths
        saved = pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)
        assert len(saved) == len(close.index) * 2
        assert not saved.duplicated(["time", "htsc_code"]).any()
        assert not list((output_root / f"factor={factor_name}").glob("year=*/month=*/part_*.parquet"))

    runner.run(args)
    for factor_name in ("MACD_golden_cross", "RSI_golden_cross"):
        paths = sorted((output_root / f"factor={factor_name}").glob("year=*/month=*/merged.parquet"))
        saved = pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)
        assert len(saved) == len(close.index) * 2
