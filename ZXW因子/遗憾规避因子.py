from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


BUNDLE_ID = "mins_regret_factor"
FACTOR_PREFIX = "mins_regret_factor"
FACTOR_CN_PREFIX = "分钟级别遗憾规避因子"

TAIL_START = "14:30"
TAIL_END = "14:57"

FACTOR_KEYS: tuple[str, ...] = (
    "HCVOLE1",
    "HCVOLE2",
    "LCVOLE1",
    "LCVOLE2",
    "HCPE",
    "LCPE",
)


def _factor_name(key: str) -> str:
    return f"{FACTOR_PREFIX}_{key}"


def _factor_cn_name(key: str) -> str:
    return f"{FACTOR_CN_PREFIX}_{key}"


def _empty_result() -> dict[str, Any]:
    factor_dfs = {name: pd.DataFrame(dtype=float) for name in map(_factor_name, FACTOR_KEYS)}
    factor_name_map = {_factor_cn_name(key): _factor_name(key) for key in FACTOR_KEYS}
    return {"factor_dfs": factor_dfs, "factor_name_map": factor_name_map}


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = denominator.replace(0.0, np.nan)
    return numerator / denominator


def _to_wide(frame: pd.DataFrame, value_column: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(dtype=float)
    return (
        frame.pivot(index="date", columns="htsc_code", values=value_column)
        .sort_index()
        .sort_index(axis=1)
        .astype(float)
    )


def build_mins_regret_factor_bundle(
    minute_data: pd.DataFrame,
    *,
    tail_start: str = TAIL_START,
    tail_end: str = TAIL_END,
) -> dict[str, Any]:
    """
    分钟级别尾盘遗憾规避因子。

    口径：
    - 一分钟视作一笔成交。
    - close > open 视作买方占优，close < open 视作卖方占优，close == open 剔除方向分子。
    - 成交价使用分钟 close，日收盘价使用当日最后一个有效分钟 close。
    - 尾盘窗口默认 [14:30, 14:57)，LCPE 保留原始负数方向。
    """
    required_columns = {"htsc_code", "time", "open", "close", "volume"}
    missing = required_columns.difference(minute_data.columns)
    if missing:
        raise KeyError(f"minute_data 缺少必要字段: {sorted(missing)}")
    if minute_data.empty:
        return _empty_result()

    df = minute_data.loc[:, ["htsc_code", "time", "open", "close", "volume"]].copy()
    df["htsc_code"] = df["htsc_code"].astype(str)
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    for column in ["open", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["htsc_code", "time", "open", "close", "volume"])
    df = df[df["volume"] > 0].copy()
    if df.empty:
        return _empty_result()

    df["date"] = df["time"].dt.normalize()
    df = df.sort_values(["htsc_code", "date", "time"])
    df["day_close"] = df.groupby(["htsc_code", "date"], sort=False)["close"].transform("last")
    df = df[df["day_close"].notna() & (df["day_close"] != 0)].copy()
    if df.empty:
        return _empty_result()

    minute_of_day = df["time"].dt.strftime("%H:%M")
    df["is_tail"] = (minute_of_day >= str(tail_start)) & (minute_of_day < str(tail_end))
    df["buy_like"] = df["close"] > df["open"]
    df["sell_like"] = df["close"] < df["open"]
    df["price_deviation"] = df["close"] / df["day_close"] - 1.0

    buy_losing = df["is_tail"] & df["buy_like"] & (df["close"] > df["day_close"])
    sell_rebound = df["is_tail"] & df["sell_like"] & (df["close"] < df["day_close"])
    df["hcv_volume"] = np.where(buy_losing, df["volume"], 0.0)
    df["lcv_volume"] = np.where(sell_rebound, df["volume"], 0.0)
    df["hcp_weighted_dev"] = np.where(buy_losing, df["volume"] * df["price_deviation"], 0.0)
    df["lcp_weighted_dev"] = np.where(sell_rebound, df["volume"] * df["price_deviation"], 0.0)
    df["tail_volume"] = np.where(df["is_tail"], df["volume"], 0.0)

    grouped = df.groupby(["date", "htsc_code"], sort=True).agg(
        total_volume=("volume", "sum"),
        tail_volume=("tail_volume", "sum"),
        hcv_volume=("hcv_volume", "sum"),
        lcv_volume=("lcv_volume", "sum"),
        hcp_weighted_dev=("hcp_weighted_dev", "sum"),
        lcp_weighted_dev=("lcp_weighted_dev", "sum"),
    )

    grouped[_factor_name("HCVOLE1")] = _safe_divide(grouped["hcv_volume"], grouped["total_volume"])
    grouped[_factor_name("HCVOLE2")] = _safe_divide(grouped["hcv_volume"], grouped["tail_volume"])
    grouped[_factor_name("LCVOLE1")] = _safe_divide(grouped["lcv_volume"], grouped["total_volume"])
    grouped[_factor_name("LCVOLE2")] = _safe_divide(grouped["lcv_volume"], grouped["tail_volume"])
    grouped[_factor_name("HCPE")] = _safe_divide(grouped["hcp_weighted_dev"], grouped["hcv_volume"])
    grouped[_factor_name("LCPE")] = _safe_divide(grouped["lcp_weighted_dev"], grouped["lcv_volume"])

    factor_frame = grouped.reset_index()
    factor_dfs = {
        _factor_name(key): _to_wide(factor_frame, _factor_name(key))
        for key in FACTOR_KEYS
    }
    factor_name_map = {_factor_cn_name(key): _factor_name(key) for key in FACTOR_KEYS}

    return {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }


_DEFAULT_LOOKBACK_DAYS = 1
FACTOR_LOOKBACK_DAYS: dict[str, int] = {_factor_name(key): 1 for key in FACTOR_KEYS}


def get_factor_lookback_config() -> dict[str, Any]:
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": _DEFAULT_LOOKBACK_DAYS,
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
