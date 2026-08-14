# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from 纯技术面因子.AMA import (
    AMA,
    ama_state_cache_covers,
    build_ama_factor_matrices_with_state,
    commit_ama_state_cache,
    discard_pending_ama_states,
    load_ama_state_cache,
)
from 纯技术面因子_bundle import iter_pure_technical_factor_bundles


def _close_frame(rows: int = 140) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-02", periods=rows)
    rng = np.random.default_rng(20260814)
    values = 100.0 + rng.normal(0.05, 0.8, (rows, 2)).cumsum(axis=0)
    return pd.DataFrame(values, index=index, columns=["000001.SZ", "600000.SH"])


def _legacy_factors(close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return AMA().get_factor_matrices(close, close, close, close, close)


def test_ama_state_is_transactional_and_incremental_matches_full(tmp_path: Path) -> None:
    close = _close_frame()
    cache_path = tmp_path / "ama_latest_state.parquet"
    split = 100

    build_ama_factor_matrices_with_state(
        close.iloc[:split],
        state_cache_path=cache_path,
    )
    assert not cache_path.exists()
    commit_ama_state_cache(cache_path)
    assert cache_path.exists()
    assert ama_state_cache_covers(cache_path, close.columns)

    incremental = build_ama_factor_matrices_with_state(
        close.iloc[split - 30 :],
        state_cache_path=cache_path,
    )
    expected = _legacy_factors(close)
    new_dates = close.index[split:]
    for factor_name, frame in incremental.items():
        pd.testing.assert_frame_equal(
            frame.loc[new_dates],
            expected[factor_name].loc[new_dates],
            check_freq=False,
        )
    commit_ama_state_cache(cache_path)
    states = load_ama_state_cache(cache_path)
    assert all(state["last_dt"] == close.index[-1] for state in states.values())


def test_ama_state_rescales_for_new_backward_adjustment(tmp_path: Path) -> None:
    close = _close_frame()
    cache_path = tmp_path / "ama_latest_state.parquet"
    split = 100
    build_ama_factor_matrices_with_state(close.iloc[:split], state_cache_path=cache_path)
    commit_ama_state_cache(cache_path)

    adjusted = close * 0.25
    incremental = build_ama_factor_matrices_with_state(
        adjusted.iloc[split - 30 :],
        state_cache_path=cache_path,
    )
    expected = _legacy_factors(adjusted)
    new_dates = close.index[split:]
    for factor_name, frame in incremental.items():
        pd.testing.assert_frame_equal(
            frame.loc[new_dates],
            expected[factor_name].loc[new_dates],
            check_freq=False,
        )
    discard_pending_ama_states(cache_path)


def test_ama_state_parameter_mismatch_does_not_claim_coverage(tmp_path: Path) -> None:
    close = _close_frame(60)
    cache_path = tmp_path / "ama_latest_state.parquet"
    build_ama_factor_matrices_with_state(close, state_cache_path=cache_path)
    commit_ama_state_cache(cache_path)

    assert ama_state_cache_covers(cache_path, close.columns)
    assert not ama_state_cache_covers(cache_path, close.columns, period=11)
    assert not ama_state_cache_covers(
        cache_path,
        [*close.columns, "000002.SZ"],
    )


def test_ama_state_bootstrap_matches_valid_bar_compaction(tmp_path: Path) -> None:
    close = _close_frame(100)
    close.iloc[:25, 1] = np.nan
    close.iloc[55:58, 0] = np.nan
    close.iloc[-12:, 1] = np.nan
    valid_bar = close.notna()
    common = {
        "O": close,
        "H": close,
        "L": close,
        "C": close,
        "V": close,
        "valid_bar": valid_bar,
        "selected_indicators": ["AMA"],
    }
    expected = next(iter_pure_technical_factor_bundles(**common))["factor_dfs"]
    actual = next(
        iter_pure_technical_factor_bundles(
            **common,
            ama_state_cache_path=tmp_path / "ama_latest_state.parquet",
        )
    )["factor_dfs"]

    for factor_id, frame in actual.items():
        pd.testing.assert_frame_equal(frame, expected[factor_id], check_freq=False)
