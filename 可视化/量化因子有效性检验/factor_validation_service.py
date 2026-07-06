from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

VIS_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = VIS_ROOT.parent
SIGNAL_DAILY_BASE_PATH = Path(r"D:\database\signal_daily")
DAILY_BASE_PATH = Path(r"D:\database\stock_basic_data_daily")
UNIVERSE_CSV_PATH = PROJECT_ROOT / "\u534e\u6cf0\u6570\u636e\u83b7\u53d6" / "ALL_A_\u5168\u5e02\u573a\u80a1\u7968_20260626.csv"
FACTOR_CATALOG_PATH = PROJECT_ROOT / "\u56e0\u5b50\u5206\u7c7b" / "factor_catalog.json"
RECORDS_DIR = Path(__file__).resolve().parent / "records"
FACTOR_DIR_PREFIX = "factor="
MERGED_FILE_NAME = "merged.parquet"
DEFAULT_PERIODS = [1, 3, 5, 10, 20, 60]
PRICE_ADJUST_MODE = "backward_ratio"
ALLOWED_GROUP_COUNTS = {5, 8, 10, 20}
MAX_RECORD_ITEMS = 200


class FactorValidationError(Exception):
    pass


class FactorValidationNotFoundError(FactorValidationError):
    pass


class FactorValidationInputError(FactorValidationError):
    pass


