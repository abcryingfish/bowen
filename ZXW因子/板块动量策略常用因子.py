"""板块动量策略常用因子。

基于 ZXW 日线收盘价矩阵生成：
  - 120 日动量: 当前收盘价 / 120 个交易日前收盘价 - 1
  - 纯动量: 120 日动量 - 20 日动量
  - 收盘价高于 MA60: 收盘价 > 60 日简单移动平均
  - 60 日年化波动率: 60 日收益率样本标准差 * sqrt(252)
  - 板块波动率 ZScore: 20 日年化波动率相对自身 252 日历史的标准分
  - 板块 8 日涨跌幅 ZScore: 8 日对数涨跌幅相对自身 252 日历史的标准分
  - 板块 EWMA-RMS 移动强度 ZScore: 短期方向无关移动强度相对自身 252 日历史的标准分
"""
from __future__ import annotations

from typing import Any
from pathlib import Path

import numpy as np
import pandas as pd
import duckdb


BUNDLE_ID = "momentum_common"
_DEFAULT_LOOKBACK_DAYS = 240
_SECTOR_VOLATILITY_WINDOW = 20
_SECTOR_VOLATILITY_ZSCORE_WINDOW = 252
_SECTOR_VOLATILITY_ZSCORE_MIN_PERIODS = 120
_SECTOR_VOLATILITY_ZSCORE_HISTORY_CALENDAR_DAYS = 420
_SECTOR_MOVE_WINDOW = 8
_SECTOR_EWMA_RMS_HALFLIFE = 5
_SECTOR_SHORT_ZSCORE_WINDOW = 252
_SECTOR_SHORT_ZSCORE_MIN_PERIODS = 120
_SECTOR_SHORT_HISTORY_CALENDAR_DAYS = 420
_INDUSTRY_PB_PERCENTILE_WINDOW_3Y = 756
_INDUSTRY_PB_PERCENTILE_WINDOW_5Y = 1260
# 主生成器按日历日回退查询起点；滚动分位仍分别使用 756/1260 个交易日。
# 1300/2000 个日历日用于覆盖节假日和停牌缺口，避免增量计算时窗口不足。
_INDUSTRY_PB_3Y_HISTORY_CALENDAR_DAYS = 1300
_INDUSTRY_PB_5Y_HISTORY_CALENDAR_DAYS = 2000
_DEFAULT_INDUSTRY_SNAPSHOT = Path(
    r"D:\database\sector_information\constituent_snapshots_eligible\analysis_date=2026-07-15\part-000.parquet"
)
_VALUATION_GLOB = (
    r"D:\database\qmt_company_data\table=factor_fundamental_valuation\year=*\month=*\merged.parquet"
)

FACTOR_LOOKBACK_DAYS: dict[str, int] = {
    "momentum_5d": 5,
    "momentum_20d": 20,
    "momentum_60d": 60,
    "momentum_120d": 120,
    "momentum_252d": 252,
    "pure_momentum": 120,
    "pure_momentum_60d": 60,
    "pure_momentum_252d": 252,
    "close_above_ma60": 60,
    "annual_vol_60d": 60,
    "sector_volatility_zscore_20d_252d": _SECTOR_VOLATILITY_ZSCORE_HISTORY_CALENDAR_DAYS,
    "sector_return_zscore_8d_252d": _SECTOR_SHORT_HISTORY_CALENDAR_DAYS,
    "sector_ewma_rms_zscore_252d": _SECTOR_SHORT_HISTORY_CALENDAR_DAYS,
    "industry_pb_percentile_3y_mcap": _INDUSTRY_PB_3Y_HISTORY_CALENDAR_DAYS,
    "industry_pb_percentile_3y_median": _INDUSTRY_PB_3Y_HISTORY_CALENDAR_DAYS,
    "industry_pb_percentile_mcap": _INDUSTRY_PB_5Y_HISTORY_CALENDAR_DAYS,
    "industry_pb_percentile_median": _INDUSTRY_PB_5Y_HISTORY_CALENDAR_DAYS,
    "industry_profit_yoy_mcap": 365,
    "industry_profit_yoy_median": 365,
}


