from __future__ import annotations

import argparse
import gc
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import backtrader as bt
import duckdb
import numpy as np
import pandas as pd
import polars as pl

INITIAL_CASH = 10_000_000.0
COMMISSION = 0.0003

PORTFOLIO_CURVE_CODE = "000000.YKRS"
CASH_CURVE_CODE = "0000000.YKRS"
BUY_HOLD_CURVE_CODE = "000001.YKRS"
PORTFOLIO_SECURITY_ID = "000000"
CASH_SECURITY_ID = "0000000"
BUY_HOLD_SECURITY_ID = "000001"

STOCK_BASE_PATH = Path(r"D:\database\stock_portfolio_data_daily")
SAVE_DIR = Path(r"D:\database\bs_dialy")
TOTAL_RECORD_DIR = Path(r"D:\database\total_record")
PRICE_BASE_PATH = r"D:\database\stock_basic_data_daily"
SIGNAL_BASE_PATH = Path(r"D:\database\signal_daily")
# 与 `ZXW因子/ZXW策略技术因子生成.ipynb` 对齐：`none` | `forward` | `backward`
ADJ_MODE: str = "backward"
ADJ_BASE_PATH = r"D:\database\stock_adj_daily"
_OHLC_NAMES = ("open", "high", "low", "close")
_ZXW_ADJ_VIEW_BT = "_zxw_stock_adj_segments_bt"

FACTOR_COLUMN_MAP = {
    "总买入信号": "total_buy_signal",
    "总买入信号改": "total_buy_signal_adjusted",
    "总卖出信号+逃顶总分+J值超买因子": "sell_combo_signal",
    "RSI死叉+RSI超买": "rsi_sell_combo",
    "抄底总分": "bottom_fishing_score",
    "MAC总": "mac_total",
    "总卖出信号": "total_sell_signal",
}

BACKTEST_YEARS = [2019, 2020, 2021]
_INVALID_FACTOR_DIR_CHARS = re.compile(r'[\\/:*?"<>|]')


class FactorPandasData(bt.feeds.PandasData):
    """OHLCV feed with merged factor/signal columns."""

    lines = (
        "total_buy_signal",
        "total_buy_signal_adjusted",
        "strong_buy_signal",
        "sell_combo_signal",
        "rsi_sell_combo",
        "bottom_fishing_score",
        "mac_total",
        "total_sell_signal",
        "strong_sell_signal",
        "block_halving_future_buy",
    )
    params = (
        ("total_buy_signal", -1),
        ("total_buy_signal_adjusted", -1),
        ("strong_buy_signal", -1),
        ("sell_combo_signal", -1),
        ("rsi_sell_combo", -1),
        ("bottom_fishing_score", -1),
        ("mac_total", -1),
        ("total_sell_signal", -1),
        ("strong_sell_signal", -1),
        ("block_halving_future_buy", -1),
    )


def create_duckdb_view(base_path: str, view_name: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(
        f"""
        CREATE OR REPLACE VIEW {view_name} AS
        SELECT *
        FROM read_parquet('{base_path}/year=*/month=*/merged.parquet', hive_partitioning=1)
        """
    )
    return con


def create_cerebro(target_codes: list[str], df_multi: pd.DataFrame, verbose: bool = True) -> bt.Cerebro:
    cerebro = bt.Cerebro()
    cerebro.broker.set_coc(True)
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)

    for code in target_codes:
        code_df = df_multi[df_multi["htsc_code"] == code].copy()
        code_df = code_df.sort_values("time").reset_index(drop=True)
        if code_df.empty:
            if verbose:
                print(f"⚠️ 股票 {code} 无数据，跳过")
            continue

        def _col(name: str) -> str | int:
            return name if name in code_df.columns else -1

        data = FactorPandasData(
            dataname=code_df,
            datetime="time",
            open="open",
            high="high",
            low="low",
            close="close",
            volume="volume",
            openinterest=-1,
            total_buy_signal=_col("total_buy_signal"),
            total_buy_signal_adjusted=_col("total_buy_signal_adjusted"),
            strong_buy_signal=_col("strong_buy_signal"),
            sell_combo_signal=_col("sell_combo_signal"),
            rsi_sell_combo=_col("rsi_sell_combo"),
            bottom_fishing_score=_col("bottom_fishing_score"),
            mac_total=_col("mac_total"),
            total_sell_signal=_col("total_sell_signal"),
            strong_sell_signal=_col("strong_sell_signal"),
            block_halving_future_buy=_col("block_halving_future_buy"),
            timeframe=bt.TimeFrame.Days,
        )
        data._name = code
        cerebro.adddata(data)
        if verbose:
            print(f"✓ 已添加数据: {code} ({len(code_df)} 条)")
    return cerebro


def _sanitize_factor_dir_name(factor_name: str) -> str:
    safe_name = _INVALID_FACTOR_DIR_CHARS.sub("_", str(factor_name).strip())
    safe_name = safe_name.rstrip(" .")
    return safe_name or "未命名因子"


def _iter_year_month(start_dt: pd.Timestamp, end_dt: pd.Timestamp) -> list[tuple[int, int]]:
    cursor = pd.Timestamp(year=start_dt.year, month=start_dt.month, day=1)
    end_cursor = pd.Timestamp(year=end_dt.year, month=end_dt.month, day=1)
    result: list[tuple[int, int]] = []
    while cursor <= end_cursor:
        result.append((int(cursor.year), int(cursor.month)))
        cursor = cursor + pd.offsets.MonthBegin(1)
    return result


def _existing_factor_partition_paths(
    base_path: Path,
    factor_name: str,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
) -> list[str]:
    factor_dir = _sanitize_factor_dir_name(factor_name)
    paths: list[str] = []
    for year, month in _iter_year_month(start_dt, end_dt):
        month_dir = base_path / f"factor={factor_dir}" / f"year={year}" / f"month={month:02d}"
        merged_path = month_dir / "merged.parquet"
        if merged_path.exists():
            paths.append(merged_path.as_posix())
        if month_dir.exists():
            paths.extend(p.as_posix() for p in sorted(month_dir.glob("part_*.parquet")))
    return paths


