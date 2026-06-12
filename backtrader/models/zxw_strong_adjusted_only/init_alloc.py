"""首日回溯建仓：从 start_date 之前按日历倒序扫 strong_buy_signal，最多 50 只、每只目标权重默认 5%（总和不超过 total_cap）。"""

from __future__ import annotations

import pandas as pd


def _no_sell_from_signal_to_start(
    sub: pd.DataFrame,
    code: str,
    signal_date: pd.Timestamp,
    start_ts: pd.Timestamp,
    *,
    sell_col: str,
) -> bool:
    """信号日（含）至 backtest_start（不含）区间内无 strong_sell_signal >= 1。"""
    hit = sub[
        (sub["htsc_code"] == code)
        & (sub["time"] >= signal_date)
        & (sub["time"] < start_ts)
        & (sub[sell_col] >= 1.0)
    ]
    return hit.empty


def compute_backscan_initial_weights(
    bt_df: pd.DataFrame,
    target_codes: list[str],
    backtest_start: str,
    *,
    max_stocks: int = 50,
    per_stock_cap: float = 0.05,
    total_cap: float = 1.0,
) -> dict[str, float]:
    """
    在 backtest_start 之前（不含当日）逐日倒序扫描；某日多票同时有信号则一并纳入，
    按「最近日优先」依次填满 max_stocks；每只股票目标权重 min(per_stock_cap, 剩余空间均分)。

    纳入条件：信号日 strong_buy_signal >= 1，且从该信号日（含）到 backtest_start（不含）
    的整段区间内均无 strong_sell_signal >= 1（前端卖出因子合成，不用宽表 total_sell_signal）。
    """
    if bt_df.empty or not target_codes:
        return {}
    start_ts = pd.Timestamp(str(backtest_start)).normalize()
    code_set = {str(c).strip().upper() for c in target_codes}
    sub = bt_df[bt_df["time"] < start_ts].copy()
    if sub.empty:
        return {}
    sub["time"] = pd.to_datetime(sub["time"], errors="coerce").dt.normalize()
    sub["htsc_code"] = sub["htsc_code"].astype(str).str.strip().str.upper()
    buy_col = "strong_buy_signal" if "strong_buy_signal" in sub.columns else "total_buy_signal"
    if buy_col not in sub.columns:
        sub[buy_col] = 0.0
    else:
        sub[buy_col] = pd.to_numeric(sub[buy_col], errors="coerce").fillna(0.0)
    sell_col = "strong_sell_signal" if "strong_sell_signal" in sub.columns else None
    if sell_col is None:
        sub["strong_sell_signal"] = 0.0
        sell_col = "strong_sell_signal"
    else:
        sub[sell_col] = pd.to_numeric(sub[sell_col], errors="coerce").fillna(0.0)

    dates = sorted(sub["time"].dropna().unique(), reverse=True)
    chosen: list[str] = []
    for d in dates:
        if len(chosen) >= max_stocks:
            break
        day = sub[sub["time"] == d]
        picks: list[str] = []
        for _, row in day.iterrows():
            c = str(row["htsc_code"]).strip().upper()
            if c not in code_set or c in chosen:
                continue
            if float(row[buy_col]) >= 1.0 and _no_sell_from_signal_to_start(
                sub, c, d, start_ts, sell_col=sell_col
            ):
                picks.append(c)
        for c in picks:
            if len(chosen) >= max_stocks:
                break
            if c not in chosen:
                chosen.append(c)
    if not chosen:
        return {}
    w_each = min(float(per_stock_cap), float(total_cap) / float(len(chosen)))
    s = w_each * len(chosen)
    if s > total_cap + 1e-12:
        w_each = float(total_cap) / float(len(chosen))
    return {c: float(w_each) for c in chosen}