def get_factor_catalog() -> dict[str, dict[str, str]]:
    """返回主脚本自动规划使用的因子目录，不触发数据读取。"""
    return {
        "factor_name_map": {
            "5日动量": "momentum_5d",
            "20日动量": "momentum_20d",
            "60日动量": "momentum_60d",
            "120日动量": "momentum_120d",
            "252日动量": "momentum_252d",
            "纯动量": "pure_momentum",
            "60日纯动量": "pure_momentum_60d",
            "252日纯动量": "pure_momentum_252d",
            "收盘价高于MA60": "close_above_ma60",
            "60日年化波动率": "annual_vol_60d",
            "板块20日波动率ZScore_252日": "sector_volatility_zscore_20d_252d",
            "板块8日涨跌幅ZScore_252日": "sector_return_zscore_8d_252d",
            "板块EWMA_RMS移动强度ZScore_252日": "sector_ewma_rms_zscore_252d",
            "板块PB历史分位_3年_整体法": "industry_pb_percentile_3y_mcap",
            "板块PB历史分位_3年_中位数": "industry_pb_percentile_3y_median",
            "板块PB历史分位_5年_整体法": "industry_pb_percentile_mcap",
            "板块PB历史分位_5年_中位数": "industry_pb_percentile_median",
            "行业净利润改善率_市值加权": "industry_profit_yoy_mcap",
            "行业净利润改善率_中位数": "industry_profit_yoy_median",
        }
    }


def _industry_event_start(start_date: pd.Timestamp, *, want_profit: bool) -> pd.Timestamp:
    """返回估值事件读取起点；利润需覆盖上年同期及公告延迟。"""
    start = pd.Timestamp(start_date).floor("D")
    return start - pd.Timedelta(days=550) if want_profit else start