def _sql_quote_string(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _sql_escape_htsc(code: str) -> str:
    return str(code).strip().upper().replace("'", "''")


def _in_clause_for_batch(batch: list[str]) -> str:
    inner = ", ".join([f"'{_sql_escape_htsc(c)}'" for c in batch])
    return f"AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN ({inner})"


def _zxw_ohlc_cols(df: pd.DataFrame) -> list[str]:
    lower = {c.lower(): c for c in df.columns}
    return [lower[k] for k in _OHLC_NAMES if k in lower]


def _zxw_build_adj_factor_long(seg_all: pd.DataFrame, codes: np.ndarray) -> pd.DataFrame:
    seg_all = seg_all[seg_all["htsc_code"].isin(codes)].copy()
    rows: list[dict[str, Any]] = []
    for _code, g in seg_all.groupby("htsc_code", sort=False):
        code = str(_code).strip().upper()
        seg = g.sort_values("begin_date").reset_index(drop=True)
        if seg.empty:
            continue
        xdy = np.ascontiguousarray(seg["xdy"].astype(np.float64).to_numpy())
        k = len(xdy)
        suffix = np.ones(k, dtype=np.float64)
        for ii in range(k - 2, -1, -1):
            suffix[ii] = suffix[ii + 1] * xdy[ii + 1]
        cum = np.cumprod(xdy)
        for i in range(k):
            b, e = seg.at[i, "begin_date"], seg.at[i, "end_date"]
            if pd.isna(b) or pd.isna(e):
                continue
            sx = float(suffix[i])
            hv = float(cum[i])
            for d in pd.date_range(b, e, freq="D"):
                if d.dayofweek >= 5:
                    continue
                t = pd.Timestamp(d).normalize()
                rows.append(
                    {
                        "htsc_code": code,
                        "time": t,
                        "suffix_xdy_cum": sx,
                        "backward_cum_factor": hv,
                    }
                )
    if not rows:
        return pd.DataFrame(columns=["htsc_code", "time", "suffix_xdy_cum", "backward_cum_factor"])
    return pd.DataFrame(rows)


def _zxw_adj_parquet_path() -> str:
    adj_seg = Path(ADJ_BASE_PATH) / "adj_factor_segments.parquet"
    adj_glob = str(Path(ADJ_BASE_PATH) / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")
    return str(adj_seg).replace("\\", "/") if adj_seg.is_file() else adj_glob


def _zxw_query_end_inclusive(backtest_end_exclusive: str) -> str:
    return (pd.Timestamp(backtest_end_exclusive).floor("D") - pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def apply_ohlc_adj_to_price_df(
    price_df: pd.DataFrame,
    *,
    target_codes: list[str],
    query_start_date: str,
    query_end_exclusive: str,
    adj_mode: str | None = None,
) -> pd.DataFrame:
    """与因子 notebook 一致：工作日展开复权因子、left merge、缺因子=1；仅改 OHLC，volume 不改。"""
    mode = str(adj_mode if adj_mode is not None else ADJ_MODE).strip().lower()
    if mode not in ("none", "forward", "backward"):
        raise ValueError("ADJ_MODE 须为 none / forward / backward")
    if mode == "none" or price_df.empty:
        out = price_df.copy()
        out["htsc_code"] = out["htsc_code"].astype(str).str.strip().str.upper()
        out["time"] = pd.to_datetime(out["time"], errors="coerce").dt.normalize()
        return out

    query_end_inclusive = _zxw_query_end_inclusive(query_end_exclusive)
    ordered_codes = sorted({str(c).strip().upper() for c in target_codes if str(c).strip()})
    if not ordered_codes:
        return price_df

    adj_parquet = _zxw_adj_parquet_path()
    seg_extra = _in_clause_for_batch(ordered_codes)

    adj_con = duckdb.connect(database=":memory:")
    try:
        adj_con.execute(
            f"""
            CREATE OR REPLACE VIEW {_ZXW_ADJ_VIEW_BT} AS
            SELECT * FROM read_parquet('{adj_parquet}', hive_partitioning=1, union_by_name=True)
            """
        )
        adj_sql = f"""
            SELECT *
            FROM {_ZXW_ADJ_VIEW_BT}
            WHERE CAST(end_date AS DATE) >= DATE '{query_start_date}'
              AND CAST(begin_date AS DATE) <= DATE '{query_end_inclusive}'
              AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) NOT LIKE '%.YKRS'
              {seg_extra}
        """
        stock_adj_data = adj_con.execute(adj_sql).df()
    finally:
        adj_con.close()

    if len(stock_adj_data) and "htsc_code" in stock_adj_data.columns:
        stock_adj_data["htsc_code"] = stock_adj_data["htsc_code"].astype(str).str.strip().str.upper()
        stock_adj_data["begin_date"] = pd.to_datetime(stock_adj_data["begin_date"], errors="coerce").dt.normalize()
        stock_adj_data["end_date"] = pd.to_datetime(stock_adj_data["end_date"], errors="coerce").dt.normalize()
        stock_adj_data = stock_adj_data.dropna(subset=["htsc_code", "begin_date", "end_date"]).reset_index(drop=True)
    else:
        stock_adj_data = pd.DataFrame(columns=["htsc_code", "begin_date", "end_date", "xdy"])

    df_multi = price_df.copy()
    df_multi["htsc_code"] = df_multi["htsc_code"].astype(str).str.strip().str.upper()
    df_multi["time"] = pd.to_datetime(df_multi["time"], errors="coerce").dt.normalize()

    codes = df_multi["htsc_code"].unique()
    fac = _zxw_build_adj_factor_long(stock_adj_data, codes)
    del stock_adj_data
    gc.collect()

    merged = df_multi.merge(fac, on=["htsc_code", "time"], how="left")
    del fac
    gc.collect()

    for col in ("suffix_xdy_cum", "backward_cum_factor"):
        if col not in merged.columns:
            merged[col] = 1.0
        else:
            merged[col] = merged[col].fillna(1.0).astype(np.float64)

    ohlc_cols = _zxw_ohlc_cols(merged)
    if not ohlc_cols:
        raise KeyError("未找到 open/high/low/close 列，无法复权")

    if mode == "forward":
        su = np.ascontiguousarray(merged["suffix_xdy_cum"].to_numpy(dtype=np.float64))
        for c in ohlc_cols:
            v = np.ascontiguousarray(merged[c].to_numpy(dtype=np.float64))
            merged[c] = (v / su).astype(np.float64)
    else:
        bf = np.ascontiguousarray(merged["backward_cum_factor"].to_numpy(dtype=np.float64))
        for c in ohlc_cols:
            v = np.ascontiguousarray(merged[c].to_numpy(dtype=np.float64))
            merged[c] = (v * bf).astype(np.float64)

    drop_cols = [x for x in ("suffix_xdy_cum", "backward_cum_factor") if x in merged.columns]
    out = merged.drop(columns=drop_cols, errors="ignore").reset_index(drop=True)
    del merged
    gc.collect()

    out["time"] = pd.to_datetime(out["time"]).dt.floor("D")
    return out


def load_signal_factor_wide(
    base_path: Path,
    factor_names: list[str],
    codes_sql_in_list: str,
    backtest_start: str,
    backtest_end: str,
) -> pd.DataFrame:
    start_dt = pd.Timestamp(backtest_start).floor("D")
    end_dt = pd.Timestamp(backtest_end).floor("D")
    con = duckdb.connect(database=":memory:")
    try:
        frames: list[pd.DataFrame] = []
        for factor_name in factor_names:
            paths = _existing_factor_partition_paths(base_path, factor_name, start_dt, end_dt)
            if not paths:
                continue

            path_list_sql = ", ".join([_sql_quote_string(p) for p in paths])
            factor_sql = f"""
                SELECT
                    CAST(time AS TIMESTAMP) AS time,
                    CAST(htsc_code AS VARCHAR) AS htsc_code,
                    TRY_CAST(value AS DOUBLE) AS value
                FROM read_parquet([{path_list_sql}], union_by_name=true)
                WHERE CAST(htsc_code AS VARCHAR) IN ({codes_sql_in_list})
                  AND CAST(time AS DATE) >= DATE '{backtest_start}'
                  AND CAST(time AS DATE) < DATE '{backtest_end}'
                ORDER BY htsc_code, time
            """
            factor_df = con.execute(factor_sql).df()
            if factor_df.empty:
                continue
            factor_df["time"] = pd.to_datetime(factor_df["time"]).dt.normalize()
            factor_df["htsc_code"] = factor_df["htsc_code"].astype(str)
            factor_df = factor_df.drop_duplicates(["time", "htsc_code"], keep="last")
            factor_df = factor_df.rename(columns={"value": factor_name})
            frames.append(factor_df[["time", "htsc_code", factor_name]])

        if not frames:
            return pd.DataFrame(columns=["time", "htsc_code", *factor_names])

        merged = frames[0]
        for frame in frames[1:]:
            merged = merged.merge(frame, on=["time", "htsc_code"], how="outer")
        for factor_name in factor_names:
            if factor_name not in merged.columns:
                merged[factor_name] = np.nan
        return merged.sort_values(["htsc_code", "time"]).reset_index(drop=True)
    finally:
        con.close()


def compute_future_halving_no_buy_mask(extended_price: pd.DataFrame) -> pd.DataFrame:
    """
    规则 7（前视）：若 次年第 5 个交易日收盘 / 当年第 5 个交易日收盘 <= 0.5，
    则在「当年第 5 个交易日之后 ~ 次年第 5 个交易日（含）」窗口内禁止买入该标的。
    无法取得次年第 5 日时该年不生成拦截。
    """
    base_cols = ["time", "htsc_code", "close"]
    if not set(base_cols).issubset(extended_price.columns):
        return pd.DataFrame(columns=["time", "htsc_code", "block_halving_future_buy"])

    df = extended_price[base_cols].copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce").dt.normalize()
    df["htsc_code"] = df["htsc_code"].astype(str).str.strip().str.upper()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["block_halving_future_buy"] = 0.0

    for _code, sub in df.groupby("htsc_code", sort=False):
        sub = sub.sort_values("time")
        ix_list = sub.index.tolist()
        if len(ix_list) < 5:
            continue
        years = sub["time"].dt.year.to_numpy()
        uniq_y = sorted(int(y) for y in np.unique(years))
        for Y in uniq_y:
            idx_y = np.flatnonzero(years == Y)
            if len(idx_y) < 5:
                continue
            i5 = int(idx_y[4])
            c_y5 = float(sub.iloc[i5]["close"])
            if not math.isfinite(c_y5) or c_y5 <= 0:
                continue
            idx_ny = np.flatnonzero(years == Y + 1)
            if len(idx_ny) < 5:
                continue
            i5n = int(idx_ny[4])
            c_n5 = float(sub.iloc[i5n]["close"])
            if not math.isfinite(c_n5):
                continue
            if (c_n5 / c_y5) > 0.5:
                continue
            start_k = i5 + 1
            end_k = i5n
            if start_k > end_k:
                continue
            for k in range(start_k, end_k + 1):
                orig_ix = ix_list[k]
                df.at[orig_ix, "block_halving_future_buy"] = 1.0

    return df[["time", "htsc_code", "block_halving_future_buy"]].copy()


def build_bt_dataframe(
    *,
    price_df: pd.DataFrame,
    target_codes: list[str],
    backtest_start: str,
    backtest_end_exclusive: str,
    signal_base_path: Path | None = None,
    clip_date_end_exclusive: str | None = None,
    enable_future_halving_mask: bool = True,
) -> pd.DataFrame:
    """合并行情、因子、可选未来腰斩禁买标记。可选裁剪到回测区间末端（行情仍用扩展段算禁买）。"""
    base_path = signal_base_path or SIGNAL_BASE_PATH
    codes_str = ", ".join([f"'{_sql_escape_htsc(c)}'" for c in target_codes])
    signal_df = load_signal_factor_wide(
        base_path=base_path,
        factor_names=list(FACTOR_COLUMN_MAP.keys()),
        codes_sql_in_list=codes_str,
        backtest_start=backtest_start,
        backtest_end=backtest_end_exclusive,
    )
    signal_factor_df = signal_df.rename(columns=FACTOR_COLUMN_MAP)
    if not signal_factor_df.empty and "htsc_code" in signal_factor_df.columns:
        signal_factor_df["htsc_code"] = signal_factor_df["htsc_code"].astype(str).str.strip().str.upper()
    bt_df = price_df.merge(signal_factor_df, on=["time", "htsc_code"], how="left")
    for factor_col in FACTOR_COLUMN_MAP.values():
        if factor_col not in bt_df.columns:
            bt_df[factor_col] = 0.0
        else:
            bt_df[factor_col] = pd.to_numeric(bt_df[factor_col], errors="coerce").fillna(0.0)

    if enable_future_halving_mask:
        ext_mask = compute_future_halving_no_buy_mask(price_df)
        if not ext_mask.empty:
            bt_df = bt_df.merge(ext_mask, on=["time", "htsc_code"], how="left")
    if "block_halving_future_buy" not in bt_df.columns:
        bt_df["block_halving_future_buy"] = 0.0
    else:
        bt_df["block_halving_future_buy"] = pd.to_numeric(
            bt_df["block_halving_future_buy"], errors="coerce"
        ).fillna(0.0)
    if clip_date_end_exclusive:
        end_ts = pd.Timestamp(clip_date_end_exclusive).floor("D")
        bt_df = bt_df[bt_df["time"] < end_ts].copy()
    return bt_df


class ZxwRuleBacktestStrategy(bt.Strategy):
    """
    ZXW 组合规则：首日等权满仓；止损/次卖清仓；分档止盈与回撤加仓；总仓位<80%（默认用**上一交易日收盘**
    后的仓位占比，见 notify_cashvalue）时次买；强买（总买入）5%；未来腰斩禁买 block_halving_future_buy。

    profit_tier_mode：
      - "legacy"（默认）：盈利>100% 卖约 75%；>50% 卖约 50%；回撤绑定两档。
      - "profit30"：盈利>100% 且 either_combo → 清仓；>50% 卖约 75%；>30% 卖约 50%；回撤分别绑定 50% 档与 30% 档。
    """

    params = dict(max_weight=0.05, drawdown_add_weight=0.025, profit_tier_mode="legacy")

    def __init__(self) -> None:
        self.order_meta: dict[Any, dict[str, Any]] = {}
        self.order_log: list[dict[str, Any]] = []
        self.trade_log: list[dict[str, Any]] = []
        self.position_log: list[dict[str, Any]] = []
        self._position_log_seen: set[tuple[str, str]] = set()
        self.daily_value_log: list[dict[str, Any]] = []
        self._initialized = False
        self._tier1_half_done: set[str] = set()
        self._tier2_half_done: set[str] = set()
        self._post_tier1_peak: dict[str, float] = {}
        self._post_tier2_peak: dict[str, float] = {}
        self._tier1_dd_add_done: set[str] = set()
        self._tier2_dd_add_done: set[str] = set()
        # profit30 分档专用（与 legacy 状态互斥使用）
        self._tier30_half_done: set[str] = set()
        self._tier50_75_done: set[str] = set()
        self._post_tier30_peak: dict[str, float] = {}
        self._post_tier50_peak: dict[str, float] = {}
        self._tier30_dd_add_done: set[str] = set()
        self._tier50_dd_add_done: set[str] = set()
        self._eod_invested_ratio: float | None = None

    def _clear_code_state(self, code: str) -> None:
        self._tier1_half_done.discard(code)
        self._tier2_half_done.discard(code)
        self._post_tier1_peak.pop(code, None)
        self._post_tier2_peak.pop(code, None)
        self._tier1_dd_add_done.discard(code)
        self._tier2_dd_add_done.discard(code)
        self._tier30_half_done.discard(code)
        self._tier50_75_done.discard(code)
        self._post_tier30_peak.pop(code, None)
        self._post_tier50_peak.pop(code, None)
        self._tier30_dd_add_done.discard(code)
        self._tier50_dd_add_done.discard(code)

    def _dt_str(self, data: Any) -> str:
        return bt.num2date(data.datetime[0]).strftime("%Y-%m-%d")

    def _line_value(self, data: Any, line_name: str) -> float:
        value = float(getattr(data, line_name)[0])
        return value if np.isfinite(value) else 0.0

    def _record_position_snapshot(self, data: Any) -> None:
        dt_str = self._dt_str(data)
        key = (dt_str, data._name)
        if key in self._position_log_seen:
            return
        self._position_log_seen.add(key)
        pos = self.getposition(data)
        close_px = float(data.close[0])
        market_value = pos.size * close_px
        cost_basis = pos.size * float(pos.price)
        self.position_log.append(
            {
                "date": dt_str,
                "code": data._name,
                "position_size": pos.size,
                "position_price": float(pos.price),
                "close": close_px,
                "market_value": market_value,
                "unrealized_pnl": market_value - cost_basis,
            }
        )

    def _submit_order_target_value(self, data: Any, target_value: float, signal: str) -> None:
        if target_value < 0:
            return
        order = self.order_target_value(data=data, target=target_value)
        if order is not None:
            self.order_meta[order.ref] = {
                "signal": signal,
                "target_value": float(target_value),
                "date": self._dt_str(data),
            }

    def _submit_buy_value(self, data: Any, buy_value: float, signal: str) -> None:
        close_px = float(data.close[0])
        if not np.isfinite(close_px) or close_px <= 0 or buy_value <= 0:
            return
        shares = int(buy_value / (close_px * (1.0 + COMMISSION)))
        if shares <= 0:
            return
        order = self.buy(data=data, size=shares)
        if order is not None:
            self.order_meta[order.ref] = {
                "signal": signal,
                "target_value": float(shares * close_px),
                "date": self._dt_str(data),
            }

    def _initialize_equal_weight_positions(self) -> None:
        valid_datas = [d for d in self.datas if len(d) > 0 and np.isfinite(float(d.close[0])) and float(d.close[0]) > 0]
        if not valid_datas:
            return
        target_weight = 1.0 / len(valid_datas)
        investable_value = self.broker.getcash() / (1.0 + COMMISSION)
        for d in valid_datas:
            target_value = investable_value * target_weight
            self._submit_order_target_value(d, target_value, "INITIAL_EQUAL_WEIGHT_FULL_POSITION")
        self._initialized = True

    def next(self) -> None:
        total_value = self.broker.getvalue()
        if not self._initialized:
            self._initialize_equal_weight_positions()
            return
        if total_value <= 0:
            return

        sorted_ds = sorted(self.datas, key=lambda x: str(x._name))

        for d in sorted_ds:
            if self.getposition(d).size <= 0:
                self._clear_code_state(d._name)

        v0 = float(self.broker.getvalue())
        inv0 = 0.0
        for d in sorted_ds:
            pos = self.getposition(d)
            cx = float(d.close[0])
            if pos.size > 0 and np.isfinite(cx):
                inv0 += pos.size * cx
        inv_ratio_start = inv0 / v0 if v0 > 0 else 0.0

        for d in sorted_ds:
            self._record_position_snapshot(d)
            pos = self.getposition(d)
            close_px = float(d.close[0])
            code = str(d._name)
            if not np.isfinite(close_px) or close_px <= 0:
                continue

            tss = self._line_value(d, "total_sell_signal")
            sc = self._line_value(d, "sell_combo_signal")
            rc = self._line_value(d, "rsi_sell_combo")

            either_combo = sc >= 1.0 or rc >= 1.0
            weak_sell = tss >= 1.0

            if pos.size <= 0 or float(pos.price) <= 0:
                continue

            cost = float(pos.price)
            profit_ratio = close_px / cost - 1.0
            weight = (pos.size * close_px) / v0 if v0 > 0 else 0.0

            if profit_ratio <= -0.15:
                order = self.close(data=d)
                if order is not None:
                    self.order_meta[order.ref] = {
                        "signal": "STOP_LOSS_15PCT",
                        "target_value": 0.0,
                        "date": self._dt_str(d),
                    }
                continue

            if weak_sell and weight < 0.01:
                order = self.close(data=d)
                if order is not None:
                    self.order_meta[order.ref] = {
                        "signal": "WEAK_SELL_CLEAR_LT_1PCT_WEIGHT",
                        "target_value": 0.0,
                        "date": self._dt_str(d),
                    }
                continue

            tier_mode = str(getattr(self.p, "profit_tier_mode", "legacy") or "legacy")

            if tier_mode == "profit30":
                if profit_ratio > 1.0 and either_combo:
                    order = self.close(data=d)
                    if order is not None:
                        self.order_meta[order.ref] = {
                            "signal": "FULL_CLOSE_PROFIT_GT_100_EITHER_COMBO",
                            "target_value": 0.0,
                            "date": self._dt_str(d),
                        }
                    continue

                if profit_ratio > 0.5 and either_combo and code not in self._tier50_75_done:
                    sell_size = int(abs(pos.size) * 0.75)
                    if sell_size > 0:
                        order = self.sell(data=d, size=sell_size)
                        if order is not None:
                            self._tier50_75_done.add(code)
                            self._post_tier50_peak[code] = close_px
                            self.order_meta[order.ref] = {
                                "signal": "SELL_75PCT_TIER_PROFIT_GT_50_EITHER_COMBO",
                                "target_value": float((pos.size - sell_size) * close_px),
                                "date": self._dt_str(d),
                            }
                            continue

                if profit_ratio > 0.3 and either_combo and code not in self._tier30_half_done:
                    sell_size = int(abs(pos.size) * 0.5)
                    if sell_size > 0:
                        order = self.sell(data=d, size=sell_size)
                        if order is not None:
                            self._tier30_half_done.add(code)
                            self._post_tier30_peak[code] = close_px
                            self.order_meta[order.ref] = {
                                "signal": "HALF_SELL_TIER_PROFIT_GT_30_EITHER_COMBO",
                                "target_value": float((pos.size - sell_size) * close_px),
                                "date": self._dt_str(d),
                            }
                            continue

                if code in self._tier30_half_done and code not in self._tier30_dd_add_done:
                    pk30 = max(self._post_tier30_peak.get(code, close_px), close_px)
                    self._post_tier30_peak[code] = pk30
                    if pk30 > 0 and (close_px / pk30 - 1.0) <= -0.2:
                        self._submit_buy_value(
                            d,
                            v0 * self.p.drawdown_add_weight,
                            "ADD_AFTER_TIER30_HALF_DRAWDOWN_20PCT",
                        )
                        self._tier30_dd_add_done.add(code)

                if code in self._tier50_75_done and code not in self._tier50_dd_add_done:
                    pk50 = max(self._post_tier50_peak.get(code, close_px), close_px)
                    self._post_tier50_peak[code] = pk50
                    if pk50 > 0 and (close_px / pk50 - 1.0) <= -0.3:
                        self._submit_buy_value(
                            d,
                            v0 * self.p.drawdown_add_weight,
                            "ADD_AFTER_TIER50_75_DRAWDOWN_30PCT",
                        )
                        self._tier50_dd_add_done.add(code)

            else:
                if (
                    profit_ratio > 1.0
                    and either_combo
                    and code not in self._tier2_half_done
                ):
                    sell_size = int(abs(pos.size) * 0.75)
                    if sell_size > 0:
                        order = self.sell(data=d, size=sell_size)
                        if order is not None:
                            self._tier2_half_done.add(code)
                            self._post_tier2_peak[code] = close_px
                            self.order_meta[order.ref] = {
                                "signal": "SELL_75PCT_TIER2_PROFIT_GT_100_EITHER_COMBO",
                                "target_value": float((pos.size - sell_size) * close_px),
                                "date": self._dt_str(d),
                            }
                            continue

                if profit_ratio > 0.5 and either_combo and code not in self._tier1_half_done:
                    sell_size = int(abs(pos.size) * 0.5)
                    if sell_size > 0:
                        order = self.sell(data=d, size=sell_size)
                        if order is not None:
                            self._tier1_half_done.add(code)
                            self._post_tier1_peak[code] = close_px
                            self.order_meta[order.ref] = {
                                "signal": "HALF_SELL_TIER1_PROFIT_GT_50_EITHER_COMBO",
                                "target_value": float((pos.size - sell_size) * close_px),
                                "date": self._dt_str(d),
                            }
                            continue

                if code in self._tier1_half_done and code not in self._tier1_dd_add_done:
                    pk = max(self._post_tier1_peak.get(code, close_px), close_px)
                    self._post_tier1_peak[code] = pk
                    if pk > 0 and (close_px / pk - 1.0) <= -0.2:
                        self._submit_buy_value(
                            d,
                            v0 * self.p.drawdown_add_weight,
                            "ADD_AFTER_TIER1_HALF_DRAWDOWN_20PCT",
                        )
                        self._tier1_dd_add_done.add(code)

                if code in self._tier2_half_done and code not in self._tier2_dd_add_done:
                    pk2 = max(self._post_tier2_peak.get(code, close_px), close_px)
                    self._post_tier2_peak[code] = pk2
                    if pk2 > 0 and (close_px / pk2 - 1.0) <= -0.3:
                        self._submit_buy_value(
                            d,
                            v0 * self.p.drawdown_add_weight,
                            "ADD_AFTER_TIER2_HALF_DRAWDOWN_30PCT",
                        )
                        self._tier2_dd_add_done.add(code)

        total_value = float(self.broker.getvalue())
        if total_value <= 0:
            return

        inv_gate = self._eod_invested_ratio if self._eod_invested_ratio is not None else inv_ratio_start

        for d in sorted_ds:
            close_px = float(d.close[0])
            if not np.isfinite(close_px) or close_px <= 0:
                continue
            if self._line_value(d, "block_halving_future_buy") >= 1.0:
                continue
            pos = self.getposition(d)
            bottom = self._line_value(d, "bottom_fishing_score")
            mac = self._line_value(d, "mac_total")
            weak_buy = bottom > 0 and mac > 0
            if not weak_buy:
                continue
            if inv_gate >= 0.8 - 1e-9:
                continue
            target_value = total_value * self.p.max_weight
            current_value = pos.size * close_px
            if current_value < target_value - 1e-6:
                self._submit_order_target_value(d, target_value, "WEAK_BUY_BOTTOM_AND_MAC_5PCT")

        for d in sorted_ds:
            close_px = float(d.close[0])
            if not np.isfinite(close_px) or close_px <= 0:
                continue
            if self._line_value(d, "block_halving_future_buy") >= 1.0:
                continue
            pos = self.getposition(d)
            tbs = self._line_value(d, "total_buy_signal")
            if tbs >= 1.0:
                target_value = total_value * self.p.max_weight
                current_value = pos.size * close_px
                if current_value < target_value - 1e-6:
                    self._submit_order_target_value(d, target_value, "STRONG_BUY_TOTAL_SIGNAL_5PCT")

    def notify_cashvalue(self, cash: float, value: float) -> None:
        if len(self) <= 0:
            return
        if value > 0:
            self._eod_invested_ratio = float(value - cash) / float(value)
        dt_str = bt.num2date(self.datetime[0]).strftime("%Y-%m-%d")
        payload = {
            "date": dt_str,
            "cash_value": float(cash),
            "portfolio_value": float(value),
            "positions_value": float(value) - float(cash),
        }
        if self.daily_value_log and self.daily_value_log[-1]["date"] == dt_str:
            self.daily_value_log[-1].update(payload)
        else:
            self.daily_value_log.append(payload)

    def notify_order(self, order: Any) -> None:
        if order.status not in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            return
        data = order.data
        meta = self.order_meta.get(order.ref, {})
        executed = order.executed
        self.order_log.append(
            {
                "date": meta.get("date") or self._dt_str(data),
                "code": data._name,
                "signal": meta.get("signal", ""),
                "status": order.getstatusname(),
                "side": "BUY" if order.isbuy() else "SELL",
                "created_size": float(order.created.size or 0.0),
                "executed_size": float(executed.size or 0.0),
                "executed_price": float(executed.price or 0.0),
                "executed_value": float(executed.value or 0.0),
                "commission": float(executed.comm or 0.0),
                "target_value": float(meta.get("target_value") or 0.0),
                "position_after": float(self.getposition(data).size),
                "cash_after": float(self.broker.getcash()),
                "portfolio_value_after": float(self.broker.getvalue()),
            }
        )

    def notify_trade(self, trade: Any) -> None:
        if not trade.isclosed:
            return
        self.trade_log.append(
            {
                "code": trade.data._name,
                "date_open": bt.num2date(trade.dtopen).strftime("%Y-%m-%d") if trade.dtopen else None,
                "date_close": bt.num2date(trade.dtclose).strftime("%Y-%m-%d") if trade.dtclose else None,
                "barlen": int(trade.barlen or 0),
                "pnl": float(trade.pnl),
                "pnlcomm": float(trade.pnlcomm),
            }
        )


# 兼容旧名称
MacKdjBottomScoreBuyAndHoldStrategy = ZxwRuleBacktestStrategy
class BuyAndHoldBenchmarkStrategy(bt.Strategy):
    def __init__(self) -> None:
        self.daily_value_log = []
        self._initialized = False

    def nextstart(self) -> None:
        if self._initialized:
            return
        valid_datas = [d for d in self.datas if len(d) > 0 and np.isfinite(float(d.close[0])) and float(d.close[0]) > 0]
        if not valid_datas:
            return
        target_weight = 1.0 / len(valid_datas)
        investable_value = self.broker.getcash() / (1.0 + COMMISSION)
        for d in valid_datas:
            self.order_target_value(data=d, target=investable_value * target_weight)
        self._initialized = True

    def notify_cashvalue(self, cash: float, value: float) -> None:
        if len(self) <= 0:
            return
        dt_str = bt.num2date(self.datetime[0]).strftime("%Y-%m-%d")
        payload = {"date": dt_str, "cash_value": float(cash), "portfolio_value": float(value), "positions_value": float(value) - float(cash)}
        if self.daily_value_log and self.daily_value_log[-1]["date"] == dt_str:
            self.daily_value_log[-1].update(payload)
        else:
            self.daily_value_log.append(payload)


def _normalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.floating, float, np.integer, int)):
        if not math.isfinite(float(value)):
            return None
        return round(float(value), 4)
    return value


def _normalize_value(value: Any, digits: int = 2) -> Any:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value
    if not math.isfinite(numeric):
        return None
    return round(numeric, digits)


def _normalize_percent(value: Any) -> str | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return f"{round(numeric * 100, 2)}%"


def build_stock_performance_summary(
    order_log_df: pd.DataFrame,
    trade_log_df: pd.DataFrame,
    position_log_df: pd.DataFrame,
    final_value: float,
) -> dict[str, list[dict[str, Any]]]:
    """汇总已平仓与期末仍持仓股票表现，供结果展示页直接读取。"""
    final_position_df = pd.DataFrame()
    open_codes: set[str] = set()
    if not position_log_df.empty and {"date", "code"}.issubset(position_log_df.columns):
        final_date = str(position_log_df["date"].dropna().max())
        final_position_df = position_log_df[position_log_df["date"].astype(str) == final_date].copy()
        final_position_df["position_size"] = pd.to_numeric(final_position_df.get("position_size"), errors="coerce").fillna(0.0)
        final_position_df = final_position_df[final_position_df["position_size"] != 0.0]
        open_codes = set(final_position_df["code"].dropna().astype(str))

    buy_cost_by_code: dict[str, float] = {}
    if not order_log_df.empty and {"code", "side", "executed_value"}.issubset(order_log_df.columns):
        orders = order_log_df.copy()
        orders["side"] = orders["side"].astype(str).str.upper()
        if "status" in orders.columns:
            orders = orders[orders["status"].astype(str).str.upper() == "COMPLETED"]
        buy_orders = orders[orders["side"] == "BUY"].copy()
        buy_orders["executed_value"] = pd.to_numeric(buy_orders["executed_value"], errors="coerce").abs().fillna(0.0)
        if "commission" in buy_orders.columns:
            buy_orders["commission"] = pd.to_numeric(buy_orders["commission"], errors="coerce").fillna(0.0)
        else:
            buy_orders["commission"] = 0.0
        buy_cost_by_code = (buy_orders["executed_value"] + buy_orders["commission"]).groupby(buy_orders["code"].astype(str)).sum().to_dict()

    strategy_profit = float(final_value) - float(INITIAL_CASH)
    realized_pnl_by_code: dict[str, float] = {}
    trades = pd.DataFrame()
    if not trade_log_df.empty and {"code", "pnlcomm"}.issubset(trade_log_df.columns):
        trades = trade_log_df.copy()
        trades["code"] = trades["code"].astype(str)
        trades["pnlcomm"] = pd.to_numeric(trades["pnlcomm"], errors="coerce").fillna(0.0)
        realized_pnl_by_code = trades.groupby("code")["pnlcomm"].sum().to_dict()

    closed_items: list[dict[str, Any]] = []
    if not trades.empty:
        closed_trades = trades[~trades["code"].isin(open_codes)]
        if not closed_trades.empty:
            grouped = closed_trades.groupby("code", as_index=False).agg(
                realized_pnl=("pnlcomm", "sum"),
                trade_count=("pnlcomm", "size"),
                first_entry_date=("date_open", "min"),
                last_exit_date=("date_close", "max"),
                holding_days=("barlen", "sum"),
            )
            for row in grouped.sort_values("realized_pnl", ascending=False).to_dict("records"):
                code = str(row.get("code", ""))
                buy_cost = float(buy_cost_by_code.get(code, 0.0) or 0.0)
                realized_pnl = float(row.get("realized_pnl") or 0.0)
                closed_items.append(
                    {
                        "code": code,
                        "realized_pnl": _normalize_value(realized_pnl),
                        "buy_cost": _normalize_value(buy_cost),
                        "realized_return_pct": _normalize_percent(realized_pnl / buy_cost) if abs(buy_cost) > 1e-12 else None,
                        "contribution_pct": _normalize_percent(realized_pnl / strategy_profit) if abs(strategy_profit) > 1e-12 else None,
                        "trade_count": int(row.get("trade_count") or 0),
                        "first_entry_date": row.get("first_entry_date"),
                        "last_exit_date": row.get("last_exit_date"),
                        "holding_days": _normalize_value(row.get("holding_days"), 0),
                    }
                )

    open_items: list[dict[str, Any]] = []
    if not final_position_df.empty:
        for _, row in final_position_df.sort_values("market_value", ascending=False).iterrows():
            market_value = float(row.get("market_value") or 0.0)
            position_size = float(row.get("position_size") or 0.0)
            position_price = float(row.get("position_price") or 0.0)
            close = float(row.get("close") or 0.0)
            cost_basis = position_size * position_price
            unrealized_pnl = market_value - cost_basis
            code = str(row.get("code", ""))
            realized_pnl = float(realized_pnl_by_code.get(code, 0.0) or 0.0)
            total_pnl = realized_pnl + unrealized_pnl
            open_items.append(
                {
                    "code": code,
                    "unrealized_return_pct": _normalize_percent(unrealized_pnl / cost_basis) if abs(cost_basis) > 1e-12 else None,
                    "realized_pnl": _normalize_value(realized_pnl),
                    "unrealized_pnl": _normalize_value(unrealized_pnl),
                    "total_pnl": _normalize_value(total_pnl),
                    "contribution_pct": _normalize_percent(total_pnl / strategy_profit) if abs(strategy_profit) > 1e-12 else None,
                    "weight_pct": _normalize_percent(market_value / final_value) if abs(final_value) > 1e-12 else None,
                    "market_value": _normalize_value(market_value),
                    "position_size": _normalize_value(position_size, 0),
                    "close": _normalize_value(close),
                }
            )

    return {
        "已平仓股票表现": closed_items,
        "期末持仓股票表现": open_items,
    }


def run_zxw_backtest(
    target_codes: list[str],
    df_multi: pd.DataFrame,
    backtest_start: str,
    backtest_end: str,
) -> dict[str, Any]:
    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    TOTAL_RECORD_DIR.mkdir(parents=True, exist_ok=True)

    cerebro = create_cerebro(target_codes, df_multi, verbose=False)
    cerebro.addstrategy(ZxwRuleBacktestStrategy, max_weight=0.05)
    results = cerebro.run()
    strat = results[0]

    benchmark_cerebro = create_cerebro(target_codes, df_multi, verbose=False)
    benchmark_cerebro.addstrategy(BuyAndHoldBenchmarkStrategy)
    benchmark_cerebro.run()

    final_value = float(cerebro.broker.getvalue())
    benchmark_value = float(benchmark_cerebro.broker.getvalue())
    order_log_df = pd.DataFrame(strat.order_log)
    trade_log_df = pd.DataFrame(strat.trade_log)
    position_log_df = pd.DataFrame(strat.position_log)
    stock_performance = build_stock_performance_summary(
        order_log_df=order_log_df,
        trade_log_df=trade_log_df,
        position_log_df=position_log_df,
        final_value=final_value,
    )
    summary_payload = {
        "backtest_start": backtest_start,
        "backtest_end": backtest_end,
        "策略说明": "首日等权满仓；止损-15%；次卖(总卖出)+权重<1%清仓；盈利>50%减半/盈利>100%卖约75%（两强卖因子满足其一），二档可不经过一档；回撤加仓；"
        "日初总仓位<80%时次买(抄底+MAC)至单票5%；强买(总买入)5%；未来腰斩禁买(前视)。",
        "初始资金": _normalize(INITIAL_CASH),
        "策略最终总资产（扣手续费）": _normalize(final_value),
        "买入持有最终资产": _normalize(benchmark_value),
        "累计收益率（扣手续费）": _normalize(final_value / INITIAL_CASH - 1.0),
        **stock_performance,
    }

    summary_path = TOTAL_RECORD_DIR / f"summary_{run_tag}.json"
    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"run_tag": run_tag, "summary": summary_payload, "summary_path": str(summary_path)}


