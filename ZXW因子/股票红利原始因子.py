"""基于已实施除权除息事件的股票红利原始因子。"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


BUNDLE_ID = "stock_dividend_raw"
SOURCE_HISTORY_START = "2010-01-01"
DIVIDEND_SOURCE_GLOB = (
    r"D:\database\stock_adj_daily_raw\year=*\month=*\merged.parquet"
)
FACTOR_NAME_MAP = {
    "调整后每股现金分红_TTM": "cash_dividend_per_share_ttm_adjusted",
    "已实施股息率_TTM": "realized_dividend_yield_ttm",
    "现金分红次数_近3年": "cash_dividend_event_count_3y",
    "有分红年度占比_近5年": "cash_dividend_active_year_ratio_5y",
    "连续分红年数": "cash_dividend_consecutive_years",
    "每股分红三年复合增长率": "cash_dividend_cagr_3y",
    "分红削减次数_近5年": "cash_dividend_cut_count_5y",
}
SOURCE_COLUMNS = (
    "htsc_code",
    "event_date",
    "interest",
    "stockBonus",
    "stockGift",
)


def get_factor_catalog() -> dict[str, dict[str, str]]:
    return {"factor_name_map": dict(FACTOR_NAME_MAP)}


def get_factor_lookback_config() -> dict[str, object]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": 0,
        "factor_lookback_days": {key: 0 for key in FACTOR_NAME_MAP.values()},
        "source_history_start": SOURCE_HISTORY_START,
    }


def _normalize_code(value: object) -> str:
    return str(value or "").strip().upper()


def _source_for_duckdb(source_glob: str) -> str | list[str]:
    path = Path(source_glob)
    if path.is_file():
        return str(path)
    return str(source_glob).replace("\\", "/")


def _read_events(
    source_glob: str,
    target_codes: list[str],
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    source = _source_for_duckdb(source_glob)
    placeholders = ", ".join("?" for _ in target_codes)
    with duckdb.connect(database=":memory:") as con:
        try:
            available = {
                str(row[0])
                for row in con.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?, union_by_name=true)",
                    [source],
                ).fetchall()
            }
        except Exception as exc:
            raise ValueError(f"红利事件源无法读取: {source_glob}") from exc
        missing = [column for column in SOURCE_COLUMNS if column not in available]
        if missing:
            raise ValueError(
                "红利事件源缺少字段: "
                f"{', '.join(missing)}；source={source_glob}"
            )
        query = f"""
            SELECT
                UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                CAST(event_date AS DATE) AS event_date,
                TRY_CAST(interest AS DOUBLE) AS interest,
                TRY_CAST(stockBonus AS DOUBLE) AS stockBonus,
                TRY_CAST(stockGift AS DOUBLE) AS stockGift
            FROM read_parquet(?, union_by_name=true)
            WHERE CAST(event_date AS DATE) >= DATE '{SOURCE_HISTORY_START}'
              AND CAST(event_date AS DATE) <= ?
              AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN ({placeholders})
            ORDER BY htsc_code, event_date
        """
        frame = con.execute(query, [source, end_date.date(), *target_codes]).df()
    if frame.empty:
        return pd.DataFrame(columns=SOURCE_COLUMNS)
    frame["event_date"] = pd.to_datetime(frame["event_date"], errors="coerce").dt.floor("D")
    frame["htsc_code"] = frame["htsc_code"].map(_normalize_code)
    for column in SOURCE_COLUMNS[2:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["htsc_code", "event_date"])
    frame["interest"] = frame["interest"].fillna(0.0)
    frame["stockBonus"] = frame["stockBonus"].fillna(0.0)
    frame["stockGift"] = frame["stockGift"].fillna(0.0)
    frame["effective_date"] = frame["event_date"] + pd.Timedelta(days=1)
    frame = frame.drop_duplicates(["htsc_code", "effective_date"], keep="last")
    return frame.sort_values(["htsc_code", "effective_date"]).reset_index(drop=True)


def _empty_factor_frames(index: pd.DatetimeIndex, codes: list[str]) -> dict[str, pd.DataFrame]:
    return {
        key: pd.DataFrame(index=index, columns=codes, dtype=float)
        for key in FACTOR_NAME_MAP.values()
    }


def _calculate_code_factors(
    events: pd.DataFrame,
    index: pd.DatetimeIndex,
    close: pd.Series,
) -> dict[str, np.ndarray]:
    result = {
        key: np.full(len(index), np.nan, dtype=float)
        for key in FACTOR_NAME_MAP.values()
    }
    if events.empty:
        for key in (
            "cash_dividend_per_share_ttm_adjusted",
            "cash_dividend_event_count_3y",
            "cash_dividend_active_year_ratio_5y",
            "cash_dividend_consecutive_years",
            "cash_dividend_cut_count_5y",
        ):
            result[key].fill(0.0)
        return result

    work = events.sort_values("effective_date").reset_index(drop=True).copy()
    expansion = 1.0 + work["stockBonus"].to_numpy(float) + work["stockGift"].to_numpy(float)
    if (~np.isfinite(expansion)).any() or (expansion <= 0).any():
        raise ValueError("红利事件存在非法送转扩股倍率（必须大于0）")
    cumulative_after = np.cumprod(expansion)
    cumulative_before = np.concatenate(([1.0], cumulative_after[:-1]))
    interest = work["interest"].to_numpy(float)
    valid_interest = np.isfinite(interest) & (interest > 0)
    cash_base = np.where(valid_interest, interest * cumulative_before, 0.0)
    dates = pd.DatetimeIndex(work["effective_date"])
    years = dates.year.to_numpy(dtype=int)
    event_ns = dates.asi8

    for pos, research_date in enumerate(index):
        research_ns = research_date.value
        current_pos = int(np.searchsorted(event_ns, research_ns, side="right") - 1)
        current_factor = cumulative_after[current_pos] if current_pos >= 0 else 1.0
        if not np.isfinite(current_factor) or current_factor <= 0:
            raise ValueError("红利事件累计送转倍率非法")

        ttm_start = research_date - pd.Timedelta(days=365)
        ttm_mask = (dates > ttm_start) & (dates <= research_date) & valid_interest
        ttm_value = float(cash_base[ttm_mask].sum() / current_factor)
        result["cash_dividend_per_share_ttm_adjusted"][pos] = ttm_value
        price = pd.to_numeric(close.iloc[pos], errors="coerce")
        if np.isfinite(price) and price > 0:
            result["realized_dividend_yield_ttm"][pos] = ttm_value / price * 100.0

        three_year_start = research_date - pd.DateOffset(years=3)
        count_mask = (
            (dates > three_year_start)
            & (dates <= research_date)
            & valid_interest
        )
        result["cash_dividend_event_count_3y"][pos] = float(count_mask.sum())

        latest_completed_year = research_date.year - 1
        completed_years = list(range(latest_completed_year - 4, latest_completed_year + 1))
        annual_base = {
            year: float(cash_base[(years == year) & valid_interest].sum())
            for year in completed_years
        }
        history_complete = completed_years[0] >= int(SOURCE_HISTORY_START[:4])
        if history_complete:
            active_years = sum(value > 0 for value in annual_base.values())
            result["cash_dividend_active_year_ratio_5y"][pos] = active_years / 5.0 * 100.0

            consecutive = 0
            for year in reversed(completed_years):
                if annual_base[year] <= 0:
                    break
                consecutive += 1
            result["cash_dividend_consecutive_years"][pos] = float(consecutive)

        start_year = research_date.year - 4
        end_year = research_date.year - 1
        cagr_values = [annual_base[year] for year in range(start_year, end_year + 1)]
        if all(value > 0 for value in cagr_values):
            result["cash_dividend_cagr_3y"][pos] = (
                (cagr_values[-1] / cagr_values[0]) ** (1.0 / 3.0) - 1.0
            ) * 100.0

        if history_complete:
            cuts = sum(
                annual_base[year] < annual_base[year - 1]
                for year in completed_years[1:]
                if annual_base[year - 1] > 0
            )
            result["cash_dividend_cut_count_5y"][pos] = float(cuts)

    return result


def build_stock_dividend_raw_factor_bundle(
    C: pd.DataFrame,
    *,
    stock_codes: set[str] | list[str] | tuple[str, ...],
    source_glob: str = DIVIDEND_SOURCE_GLOB,
) -> dict[str, object]:
    index = pd.DatetimeIndex(pd.to_datetime(C.index)).floor("D")
    market_codes = {_normalize_code(code) for code in C.columns}
    target_codes = sorted(
        market_codes
        & {_normalize_code(code) for code in stock_codes if _normalize_code(code)}
    )
    factors = _empty_factor_frames(index, target_codes)
    if index.empty or not target_codes:
        return {
            "bundle_id": BUNDLE_ID,
            "factor_dfs": factors,
            "factor_name_map": dict(FACTOR_NAME_MAP),
        }

    events = _read_events(source_glob, target_codes, index.max())
    for code in target_codes:
        code_events = events[events["htsc_code"] == code]
        code_values = _calculate_code_factors(code_events, index, C[code].reindex(index))
        for factor_key, values in code_values.items():
            factors[factor_key][code] = values
    return {
        "bundle_id": BUNDLE_ID,
        "factor_dfs": factors,
        "factor_name_map": dict(FACTOR_NAME_MAP),
    }