def _as_float_frame(value: pd.DataFrame, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    """对齐矩阵并统一为浮点型，保留原始 index/columns。"""
    return value.reindex(index=index, columns=columns).astype(float)


def select_ths_columns(columns: pd.Index) -> pd.Index:
    """保留同花顺板块代码，兼容大小写和代码两侧空白。"""
    return pd.Index([
        column
        for column in columns
        if str(column).strip().upper().endswith(".THS")
    ])


def build_momentum_factor_bundle(C: pd.DataFrame) -> dict[str, dict[str, pd.DataFrame]]:
    """生成传入板块行情的动量因子；调用方负责只传入 THS 列。"""
    index, columns = C.index, C.columns
    close = _as_float_frame(C, index=index, columns=columns)

    momentum_5d = close / close.shift(5) - 1.0
    momentum_20d = close / close.shift(20) - 1.0
    momentum_60d = close / close.shift(60) - 1.0
    momentum_120d = close / close.shift(120) - 1.0
    momentum_252d = close / close.shift(252) - 1.0
    pure_momentum = momentum_120d - momentum_20d
    pure_momentum_60d = momentum_60d - momentum_20d
    pure_momentum_252d = momentum_252d - momentum_20d
    ma60 = close.rolling(window=60, min_periods=60).mean()
    close_above_ma60 = (close > ma60).astype(float)
    annual_vol_60d = close.pct_change().rolling(window=60, min_periods=60).std() * np.sqrt(252.0)
    sector_close = close.loc[:, select_ths_columns(close.columns)]
    annual_vol_20d = (
        sector_close.pct_change()
        .rolling(window=_SECTOR_VOLATILITY_WINDOW, min_periods=_SECTOR_VOLATILITY_WINDOW)
        .std()
        * np.sqrt(252.0)
    )
    log_vol_20d = np.log(annual_vol_20d.where(annual_vol_20d > 0.0))
    zscore_mean = log_vol_20d.rolling(
        window=_SECTOR_VOLATILITY_ZSCORE_WINDOW,
        min_periods=_SECTOR_VOLATILITY_ZSCORE_MIN_PERIODS,
    ).mean()
    zscore_std = log_vol_20d.rolling(
        window=_SECTOR_VOLATILITY_ZSCORE_WINDOW,
        min_periods=_SECTOR_VOLATILITY_ZSCORE_MIN_PERIODS,
    ).std()
    sector_volatility_zscore = (
        (log_vol_20d - zscore_mean) / zscore_std.replace(0.0, np.nan)
    ).clip(lower=-3.0, upper=3.0)

    sector_price = sector_close.where(sector_close > 0.0)
    move_8d = np.log(sector_price / sector_price.shift(_SECTOR_MOVE_WINDOW))
    move_mean = move_8d.rolling(
        window=_SECTOR_SHORT_ZSCORE_WINDOW,
        min_periods=_SECTOR_SHORT_ZSCORE_MIN_PERIODS,
    ).mean()
    move_std = move_8d.rolling(
        window=_SECTOR_SHORT_ZSCORE_WINDOW,
        min_periods=_SECTOR_SHORT_ZSCORE_MIN_PERIODS,
    ).std()
    sector_return_zscore = (
        (move_8d - move_mean) / move_std.replace(0.0, np.nan)
    ).clip(lower=-3.0, upper=3.0).where(sector_close.notna())

    sector_log_return = np.log(sector_price / sector_price.shift(1))
    sector_ewma_rms = np.sqrt(
        252.0
        * sector_log_return.pow(2).ewm(
            halflife=_SECTOR_EWMA_RMS_HALFLIFE,
            adjust=False,
            min_periods=1,
        ).mean()
    )
    sector_log_ewma_rms = np.log(sector_ewma_rms.where(sector_ewma_rms > 0.0))
    ewma_rms_mean = sector_log_ewma_rms.rolling(
        window=_SECTOR_SHORT_ZSCORE_WINDOW,
        min_periods=_SECTOR_SHORT_ZSCORE_MIN_PERIODS,
    ).mean()
    ewma_rms_std = sector_log_ewma_rms.rolling(
        window=_SECTOR_SHORT_ZSCORE_WINDOW,
        min_periods=_SECTOR_SHORT_ZSCORE_MIN_PERIODS,
    ).std()
    sector_ewma_rms_zscore = (
        (sector_log_ewma_rms - ewma_rms_mean)
        / ewma_rms_std.replace(0.0, np.nan)
    ).clip(lower=-3.0, upper=3.0).where(sector_close.notna())

    factor_dfs = {
        "momentum_5d": momentum_5d,
        "momentum_20d": momentum_20d,
        "momentum_60d": momentum_60d,
        "momentum_120d": momentum_120d,
        "momentum_252d": momentum_252d,
        "pure_momentum": pure_momentum,
        "pure_momentum_60d": pure_momentum_60d,
        "pure_momentum_252d": pure_momentum_252d,
        "close_above_ma60": close_above_ma60,
        "annual_vol_60d": annual_vol_60d,
        "sector_volatility_zscore_20d_252d": sector_volatility_zscore,
        "sector_return_zscore_8d_252d": sector_return_zscore,
        "sector_ewma_rms_zscore_252d": sector_ewma_rms_zscore,
    }
    factor_name_map = {
        "5日动量": "momentum_5d",
        "20日动量": "momentum_20d",
        "60日动量": "momentum_60d",
        "120日动量": "momentum_120d",
        "252日动量": "momentum_252d",
        "纯动量": "pure_momentum",
        "60日纯动量": "pure_momentum_60d",
        "252日纯动量": "pure_momentum_252d",
        "收盘价高于MA60": "close_above_ma60",
        "60日年化波动率": "annual_vol_60d",
        "板块20日波动率ZScore_252日": "sector_volatility_zscore_20d_252d",
        "板块8日涨跌幅ZScore_252日": "sector_return_zscore_8d_252d",
        "板块EWMA_RMS移动强度ZScore_252日": "sector_ewma_rms_zscore_252d",
    }
    return {
        "bundle_id": BUNDLE_ID,
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
        "factor_merge_policies": {
            "sector_volatility_zscore_20d_252d": {
                "preserve_columns": True,
                "preserve_nan": True,
            },
            "sector_return_zscore_8d_252d": {
                "preserve_columns": True,
                "preserve_nan": True,
            },
            "sector_ewma_rms_zscore_252d": {
                "preserve_columns": True,
                "preserve_nan": True,
            },
        },
    }


def _latest_snapshot_path() -> Path:
    root = _DEFAULT_INDUSTRY_SNAPSHOT.parent.parent
    candidates = sorted(root.glob("analysis_date=*/part-*.parquet"))
    return candidates[-1] if candidates else _DEFAULT_INDUSTRY_SNAPSHOT


def build_industry_factor_bundle(
    dates: pd.Index,
    stock_codes: pd.Index,
    snapshot_path: Path | None = None,
    valuation_glob: str = _VALUATION_GLOB,
    valid_bar: pd.DataFrame | None = None,
    target_factor_keys: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, dict[str, pd.DataFrame]]:
    """按当前行业快照聚合行业 PB 和净利润改善率因子。

    行业成员固定使用快照中的 eligible 成分；财务数据按公告日点时过滤。
    valid_bar 仅为兼容统一 bundle 接口保留，不改变财务合成范围。成分股当日缺少
    估值记录时，使用截至当日最近一条有效记录，且不会从未来日期反向填充。
    DuckDB 负责读取、连接和横截面聚合，Pandas 只负责透视和滚动分位。
    """
    index = pd.DatetimeIndex(pd.to_datetime(dates)).normalize()
    if index.empty:
        return {"factor_dfs": {}, "factor_name_map": {}}

    snapshot = snapshot_path or _latest_snapshot_path()
    if not snapshot.exists():
        return {"factor_dfs": {}, "factor_name_map": {}}

    requested_codes = {str(code).strip().upper() for code in stock_codes if str(code).strip()}
    if not requested_codes:
        return {"factor_dfs": {}, "factor_name_map": {}}

    aggregate_factor_keys = {
        "industry_pb_percentile_3y_mcap",
        "industry_pb_percentile_3y_median",
        "industry_pb_percentile_mcap",
        "industry_pb_percentile_median",
        "industry_profit_yoy_mcap",
        "industry_profit_yoy_median",
    }
    if target_factor_keys is None:
        requested_factors = set(aggregate_factor_keys)
    else:
        requested_factors = {
            str(key).strip()
            for key in target_factor_keys
            if str(key).strip() in aggregate_factor_keys
        }
    if not requested_factors:
        return {"factor_dfs": {}, "factor_name_map": {}}

    want_pb_mcap = bool(requested_factors & {
        "industry_pb_percentile_3y_mcap", "industry_pb_percentile_mcap"
    })
    want_pb_median = bool(requested_factors & {
        "industry_pb_percentile_3y_median", "industry_pb_percentile_median"
    })
    want_profit_mcap = "industry_profit_yoy_mcap" in requested_factors
    want_profit_median = "industry_profit_yoy_median" in requested_factors
    want_profit = want_profit_mcap or want_profit_median

    members = pd.read_parquet(snapshot, columns=["sector_code", "stock_code", "eligible"])
    members["sector_code"] = members["sector_code"].astype(str).str.strip().str.upper()
    members["stock_code"] = members["stock_code"].astype(str).str.strip().str.upper()
    members = members[
        members["eligible"].fillna(False).astype(bool)
        & members["stock_code"].isin(requested_codes)
        & members["sector_code"].str.endswith(".THS")
    ][["sector_code", "stock_code"]].drop_duplicates()
    if members.empty:
        return {"factor_dfs": {}, "factor_name_map": {}}

    start_date = index.min()
    end_date = index.max()
    requested_dates = pd.DataFrame({"trade_date": index.unique()})
    # PB 的滚动历史已包含在主生成器传入的日期矩阵中；仅利润分支额外读取上年同期事件。
    event_start = _industry_event_start(start_date, want_profit=want_profit)

    # 只读取目标因子真正需要的估值列；公告日条件仍使用真实 income_announce_date，
    # 不因按需分支改变原有点时口径。
    valuation_columns = [
        "UPPER(TRIM(CAST(v.htsc_code AS VARCHAR))) AS stock_code",
        "CAST(v.time AS DATE) AS trade_date",
    ]
    if want_pb_mcap or want_pb_median:
        valuation_columns.append("TRY_CAST(v.pb AS DOUBLE) AS pb")
    if want_pb_mcap or want_profit_mcap:
        valuation_columns.append("TRY_CAST(v.total_market_val AS DOUBLE) AS market_cap")
    if want_profit:
        valuation_columns.extend([
            "CAST(v.income_report_date AS DATE) AS report_date",
            "TRY_CAST(v.net_profit_parent_ttm AS DOUBLE) AS profit_ttm",
        ])

    daily_columns = ["md.sector_code", "md.trade_date"]
    if want_pb_mcap or want_pb_median:
        daily_columns.append("v.pb")
    if want_pb_mcap:
        daily_columns.append("v.market_cap")
    if want_profit:
        daily_columns.extend(["v.profit_ttm", "p.profit_ttm AS previous_profit_ttm"])
    if want_profit_mcap:
        daily_columns.extend([
            "v.previous_market_cap",
            """CASE
                WHEN p.profit_ttm IS NOT NULL
                 AND v.profit_ttm IS NOT NULL
                 AND ABS(v.profit_ttm) + ABS(p.profit_ttm) <> 0
                THEN 2.0 * (v.profit_ttm - p.profit_ttm)
                     / (ABS(v.profit_ttm) + ABS(p.profit_ttm))
                ELSE NULL
            END AS profit_improvement_symmetric""",
        ])
    if want_profit_median:
        # 个股改善率 = (本期利润 - 上年同期利润) / ABS(上年同期利润)。
        # 因而扭亏、亏损收窄为正，转亏、亏损扩大为负；上期为0时保持缺失。
        daily_columns.append(
            """CASE
                WHEN p.profit_ttm IS NOT NULL
                 AND p.profit_ttm <> 0
                 AND v.profit_ttm IS NOT NULL
                THEN (v.profit_ttm - p.profit_ttm) / ABS(p.profit_ttm)
                ELSE NULL
            END AS profit_improvement"""
        )

    aggregate_columns: list[str] = []
    if want_pb_mcap:
        # 板块整体PB = 有效成分总市值 / 正净资产合计，保留原整体法口径。
        aggregate_columns.append(
            """SUM(CASE WHEN pb > 0 AND market_cap > 0 THEN market_cap END)
                / NULLIF(SUM(CASE WHEN pb > 0 AND market_cap > 0 THEN market_cap / pb END), 0) AS pb_mcap"""
        )
    if want_pb_median:
        aggregate_columns.append("MEDIAN(CASE WHEN pb > 0 THEN pb END) AS pb_median")
    if want_profit_mcap:
        # 保留历史 mcap 英文键兼容下游；使用上一交易日市值权重聚合
        # 对称利润改善率，避免利润基数接近0时产生无界极端值。
        aggregate_columns.append(
            """SUM(CASE
                    WHEN previous_market_cap > 0 AND profit_improvement_symmetric IS NOT NULL
                    THEN previous_market_cap * profit_improvement_symmetric
                END) / NULLIF(
                SUM(CASE
                    WHEN previous_market_cap > 0 AND profit_improvement_symmetric IS NOT NULL
                    THEN previous_market_cap
                END),
                0
            ) AS profit_improvement_mcap"""
        )
    if want_profit_median:
        aggregate_columns.append("MEDIAN(profit_improvement) AS profit_improvement_median")

    ctes = [f"""
        valuation AS (
            SELECT
                {', '.join(valuation_columns)}
            FROM read_parquet('{valuation_glob}', union_by_name=true) v
            INNER JOIN (
                SELECT DISTINCT stock_code
                FROM industry_members
            ) requested_stocks
              ON UPPER(TRIM(CAST(v.htsc_code AS VARCHAR))) = requested_stocks.stock_code
            WHERE CAST(v.time AS DATE) >= DATE '{event_start.date()}'
              AND CAST(v.time AS DATE) <= DATE '{end_date.date()}'
              AND CAST(v.income_announce_date AS DATE) <= CAST(v.time AS DATE)
        )
    """]
    if want_profit:
        ctes.append("""
        events AS (
            SELECT stock_code, report_date, MAX(profit_ttm) AS profit_ttm
            FROM valuation
            WHERE report_date IS NOT NULL
            GROUP BY stock_code, report_date
        )
        """)
    if want_profit_mcap:
        ctes.append("""
        valuation_with_market_cap_lag AS (
            SELECT
                *,
                LAG(market_cap) OVER (
                    PARTITION BY stock_code
                    ORDER BY trade_date
                ) AS previous_market_cap
            FROM valuation
        )
        """)
    ctes.append("""
        member_dates AS (
            SELECT d.trade_date, m.sector_code, m.stock_code
            FROM requested_dates d
            CROSS JOIN industry_members m
        )
    """)

    previous_profit_join = """
            LEFT JOIN events p
              ON p.stock_code = v.stock_code
             AND p.report_date = v.report_date - INTERVAL '1 year'
    """ if want_profit else ""
    daily_source = "valuation_with_market_cap_lag" if want_profit_mcap else "valuation"
    ctes.append(f"""
        daily AS (
            SELECT
                {', '.join(daily_columns)}
            FROM member_dates md
            ASOF LEFT JOIN {daily_source} v
              ON md.stock_code = v.stock_code
             AND md.trade_date >= v.trade_date
            {previous_profit_join}
            WHERE v.stock_code IS NOT NULL
        )
    """)

    conn = duckdb.connect(database=":memory:")
    try:
        conn.register("industry_members", members)
        conn.register("requested_dates", requested_dates)
        sql = f"""
        WITH {', '.join(ctes)}
        SELECT
            sector_code,
            trade_date,
            {', '.join(aggregate_columns)}
        FROM daily
        GROUP BY sector_code, trade_date
        ORDER BY trade_date, sector_code
        """
        aggregated = conn.execute(sql).df()
    finally:
        conn.close()

    if aggregated.empty:
        return {"factor_dfs": {}, "factor_name_map": {}}

    aggregated["trade_date"] = pd.to_datetime(aggregated["trade_date"]).dt.normalize()
    aggregated = aggregated.set_index("trade_date")

    def _pivot(column: str, *, align_to_output: bool = True) -> pd.DataFrame:
        frame = aggregated.pivot(columns="sector_code", values=column).sort_index()
        return frame.reindex(index=index) if align_to_output else frame

    def _rolling_percentile(frame: pd.DataFrame, window: int) -> pd.DataFrame:
        return frame.rolling(window, min_periods=window).rank(pct=True).reindex(index=index)

    factor_dfs: dict[str, pd.DataFrame] = {}
    if want_pb_mcap:
        # 同一种整体PB矩阵只聚合一次，3年和5年同时请求时共用。
        pb_mcap = _pivot("pb_mcap", align_to_output=False)
        if "industry_pb_percentile_3y_mcap" in requested_factors:
            factor_dfs["industry_pb_percentile_3y_mcap"] = _rolling_percentile(
                pb_mcap, _INDUSTRY_PB_PERCENTILE_WINDOW_3Y
            )
        if "industry_pb_percentile_mcap" in requested_factors:
            factor_dfs["industry_pb_percentile_mcap"] = _rolling_percentile(
                pb_mcap, _INDUSTRY_PB_PERCENTILE_WINDOW_5Y
            )
    if want_pb_median:
        pb_median = _pivot("pb_median", align_to_output=False)
        if "industry_pb_percentile_3y_median" in requested_factors:
            factor_dfs["industry_pb_percentile_3y_median"] = _rolling_percentile(
                pb_median, _INDUSTRY_PB_PERCENTILE_WINDOW_3Y
            )
        if "industry_pb_percentile_median" in requested_factors:
            factor_dfs["industry_pb_percentile_median"] = _rolling_percentile(
                pb_median, _INDUSTRY_PB_PERCENTILE_WINDOW_5Y
            )
    if want_profit_mcap:
        factor_dfs["industry_profit_yoy_mcap"] = _pivot("profit_improvement_mcap")
    if want_profit_median:
        factor_dfs["industry_profit_yoy_median"] = _pivot("profit_improvement_median")

    full_name_map = get_factor_catalog()["factor_name_map"]
    factor_name_map = {
        ch_name: eng_name
        for ch_name, eng_name in full_name_map.items()
        if eng_name in factor_dfs
    }

    return {
        "factor_dfs": factor_dfs,
        "factor_name_map": factor_name_map,
    }


def get_factor_lookback_config() -> dict[str, Any]:
    """返回主脚本自动规划所需的回看窗口。"""
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": max(_DEFAULT_LOOKBACK_DAYS, max(FACTOR_LOOKBACK_DAYS.values(), default=0)),
        "factor_lookback_days": dict(FACTOR_LOOKBACK_DAYS),
    }