def _parse_codes_from_file(path: Path) -> list[str]:
    df = pd.read_csv(path)
    col = "证券代码" if "证券代码" in df.columns else df.columns[0]
    return [str(x).strip().upper() for x in df[col].dropna().tolist() if str(x).strip()]


def build_zxw_rule_bt_dataframe_for_range(
    target_codes: list[str],
    backtest_start: str,
    backtest_end_exclusive: str,
    *,
    init_lookback_calendar_days: int = 0,
    enable_future_halving_mask: bool = True,
) -> tuple[pd.DataFrame, list[str]]:
    """
    按代码列表与 [start, end) 构建与脚本一致的回测宽表（可选向后扩展行情用于未来腰斩标记，再裁剪到 end）。
    供 `models/*/runner` 与 `run_single_range_backtest` 共用。

    init_lookback_calendar_days：>0 时，行情与信号从 backtest_start 再向前多取若干**自然日**（用于首日回溯建仓），
    宽表仍含 backtest_start 之前的 bar；策略侧需自行忽略早于 backtest_start 的交易日。
    enable_future_halving_mask：为 True 时行情向后多取约 14 个月以计算 block_halving_future_buy。
    """
    codes = sorted({str(c).strip().upper() for c in target_codes if str(c).strip()})
    if not codes:
        raise ValueError("target_codes 为空")
    codes_str = ", ".join([f"'{_sql_escape_htsc(c)}'" for c in codes])
    if enable_future_halving_mask:
        ext_end = (pd.Timestamp(backtest_end_exclusive) + pd.DateOffset(months=14)).strftime("%Y-%m-%d")
    else:
        ext_end = str(backtest_end_exclusive)
    query_start = str(backtest_start)
    if int(init_lookback_calendar_days or 0) > 0:
        query_start = (
            pd.Timestamp(backtest_start).normalize() - pd.Timedelta(days=int(init_lookback_calendar_days))
        ).strftime("%Y-%m-%d")

    price_view_name = "price_day_merged"
    price_con = create_duckdb_view(base_path=PRICE_BASE_PATH, view_name=price_view_name)
    price_df = price_con.execute(
        f"""
        SELECT *
        FROM {price_view_name}
        WHERE UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN ({codes_str})
          AND time >= '{query_start}'
          AND time < '{ext_end}'
        ORDER BY htsc_code, time
        """
    ).df()
    price_df["time"] = pd.to_datetime(price_df["time"]).dt.normalize()
    price_df["htsc_code"] = price_df["htsc_code"].astype(str).str.strip().str.upper()
    price_df = apply_ohlc_adj_to_price_df(
        price_df,
        target_codes=codes,
        query_start_date=query_start,
        query_end_exclusive=ext_end,
    )
    bt_df = build_bt_dataframe(
        price_df=price_df,
        target_codes=codes,
        backtest_start=query_start,
        backtest_end_exclusive=ext_end,
        clip_date_end_exclusive=backtest_end_exclusive,
        enable_future_halving_mask=enable_future_halving_mask,
    )
    actual_codes = sorted(bt_df["htsc_code"].astype(str).str.upper().unique().tolist())
    return bt_df, actual_codes


