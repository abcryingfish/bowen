"""构建板块多周期模型的六组因子面板。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import polars as pl


DEFAULT_PANEL_PATH = Path(r"D:\database\sector_peak_valley_ml\panel\panel.parquet")
DEFAULT_MARKET_PATH = Path(r"D:\database\index_data_daily")
DEFAULT_STOCK_PATH = Path(r"D:\database\stock_basic_data_daily")
DEFAULT_ADJ_PATH = Path(r"D:\database\stock_adj_daily\adj_factor_daily")
DEFAULT_SIGNAL_PATH = Path(r"D:\database\signal_daily")
DEFAULT_CONSTITUENT_SNAPSHOT_PATH = Path(
    r"D:\database\sector_information\constituent_snapshots_eligible"
    r"\analysis_date=2026-08-14\part-000.parquet"
)
DEFAULT_CONFIG_PATH = Path(__file__).with_name("sector_factor_groups_v1.json")
DEFAULT_OUTPUT_PATH = Path(r"D:\database\sector_peak_valley_ml\factor_groups_v1")
DEFAULT_REPORT_PATH = Path("outputs/sector_peak_valley_ml/stage_l_factor_groups")

KEYS = ["htsc_code", "time"]
GROUP_IDS = (
    "technical_trend",
    "sideways_volatility",
    "relative_strength",
    "constituent_breadth",
    "leader_diffusion",
    "hot_sentiment",
)

RELATIVE_FEATURES = [
    "rs_vs_all_5d",
    "rs_vs_all_20d",
    "rs_vs_all_60d",
    "rs_vs_family_5d",
    "rs_vs_family_20d",
    "rs_vs_family_60d",
    "strength_pct_all_20d",
    "strength_pct_family_20d",
    "strength_pct_change_5d",
    "residual_strength_20d",
]

BREADTH_FEATURES = [
    "constituent_up_ratio_1d",
    "constituent_down_ratio_1d",
    "constituent_positive_return_ratio_5d",
    "constituent_above_ma20_ratio",
    "constituent_new_high_ratio_20d",
    "constituent_new_low_ratio_20d",
    "constituent_rsi_oversold_ratio",
    "constituent_rsi_overbought_ratio",
    "constituent_valid_count",
    "constituent_coverage",
]

LEADER_FEATURES = [
    "top5_return_contribution_20d",
    "top5_turnover_concentration",
    "constituent_median_return_20d",
    "constituent_return_dispersion_20d",
    "leader_median_return_gap_20d",
    "advance_decline_spread_1d",
    "approx_limit_up_ratio",
    "approx_limit_down_ratio",
    "limit_proxy_coverage",
]

HOT_FEATURES = [
    "popularity_strength_mean",
    "popularity_strength_median",
    "popularity_rank_improvement_per_day",
    "popularity_rank_improvement_1d_mean",
    "popularity_rank_improvement_3d_mean",
    "popularity_rank_improvement_5d_mean",
    "hot_stock_ratio_top100",
    "new_fan_ratio_mean",
    "new_fan_change_mean",
    "old_fan_change_mean",
    "hot_streak_days",
    "sentiment_valid_count",
    "sentiment_coverage",
]


def _glob(base: Path) -> str:
    return str(base / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")


def _factor_glob(base: Path, factor_id: str) -> str:
    return _glob(base / f"factor={factor_id}")


def load_config(config_path: Path) -> dict:
    return json.loads(config_path.read_text(encoding="utf-8"))


def load_base_panel(panel_path: Path) -> pd.DataFrame:
    panel = pd.read_parquet(panel_path)
    required = {"htsc_code", "time", "sector_family"}
    missing = required.difference(panel.columns)
    if missing:
        raise ValueError(f"训练面板缺少字段: {sorted(missing)}")
    panel["htsc_code"] = panel["htsc_code"].astype(str).str.strip().str.upper()
    panel["time"] = pd.to_datetime(panel["time"], errors="coerce").dt.floor("D")
    panel["sector_family"] = panel["sector_family"].astype(str).str.strip()
    if panel.duplicated(KEYS).any():
        raise ValueError("训练面板存在重复主键")
    return panel.sort_values(KEYS).reset_index(drop=True)


def select_existing_group(
    panel: pd.DataFrame, config: dict, group_id: str
) -> pd.DataFrame:
    factors = config["groups"][group_id]["factors"]
    missing = sorted(set(factors).difference(panel.columns))
    if missing:
        raise ValueError(f"{group_id} 缺少因子: {missing}")
    return panel[[*KEYS, "sector_family", *factors]].copy()


def build_relative_strength(panel: pd.DataFrame) -> pd.DataFrame:
    required = {
        "mkt_return_1d",
        "mkt_momentum_5d",
        "mkt_momentum_20d",
        "mkt_momentum_60d",
    }
    missing = required.difference(panel.columns)
    if missing:
        raise ValueError(f"相对强弱缺少基础字段: {sorted(missing)}")
    values = panel[[*KEYS, "sector_family", *sorted(required)]].copy()
    values = values.sort_values(["htsc_code", "time"]).reset_index(drop=True)

    for horizon in (5, 20, 60):
        source = f"mkt_momentum_{horizon}d"
        all_median = values.groupby("time", sort=False)[source].transform("median")
        family_median = values.groupby(["time", "sector_family"], sort=False)[source].transform(
            "median"
        )
        values[f"rs_vs_all_{horizon}d"] = values[source] - all_median
        values[f"rs_vs_family_{horizon}d"] = values[source] - family_median

    values["strength_pct_all_20d"] = values.groupby("time", sort=False)[
        "mkt_momentum_20d"
    ].rank(method="average", pct=True)
    values["strength_pct_family_20d"] = values.groupby(
        ["time", "sector_family"], sort=False
    )["mkt_momentum_20d"].rank(method="average", pct=True)
    values["strength_pct_change_5d"] = values.groupby("htsc_code", sort=False)[
        "strength_pct_all_20d"
    ].diff(5)

    broad = (
        values.groupby("time", sort=True)["mkt_return_1d"]
        .median()
        .rename("broad_return_1d")
        .reset_index()
    )
    broad["broad_return_20d"] = (
        (1.0 + broad["broad_return_1d"]).rolling(20, min_periods=20).apply(np.prod, raw=True)
        - 1.0
    )
    values = values.merge(broad, on="time", how="left", validate="many_to_one")
    pieces = []
    for _, group in values.groupby("htsc_code", sort=False):
        group = group.sort_values("time").copy()
        covariance = group["mkt_return_1d"].rolling(60, min_periods=40).cov(
            group["broad_return_1d"]
        )
        variance = group["broad_return_1d"].rolling(60, min_periods=40).var()
        beta = covariance / variance.replace(0.0, np.nan)
        group["residual_strength_20d"] = (
            group["mkt_momentum_20d"] - beta * group["broad_return_20d"]
        )
        pieces.append(group)
    result = pd.concat(pieces, ignore_index=True)
    return result[[*KEYS, "sector_family", *RELATIVE_FEATURES]].sort_values(KEYS)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_latest_members(snapshot_path: Path, sector_codes: set[str]) -> pd.DataFrame:
    with duckdb.connect() as con:
        members = con.execute(
            """
            SELECT DISTINCT
                UPPER(TRIM(CAST(sector_code AS VARCHAR))) AS sector_code,
                UPPER(TRIM(CAST(stock_code AS VARCHAR))) AS stock_code
            FROM read_parquet(?)
            WHERE eligible = true
            """,
            [str(snapshot_path)],
        ).df()
    members = members[members["sector_code"].isin(sector_codes)].copy()
    if members.empty:
        raise ValueError("最新快照没有匹配训练面板的板块成分")
    if members.duplicated(["sector_code", "stock_code"]).any():
        raise ValueError("最新成分快照存在重复板块-股票映射")
    return members.sort_values(["sector_code", "stock_code"]).reset_index(drop=True)


def _constituent_year_sql() -> str:
    return """
        WITH raw_prices AS (
            SELECT
                UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS stock_code,
                CAST(time AS DATE) AS time,
                MAX(TRY_CAST(close AS DOUBLE)) AS close,
                MAX(TRY_CAST(high AS DOUBLE)) AS high,
                MAX(TRY_CAST(low AS DOUBLE)) AS low,
                MAX(TRY_CAST(value AS DOUBLE)) AS trading_value
            FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
            WHERE CAST(time AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
              AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN (
                  SELECT DISTINCT stock_code FROM members
            )
            GROUP BY 1, 2
        ), adj AS (
            SELECT
                UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS stock_code,
                CAST(time AS DATE) AS time,
                MAX(TRY_CAST(adj_factor AS DOUBLE)) AS adj_factor
            FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
            WHERE CAST(time AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
              AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN (
                  SELECT DISTINCT stock_code FROM members
              )
            GROUP BY 1, 2
        ), raw AS (
            SELECT
                p.stock_code,
                p.time,
                p.close * a.adj_factor AS close,
                p.high * a.adj_factor AS high,
                p.low * a.adj_factor AS low,
                p.trading_value
            FROM raw_prices p
            INNER JOIN adj a USING (stock_code, time)
            WHERE a.adj_factor IS NOT NULL AND a.adj_factor > 0
        ), lagged AS (
            SELECT *,
                close / LAG(close, 1) OVER w - 1.0 AS return_1d,
                close / LAG(close, 5) OVER w - 1.0 AS return_5d,
                close / LAG(close, 20) OVER w - 1.0 AS return_20d,
                close - LAG(close, 1) OVER w AS close_change,
                AVG(close) OVER (PARTITION BY stock_code ORDER BY time ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
                MAX(high) OVER (PARTITION BY stock_code ORDER BY time ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS high20,
                MIN(low) OVER (PARTITION BY stock_code ORDER BY time ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS low20
            FROM raw
            WINDOW w AS (PARTITION BY stock_code ORDER BY time)
        ), indicators AS (
            SELECT *,
                AVG(GREATEST(close_change, 0.0)) OVER rsiw AS avg_gain14,
                AVG(GREATEST(-close_change, 0.0)) OVER rsiw AS avg_loss14
            FROM lagged
            WINDOW rsiw AS (PARTITION BY stock_code ORDER BY time ROWS BETWEEN 13 PRECEDING AND CURRENT ROW)
        ), joined AS (
            SELECT
                m.sector_code AS htsc_code,
                i.*,
                CASE
                    WHEN avg_loss14 = 0 AND avg_gain14 > 0 THEN 100.0
                    WHEN avg_loss14 > 0 THEN 100.0 - 100.0 / (1.0 + avg_gain14 / avg_loss14)
                END AS rsi14,
                CASE
                    WHEN stock_code LIKE '300%' OR stock_code LIKE '301%'
                      OR stock_code LIKE '688%' OR stock_code LIKE '689%' THEN 0.195
                    WHEN stock_code LIKE '%.BJ' THEN 0.295
                    ELSE 0.095
                END AS limit_threshold
            FROM indicators i
            INNER JOIN members m USING (stock_code)
            WHERE i.time BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        ), ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY htsc_code, time
                    ORDER BY return_20d DESC NULLS LAST, stock_code ASC
                ) AS return_rank_desc,
                ROW_NUMBER() OVER (
                    PARTITION BY htsc_code, time
                    ORDER BY trading_value DESC NULLS LAST, stock_code ASC
                ) AS value_rank_desc
            FROM joined
        )
        SELECT
            htsc_code,
            time,
            AVG(CASE WHEN return_1d > 0 THEN 1.0 ELSE 0.0 END) FILTER (WHERE return_1d IS NOT NULL) AS constituent_up_ratio_1d,
            AVG(CASE WHEN return_1d < 0 THEN 1.0 ELSE 0.0 END) FILTER (WHERE return_1d IS NOT NULL) AS constituent_down_ratio_1d,
            AVG(CASE WHEN return_5d > 0 THEN 1.0 ELSE 0.0 END) FILTER (WHERE return_5d IS NOT NULL) AS constituent_positive_return_ratio_5d,
            AVG(CASE WHEN close > ma20 THEN 1.0 ELSE 0.0 END) FILTER (WHERE ma20 IS NOT NULL) AS constituent_above_ma20_ratio,
            AVG(CASE WHEN close >= high20 THEN 1.0 ELSE 0.0 END) FILTER (WHERE high20 IS NOT NULL) AS constituent_new_high_ratio_20d,
            AVG(CASE WHEN close <= low20 THEN 1.0 ELSE 0.0 END) FILTER (WHERE low20 IS NOT NULL) AS constituent_new_low_ratio_20d,
            AVG(CASE WHEN rsi14 < 30 THEN 1.0 ELSE 0.0 END) FILTER (WHERE rsi14 IS NOT NULL) AS constituent_rsi_oversold_ratio,
            AVG(CASE WHEN rsi14 > 70 THEN 1.0 ELSE 0.0 END) FILTER (WHERE rsi14 IS NOT NULL) AS constituent_rsi_overbought_ratio,
            COUNT(return_1d) AS constituent_valid_count,
            COUNT(return_1d) / MAX(mc.member_count)::DOUBLE AS constituent_coverage,
            SUM(CASE WHEN return_rank_desc <= 5 THEN GREATEST(return_20d, 0.0) ELSE 0.0 END)
                / NULLIF(SUM(GREATEST(return_20d, 0.0)), 0.0) AS top5_return_contribution_20d,
            SUM(CASE WHEN value_rank_desc <= 5 THEN trading_value ELSE 0.0 END)
                / NULLIF(SUM(trading_value), 0.0) AS top5_turnover_concentration,
            MEDIAN(return_20d) AS constituent_median_return_20d,
            STDDEV_SAMP(return_20d) AS constituent_return_dispersion_20d,
            AVG(return_20d) FILTER (WHERE return_rank_desc <= 5)
                - MEDIAN(return_20d) AS leader_median_return_gap_20d,
            AVG(CASE WHEN return_1d > 0 THEN 1.0 WHEN return_1d < 0 THEN -1.0 ELSE 0.0 END)
                FILTER (WHERE return_1d IS NOT NULL) AS advance_decline_spread_1d,
            AVG(CASE WHEN return_1d >= limit_threshold AND close >= high * 0.999 THEN 1.0 ELSE 0.0 END)
                FILTER (WHERE return_1d IS NOT NULL) AS approx_limit_up_ratio,
            AVG(CASE WHEN return_1d <= -limit_threshold AND close <= low * 1.001 THEN 1.0 ELSE 0.0 END)
                FILTER (WHERE return_1d IS NOT NULL) AS approx_limit_down_ratio,
            COUNT(return_1d) / MAX(mc.member_count)::DOUBLE AS limit_proxy_coverage
        FROM ranked r
        INNER JOIN member_counts mc ON r.htsc_code = mc.sector_code
        GROUP BY htsc_code, time
        ORDER BY htsc_code, time
    """


def build_constituent_groups(
    panel: pd.DataFrame,
    members: pd.DataFrame,
    stock_path: Path,
    adj_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    min_date = panel["time"].min()
    max_date = panel["time"].max()
    member_counts = (
        members.groupby("sector_code", sort=True)["stock_code"]
        .nunique()
        .rename("member_count")
        .reset_index()
    )
    pieces = []
    with duckdb.connect() as con:
        con.register("members", members)
        con.register("member_counts", member_counts)
        con.execute("PRAGMA threads=4")
        for year in range(min_date.year, max_date.year + 1):
            output_start = max(min_date, pd.Timestamp(year=year, month=1, day=1))
            output_end = min(max_date, pd.Timestamp(year=year, month=12, day=31))
            context_start = output_start - pd.Timedelta(days=180)
            print(f"[成分聚合] {year}: {output_start.date()} ~ {output_end.date()}")
            part = con.execute(
                _constituent_year_sql(),
                [
                    _glob(stock_path),
                    context_start.strftime("%Y-%m-%d"),
                    output_end.strftime("%Y-%m-%d"),
                    _glob(adj_path),
                    context_start.strftime("%Y-%m-%d"),
                    output_end.strftime("%Y-%m-%d"),
                    output_start.strftime("%Y-%m-%d"),
                    output_end.strftime("%Y-%m-%d"),
                ],
            ).df()
            pieces.append(part)
    combined = pd.concat(pieces, ignore_index=True)
    combined["time"] = pd.to_datetime(combined["time"]).dt.floor("D")
    base_keys = panel[[*KEYS, "sector_family"]]
    combined = base_keys.merge(combined, on=KEYS, how="left", validate="one_to_one")
    breadth = combined[[*KEYS, "sector_family", *BREADTH_FEATURES]].copy()
    leader = combined[[*KEYS, "sector_family", *LEADER_FEATURES]].copy()
    return breadth, leader


def _available_hot_factor_ids(signal_path: Path) -> list[str]:
    candidates = [
        "history_rank",
        "new_uid_rate",
        "new_uid_change_rank",
        "old_uid_rate",
        "old_uid_change_rank",
    ]
    return [
        factor_id
        for factor_id in candidates
        if any((signal_path / f"factor={factor_id}").glob("year=*/month=*/merged.parquet"))
    ]


def add_hot_streak(frame: pd.DataFrame) -> pd.DataFrame:
    values = frame.sort_values(["htsc_code", "time"]).copy()
    streaks = np.zeros(len(values), dtype=np.int32)
    for _, positions in values.groupby("htsc_code", sort=False).indices.items():
        current = 0
        for position in positions:
            hot = values.iloc[position]["hot_stock_ratio_top100"]
            current = current + 1 if pd.notna(hot) and hot > 0 else 0
            streaks[position] = current
    values["hot_streak_days"] = streaks
    return values


def popularity_strength_from_rank(ranks: pd.Series) -> pd.Series:
    """把热点排名转换为方向明确的强度：排名 1（最热门）得到最高分。"""

    values = pd.to_numeric(ranks, errors="coerce")
    valid = values.notna()
    result = pd.Series(np.nan, index=values.index, dtype=float)
    count = int(valid.sum())
    if count == 0:
        return result
    if count == 1:
        result.loc[valid] = 1.0
        return result
    ascending_rank = values.loc[valid].rank(method="min", ascending=True)
    result.loc[valid] = (count - ascending_rank) / (count - 1)
    return result


def build_hot_sentiment(
    panel: pd.DataFrame,
    members: pd.DataFrame,
    signal_path: Path,
) -> tuple[pd.DataFrame, list[str]]:
    available = _available_hot_factor_ids(signal_path)
    if "history_rank" not in available:
        raise ValueError("热点舆情组缺少 history_rank")
    selects = []
    params = []
    for factor_id in available:
        selects.append(
            "SELECT UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS stock_code, "
            "CAST(time AS DATE) AS time, TRY_CAST(value AS DOUBLE) AS value, "
            f"'{factor_id}' AS factor_id FROM read_parquet(?, hive_partitioning=true, union_by_name=true)"
        )
        params.append(_factor_glob(signal_path, factor_id))
    union_sql = " UNION ALL ".join(selects)
    member_counts = (
        members.groupby("sector_code")["stock_code"].nunique().rename("member_count").reset_index()
    )
    with duckdb.connect() as con:
        con.register("members", members)
        con.register("member_counts", member_counts)
        hot = con.execute(
            f"""
            WITH raw AS ({union_sql}),
            wide AS (
                SELECT stock_code, time,
                    MAX(value) FILTER (WHERE factor_id='history_rank') AS history_rank,
                    MAX(value) FILTER (WHERE factor_id='new_uid_rate') AS new_uid_rate,
                    MAX(value) FILTER (WHERE factor_id='new_uid_change_rank') AS new_uid_change_rank,
                    MAX(value) FILTER (WHERE factor_id='old_uid_rate') AS old_uid_rate,
                    MAX(value) FILTER (WHERE factor_id='old_uid_change_rank') AS old_uid_change_rank
                FROM raw
                GROUP BY stock_code, time
            ), ranked AS (
                SELECT *,
                    1.0 - PERCENT_RANK() OVER (
                        PARTITION BY time ORDER BY history_rank ASC NULLS LAST
                    ) AS popularity_strength,
                    LAG(history_rank) OVER (PARTITION BY stock_code ORDER BY time) AS prior_rank,
                    LAG(time) OVER (PARTITION BY stock_code ORDER BY time) AS prior_time,
                    LAG(history_rank, 3) OVER (PARTITION BY stock_code ORDER BY time) AS prior_rank_3,
                    LAG(time, 3) OVER (PARTITION BY stock_code ORDER BY time) AS prior_time_3,
                    LAG(history_rank, 5) OVER (PARTITION BY stock_code ORDER BY time) AS prior_rank_5,
                    LAG(time, 5) OVER (PARTITION BY stock_code ORDER BY time) AS prior_time_5
                FROM wide
            ), joined AS (
                SELECT m.sector_code AS htsc_code, r.*
                FROM ranked r
                INNER JOIN members m USING (stock_code)
            )
            SELECT
                htsc_code,
                time,
                AVG(popularity_strength) FILTER (WHERE history_rank IS NOT NULL) AS popularity_strength_mean,
                MEDIAN(popularity_strength) FILTER (WHERE history_rank IS NOT NULL) AS popularity_strength_median,
                AVG((prior_rank-history_rank) / NULLIF(DATE_DIFF('day', prior_time, time), 0))
                    FILTER (WHERE prior_time IS NOT NULL AND DATE_DIFF('day', prior_time, time) BETWEEN 1 AND 10)
                    AS popularity_rank_improvement_per_day,
                AVG(prior_rank-history_rank)
                    FILTER (WHERE prior_time IS NOT NULL AND DATE_DIFF('day', prior_time, time) BETWEEN 1 AND 5)
                    AS popularity_rank_improvement_1d_mean,
                AVG(prior_rank_3-history_rank)
                    FILTER (WHERE prior_time_3 IS NOT NULL AND DATE_DIFF('day', prior_time_3, time) BETWEEN 1 AND 10)
                    AS popularity_rank_improvement_3d_mean,
                AVG(prior_rank_5-history_rank)
                    FILTER (WHERE prior_time_5 IS NOT NULL AND DATE_DIFF('day', prior_time_5, time) BETWEEN 1 AND 15)
                    AS popularity_rank_improvement_5d_mean,
                AVG(CASE WHEN history_rank <= 100 THEN 1.0 ELSE 0.0 END)
                    FILTER (WHERE history_rank IS NOT NULL) AS hot_stock_ratio_top100,
                AVG(new_uid_rate) AS new_fan_ratio_mean,
                AVG(new_uid_change_rank) AS new_fan_change_mean,
                AVG(old_uid_change_rank) AS old_fan_change_mean,
                COUNT(history_rank) AS sentiment_valid_count,
                COUNT(history_rank) / MAX(mc.member_count)::DOUBLE AS sentiment_coverage
            FROM joined j
            INNER JOIN member_counts mc ON j.htsc_code=mc.sector_code
            GROUP BY htsc_code, time
            ORDER BY htsc_code, time
            """,
            params,
        ).df()
    hot["time"] = pd.to_datetime(hot["time"]).dt.floor("D")
    hot = add_hot_streak(hot)
    result = panel[[*KEYS, "sector_family"]].merge(
        hot, on=KEYS, how="left", validate="one_to_one"
    )
    return result[[*KEYS, "sector_family", *HOT_FEATURES]], available


def validate_group(frame: pd.DataFrame, group_id: str, feature_names: list[str]) -> dict:
    if frame.duplicated(KEYS).any():
        raise ValueError(f"{group_id} 存在重复主键")
    missing = sorted(set(feature_names).difference(frame.columns))
    if missing:
        raise ValueError(f"{group_id} 缺少输出字段: {missing}")
    numeric = frame[feature_names].replace([np.inf, -np.inf], np.nan)
    valid = numeric.notna().any(axis=1)
    return {
        "group_id": group_id,
        "rows": int(len(frame)),
        "features": len(feature_names),
        "valid_rows": int(valid.sum()),
        "coverage": float(valid.mean()),
        "min_valid_date": frame.loc[valid, "time"].min().strftime("%Y-%m-%d") if valid.any() else None,
        "max_valid_date": frame.loc[valid, "time"].max().strftime("%Y-%m-%d") if valid.any() else None,
    }


def write_group(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.from_pandas(frame, include_index=False).write_parquet(path, compression="zstd")


def build_all_groups(
    *,
    panel_path: Path = DEFAULT_PANEL_PATH,
    stock_path: Path = DEFAULT_STOCK_PATH,
    adj_path: Path = DEFAULT_ADJ_PATH,
    signal_path: Path = DEFAULT_SIGNAL_PATH,
    constituent_snapshot_path: Path = DEFAULT_CONSTITUENT_SNAPSHOT_PATH,
    config_path: Path = DEFAULT_CONFIG_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> dict:
    panel = load_base_panel(panel_path)
    config = load_config(config_path)
    if not constituent_snapshot_path.is_file():
        raise FileNotFoundError(f"固定成分快照不存在: {constituent_snapshot_path}")
    snapshot = constituent_snapshot_path
    members = load_latest_members(snapshot, set(panel["htsc_code"]))

    technical = select_existing_group(panel, config, "technical_trend")
    sideways = select_existing_group(panel, config, "sideways_volatility")
    relative = build_relative_strength(panel)
    breadth, leader = build_constituent_groups(panel, members, stock_path, adj_path)
    hot, available_hot_factors = build_hot_sentiment(panel, members, signal_path)

    groups = {
        "technical_trend": (technical, config["groups"]["technical_trend"]["factors"]),
        "sideways_volatility": (sideways, config["groups"]["sideways_volatility"]["factors"]),
        "relative_strength": (relative, RELATIVE_FEATURES),
        "constituent_breadth": (breadth, BREADTH_FEATURES),
        "leader_diffusion": (leader, LEADER_FEATURES),
        "hot_sentiment": (hot, HOT_FEATURES),
    }
    audits = []
    output_hashes = {}
    for group_id, (frame, features) in groups.items():
        audits.append(validate_group(frame, group_id, features))
        group_path = output_path / f"{group_id}.parquet"
        write_group(frame, group_path)
        output_hashes[group_id] = sha256_file(group_path)

    report = {
        "version": "v2_rank_change_audit_inputs",
        "panel_rows": int(len(panel)),
        "panel_start": panel["time"].min().strftime("%Y-%m-%d"),
        "panel_end": panel["time"].max().strftime("%Y-%m-%d"),
        "constituent_snapshot": str(snapshot),
        "constituent_snapshot_sha256": sha256_file(snapshot),
        "config_path": str(config_path),
        "config_sha256": sha256_file(config_path),
        "constituent_policy": "latest_snapshot_backfilled_to_all_history_by_user_request",
        "constituent_memberships": int(len(members)),
        "matched_sectors": int(members["sector_code"].nunique()),
        "limit_ratio_method": "approximate_close_at_limit_proxy_without_historical_st_or_ipo_rules",
        "hot_rank_policy": "history_rank=1 is most popular; popularity_strength is reversed ascending percentile so lower rank receives higher strength",
        "hot_rank_change_policy": "short-term stock rank movement aggregated by sector; prior_rank - current_rank is positive when popularity improves, using 1/3/5 prior sentiment observations",
        "constituent_price_adjustment": "raw_ohlc_multiplied_by_adj_factor_daily",
        "available_hot_factor_ids": available_hot_factors,
        "hot_model_split_policy": "chronological_first_half_train_second_half_test",
        "groups": audits,
        "output_sha256": output_hashes,
    }
    report_path.mkdir(parents=True, exist_ok=True)
    (report_path / "factor_group_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(audits).to_csv(
        report_path / "factor_group_coverage.csv", index=False, encoding="utf-8-sig"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="构建板块六组因子面板")
    parser.add_argument("--panel-path", type=Path, default=DEFAULT_PANEL_PATH)
    parser.add_argument("--stock-path", type=Path, default=DEFAULT_STOCK_PATH)
    parser.add_argument("--adj-path", type=Path, default=DEFAULT_ADJ_PATH)
    parser.add_argument("--signal-path", type=Path, default=DEFAULT_SIGNAL_PATH)
    parser.add_argument(
        "--constituent-snapshot-path",
        type=Path,
        default=DEFAULT_CONSTITUENT_SNAPSHOT_PATH,
    )
    parser.add_argument("--config-path", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    build_all_groups(**vars(args))


if __name__ == "__main__":
    main()