def apply_ohlc_adj_to_price_df(price_df: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    bt_dir = str(PROJECT_ROOT / "backtrader")
    if bt_dir not in sys.path:
        sys.path.append(bt_dir)
    from models.zxw_rule_backtest.zxw_view_results_full import apply_ohlc_adj_to_price_df as _apply

    return _apply(price_df, **kwargs)


def _sanitize_factor_dir_name(factor_name: str) -> str:
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", str(factor_name).strip())
    safe_name = safe_name.rstrip(" .")
    return safe_name or "未命名因子"


def _list_partition_data_files(partition_dir: Path) -> list[str]:
    if not partition_dir.is_dir():
        return []
    paths: list[str] = []
    merged = partition_dir / MERGED_FILE_NAME
    if merged.is_file():
        paths.append(merged.as_posix())
    for item in sorted(partition_dir.glob("part_*.parquet")):
        if item.is_file():
            paths.append(item.as_posix())
    return paths


def _iter_year_month(start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[int, int]]:
    cur = pd.Timestamp(start.year, start.month, 1)
    last = pd.Timestamp(end.year, end.month, 1)
    out: list[tuple[int, int]] = []
    while cur <= last:
        out.append((int(cur.year), int(cur.month)))
        cur += pd.DateOffset(months=1)
    return out


def _build_month_partition_paths(base_path: Path, start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    paths: list[str] = []
    for year, month in _iter_year_month(start, end):
        paths.extend(_list_partition_data_files(base_path / f"year={year}" / f"month={month:02d}"))
    return paths


def _build_factor_partition_paths(factor_name: str, start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    factor_base = SIGNAL_DAILY_BASE_PATH / f"{FACTOR_DIR_PREFIX}{_sanitize_factor_dir_name(factor_name)}"
    if not factor_base.exists():
        return []
    return _build_month_partition_paths(factor_base, start, end)


def _load_available_factors() -> list[str]:
    if not SIGNAL_DAILY_BASE_PATH.exists():
        return []
    names: list[str] = []
    for item in SIGNAL_DAILY_BASE_PATH.iterdir():
        if item.is_dir() and item.name.startswith(FACTOR_DIR_PREFIX):
            name = item.name[len(FACTOR_DIR_PREFIX) :].strip()
            if name:
                names.append(name)
    return sorted(set(names))


def _load_factor_catalog(available_factors: list[str]) -> list[dict[str, Any]]:
    available = set(available_factors)
    if not FACTOR_CATALOG_PATH.exists():
        return [{"group_id": "all", "group_name": "全部因子", "children": available_factors}]
    try:
        raw = json.loads(FACTOR_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    groups: list[dict[str, Any]] = []
    grouped: set[str] = set()
    for item in raw.get("groups", []) if isinstance(raw, dict) else []:
        if not isinstance(item, dict):
            continue
        children = [str(x).strip() for x in item.get("children", []) if str(x).strip() in available]
        if not children:
            continue
        groups.append(
            {
                "group_id": str(item.get("group_id") or "group").strip(),
                "group_name": str(item.get("group_name") or item.get("group_id") or "未命名").strip(),
                "children": children,
            }
        )
        grouped.update(children)
    ungrouped = [name for name in available_factors if name not in grouped]
    if ungrouped:
        groups.append({"group_id": "ungrouped", "group_name": "未分类", "children": ungrouped})
    if not groups:
        groups.append({"group_id": "all", "group_name": "全部因子", "children": available_factors})
    return groups


def list_factor_validation_factors() -> dict[str, Any]:
    factors = _load_available_factors()
    return {
        "factors": factors,
        "groups": _load_factor_catalog(factors),
        "meta": {
            "count": len(factors),
            "base_path": str(SIGNAL_DAILY_BASE_PATH),
            "server_time": int(time.time()),
        },
    }


def _parse_date(value: Any, field_name: str) -> pd.Timestamp:
    if value is None or str(value).strip() == "":
        raise FactorValidationInputError(f"{field_name} 不能为空")
    ts = pd.to_datetime(str(value).strip(), errors="coerce")
    if pd.isna(ts):
        raise FactorValidationInputError(f"{field_name} 日期格式无效")
    return pd.Timestamp(ts).normalize()


def _parse_periods(value: Any) -> list[int]:
    if value is None:
        return list(DEFAULT_PERIODS)
    raw = value if isinstance(value, list) else str(value).split(",")
    periods: list[int] = []
    for item in raw:
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            continue
        if parsed > 0 and parsed not in periods:
            periods.append(parsed)
    return periods or list(DEFAULT_PERIODS)


def _parse_positive_int(value: Any, default: int, field_name: str) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise FactorValidationInputError(f"{field_name} 必须是整数") from exc
    if parsed <= 0:
        raise FactorValidationInputError(f"{field_name} 必须大于 0")
    return parsed


def _load_universe_codes(path: Path = UNIVERSE_CSV_PATH) -> list[str]:
    if not path.exists():
        raise FactorValidationNotFoundError(f"股票池 CSV 不存在: {path}")
    df = pd.read_csv(path, encoding="utf-8-sig")
    col = "stock_code" if "stock_code" in df.columns else "htsc_code"
    if col not in df.columns:
        raise FactorValidationInputError("股票池 CSV 缺少 stock_code/htsc_code 列")
    codes = (
        df[col]
        .astype(str)
        .str.strip()
        .str.upper()
        .loc[lambda s: s.str.contains(r"^\d{6}\.(SH|SZ|BJ)$", regex=True, na=False)]
        .drop_duplicates()
        .tolist()
    )
    if not codes:
        raise FactorValidationNotFoundError("股票池 CSV 没有有效股票代码")
    return codes


def _read_factor_frame(factor_name: str, start: pd.Timestamp, end: pd.Timestamp, codes: list[str]) -> pd.DataFrame:
    paths = _build_factor_partition_paths(factor_name, start, end)
    if not paths:
        raise FactorValidationNotFoundError(f"未找到因子分区: {factor_name}")
    placeholders = ", ".join("?" for _ in paths)
    con = duckdb.connect(database=":memory:")
    try:
        df = con.execute(
            f"""
            SELECT
                UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                CAST(COALESCE(TRY_CAST(time AS TIMESTAMP), TO_TIMESTAMP(TRY_CAST(time AS BIGINT))) AS DATE) AS time,
                TRY_CAST(value AS DOUBLE) AS value
            FROM read_parquet([{placeholders}], union_by_name=true)
            WHERE htsc_code IS NOT NULL
            """,
            paths,
        ).fetchdf()
    finally:
        con.close()
    if df.empty:
        raise FactorValidationNotFoundError(f"因子没有可用数据: {factor_name}")
    code_set = set(codes)
    df["htsc_code"] = df["htsc_code"].astype(str).str.strip().str.upper()
    df["time"] = pd.to_datetime(df["time"], errors="coerce").dt.normalize()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df[df["htsc_code"].isin(code_set) & df["time"].between(start, end)]
    return df.dropna(subset=["htsc_code", "time"]).drop_duplicates(["time", "htsc_code"], keep="last")


def _read_price_frame(start: pd.Timestamp, end: pd.Timestamp, codes: list[str], max_period: int) -> pd.DataFrame:
    price_end = end + pd.Timedelta(days=max_period * 3 + 14)
    paths = _build_month_partition_paths(DAILY_BASE_PATH, start, price_end)
    if not paths:
        raise FactorValidationNotFoundError("未找到日频行情分区")
    placeholders = ", ".join("?" for _ in paths)
    con = duckdb.connect(database=":memory:")
    try:
        df = con.execute(
            f"""
            SELECT
                UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
                CAST(time AS DATE) AS time,
                TRY_CAST(close AS DOUBLE) AS close
            FROM read_parquet([{placeholders}], union_by_name=true)
            WHERE htsc_code IS NOT NULL
              AND close IS NOT NULL
            """,
            paths,
        ).fetchdf()
    finally:
        con.close()
    code_set = set(codes)
    df["htsc_code"] = df["htsc_code"].astype(str).str.strip().str.upper()
    df["time"] = pd.to_datetime(df["time"], errors="coerce").dt.normalize()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df[df["htsc_code"].isin(code_set)]
    df = df.dropna(subset=["htsc_code", "time", "close"]).drop_duplicates(["time", "htsc_code"], keep="last")
    if df.empty:
        return df
    adjusted = apply_ohlc_adj_to_price_df(
        df,
        target_codes=codes,
        query_start_date=start.strftime("%Y-%m-%d"),
        query_end_exclusive=(price_end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        adj_mode=PRICE_ADJUST_MODE,
    )
    adjusted["htsc_code"] = adjusted["htsc_code"].astype(str).str.strip().str.upper()
    adjusted["time"] = pd.to_datetime(adjusted["time"], errors="coerce").dt.normalize()
    adjusted["close"] = pd.to_numeric(adjusted["close"], errors="coerce")
    return adjusted.dropna(subset=["htsc_code", "time", "close"]).drop_duplicates(["time", "htsc_code"], keep="last")


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _round_float(value: Any, digits: int = 6) -> float | None:
    parsed = _safe_float(value)
    return None if parsed is None else round(parsed, digits)


def _pearson(x: pd.Series, y: pd.Series) -> float | None:
    valid = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(valid) < 2 or valid["x"].nunique() < 2 or valid["y"].nunique() < 2:
        return None
    return _safe_float(valid["x"].corr(valid["y"], method="pearson"))


def _spearman(x: pd.Series, y: pd.Series) -> float | None:
    valid = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(valid) < 2 or valid["x"].nunique() < 2 or valid["y"].nunique() < 2:
        return None
    return _safe_float(valid["x"].rank(method="average").corr(valid["y"].rank(method="average"), method="pearson"))


def _build_forward_returns(price_df: pd.DataFrame, periods: list[int]) -> pd.DataFrame:
    out_parts: list[pd.DataFrame] = []
    for code, sub in price_df.sort_values(["htsc_code", "time"]).groupby("htsc_code", sort=False):
        tmp = sub[["time", "htsc_code", "close"]].copy().sort_values("time")
        for period in periods:
            tmp[f"ret_{period}"] = tmp["close"].shift(-period) / tmp["close"] - 1.0
        out_parts.append(tmp.drop(columns=["close"]))
    return pd.concat(out_parts, ignore_index=True) if out_parts else pd.DataFrame()


def _quality_metrics(factor_df: pd.DataFrame, universe_size: int) -> dict[str, Any]:
    clean = factor_df.copy()
    clean["is_valid"] = pd.to_numeric(clean["value"], errors="coerce").map(lambda v: bool(pd.notna(v) and math.isfinite(float(v))))
    rows: list[dict[str, Any]] = []
    for ts, sub in clean.groupby("time"):
        valid = pd.to_numeric(sub.loc[sub["is_valid"], "value"], errors="coerce").dropna()
        abnormal_count = 0
        if len(valid) > 0:
            median = valid.median()
            mad = (valid - median).abs().median()
            if pd.notna(mad) and float(mad) > 0:
                lo = median - 5 * mad
                hi = median + 5 * mad
            else:
                lo = valid.quantile(0.001)
                hi = valid.quantile(0.999)
            abnormal_count = int(((valid < lo) | (valid > hi)).sum())
        valid_count = int(len(valid))
        rows.append(
            {
                "date": pd.Timestamp(ts).strftime("%Y-%m-%d"),
                "valid_stock_count": valid_count,
                "coverage": valid_count / universe_size if universe_size else None,
                "abnormal_ratio": abnormal_count / valid_count if valid_count else 0.0,
            }
        )
    if not rows:
        return {"daily": [], "avg_valid_stock_count": 0.0, "avg_coverage": 0.0, "avg_abnormal_ratio": 0.0, "empty_dates": []}
    daily = pd.DataFrame(rows)
    return {
        "daily": rows,
        "avg_valid_stock_count": _round_float(daily["valid_stock_count"].mean(), 2),
        "avg_coverage": _round_float(daily["coverage"].mean(), 6),
        "avg_abnormal_ratio": _round_float(daily["abnormal_ratio"].mean(), 6),
        "empty_dates": daily.loc[daily["valid_stock_count"].eq(0), "date"].tolist(),
    }


def _ic_metrics(panel: pd.DataFrame, periods: list[int], rolling_window: int) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    summary: list[dict[str, Any]] = []
    series_by_period: dict[str, list[dict[str, Any]]] = {}
    rolling_by_period: dict[str, list[dict[str, Any]]] = {}
    for period in periods:
        ret_col = f"ret_{period}"
        daily_rows: list[dict[str, Any]] = []
        for ts, sub in panel.dropna(subset=["value", ret_col]).groupby("time"):
            ic = _pearson(sub["value"], sub[ret_col])
            rank_ic = _spearman(sub["value"], sub[ret_col])
            daily_rows.append(
                {
                    "date": pd.Timestamp(ts).strftime("%Y-%m-%d"),
                    "ic": _round_float(ic),
                    "rank_ic": _round_float(rank_ic),
                    "count": int(len(sub)),
                }
            )
        series_df = pd.DataFrame(daily_rows)
        if series_df.empty:
            series_by_period[str(period)] = []
            rolling_by_period[str(period)] = []
            summary.append({"period": period, "ic_mean": None, "rank_ic_mean": None, "icir": None, "win_rate": None, "count": 0})
            continue
        series_df["cum_ic"] = pd.to_numeric(series_df["ic"], errors="coerce").fillna(0.0).cumsum()
        ic_values = pd.to_numeric(series_df["ic"], errors="coerce").dropna()
        rank_values = pd.to_numeric(series_df["rank_ic"], errors="coerce").dropna()
        ic_std = ic_values.std(ddof=1)
        summary.append(
            {
                "period": period,
                "ic_mean": _round_float(ic_values.mean()),
                "rank_ic_mean": _round_float(rank_values.mean()),
                "icir": _round_float(ic_values.mean() / ic_std if len(ic_values) > 1 and ic_std else None),
                "win_rate": _round_float((ic_values > 0).mean() if len(ic_values) else None),
                "count": int(len(ic_values)),
            }
        )
        series_by_period[str(period)] = [
            {
                "date": str(row.date),
                "ic": _round_float(row.ic),
                "rank_ic": _round_float(row.rank_ic),
                "cum_ic": _round_float(row.cum_ic),
                "count": int(row.count),
            }
            for row in series_df.itertuples(index=False)
        ]
        roll = series_df.copy()
        roll["rolling_ic"] = pd.to_numeric(roll["ic"], errors="coerce").rolling(rolling_window, min_periods=2).mean()
        roll["rolling_rank_ic"] = pd.to_numeric(roll["rank_ic"], errors="coerce").rolling(rolling_window, min_periods=2).mean()
        roll["rolling_ic_std"] = pd.to_numeric(roll["ic"], errors="coerce").rolling(rolling_window, min_periods=2).std()
        roll["rolling_icir"] = roll["rolling_ic"] / roll["rolling_ic_std"]
        rolling_by_period[str(period)] = [
            {
                "date": str(row.date),
                "rolling_ic": _round_float(row.rolling_ic),
                "rolling_rank_ic": _round_float(row.rolling_rank_ic),
                "rolling_icir": _round_float(row.rolling_icir),
            }
            for row in roll.itertuples(index=False)
        ]
    return summary, series_by_period, rolling_by_period


def _assign_groups(values: pd.Series, group_count: int) -> pd.Series:
    ranks = values.rank(method="first")
    valid_count = int(values.notna().sum())
    if valid_count <= 0:
        return pd.Series([pd.NA] * len(values), index=values.index)
    groups = ((ranks - 1) / max(valid_count, 1) * group_count).apply(lambda v: int(v) + 1 if pd.notna(v) else pd.NA)
    return groups.clip(upper=group_count)


def _group_returns(panel: pd.DataFrame, periods: list[int], group_count: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    work = panel.copy()
    work["group"] = work.groupby("time", group_keys=False)["value"].apply(lambda s: _assign_groups(s, group_count))
    for period in periods:
        ret_col = f"ret_{period}"
        groups: list[dict[str, Any]] = []
        for group_id in range(1, group_count + 1):
            sub = work[work["group"].eq(group_id)].dropna(subset=[ret_col])
            daily = sub.groupby("time")[ret_col].mean().sort_index()
            cum = (1.0 + daily.fillna(0.0)).cumprod() - 1.0
            groups.append(
                {
                    "group": group_id,
                    "count": int(len(sub)),
                    "mean_return": _round_float(sub[ret_col].mean()),
                    "series": [
                        {"date": pd.Timestamp(idx).strftime("%Y-%m-%d"), "cum_return": _round_float(value)}
                        for idx, value in cum.items()
                    ],
                }
            )
        result[str(period)] = {"groups": groups}
    return result


def _event_study(panel: pd.DataFrame, periods: list[int], rolling_window: int) -> dict[str, Any]:
    factor_values = pd.to_numeric(panel["value"], errors="coerce")
    non_null = factor_values.dropna()
    is_binary = bool(len(non_null) > 0 and set(non_null.unique()).issubset({0.0, 1.0}))
    work = panel.copy()
    if is_binary:
        events = work[pd.to_numeric(work["value"], errors="coerce") > 0].copy()
        mode = "binary_positive"
    else:
        thresholds = work.groupby("time")["value"].transform(lambda s: pd.to_numeric(s, errors="coerce").quantile(0.8))
        events = work[pd.to_numeric(work["value"], errors="coerce") >= thresholds].copy()
        mode = "continuous_top_20pct"
    summary: list[dict[str, Any]] = []
    rolling: dict[str, list[dict[str, Any]]] = {}
    for period in periods:
        ret_col = f"ret_{period}"
        sub = events.dropna(subset=[ret_col])
        returns = pd.to_numeric(sub[ret_col], errors="coerce").dropna()
        summary.append(
            {
                "period": period,
                "event_count": int(len(returns)),
                "mean_return": _round_float(returns.mean()),
                "median_return": _round_float(returns.median()),
                "win_rate": _round_float((returns > 0).mean() if len(returns) else None),
            }
        )
        daily = sub.groupby("time")[ret_col].mean().sort_index()
        roll = daily.rolling(rolling_window, min_periods=1).mean()
        rolling[str(period)] = [
            {"date": pd.Timestamp(idx).strftime("%Y-%m-%d"), "rolling_mean_return": _round_float(value)}
            for idx, value in roll.items()
        ]
    return {"mode": mode, "summary": summary, "rolling": rolling}


def calculate_factor_validation(
    factor_df: pd.DataFrame,
    price_df: pd.DataFrame,
    universe_codes: list[str],
    factor_name: str,
    start_date: str,
    end_date: str,
    periods: list[int],
    rolling_window: int,
    group_count: int,
) -> dict[str, Any]:
    if group_count not in ALLOWED_GROUP_COUNTS:
        raise FactorValidationInputError("分组数仅支持 5、8、10、20")
    factor = factor_df.copy()
    price = price_df.copy()
    factor["htsc_code"] = factor["htsc_code"].astype(str).str.strip().str.upper()
    factor["time"] = pd.to_datetime(factor["time"], errors="coerce").dt.normalize()
    factor["value"] = pd.to_numeric(factor["value"], errors="coerce")
    price["htsc_code"] = price["htsc_code"].astype(str).str.strip().str.upper()
    price["time"] = pd.to_datetime(price["time"], errors="coerce").dt.normalize()
    price["close"] = pd.to_numeric(price["close"], errors="coerce")
    returns = _build_forward_returns(price, periods)
    panel = factor.merge(returns, on=["time", "htsc_code"], how="left")
    quality = _quality_metrics(factor, len(set(universe_codes)))
    ic_summary, ic_series, rolling_ic = _ic_metrics(panel, periods, rolling_window)
    group_returns = _group_returns(panel, periods, group_count)
    event_study = _event_study(panel, periods, rolling_window)
    return {
        "quality": quality,
        "ic_summary": ic_summary,
        "ic_series": ic_series,
        "rolling_ic": rolling_ic,
        "group_returns": group_returns,
        "event_study": event_study,
        "meta": {
            "factor": factor_name,
            "stock_pool": "ALL_A",
            "start_date": start_date,
            "end_date": end_date,
            "periods": periods,
            "rolling_window": rolling_window,
            "group_count": group_count,
            "price_adjust_mode": PRICE_ADJUST_MODE,
            "factor_rows": int(len(factor)),
            "price_rows": int(len(price)),
            "server_time": int(time.time()),
        },
    }


def run_factor_validation(payload: dict[str, Any]) -> dict[str, Any]:
    factor_name = str(payload.get("factor") or "").strip()
    if not factor_name:
        raise FactorValidationInputError("factor 不能为空")
    end = _parse_date(payload.get("end_date") or datetime.now().strftime("%Y-%m-%d"), "end_date")
    default_start = (end - pd.DateOffset(years=3)).strftime("%Y-%m-%d")
    start = _parse_date(payload.get("start_date") or default_start, "start_date")
    if start > end:
        raise FactorValidationInputError("start_date 不能大于 end_date")
    periods = _parse_periods(payload.get("periods"))
    rolling_window = _parse_positive_int(payload.get("rolling_window"), 60, "rolling_window")
    group_count = _parse_positive_int(payload.get("group_count"), 5, "group_count")
    if group_count not in ALLOWED_GROUP_COUNTS:
        raise FactorValidationInputError("group_count 仅支持 5、8、10、20")
    codes = _load_universe_codes()
    factor_df = _read_factor_frame(factor_name, start, end, codes)
    price_df = _read_price_frame(start, end, codes, max(periods))
    if factor_df.empty:
        raise FactorValidationNotFoundError("所选股票池和时间段内没有因子数据")
    if price_df.empty:
        raise FactorValidationNotFoundError("所选股票池和时间段内没有行情数据")
    return calculate_factor_validation(
        factor_df=factor_df,
        price_df=price_df,
        universe_codes=codes,
        factor_name=factor_name,
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        periods=periods,
        rolling_window=rolling_window,
        group_count=group_count,
    )


def _record_path(record_id: str, records_dir: Path = RECORDS_DIR) -> Path:
    safe_id = re.sub(r"[^0-9A-Za-z_-]", "", str(record_id or "").strip())
    if not safe_id:
        raise FactorValidationInputError("记录 id 无效")
    return records_dir / f"{safe_id}.json"


def save_factor_validation_record(payload: dict[str, Any], records_dir: Path = RECORDS_DIR) -> dict[str, Any]:
    records_dir.mkdir(parents=True, exist_ok=True)
    record_id = str(payload.get("id") or uuid.uuid4().hex[:16])
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    record = dict(payload)
    record["id"] = record_id
    record["created_at"] = str(payload.get("created_at") or now)
    path = _record_path(record_id, records_dir)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def list_factor_validation_records(records_dir: Path = RECORDS_DIR) -> dict[str, Any]:
    records_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for path in sorted(records_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            items.append(payload)
        if len(items) >= MAX_RECORD_ITEMS:
            break
    return {"items": items, "meta": {"count": len(items), "records_dir": str(records_dir), "server_time": int(time.time())}}


def delete_factor_validation_record(record_id: str, records_dir: Path = RECORDS_DIR) -> dict[str, Any]:
    path = _record_path(record_id, records_dir)
    if not path.exists():
        raise FactorValidationNotFoundError("记录不存在")
    path.unlink()
    return {"deleted": True, "id": record_id}