def run_single_range_backtest(
    target_codes: list[str],
    backtest_start: str,
    backtest_end_exclusive: str,
) -> dict[str, Any]:
    """按代码列表与 [start, end) 区间跑一次回测（行情自动向后扩展用于未来腰斩标记）。"""
    bt_df, actual_codes = build_zxw_rule_bt_dataframe_for_range(
        target_codes, backtest_start, backtest_end_exclusive
    )
    return run_zxw_backtest(
        target_codes=actual_codes,
        df_multi=bt_df,
        backtest_start=backtest_start,
        backtest_end=backtest_end_exclusive,
    )


def run_yearly_backtests(years: list[int]) -> pd.DataFrame:
    price_view_name = "price_day_merged"
    price_con = create_duckdb_view(base_path=PRICE_BASE_PATH, view_name=price_view_name)

    summary_rows: list[dict[str, Any]] = []
    for year in years:
        backtest_start = f"{year}-01-01"
        backtest_end_exclusive = f"{year + 1}-01-01"
        price_ext_exclusive = f"{year + 2}-02-01"
        pool_path = Path(rf"D:\database\{year}.csv")
        if not pool_path.exists():
            print(f"⚠️ 股票池不存在，跳过 {year}: {pool_path}")
            continue

        code_df = duckdb.read_csv(str(pool_path)).df()
        target_codes = [str(x).strip().upper() for x in code_df["证券代码"].dropna().tolist()]
        if not target_codes:
            print(f"⚠️ 股票池为空，跳过 {year}")
            continue

        codes_str = ", ".join([f"'{code}'" for code in target_codes])
        print("=" * 80)
        print(f"开始回测 {year}: 区间=[{backtest_start}, {backtest_end_exclusive})")

        price_df = price_con.execute(
            f"""
            SELECT *
            FROM {price_view_name}
            WHERE htsc_code IN ({codes_str})
              AND time >= '{backtest_start}'
              AND time < '{price_ext_exclusive}'
            ORDER BY htsc_code, time
            """
        ).df()
        price_df["time"] = pd.to_datetime(price_df["time"]).dt.normalize()
        price_df["htsc_code"] = price_df["htsc_code"].astype(str).str.strip().str.upper()
        price_df = apply_ohlc_adj_to_price_df(
            price_df,
            target_codes=target_codes,
            query_start_date=backtest_start,
            query_end_exclusive=price_ext_exclusive,
        )
        print(f"行情复权: ADJ_MODE={ADJ_MODE}，扩展行情行数={len(price_df)}")

        bt_df = build_bt_dataframe(
            price_df=price_df,
            target_codes=target_codes,
            backtest_start=backtest_start,
            backtest_end_exclusive=price_ext_exclusive,
            clip_date_end_exclusive=backtest_end_exclusive,
        )
        actual_codes = sorted(bt_df["htsc_code"].astype(str).str.upper().unique().tolist())

        out = run_zxw_backtest(
            target_codes=actual_codes,
            df_multi=bt_df,
            backtest_start=backtest_start,
            backtest_end=backtest_end_exclusive,
        )
        row = {"year": year, **out["summary"], "summary_path": out["summary_path"]}
        summary_rows.append(row)
        print(f"{year} 回测完成，summary: {out['summary_path']}")

    return pd.DataFrame(summary_rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ZXW 规则回测：等权起步+减仓/加仓/未来腰斩禁买等")
    parser.add_argument("--codes", type=str, default="", help="逗号分隔证券代码，如 000001.SZ,600000.SH")
    parser.add_argument("--codes-file", type=Path, default=None, help="CSV 路径，列「证券代码」或首列为代码")
    parser.add_argument("--start", type=str, default="", help="回测起始日 YYYY-MM-DD")
    parser.add_argument(
        "--end",
        type=str,
        default="",
        help="回测结束日（不包含）YYYY-MM-DD，例如 2021-01-01 表示数据到 2020-12-31",
    )
    parser.add_argument("--years", action="store_true", help="按 BACKTEST_YEARS 跑年度 CSV 模式")
    args = parser.parse_args()

    if args.start and args.end:
        codes: list[str] = []
        if args.codes_file is not None:
            codes.extend(_parse_codes_from_file(args.codes_file))
        if args.codes.strip():
            codes.extend([c.strip().upper() for c in args.codes.split(",") if c.strip()])
        codes = sorted({c for c in codes if c})
        if not codes:
            raise SystemExit("请提供 --codes 或 --codes-file")
        out = run_single_range_backtest(codes, args.start.strip(), args.end.strip())
        print(json.dumps(out["summary"], ensure_ascii=False, indent=2))
        print("summary_path:", out["summary_path"])
    elif args.years:
        result_df = run_yearly_backtests(BACKTEST_YEARS)
        print("=" * 80)
        print("年度回测汇总:")
        if result_df.empty:
            print("无可用回测结果。")
        else:
            print(result_df.to_string(index=False))
    else:
        result_df = run_yearly_backtests(BACKTEST_YEARS)
        print("=" * 80)
        print("年度回测汇总:")
        if result_df.empty:
            print("无可用回测结果。")
        else:
            print(result_df.to_string(index=False))
