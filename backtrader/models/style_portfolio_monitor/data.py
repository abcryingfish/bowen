"""Read-only market and factor snapshots for style portfolio monitoring."""

from __future__ import annotations

import re
from collections import OrderedDict
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

import pandas as pd

from .config import LIQUIDITY_LOOKBACK_DAYS, MIN_AVERAGE_TURNOVER, MIN_FACTOR_COVERAGE, MIN_HISTORY_DAYS

_STOCK_CODE = re.compile(r"^[036]\d{5}\.(?:SH|SZ)$")


class StyleDataError(RuntimeError):
    """Raised when a market or factor partition cannot satisfy the data contract."""


class StyleDataSource:
    def __init__(self, market_root: str | Path = Path(r"D:\database\stock_basic_data_daily"), signal_root: str | Path = Path(r"D:\database\signal_daily")) -> None:
        self.market_root = Path(market_root)
        self.signal_root = Path(signal_root)
        self._market_cache: OrderedDict[Path, pd.DataFrame] = OrderedDict()
        self._factor_cache: OrderedDict[tuple[str, Path], pd.DataFrame] = OrderedDict()
        self._market_date_cache: dict[Path, set[date]] = {}

    @staticmethod
    def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
        required = {"time", "htsc_code", "value"}
        if not required <= set(frame.columns):
            raise StyleDataError(f"分区缺少列: {sorted(required - set(frame.columns))}")
        result = frame.copy()
        result["time"] = pd.to_datetime(result["time"], errors="coerce").dt.floor("D")
        result["htsc_code"] = result["htsc_code"].astype(str).str.strip().str.upper()
        result["value"] = pd.to_numeric(result["value"], errors="coerce")
        return result.dropna(subset=["time", "htsc_code"])

    def _read_files(self, files: list[Path], columns: list[str], cache: OrderedDict, cache_key_prefix: str = "") -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for path in files:
            key = (cache_key_prefix, path) if cache_key_prefix else path
            if key in cache:
                frame = cache.pop(key)
                cache[key] = frame
            else:
                try:
                    frame = pd.read_parquet(path, columns=columns)
                except Exception as exc:  # noqa: BLE001
                    raise StyleDataError(f"读取 Parquet 失败: {path}: {exc}") from exc
                frame = self._normalize(frame)
                cache[key] = frame
                while len(cache) > (20 if cache is self._factor_cache else 8):
                    cache.popitem(last=False)
            frames.append(frame)
        if not frames:
            return pd.DataFrame(columns=columns)
        merged = pd.concat(frames, ignore_index=True)
        merged["_file_order"] = range(len(merged))
        return merged

    @staticmethod
    def _deduplicate(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame
        return frame.sort_values(["time", "htsc_code", "_file_order"]).drop_duplicates(["time", "htsc_code"], keep="last").drop(columns=["_file_order"], errors="ignore")

    @staticmethod
    def _months(start: date, end: date):
        current = date(start.year, start.month, 1)
        final = date(end.year, end.month, 1)
        while current <= final:
            yield current.year, current.month
            current = date(current.year + (current.month == 12), 1 if current.month == 12 else current.month + 1, 1)

    def _market_files(self, start: date, end: date) -> list[Path]:
        files: list[Path] = []
        for year, month in self._months(start, end):
            directory = self.market_root / f"year={year}" / f"month={month:02d}"
            merged = directory / "merged.parquet"
            if merged.is_file():
                files.append(merged)
            files.extend(sorted(directory.glob("part_*.parquet")))
        return files

    def _factor_files(self, factor_name: str, start: date | None = None, end: date | None = None) -> list[Path]:
        directory = self.signal_root / f"factor={factor_name}"
        if start is not None and end is not None:
            files: list[Path] = []
            for year, month in self._months(start, end):
                month_dir = directory / f"year={year}" / f"month={month:02d}"
                merged = month_dir / "merged.parquet"
                if merged.is_file():
                    files.append(merged)
                files.extend(sorted(month_dir.glob("part_*.parquet")))
            return files
        return sorted([*directory.glob("year=*/month=*/merged.parquet"), *directory.glob("year=*/month=*/part_*.parquet")])

    def _load_market(self, start: date, end: date) -> pd.DataFrame:
        frame = self._read_files(self._market_files(start, end), ["time", "htsc_code", "close", "volume", "value"], self._market_cache)
        if frame.empty:
            raise StyleDataError(f"行情目录没有数据: {self.market_root}")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
        frame = self._deduplicate(frame)
        return frame[frame["time"].between(pd.Timestamp(start), pd.Timestamp(end))].copy()

    def _load_factor(self, factor_name: str, start: date, end: date) -> pd.DataFrame:
        files = self._factor_files(factor_name, start, end)
        if not files:
            raise StyleDataError(f"因子目录不存在或没有分区: {self.signal_root / f'factor={factor_name}'}")
        frame = self._read_files(files, ["time", "htsc_code", "value"], self._factor_cache, factor_name)
        frame = self._deduplicate(frame)
        return frame[frame["time"].between(pd.Timestamp(start), pd.Timestamp(end))].rename(columns={"value": "score"}).copy()

    def available_market_dates(self, start: date, end: date | None = None) -> list[date]:
        end = end or date.today()
        dates: set[date] = set()
        for path in self._market_files(start, end):
            if path not in self._market_date_cache:
                try:
                    values = pd.to_datetime(pd.read_parquet(path, columns=["time"])["time"], errors="coerce").dropna().dt.date
                except Exception as exc:  # noqa: BLE001
                    raise StyleDataError(f"读取行情日期失败: {path}: {exc}") from exc
                self._market_date_cache[path] = set(values)
            dates.update(item for item in self._market_date_cache[path] if start <= item <= end)
        return sorted(dates)

    def latest_common_date(self, factor_name: str) -> date | None:
        def latest(files: list[Path]) -> date | None:
            by_partition: dict[Path, list[Path]] = {}
            for path in files:
                by_partition.setdefault(path.parent, []).append(path)
            for partition in sorted(by_partition, reverse=True):
                latest_value = None
                for path in by_partition[partition]:
                    try:
                        values = pd.to_datetime(pd.read_parquet(path, columns=["time"])["time"], errors="coerce").dropna()
                    except Exception as exc:  # noqa: BLE001
                        raise StyleDataError(f"读取最新日期失败: {path}: {exc}") from exc
                    if not values.empty:
                        candidate = values.max()
                        latest_value = candidate if latest_value is None else max(latest_value, candidate)
                if latest_value is not None:
                    return latest_value.date()
            return None

        market_latest = latest(self._market_files(date(1900, 1, 1), date.today()))
        factor_latest = latest(self._factor_files(factor_name))
        return min(market_latest, factor_latest) if market_latest and factor_latest else None

    def first_usable_date(self, factor_name: str, start: date, minimum_coverage: float = MIN_FACTOR_COVERAGE) -> date | None:
        all_factor_files = self._factor_files(factor_name)
        if not all_factor_files:
            raise StyleDataError(f"因子目录不存在或没有分区: {self.signal_root / f'factor={factor_name}'}")
        first_value = None
        by_partition: dict[Path, list[Path]] = {}
        for path in all_factor_files:
            by_partition.setdefault(path.parent, []).append(path)
        for partition in sorted(by_partition):
            partition_values = []
            for path in by_partition[partition]:
                try:
                    values = pd.to_datetime(pd.read_parquet(path, columns=["time"])["time"], errors="coerce").dropna()
                except Exception as exc:  # noqa: BLE001
                    raise StyleDataError(f"读取因子起始日期失败: {path}: {exc}") from exc
                if not values.empty:
                    partition_values.append(values.min())
            if partition_values:
                first_value = min(partition_values)
                break
        if first_value is None:
            raise StyleDataError(f"因子所有分区均没有有效日期: {self.signal_root / f'factor={factor_name}'}")
        factor_start = max(start, first_value.date())
        dates = self.available_market_dates(factor_start)
        for trade_date in dates:
            snapshot = self.build_eligible_snapshot(trade_date, factor_name)
            if snapshot.attrs.get("factor_coverage", 0.0) >= minimum_coverage:
                return trade_date
        return None

    def build_eligible_snapshot(self, trade_date: date, factor_name: str) -> pd.DataFrame:
        market = self._load_market(trade_date - timedelta(days=210), trade_date)
        market = market[market["htsc_code"].map(lambda code: bool(_STOCK_CODE.fullmatch(code)))].copy()
        market = market[(market["close"] > 0) & (market["volume"] > 0)]
        if market.empty:
            result = pd.DataFrame(columns=["htsc_code", "score", "close", "average_turnover_20d", "history_days"])
            result.attrs.update(tradable_count=0, factor_valid_count=0, factor_coverage=0.0)
            return result
        recent_dates = sorted(market["time"].dt.date.unique())[-LIQUIDITY_LOOKBACK_DAYS:]
        recent = market[market["time"].dt.date.isin(recent_dates)]
        stats = market.groupby("htsc_code").agg(history_days=("time", "nunique"), average_turnover_20d=("value", "mean"))
        recent_stats = recent.groupby("htsc_code")["value"].mean().rename("average_turnover_20d")
        stats["average_turnover_20d"] = recent_stats
        latest = market[market["time"].dt.date == trade_date].set_index("htsc_code")[["close"]]
        eligible = stats[(stats["history_days"] >= MIN_HISTORY_DAYS) & (stats["average_turnover_20d"] >= MIN_AVERAGE_TURNOVER)].join(latest, how="inner")
        factor = self._load_factor(factor_name, trade_date, trade_date)
        factor = factor[factor["time"].dt.date == trade_date].drop_duplicates("htsc_code", keep="last").set_index("htsc_code")[["score"]]
        tradable_count = len(eligible)
        result = eligible.join(factor, how="left").reset_index()
        valid_count = int(result["score"].notna().sum())
        result.attrs.update(tradable_count=tradable_count, factor_valid_count=valid_count, factor_coverage=(valid_count / tradable_count if tradable_count else 0.0))
        return result.sort_values(["score", "htsc_code"], na_position="last").reset_index(drop=True)

    def close_prices(self, trade_date: date, codes: Sequence[str]) -> dict[str, float]:
        frame = self._load_market(trade_date, trade_date)
        frame = frame[(frame["time"].dt.date == trade_date) & frame["htsc_code"].isin(list(codes))].drop_duplicates("htsc_code", keep="last")
        return {str(row.htsc_code): float(row.close) for row in frame.itertuples() if pd.notna(row.close) and float(row.close) > 0}
