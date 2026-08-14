"""无本金、无手续费的后复权等权风格收益指数。"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class StyleIndexDataError(RuntimeError):
    """风格指数数据不满足复权或日期契约。"""


def _normalise_frame(value: pd.DataFrame) -> pd.DataFrame:
    frame = value.copy()
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index, errors="coerce")).floor("D")
    frame = frame[~frame.index.isna()]
    if not frame.index.is_unique:
        raise ValueError("输入数据的日期索引必须 unique")
    frame.columns = frame.columns.astype(str).str.strip().str.upper()
    return frame.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).astype(float)


def _as_date_set(values: Iterable[pd.Timestamp | date]) -> set[pd.Timestamp]:
    return {
        pd.Timestamp(value).floor("D")
        for value in values
        if pd.notna(pd.Timestamp(value))
    }


def _month_starts(start_date: pd.Timestamp, end_date: pd.Timestamp) -> list[pd.Timestamp]:
    cursor = pd.Timestamp(start_date.year, start_date.month, 1)
    end_month = pd.Timestamp(end_date.year, end_date.month, 1)
    result: list[pd.Timestamp] = []
    while cursor <= end_month:
        result.append(cursor)
        cursor += pd.offsets.MonthBegin(1)
    return result


def _partition_files(base_dir: str | Path, months: Iterable[pd.Timestamp]) -> list[Path]:
    root = Path(base_dir)
    return [
        root / f"year={month.year}" / f"month={month.month:02d}" / "merged.parquet"
        for month in months
        if (root / f"year={month.year}" / f"month={month.month:02d}" / "merged.parquet").is_file()
    ]


def _load_market_close(
    base_dir: str | Path,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
) -> pd.DataFrame:
    months = _month_starts(start_dt, end_dt)
    files = _partition_files(base_dir, months)
    if len(files) != len(months):
        missing = [month.strftime("%Y-%m") for month in months if not (Path(base_dir) / f"year={month.year}" / f"month={month.month:02d}" / "merged.parquet").is_file()]
        raise StyleIndexDataError("股票行情缺少月份分区: " + "、".join(missing))
    frames = [pd.read_parquet(path, columns=["time", "htsc_code", "close"]) for path in files]
    long = pd.concat(frames, ignore_index=True)
    long["time"] = pd.to_datetime(long["time"], errors="coerce").dt.floor("D")
    long["htsc_code"] = long["htsc_code"].astype(str).str.strip().str.upper()
    long["close"] = pd.to_numeric(long["close"], errors="coerce")
    long = long[long["time"].between(start_dt, end_dt)].dropna(subset=["time", "htsc_code", "close"])
    long = long.drop_duplicates(["time", "htsc_code"], keep="last")
    return long


def _merge_adjusted_month(
    market: pd.DataFrame,
    factors: pd.DataFrame,
    carry: dict[str, float],
) -> tuple[pd.DataFrame, dict[str, float]]:
    """按单月合并行情与复权因子，并把月末因子带给下个月。"""
    factors = factors.copy()
    factors["time"] = pd.to_datetime(factors["time"], errors="coerce").dt.floor("D")
    factors["htsc_code"] = factors["htsc_code"].astype(str).str.strip().str.upper()
    factors["adj_factor"] = pd.to_numeric(factors["adj_factor"], errors="coerce")
    if factors["adj_factor"].isna().any():
        raise StyleIndexDataError("adj_factor_daily 存在非法复权因子")
    if (~np.isfinite(factors["adj_factor"].to_numpy(dtype=float))).any() or factors["adj_factor"].le(0).any():
        raise StyleIndexDataError("adj_factor_daily 存在无效复权因子")
    factors = factors.dropna(subset=["time", "htsc_code"]).drop_duplicates(["time", "htsc_code"], keep="last")

    merged = market.merge(factors, on=["time", "htsc_code"], how="left").sort_values(["htsc_code", "time"])
    merged["adj_factor"] = merged.groupby("htsc_code", sort=False)["adj_factor"].ffill()
    merged["adj_factor"] = merged["adj_factor"].fillna(merged["htsc_code"].map(carry))
    known_factors = merged["adj_factor"].dropna().to_numpy(dtype=float)
    if (~np.isfinite(known_factors)).any() or (known_factors <= 0).any():
        raise StyleIndexDataError("adj_factor_daily 存在无效复权因子")

    next_carry = dict(carry)
    if not factors.empty:
        latest = factors.sort_values("time").drop_duplicates("htsc_code", keep="last")
        next_carry.update({str(row.htsc_code): float(row.adj_factor) for row in latest.itertuples(index=False)})
    merged["adjusted_close"] = merged["close"].to_numpy(dtype=float) * merged["adj_factor"].to_numpy(dtype=float)
    adjusted = merged.pivot(index="time", columns="htsc_code", values="adjusted_close").sort_index().astype(float)
    adjusted.attrs["missing_adj_factor_rows"] = int(merged["adj_factor"].isna().sum())
    return adjusted, next_carry


def _load_factor_carry_before_start(
    market: pd.DataFrame,
    factor_dir: str | Path,
    start_dt: pd.Timestamp,
) -> dict[str, float]:
    """读取起始月以前最近的有效因子，避免查询起点误用身份因子。"""
    target_codes = set(market["htsc_code"].astype(str).str.strip().str.upper().unique())
    if not target_codes:
        return {}
    start_month = pd.Timestamp(start_dt.year, start_dt.month, 1)
    prior_paths: list[tuple[pd.Timestamp, Path]] = []
    for path in Path(factor_dir).glob("year=*/month=*/merged.parquet"):
        try:
            year = int(path.parent.parent.name.split("=", 1)[1])
            month = int(path.parent.name.split("=", 1)[1])
        except (IndexError, ValueError):
            continue
        partition_month = pd.Timestamp(year, month, 1)
        if partition_month < start_month:
            prior_paths.append((partition_month, path))

    carry: dict[str, float] = {}
    for _, path in sorted(prior_paths, reverse=True):
        factors = pd.read_parquet(path, columns=["time", "htsc_code", "adj_factor"])
        factors["time"] = pd.to_datetime(factors["time"], errors="coerce").dt.floor("D")
        factors["htsc_code"] = factors["htsc_code"].astype(str).str.strip().str.upper()
        factors["adj_factor"] = pd.to_numeric(factors["adj_factor"], errors="coerce")
        if factors["adj_factor"].isna().any():
            raise StyleIndexDataError("adj_factor_daily 存在非法复权因子")
        values = factors["adj_factor"].to_numpy(dtype=float)
        if (~np.isfinite(values)).any() or factors["adj_factor"].le(0).any():
            raise StyleIndexDataError("adj_factor_daily 存在无效复权因子")
        factors = factors.dropna(subset=["time", "htsc_code"])
        factors = factors[
            (factors["time"] < start_dt)
            & factors["htsc_code"].isin(target_codes - set(carry))
        ]
        if factors.empty:
            continue
        latest = factors.sort_values("time").drop_duplicates("htsc_code", keep="last")
        carry.update({str(row.htsc_code): float(row.adj_factor) for row in latest.itertuples(index=False)})
        if len(carry) == len(target_codes):
            break
    return carry


def _load_fast_adjusted_close(
    market: pd.DataFrame,
    factor_dir: str | Path,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
) -> pd.DataFrame | None:
    months = _month_starts(start_dt, end_dt)
    files = _partition_files(factor_dir, months)
    if len(files) != len(months):
        return None
    monthly_frames: list[pd.DataFrame] = []
    carry = _load_factor_carry_before_start(market, factor_dir, start_dt)
    missing_factor_rows = 0
    for month, path in zip(months, files):
        month_end = month + pd.offsets.MonthBegin(1)
        market_part = market[(market["time"] >= month) & (market["time"] < month_end)].copy()
        factors = pd.read_parquet(path, columns=["time", "htsc_code", "adj_factor"])
        if market_part.empty:
            factors["time"] = pd.to_datetime(factors["time"], errors="coerce").dt.floor("D")
            factors["htsc_code"] = factors["htsc_code"].astype(str).str.strip().str.upper()
            factors["adj_factor"] = pd.to_numeric(factors["adj_factor"], errors="coerce")
            if factors["adj_factor"].isna().any() or (~np.isfinite(factors["adj_factor"].to_numpy(dtype=float))).any() or factors["adj_factor"].le(0).any():
                raise StyleIndexDataError("adj_factor_daily 存在无效复权因子")
            factors = factors.dropna(subset=["time", "htsc_code"]).drop_duplicates(["time", "htsc_code"], keep="last")
            if not factors.empty:
                latest = factors.sort_values("time").drop_duplicates("htsc_code", keep="last")
                carry.update({str(row.htsc_code): float(row.adj_factor) for row in latest.itertuples(index=False)})
            continue
        adjusted, carry = _merge_adjusted_month(market_part, factors, carry)
        missing_factor_rows += int(adjusted.attrs.get("missing_adj_factor_rows", 0))
        monthly_frames.append(adjusted)
    if not monthly_frames:
        return pd.DataFrame(index=pd.DatetimeIndex([], name="time"))
    adjusted = pd.concat(monthly_frames, axis=0).sort_index().astype(float)
    adjusted.attrs["missing_adj_factor_rows"] = missing_factor_rows
    return adjusted


def _backward_factor_series(values: pd.Series) -> pd.Series:
    values = pd.to_numeric(values, errors="coerce").dropna().sort_index().astype(float)
    if values.empty:
        return values
    changed = values.ne(values.shift())
    return values.where(changed, 1.0).cumprod()


def _load_wide_adjusted_close(market: pd.DataFrame, wide_dir: str | Path) -> pd.DataFrame:
    paths = sorted(Path(wide_dir).glob("year=*/month=*/merged.parquet"))
    if not paths:
        raise StyleIndexDataError(f"找不到后复权数据: {wide_dir}")
    target_codes = set(market["htsc_code"].unique())
    factor_parts: list[pd.DataFrame] = []
    for path in paths:
        frame = pd.read_parquet(path)
        if "htsc_code" not in frame.columns:
            continue
        frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
        frame = frame[frame["htsc_code"].isin(target_codes)]
        if frame.empty:
            continue
        date_columns = [column for column in frame.columns if column != "htsc_code"]
        part = frame.melt(
            id_vars=["htsc_code"],
            value_vars=date_columns,
            var_name="time",
            value_name="wide_value",
        )
        part["time"] = pd.to_datetime(part["time"], format="%Y/%m/%d", errors="coerce").dt.floor("D")
        part["wide_value"] = pd.to_numeric(part["wide_value"], errors="coerce")
        factor_parts.append(part.dropna(subset=["time", "wide_value"]))
    if factor_parts:
        factor_frame = pd.concat(factor_parts, ignore_index=True)
        factor_frame = factor_frame.drop_duplicates(["htsc_code", "time"], keep="last")
        by_code = {
            str(code): group.set_index("time")["wide_value"].sort_index()
            for code, group in factor_frame.groupby("htsc_code", sort=False)
        }
    else:
        by_code = {}
    adjusted = market.copy().reset_index(drop=True)
    factors = np.full(len(adjusted), np.nan, dtype=float)
    for code, row_positions in adjusted.groupby("htsc_code", sort=False).groups.items():
        source = by_code.get(str(code), pd.Series(dtype=float))
        if not source.empty and not source.index.is_unique:
            source = source.groupby(level=0).last()
        series = _backward_factor_series(source)
        days = pd.DatetimeIndex(adjusted.loc[row_positions, "time"])
        if series.empty:
            continue
        locations = series.index.searchsorted(days, side="right") - 1
        covered = locations >= 0
        if not covered.any():
            continue
        code_factors = series.to_numpy(dtype=float)[locations[covered]]
        if (~np.isfinite(code_factors)).any() or (code_factors <= 0).any():
            bad_day = days[covered][(~np.isfinite(code_factors)) | (code_factors <= 0)][0]
            raise StyleIndexDataError(f"wide_xdy 存在无效复权因子: {code} {bad_day.date()}")
        positions = np.asarray(list(row_positions), dtype=int)
        factors[positions[covered]] = code_factors
    adjusted["adjusted_close"] = adjusted["close"].to_numpy(dtype=float) * factors
    return adjusted.pivot(index="time", columns="htsc_code", values="adjusted_close").sort_index().astype(float)


def load_adjusted_close(
    *,
    market_base_dir: str | Path,
    adj_factor_daily_dir: str | Path,
    wide_xdy_dir: str | Path,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> pd.DataFrame:
    """读取后复权收盘价，优先使用每日复权因子，失败后回退宽表。"""
    start_dt = pd.Timestamp(start_date).floor("D")
    end_dt = pd.Timestamp(end_date).floor("D")
    if start_dt > end_dt:
        raise ValueError("start_date 不能晚于 end_date")
    market = _load_market_close(market_base_dir, start_dt, end_dt)
    fast = _load_fast_adjusted_close(market, adj_factor_daily_dir, start_dt, end_dt)
    raw_close = market.pivot(index="time", columns="htsc_code", values="close").sort_index().astype(float)
    if fast is not None:
        if not int(fast.attrs.get("missing_adj_factor_rows", 0)):
            return fast.combine_first(raw_close).sort_index().astype(float)
        try:
            wide = _load_wide_adjusted_close(market, wide_xdy_dir)
        except StyleIndexDataError:
            wide = pd.DataFrame(index=raw_close.index, columns=raw_close.columns, dtype=float)
        # 只有两个复权源都没有记录的极少数股票才使用 1.0 身份因子。
        return fast.combine_first(wide).combine_first(raw_close).sort_index().astype(float)
    try:
        adjusted = _load_wide_adjusted_close(market, wide_xdy_dir)
    except StyleIndexDataError:
        adjusted = pd.DataFrame(index=raw_close.index, columns=raw_close.columns, dtype=float)
    return adjusted.combine_first(raw_close).sort_index().astype(float)


def load_adjusted_open_close(
    *,
    market_base_dir: str | Path,
    adj_factor_daily_dir: str | Path,
    wide_xdy_dir: str | Path,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """读取同一复权口径的开盘价和收盘价，供T+1开盘执行。"""
    start_dt = pd.Timestamp(start_date).floor("D")
    end_dt = pd.Timestamp(end_date).floor("D")
    adjusted_close = load_adjusted_close(
        market_base_dir=market_base_dir,
        adj_factor_daily_dir=adj_factor_daily_dir,
        wide_xdy_dir=wide_xdy_dir,
        start_date=start_dt,
        end_date=end_dt,
    )
    files = _partition_files(Path(market_base_dir), _month_starts(start_dt, end_dt))
    months = _month_starts(start_dt, end_dt)
    if len(files) != len(months):
        missing = [month.strftime("%Y-%m") for month in months if not (Path(market_base_dir) / f"year={month.year}" / f"month={month.month:02d}" / "merged.parquet").is_file()]
        raise StyleIndexDataError("股票行情缺少月份分区: " + "、".join(missing))
    frames = [pd.read_parquet(path, columns=["time", "htsc_code", "open", "close"]) for path in files]
    if not frames:
        return adjusted_close.copy(), adjusted_close
    market = pd.concat(frames, ignore_index=True)
    market["time"] = pd.to_datetime(market["time"], errors="coerce").dt.floor("D")
    market["htsc_code"] = market["htsc_code"].astype(str).str.strip().str.upper()
    market["open"] = pd.to_numeric(market["open"], errors="coerce")
    market["close"] = pd.to_numeric(market["close"], errors="coerce")
    market = market[market["time"].between(start_dt, end_dt)].drop_duplicates(["time", "htsc_code"], keep="last")
    raw_open = market.pivot(index="time", columns="htsc_code", values="open").sort_index().astype(float)
    raw_close = market.pivot(index="time", columns="htsc_code", values="close").sort_index().astype(float)
    raw_open = raw_open.reindex(index=adjusted_close.index, columns=adjusted_close.columns)
    raw_close = raw_close.reindex(index=adjusted_close.index, columns=adjusted_close.columns)
    ratio = adjusted_close.div(raw_close.where(raw_close > 0))
    adjusted_open = raw_open.where(raw_open > 0).mul(ratio)
    return adjusted_open.astype(float), adjusted_close.astype(float)


def _select_codes(snapshot: pd.DataFrame, *, ratio: float, max_count: int, ascending: bool) -> list[str]:
    if not 0.0 < float(ratio) <= 1.0:
        raise ValueError("ratio 必须大于 0 且小于等于 1")
    if int(max_count) < 1:
        raise ValueError("max_count 必须大于等于 1")
    required = {"htsc_code", "score"}
    missing = required - set(snapshot.columns)
    if missing:
        raise KeyError(f"选股快照缺少列: {sorted(missing)}")
    valid = snapshot.loc[:, ["htsc_code", "score"]].copy()
    valid["htsc_code"] = valid["htsc_code"].astype(str).str.strip().str.upper()
    valid["score"] = pd.to_numeric(valid["score"], errors="coerce")
    valid = valid.replace([np.inf, -np.inf], np.nan).dropna(subset=["htsc_code", "score"])
    valid = valid[valid["htsc_code"].ne("")].drop_duplicates("htsc_code", keep="last")
    count = min(int(max_count), max(1, math.ceil(len(valid) * float(ratio)))) if not valid.empty else 0
    if count == 0:
        return []
    return valid.sort_values(["score", "htsc_code"], ascending=[ascending, ascending]).head(count)["htsc_code"].tolist()


def select_target_weights(
    snapshot: pd.DataFrame,
    *,
    ratio: float = 0.20,
    max_count: int = 200,
) -> dict[str, dict[str, float]]:
    """按评分生成高分腿和低分腿的等权目标。"""
    high_codes = _select_codes(snapshot, ratio=ratio, max_count=max_count, ascending=False)
    low_codes = _select_codes(snapshot, ratio=ratio, max_count=max_count, ascending=True)

    def _weights(codes: list[str]) -> dict[str, float]:
        if not codes:
            return {}
        weight = 1.0 / len(codes)
        return {code: weight for code in codes}

    return {"high": _weights(high_codes), "low": _weights(low_codes)}


def _drift_weights(
    weights: Mapping[str, float],
    day_returns: pd.Series,
    portfolio_return: float,
) -> dict[str, float]:
    """将收盘后的持仓市值变化转换为下一交易日的权重。"""
    denominator = 1.0 + float(portfolio_return)
    if denominator <= 0.0:
        return {}
    values = {
        code: float(weight) * (1.0 + float(day_returns.get(code, 0.0) or 0.0))
        for code, weight in weights.items()
    }
    total = sum(values.values())
    if total <= 0.0:
        return {}
    return {code: value / total for code, value in values.items() if value > 0.0}


def _snapshot_for_date(scores: pd.DataFrame, valid_bar: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    if day not in scores.index:
        return pd.DataFrame(columns=["htsc_code", "score"])
    row = scores.loc[day]
    valid = valid_bar.loc[day] if day in valid_bar.index else pd.Series(False, index=scores.columns)
    frame = pd.DataFrame({"htsc_code": scores.columns, "score": row.to_numpy(dtype=float), "valid_bar": valid.reindex(scores.columns).fillna(False).to_numpy(dtype=bool)})
    return frame[frame["valid_bar"]].drop(columns=["valid_bar"])


def build_equal_weight_index(
    score_frame: pd.DataFrame,
    adjusted_close: pd.DataFrame,
    valid_bar: pd.DataFrame,
    *,
    adjusted_open: pd.DataFrame | None = None,
    rebalance_dates: Iterable[pd.Timestamp | date],
    ratio: float = 0.20,
    max_count: int = 200,
) -> dict[str, Any]:
    """计算 T 日收盘打分、T+1 开盘执行的无手续费高低分等权指数。"""
    scores = _normalise_frame(score_frame)
    prices = _normalise_frame(adjusted_close)
    opens = _normalise_frame(adjusted_open) if adjusted_open is not None else prices.shift(1).combine_first(prices)
    valid = valid_bar.reindex(index=prices.index, columns=prices.columns).fillna(False).astype(bool) & prices.gt(0)
    # 指数每天必须有收盘价，交易日历以收盘行情为准；因子/开盘独有日期不能制造虚假交易日。
    index = prices.index.sort_values()
    columns = prices.columns.union(opens.columns).union(scores.columns)
    prices = prices.reindex(index=index, columns=columns)
    opens = opens.reindex(index=index, columns=columns)
    scores = scores.reindex(index=index, columns=columns)
    valid = valid.reindex(index=index, columns=columns).fillna(False)
    price_for_return = prices.where(valid).ffill()
    close_returns = price_for_return.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    rebalance = _as_date_set(rebalance_dates)

    target_weights: dict[str, dict[pd.Timestamp, dict[str, float]]] = {"high": {}, "low": {}}
    for day in sorted(rebalance):
        if day not in index:
            continue
        targets = select_target_weights(_snapshot_for_date(scores, valid, day), ratio=ratio, max_count=max_count)
        target_weights["high"][day] = targets["high"]
        target_weights["low"][day] = targets["low"]

    effective_by_day: dict[str, dict[pd.Timestamp, dict[str, float]]] = {"high": {}, "low": {}}
    signal_dates: dict[date, date] = {}
    for leg in ("high", "low"):
        for day, weights in target_weights[leg].items():
            following = index[index > day]
            if len(following):
                effective_by_day[leg][following[0]] = weights
                signal_dates[following[0].date()] = day.date()

    index_dfs: dict[str, pd.Series] = {}
    weights_output: dict[str, dict[date, dict[str, float]]] = {"high": {}, "low": {}}
    diagnostics: dict[str, dict[date, dict[str, Any]]] = {"high": {}, "low": {}}
    execution_targets: dict[str, dict[date, dict[str, float]]] = {"high": {}, "low": {}}
    for leg in ("high", "low"):
        values: list[float] = []
        current = 100.0
        active: dict[str, float] = {}
        for position, day in enumerate(index):
            rebalanced = day in effective_by_day[leg]
            reported_weights = dict(active)
            if position:
                previous_day = index[position - 1]
                if rebalanced:
                    target = effective_by_day[leg][day]
                    execution_targets[leg][day.date()] = dict(target)
                    previous_close = prices.loc[previous_day]
                    day_open = opens.loc[day]
                    tradable = day_open.gt(0) & day_open.notna() & prices.loc[day].gt(0) & valid.loc[day]
                    overnight_returns = day_open.div(previous_close.where(previous_close > 0)).sub(1.0)
                    overnight_returns = overnight_returns.replace([np.inf, -np.inf], np.nan).fillna(0.0)
                    overnight_portfolio_return = float(sum(weight * float(overnight_returns.get(code, 0.0)) for code, weight in active.items()))
                    current *= 1.0 + overnight_portfolio_return
                    open_weights = _drift_weights(active, overnight_returns, overnight_portfolio_return) if active else {}
                    locked = {code: weight for code, weight in open_weights.items() if not bool(tradable.get(code, False))}
                    available_targets = {code: weight for code, weight in target.items() if bool(tradable.get(code, False))}
                    if available_targets:
                        residual = max(0.0, 1.0 - sum(locked.values()))
                        available_sum = sum(available_targets.values())
                        next_weights = dict(locked)
                        next_weights.update({code: residual * weight / available_sum for code, weight in available_targets.items()})
                    else:
                        next_weights = open_weights
                    reported_weights = dict(next_weights)
                    intraday_returns = prices.loc[day].div(day_open.where(day_open > 0)).sub(1.0)
                    fallback_returns = prices.loc[day].div(previous_close.where(previous_close > 0)).sub(1.0)
                    intraday_returns = intraday_returns.where(tradable, fallback_returns).replace([np.inf, -np.inf], np.nan).fillna(0.0)
                    intraday_portfolio_return = float(sum(weight * float(intraday_returns.get(code, 0.0)) for code, weight in next_weights.items()))
                    current *= 1.0 + intraday_portfolio_return
                    active = _drift_weights(next_weights, intraday_returns, intraday_portfolio_return) if next_weights else {}
                else:
                    reported_weights = dict(active)
                    day_returns = close_returns.loc[day].reindex(active.keys()).fillna(0.0)
                    portfolio_return = float(sum(active.get(code, 0.0) * float(day_returns.get(code, 0.0)) for code in active))
                    current *= 1.0 + portfolio_return
                    active = _drift_weights(active, day_returns, portfolio_return) if active else {}
            weights_output[leg][day.date()] = reported_weights
            valid_count = int(valid.loc[day].sum()) if day in valid.index else 0
            priced_count = int(sum(code in prices.columns and bool(valid.loc[day].get(code, False)) for code in reported_weights)) if day in valid.index else 0
            values.append(current)
            diagnostics[leg][day.date()] = {
                "weight_sum": float(sum(reported_weights.values())),
                "holding_count": len(reported_weights),
                "valid_count": valid_count,
                "valid_price_coverage": float(priced_count / len(reported_weights)) if reported_weights else 0.0,
                "rebalanced": rebalanced,
            }
        index_dfs[leg] = pd.Series(values, index=index, dtype=float, name=leg)

    return {
        "index_dfs": index_dfs,
        "weights": weights_output,
        "diagnostics": diagnostics,
        "signal_dates": signal_dates,
        "target_weights": {
            leg: dict(execution_targets[leg])
            for leg in ("high", "low")
        },
        "signal_target_weights": {
            leg: {day.date(): dict(weights) for day, weights in target_weights[leg].items()}
            for leg in ("high", "low")
        },
    }
