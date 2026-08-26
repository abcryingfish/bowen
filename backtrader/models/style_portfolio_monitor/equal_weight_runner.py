"""从已落盘因子和后复权行情生成风格等权指数账本。"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from .config import (
    INITIAL_DATE,
    MAX_SELECTION_COUNT,
    MIN_FACTOR_COVERAGE,
    MODEL_DEFINITIONS,
    SELECTION_RATIO,
    STYLE_MONITOR_DB_PATH,
    build_config_hash,
    is_rebalance_day,
)
from .data import StyleDataSource, StyleDataError
from .equal_weight_index import StyleIndexDataError, load_adjusted_open_close
from .equal_weight_service import build_and_persist_equal_weight_index
from .repository import StyleMonitorRepository


DEFAULT_SIGNAL_BASE_DIR = Path(r"D:\database\signal_daily")
DEFAULT_MARKET_BASE_DIR = Path(r"D:\database\stock_basic_data_daily")
DEFAULT_ADJ_FACTOR_DAILY_DIR = Path(r"D:\database\stock_adj_daily\adj_factor_daily")
DEFAULT_WIDE_XDY_DIR = Path(r"D:\database\stock_adj_daily\wide_xdy")


def _months(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    cursor = pd.Timestamp(start.year, start.month, 1)
    finish = pd.Timestamp(end.year, end.month, 1)
    result: list[pd.Timestamp] = []
    while cursor <= finish:
        result.append(cursor)
        cursor += pd.offsets.MonthBegin(1)
    return result


def load_saved_factor_frame(
    *,
    base_dir: str | Path,
    factor_name: str,
    start_date: date | pd.Timestamp,
    end_date: date | pd.Timestamp,
) -> pd.DataFrame:
    """读取因子分区并按(time, code)去重，返回日×股票矩阵。"""
    start = pd.Timestamp(start_date).floor("D")
    end = pd.Timestamp(end_date).floor("D")
    paths: list[Path] = []
    missing: list[str] = []
    root = Path(base_dir) / f"factor={factor_name}"
    for month in _months(start, end):
        directory = root / f"year={month.year}" / f"month={month.month:02d}"
        files = []
        merged = directory / "merged.parquet"
        if merged.is_file():
            files.append(merged)
        files.extend(sorted(directory.glob("part_*.parquet")))
        if not files:
            missing.append(month.strftime("%Y-%m"))
        paths.extend(files)
    if missing:
        raise StyleDataError(f"因子 {factor_name} 缺少月份分区: {'、'.join(missing)}")
    frames: list[pd.DataFrame] = []
    for order, path in enumerate(paths):
        frame = pd.read_parquet(path, columns=["time", "htsc_code", "value"])
        frame["_file_order"] = order
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    long = pd.concat(frames, ignore_index=True)
    long["time"] = pd.to_datetime(long["time"], errors="coerce").dt.floor("D")
    long["htsc_code"] = long["htsc_code"].astype(str).str.strip().str.upper()
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long = long[long["time"].between(start, end)].sort_values("_file_order")
    long = long.drop_duplicates(["time", "htsc_code"], keep="last")
    wide = long.pivot(index="time", columns="htsc_code", values="value").sort_index()
    wide.columns.name = None
    return wide.astype(float)


def _rebalance_dates(
    dates: list[date],
    frequency: str,
    last_rebalance_date: date | None = None,
) -> list[date]:
    selected: list[date] = []
    last: date | None = last_rebalance_date
    for day in dates:
        if is_rebalance_day(day, last, frequency, dates):
            selected.append(day)
            last = day
    return selected


def _build_model_inputs(
    *,
    definition,
    source: StyleDataSource,
    start: date,
    end: date,
    progress: Callable[[str, int, str], None] | None = None,
    adjusted_price_cache: dict[tuple[date, date], tuple[pd.DataFrame, pd.DataFrame]] | None = None,
    last_rebalance_date: date | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, set[pd.Timestamp], dict[date, float]]:
    factor_key = definition.factor_key
    dates = source.available_market_dates(start, end)
    if not dates:
        raise StyleDataError(f"{definition.model_id} 没有可用行情日期")
    rebalance_days = _rebalance_dates(dates, definition.rebalance_frequency, last_rebalance_date)
    score_rows: dict[pd.Timestamp, dict[str, float]] = {}
    coverage: dict[date, float] = {}
    accepted: set[pd.Timestamp] = set()
    for index, day in enumerate(rebalance_days, start=1):
        snapshot = source.build_eligible_snapshot(day, factor_key)
        coverage[day] = float(snapshot.attrs.get("factor_coverage", 0.0))
        if coverage[day] < MIN_FACTOR_COVERAGE:
            raise StyleDataError(f"{definition.model_id} {day} 因子覆盖率 {coverage[day]:.2%} 低于 80.00%")
        row_scores: dict[str, float] = {}
        for row in snapshot.itertuples():
            row_scores[str(row.htsc_code).strip().upper()] = float(row.score)
        score_rows[pd.Timestamp(day)] = row_scores
        accepted.add(pd.Timestamp(day))
        if progress:
            progress("生成目标权重", int(index / len(rebalance_days) * 40) if rebalance_days else 40, f"{definition.model_id} {day}")
    score = pd.DataFrame.from_dict(score_rows, orient="index")
    score.index = pd.DatetimeIndex(score.index)
    score = score.reindex(pd.DatetimeIndex(dates))
    cache_key = (start, end)
    adjusted_prices = adjusted_price_cache.get(cache_key) if adjusted_price_cache is not None else None
    if adjusted_prices is None:
        adjusted_prices = load_adjusted_open_close(
            market_base_dir=source.market_root,
            adj_factor_daily_dir=DEFAULT_ADJ_FACTOR_DAILY_DIR,
            wide_xdy_dir=DEFAULT_WIDE_XDY_DIR,
            start_date=start,
            end_date=end,
        )
        if adjusted_price_cache is not None:
            adjusted_price_cache[cache_key] = adjusted_prices
    adjusted_open, adjusted_close = adjusted_prices
    adjusted_open = adjusted_open.reindex(index=pd.DatetimeIndex(dates))
    adjusted_close = adjusted_close.reindex(index=pd.DatetimeIndex(dates))
    valid_bar = adjusted_close.gt(0)
    return score, adjusted_open, adjusted_close, valid_bar, accepted, coverage


def run_equal_weight_update(
    *,
    model_ids: list[str] | None = None,
    through_date: date | None = None,
    database_path: str | Path | None = None,
    signal_base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    market_base_dir: str | Path = DEFAULT_MARKET_BASE_DIR,
    progress: Callable[[str, int, str], None] | None = None,
    rebuild: bool = False,
) -> dict[str, Any]:
    """重建或更新所有风格模型的无本金等权指数。"""
    repo = StyleMonitorRepository(database_path or STYLE_MONITOR_DB_PATH)
    repo.initialize_schema()
    repo.clear_legacy_cash_ledger()
    source = StyleDataSource(market_root=market_base_dir, signal_root=signal_base_dir)
    definitions = {item.model_id: item for item in MODEL_DEFINITIONS}
    selected = [definitions[item] for item in (model_ids or list(definitions))]
    result: dict[str, Any] = {"completed_models": [], "skipped_models": [], "failed_models": [], "paused_models": [], "latest_dates": {}, "processed_days": {}}
    adjusted_price_cache: dict[tuple[date, date], tuple[pd.DataFrame, pd.DataFrame]] = {}
    for model_index, definition in enumerate(selected, start=1):
        try:
            latest = source.latest_common_date(definition.factor_key)
            if latest is None:
                raise StyleDataError(f"{definition.model_id} 没有因子与行情共同日期")
            end = min(latest, through_date) if through_date else latest
            version = repo.ensure_model_version(definition, build_config_hash(definition))
            existing_start, existing_end = repo.index_date_bounds(version)
            if existing_end is not None and existing_end == end and not rebuild:
                result["completed_models"].append(definition.model_id)
                result["skipped_models"].append(definition.model_id)
                result["latest_dates"][definition.model_id] = end.isoformat()
                result["processed_days"][definition.model_id] = 0
                if progress:
                    progress("模型已是最新", int(model_index / len(selected) * 100), f"{definition.model_id} {end}")
                continue
            run_state = repo.get_run_state(version)
            reset_required = bool(rebuild or (existing_end is not None and existing_end > end))
            incremental = existing_end is not None and not reset_required
            first = (
                existing_end
                if incremental
                else source.first_usable_date(definition.factor_key, INITIAL_DATE, MIN_FACTOR_COVERAGE)
            )
            if first is None:
                raise StyleDataError(f"{definition.model_id} 从 {INITIAL_DATE} 起没有达到 80% 因子覆盖率的可用日期")
            if first > end:
                continue
            score, open_prices, prices, valid_bar, rebalance_dates, coverage = _build_model_inputs(
                definition=definition,
                source=source,
                start=first,
                end=end,
                progress=progress,
                adjusted_price_cache=adjusted_price_cache,
                last_rebalance_date=None if reset_required else run_state.last_rebalance_date,
            )
            initial_values: dict[str, float] | None = None
            initial_weights: dict[str, dict[str, float]] | None = None
            initial_last_rebalance: date | None = None
            if not reset_required and existing_end is not None:
                _, initial_values, initial_weights = repo.load_index_state(version)
                initial_last_rebalance = run_state.last_rebalance_date
            if reset_required:
                repo.clear_index_model(version)
            build_and_persist_equal_weight_index(
                repo=repo,
                model_version=version,
                model_id=definition.model_id,
                config_hash=build_config_hash(definition),
                score_frame=score,
                adjusted_open=open_prices,
                adjusted_close=prices,
                valid_bar=valid_bar,
                rebalance_dates=rebalance_dates,
                factor_coverage=coverage,
                persist_start_date=(existing_end + timedelta(days=1)) if existing_end is not None and not reset_required else None,
                ratio=SELECTION_RATIO,
                max_count=MAX_SELECTION_COUNT,
                initial_last_rebalance=initial_last_rebalance,
                initial_index_values=initial_values,
                initial_weights=initial_weights,
            )
            result["completed_models"].append(definition.model_id)
            result["latest_dates"][definition.model_id] = end.isoformat()
            result["processed_days"][definition.model_id] = len(prices.index) if reset_required or existing_end is None else int(sum(day > existing_end for day in prices.index.date))
            if progress:
                progress("模型完成", int(model_index / len(selected) * 100), f"{definition.model_id} {end}")
        except Exception as exc:  # noqa: BLE001
            result["failed_models"].append({"model_id": definition.model_id, "message": str(exc)})
    return result
