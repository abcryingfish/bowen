from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

try:
    from factor_debug_log import factor_log
except Exception:  # pragma: no cover
    def factor_log(event: str, **fields: Any) -> None:
        return


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


def _build_compacted_frame(
    df: pd.DataFrame,
    valid: pd.DataFrame,
    columns: pd.Index,
    compact_index: pd.Index,
) -> pd.DataFrame:
    out = pd.DataFrame(np.nan, index=compact_index, columns=columns, dtype=float)
    for col in columns:
        mask = valid[col].to_numpy(dtype=bool)
        values = df.loc[valid.index[mask], col].to_numpy()
        if len(values) > 0:
            out.loc[compact_index[: len(values)], col] = values
    return out


def _build_compacted_valid_bar(
    valid: pd.DataFrame,
    columns: pd.Index,
    compact_index: pd.Index,
) -> pd.DataFrame:
    out = pd.DataFrame(False, index=compact_index, columns=columns, dtype=bool)
    for col in columns:
        count = int(valid[col].to_numpy(dtype=bool).sum())
        if count > 0:
            out.loc[compact_index[:count], col] = True
    return out


def _merge_compacted_result(
    compact_result: BundleResult,
    *,
    original_index: pd.Index,
    compact_index: pd.Index,
    columns: pd.Index,
    valid: pd.DataFrame,
) -> BundleResult:
    selected, bundles = compact_result
    remapped_bundles: list[dict[str, Any]] = []
    valid_np = valid.to_numpy(dtype=bool)
    row_parts: list[np.ndarray] = []
    compact_row_parts: list[np.ndarray] = []
    col_parts: list[np.ndarray] = []
    for ci in range(valid_np.shape[1]):
        row_pos = np.flatnonzero(valid_np[:, ci])
        n = int(row_pos.size)
        if n == 0:
            continue
        row_parts.append(row_pos)
        compact_row_parts.append(np.arange(n, dtype=np.intp))
        col_parts.append(np.full(n, ci, dtype=np.intp))
    if row_parts:
        real_row_idx = np.concatenate(row_parts)
        compact_row_idx = np.concatenate(compact_row_parts)
        col_idx = np.concatenate(col_parts)
    else:
        real_row_idx = np.empty(0, dtype=np.intp)
        compact_row_idx = np.empty(0, dtype=np.intp)
        col_idx = np.empty(0, dtype=np.intp)

    for bundle in bundles:
        factor_dfs: dict[str, pd.DataFrame] = {}
        for factor_name, frame in bundle.get("factor_dfs", {}).items():
            aligned = frame.reindex(index=compact_index, columns=columns).astype(float)
            out_np = np.full((len(original_index), len(columns)), np.nan, dtype=np.float64)
            if real_row_idx.size:
                aligned_np = aligned.to_numpy(dtype=np.float64, copy=False)
                out_np[real_row_idx, col_idx] = aligned_np[compact_row_idx, col_idx]
            factor_dfs[factor_name] = pd.DataFrame(out_np, index=original_index, columns=columns)
        remapped_bundles.append({**bundle, "factor_dfs": factor_dfs})
    return selected, remapped_bundles


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
        factor_names: set[str] = set()
        for _, bundles in part_results:
            bundle = bundles[bundle_idx]
            factor_names.update(bundle.get("factor_dfs", {}).keys())

        factor_log(
            "valid_bar.merge_bundle.start",
            bundle_idx=int(bundle_idx),
            factors=int(len(factor_names)),
            parts=int(len(part_results)),
            rows=int(len(index)),
            cols=int(len(columns)),
        )
        factor_dfs: dict[str, pd.DataFrame] = {}
        for factor_name in factor_names:
            pieces: list[pd.DataFrame] = []
            for _, bundles in part_results:
                frame = bundles[bundle_idx].get("factor_dfs", {}).get(factor_name)
                if frame is None:
                    continue
                pieces.append(frame.reindex(index=index).astype(float, copy=False))
            if pieces:
                factor_dfs[factor_name] = pd.concat(pieces, axis=1, copy=False).reindex(columns=columns).fillna(0.0)
            else:
                factor_dfs[factor_name] = pd.DataFrame(0.0, index=index, columns=columns)
        factor_log(
            "valid_bar.merge_bundle.finish",
            bundle_idx=int(bundle_idx),
            factors=int(len(factor_dfs)),
            rows=int(len(index)),
            cols=int(len(columns)),
        )

        merged_bundles.append(
            {
                **part_results[0][1][bundle_idx],
                "factor_dfs": factor_dfs,
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
    real_lengths = {
        col: int(valid[col].to_numpy(dtype=bool).sum())
        for col in compact_cols
    }
    compact_cols = pd.Index([col for col in compact_cols if real_lengths.get(col, 0) > 0])
    max_real_len = max((real_lengths[col] for col in compact_cols), default=0)
    compact_index = pd.RangeIndex(max_real_len)

    factor_log(
        "valid_bar.compact_groups",
        total_cols=int(len(C.columns)),
        fast_cols=int(len(fast_cols)),
        compact_cols=int(len(compact_cols)),
        groups=1 if len(compact_cols) else 0,
        largest_group=int(len(compact_cols)),
        mode="compressed_batch",
        max_real_len=int(max_real_len),
    )

    if len(compact_cols) > 0 and max_real_len > 0:
        compact_valid = _build_compacted_valid_bar(valid, compact_cols, compact_index)
        compact_result = _call_raw_compute(
            raw_compute,
            O=_build_compacted_frame(O, valid, compact_cols, compact_index),
            H=_build_compacted_frame(H, valid, compact_cols, compact_index),
            L=_build_compacted_frame(L, valid, compact_cols, compact_index),
            C=_build_compacted_frame(C, valid, compact_cols, compact_index),
            V=_build_compacted_frame(V, valid, compact_cols, compact_index),
            selected_bundles=selected_bundles,
            T=_build_compacted_frame(T, valid, compact_cols, compact_index) if T is not None else None,
            enable_bottom_cache=False,
            valid_bar=compact_valid,
        )
        part_results.append(
            _merge_compacted_result(
                compact_result,
                original_index=C.index,
                compact_index=compact_index,
                columns=compact_cols,
                valid=valid.loc[:, compact_cols],
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
