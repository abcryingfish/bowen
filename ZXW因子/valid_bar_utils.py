from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd


BundleResult = tuple[set[str], list[dict[str, Any]]]
RawBundleCompute = Callable[..., BundleResult]


def normalize_valid_bar(
    valid_bar: pd.DataFrame,
    *,
    index: pd.Index,
    columns: pd.Index,
) -> pd.DataFrame:
    return valid_bar.reindex(index=index, columns=columns).fillna(False).astype(bool)


def columns_needing_real_bar_compact(valid_bar: pd.DataFrame) -> pd.Series:
    """Columns with any invalid row after their first real bar need compaction."""
    seen_valid = valid_bar.cumsum().gt(0)
    return ((~valid_bar) & seen_valid).any(axis=0)


def _slice_frame(df: pd.DataFrame | None, rows: pd.Index, columns: pd.Index) -> pd.DataFrame | None:
    if df is None:
        return None
    return df.reindex(index=rows, columns=columns)


def _call_raw_compute(
    raw_compute: RawBundleCompute,
    *,
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    V: pd.DataFrame,
    selected_bundles: list[str] | tuple[str, ...] | set[str],
    T: pd.DataFrame | None,
    enable_bottom_cache: bool,
    valid_bar: pd.DataFrame | None,
) -> BundleResult:
    return raw_compute(
        O=O,
        H=H,
        L=L,
        C=C,
        V=V,
        selected_bundles=selected_bundles,
        T=T,
        enable_bottom_cache=enable_bottom_cache,
        valid_bar=valid_bar,
    )


def merge_bundle_outputs(
    part_results: list[BundleResult],
    *,
    index: pd.Index,
    columns: pd.Index,
) -> BundleResult:
    if not part_results:
        return set(), []

    selected_bundle_set = part_results[0][0]
    bundle_count = len(part_results[0][1])
    for _, bundles in part_results[1:]:
        if len(bundles) != bundle_count:
            raise ValueError("Cannot merge bundle outputs with different bundle counts")

    merged_bundles: list[dict[str, Any]] = []
    for bundle_idx in range(bundle_count):
        factor_name_map = part_results[0][1][bundle_idx].get("factor_name_map", {})
        factor_dfs: dict[str, pd.DataFrame] = {}
        for _, bundles in part_results:
            bundle = bundles[bundle_idx]
            for factor_name in bundle.get("factor_dfs", {}).keys():
                if factor_name not in factor_dfs:
                    factor_dfs[factor_name] = pd.DataFrame(np.nan, index=index, columns=columns)

        for _, bundles in part_results:
            bundle = bundles[bundle_idx]
            for factor_name, frame in bundle.get("factor_dfs", {}).items():
                aligned = frame.reindex(index=index).astype(float)
                factor_dfs[factor_name].loc[:, aligned.columns] = aligned

        merged_bundles.append(
            {
                **part_results[0][1][bundle_idx],
                "factor_dfs": {name: frame.fillna(0.0) for name, frame in factor_dfs.items()},
                "factor_name_map": factor_name_map,
            }
        )

    return selected_bundle_set, merged_bundles


def compute_bundles_with_valid_bar(
    raw_compute: RawBundleCompute,
    *,
    O: pd.DataFrame,
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    V: pd.DataFrame,
    selected_bundles: list[str] | tuple[str, ...] | set[str],
    T: pd.DataFrame | None = None,
    valid_bar: pd.DataFrame | None = None,
    enable_bottom_cache: bool = True,
) -> BundleResult:
    if valid_bar is None:
        return _call_raw_compute(
            raw_compute,
            O=O,
            H=H,
            L=L,
            C=C,
            V=V,
            selected_bundles=selected_bundles,
            T=T,
            enable_bottom_cache=enable_bottom_cache,
            valid_bar=None,
        )

    valid = normalize_valid_bar(valid_bar, index=C.index, columns=C.columns)
    needs_compact = columns_needing_real_bar_compact(valid)
    if not bool(needs_compact.any()):
        return _call_raw_compute(
            raw_compute,
            O=O,
            H=H,
            L=L,
            C=C,
            V=V,
            selected_bundles=selected_bundles,
            T=T,
            enable_bottom_cache=enable_bottom_cache,
            valid_bar=valid,
        )

    part_results: list[BundleResult] = []
    fast_cols = pd.Index([col for col in C.columns if not bool(needs_compact.get(col, False))])
    if len(fast_cols) > 0:
        part_results.append(
            _call_raw_compute(
                raw_compute,
                O=O.loc[:, fast_cols],
                H=H.loc[:, fast_cols],
                L=L.loc[:, fast_cols],
                C=C.loc[:, fast_cols],
                V=V.loc[:, fast_cols],
                selected_bundles=selected_bundles,
                T=_slice_frame(T, C.index, fast_cols),
                enable_bottom_cache=enable_bottom_cache,
                valid_bar=valid.loc[:, fast_cols],
            )
        )

    compact_cols = pd.Index([col for col in C.columns if bool(needs_compact.get(col, False))])
    for col in compact_cols:
        col_valid = valid[col].fillna(False).astype(bool)
        real_index = valid.index[col_valid.to_numpy()]
        if len(real_index) == 0:
            continue
        one_col = pd.Index([col])
        part_results.append(
            _call_raw_compute(
                raw_compute,
                O=O.loc[real_index, one_col],
                H=H.loc[real_index, one_col],
                L=L.loc[real_index, one_col],
                C=C.loc[real_index, one_col],
                V=V.loc[real_index, one_col],
                selected_bundles=selected_bundles,
                T=_slice_frame(T, real_index, one_col),
                enable_bottom_cache=False,
                valid_bar=valid.loc[real_index, one_col],
            )
        )

    if not part_results:
        return _call_raw_compute(
            raw_compute,
            O=O,
            H=H,
            L=L,
            C=C,
            V=V,
            selected_bundles=selected_bundles,
            T=T,
            enable_bottom_cache=enable_bottom_cache,
            valid_bar=valid,
        )

    return merge_bundle_outputs(part_results, index=C.index, columns=C.columns)
