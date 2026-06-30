from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

QMT_COMPANY_ROOT = Path(r"D:\database\qmt_company_data")
QMT_FUNDAMENTAL_VALUATION_DIR = QMT_COMPANY_ROOT / "table=factor_fundamental_valuation"
QMT_INCOME_DIR = QMT_COMPANY_ROOT / "table=Income"
QMT_PERSHARE_INDEX_DIR = QMT_COMPANY_ROOT / "table=PershareIndex"

PE_THRESHOLD = 50.0
PE_MIN_THRESHOLD = 0.0
PB_THRESHOLD = 6.0
ROE_THRESHOLD = 10.0
OPER_REVENUE_YOY_THRESHOLD = 10.0

BUY_COL = "strong_buy_signal"


def _merged_glob(base: Path) -> str:
    return (base / "year=*" / "month=*" / "merged.parquet").as_posix()


def _empty_valuation_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["htsc_code", "time", "pe", "pettm", "pb"])


def _empty_indicator_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "htsc_code",
            "end_date",
            "announce_date",
            "roe",
            "roe_5y_avg",
            "weighted_roe",
            "cut_roe",
            "oper_revenue_yoy",
        ]
    )


def _qmt_fundamental_frame_columns() -> list[str]:
    return [
        "htsc_code",
        "time",
        "income_report_date",
        "income_announce_date",
        "pe_ttm",
        "pb",
        "roe",
        "net_roe",
        "revenue",
    ]


def _normalize_loaded_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for column in columns:
        if column not in out.columns:
            out[column] = pd.NA
    return out[columns]


def _read_q4_income_frame(
    con: duckdb.DuckDBPyConnection,
    path: str,
    placeholders: str,
    params: list[str],
) -> pd.DataFrame:
    return con.execute(
        f"""
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            CAST(report_date AS TIMESTAMP) AS end_date,
            CAST(announce_date AS TIMESTAMP) AS announce_date,
            TRY_CAST(revenue AS DOUBLE) AS revenue
        FROM read_parquet(?, hive_partitioning=1, union_by_name=true)
        WHERE UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN ({placeholders})
          AND strftime(CAST(report_date AS DATE), '%m-%d') = '12-31'
        """,
        [path, *params],
    ).fetchdf()


def _read_q4_roe_frame(
    con: duckdb.DuckDBPyConnection,
    path: str,
    placeholders: str,
    params: list[str],
) -> pd.DataFrame:
    return con.execute(
        f"""
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            CAST(report_date AS TIMESTAMP) AS end_date,
            CAST(announce_date AS TIMESTAMP) AS announce_date,
            TRY_CAST(equity_roe AS DOUBLE) AS equity_roe,
            TRY_CAST(net_roe AS DOUBLE) AS net_roe,
            TRY_CAST(du_return_on_equity AS DOUBLE) AS du_return_on_equity
        FROM read_parquet(?, hive_partitioning=1, union_by_name=true)
        WHERE UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN ({placeholders})
          AND strftime(CAST(report_date AS DATE), '%m-%d') = '12-31'
        """,
        [path, *params],
    ).fetchdf()


def _build_q4_indicator_frame(income_df: pd.DataFrame, roe_df: pd.DataFrame) -> pd.DataFrame:
    if income_df.empty and roe_df.empty:
        return _empty_indicator_frame()

    income = income_df.copy()
    if not income.empty:
        income["htsc_code"] = income["htsc_code"].astype(str).str.strip().str.upper()
        income["end_date"] = pd.to_datetime(income["end_date"], errors="coerce").dt.normalize()
        income["announce_date"] = pd.to_datetime(income["announce_date"], errors="coerce").dt.normalize()
        income["revenue"] = pd.to_numeric(income["revenue"], errors="coerce")
        income = income.dropna(subset=["htsc_code", "end_date", "announce_date"])
        income = (
            income.sort_values(["htsc_code", "end_date", "announce_date"])
            .drop_duplicates(["htsc_code", "end_date"], keep="last")
            .reset_index(drop=True)
        )
        previous = income[["htsc_code", "end_date", "revenue"]].copy()
        previous["end_date"] = previous["end_date"] + pd.DateOffset(years=1)
        previous = previous.rename(columns={"revenue": "previous_revenue"})
        income = income.merge(previous, on=["htsc_code", "end_date"], how="left")
        income["oper_revenue_yoy"] = (
            (income["revenue"] - income["previous_revenue"])
            / income["previous_revenue"].abs()
            * 100.0
        )
    else:
        income = pd.DataFrame(columns=["htsc_code", "end_date", "announce_date", "oper_revenue_yoy"])

    roe = roe_df.copy()
    if not roe.empty:
        roe["htsc_code"] = roe["htsc_code"].astype(str).str.strip().str.upper()
        roe["end_date"] = pd.to_datetime(roe["end_date"], errors="coerce").dt.normalize()
        roe["announce_date"] = pd.to_datetime(roe["announce_date"], errors="coerce").dt.normalize()
        roe["roe"] = pd.to_numeric(roe["equity_roe"], errors="coerce")
        roe["roe"] = roe["roe"].combine_first(pd.to_numeric(roe["net_roe"], errors="coerce"))
        roe["roe"] = roe["roe"].combine_first(pd.to_numeric(roe["du_return_on_equity"], errors="coerce"))
        roe["cut_roe"] = pd.to_numeric(roe["net_roe"], errors="coerce")
        roe = roe.dropna(subset=["htsc_code", "end_date", "announce_date"])
        roe = (
            roe.sort_values(["htsc_code", "end_date", "announce_date"])
            .drop_duplicates(["htsc_code", "end_date"], keep="last")
            .reset_index(drop=True)
        )
        roe["roe_5y_avg"] = (
            roe.groupby("htsc_code")["roe"]
            .transform(lambda s: s.rolling(window=5, min_periods=3).mean())
        )
    else:
        roe = pd.DataFrame(columns=["htsc_code", "end_date", "announce_date", "roe", "roe_5y_avg", "cut_roe"])

    if income.empty:
        indicator = roe[
            ["htsc_code", "end_date", "announce_date", "roe", "roe_5y_avg", "cut_roe"]
        ].copy()
        indicator["oper_revenue_yoy"] = pd.NA
        indicator["weighted_roe"] = pd.NA
        return indicator[
            ["htsc_code", "end_date", "announce_date", "roe", "roe_5y_avg", "weighted_roe", "cut_roe", "oper_revenue_yoy"]
        ].sort_values(["htsc_code", "announce_date", "end_date"]).reset_index(drop=True)

    if roe.empty:
        indicator = income[
            ["htsc_code", "end_date", "announce_date", "oper_revenue_yoy"]
        ].copy()
        indicator["roe"] = pd.NA
        indicator["roe_5y_avg"] = pd.NA
        indicator["weighted_roe"] = pd.NA
        indicator["cut_roe"] = pd.NA
        return indicator[
            ["htsc_code", "end_date", "announce_date", "roe", "roe_5y_avg", "weighted_roe", "cut_roe", "oper_revenue_yoy"]
        ].sort_values(["htsc_code", "announce_date", "end_date"]).reset_index(drop=True)

    indicator = income[["htsc_code", "end_date", "announce_date", "oper_revenue_yoy"]].merge(
        roe[["htsc_code", "end_date", "announce_date", "roe", "roe_5y_avg", "cut_roe"]],
        on=["htsc_code", "end_date"],
        how="outer",
        suffixes=("_income", "_roe"),
    )
    if indicator.empty:
        return _empty_indicator_frame()
    indicator["announce_date"] = indicator["announce_date_income"].combine_first(
        indicator["announce_date_roe"]
    )
    indicator["weighted_roe"] = pd.NA
    return indicator[
        ["htsc_code", "end_date", "announce_date", "roe", "roe_5y_avg", "weighted_roe", "cut_roe", "oper_revenue_yoy"]
    ].sort_values(["htsc_code", "announce_date", "end_date"]).reset_index(drop=True)


def load_base_threshold_frames(
    codes: list[str],
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    normalized_codes = sorted({str(c).strip().upper() for c in codes if str(c).strip()})
    if not normalized_codes:
        return _empty_valuation_frame(), _empty_indicator_frame()

    con = duckdb.connect(database=":memory:")
    placeholders = ", ".join("?" for _ in normalized_codes)
    params = list(normalized_codes)

    qmt_path = _merged_glob(QMT_FUNDAMENTAL_VALUATION_DIR)
    try:
        qmt_df = con.execute(
            f"""
            SELECT *
            FROM read_parquet(?, hive_partitioning=1, union_by_name=true)
            WHERE UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN ({placeholders})
            """,
            [qmt_path, *params],
        ).fetchdf()
        qmt_df["htsc_code"] = qmt_df["htsc_code"].astype(str).str.strip().str.upper()
        qmt_df["time"] = pd.to_datetime(qmt_df["time"], errors="coerce").dt.normalize()
        qmt_df = qmt_df[qmt_df["time"] <= pd.Timestamp(end_date).normalize()]
        qmt_df = _normalize_loaded_columns(qmt_df, _qmt_fundamental_frame_columns())

        valuation_df = qmt_df.rename(columns={"pe_ttm": "pettm"})[
            ["htsc_code", "time", "pettm", "pb"]
        ].copy()
        valuation_df["pe"] = pd.NA
        valuation_df = valuation_df[["htsc_code", "time", "pe", "pettm", "pb"]]

        income_df = _read_q4_income_frame(
            con,
            _merged_glob(QMT_INCOME_DIR),
            placeholders,
            params,
        )
        roe_df = _read_q4_roe_frame(
            con,
            _merged_glob(QMT_PERSHARE_INDEX_DIR),
            placeholders,
            params,
        )
        indicator_df = _build_q4_indicator_frame(income_df, roe_df)
    except Exception:
        return _empty_valuation_frame(), _empty_indicator_frame()

    try:
        valuation_df["htsc_code"] = valuation_df["htsc_code"].astype(str).str.strip().str.upper()
        valuation_df["time"] = pd.to_datetime(valuation_df["time"], errors="coerce").dt.normalize()
        valuation_df = valuation_df[valuation_df["time"] <= pd.Timestamp(end_date).normalize()]
        valuation_df = _normalize_loaded_columns(valuation_df, ["htsc_code", "time", "pe", "pettm", "pb"])
    except Exception:
        valuation_df = _empty_valuation_frame()

    try:
        indicator_df["htsc_code"] = indicator_df["htsc_code"].astype(str).str.strip().str.upper()
        indicator_df["end_date"] = pd.to_datetime(indicator_df["end_date"], errors="coerce").dt.normalize()
        if "announce_date" in indicator_df.columns:
            indicator_df["announce_date"] = pd.to_datetime(
                indicator_df["announce_date"], errors="coerce"
            ).dt.normalize()
        else:
            indicator_df["announce_date"] = pd.NaT
        effective_date = indicator_df["announce_date"].combine_first(indicator_df["end_date"])
        indicator_df = indicator_df[effective_date <= pd.Timestamp(end_date).normalize()]
        indicator_df = _normalize_loaded_columns(
            indicator_df,
            ["htsc_code", "end_date", "announce_date", "roe", "roe_5y_avg", "weighted_roe", "cut_roe", "oper_revenue_yoy"],
        )
    except Exception:
        indicator_df = _empty_indicator_frame()

    return valuation_df, indicator_df


def _coerce_date_column(df: pd.DataFrame, column: str) -> pd.DataFrame:
    out = df.copy()
    out[column] = pd.to_datetime(out[column], errors="coerce").dt.normalize().astype("datetime64[ns]")
    return out.dropna(subset=[column])


def _numeric_column(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(float("nan"), index=df.index, dtype="float64")
    return pd.to_numeric(df[column], errors="coerce")


def _prepare_base_frame(
    valuation_df: pd.DataFrame,
    indicator_df: pd.DataFrame,
) -> pd.DataFrame:
    valuation = valuation_df.copy()
    if valuation.empty:
        return pd.DataFrame(columns=["htsc_code", "time", "pe_filter", "pb_filter", "roe_filter", "oper_revenue_yoy_filter"])
    valuation["htsc_code"] = valuation["htsc_code"].astype(str).str.strip().str.upper()
    valuation = _coerce_date_column(valuation, "time")
    valuation["pe_filter"] = _numeric_column(valuation, "pe").combine_first(
        _numeric_column(valuation, "pettm")
    )
    valuation["pb_filter"] = _numeric_column(valuation, "pb")
    valuation = valuation.sort_values(["htsc_code", "time"])

    indicator = indicator_df.copy()
    if indicator.empty:
        valuation["roe_filter"] = pd.NA
        valuation["oper_revenue_yoy_filter"] = pd.NA
        return valuation[
            ["htsc_code", "time", "pe_filter", "pb_filter", "roe_filter", "oper_revenue_yoy_filter"]
        ]

    indicator["htsc_code"] = indicator["htsc_code"].astype(str).str.strip().str.upper()
    indicator = _coerce_date_column(indicator, "end_date")
    if "announce_date" in indicator.columns:
        indicator["announce_date"] = pd.to_datetime(
            indicator["announce_date"], errors="coerce"
        ).dt.normalize()
    else:
        indicator["announce_date"] = pd.NaT
    effective_source = indicator["announce_date"].copy()
    effective_source = effective_source.where(effective_source.notna(), indicator["end_date"])
    indicator["effective_date"] = pd.to_datetime(
        effective_source,
        errors="coerce",
    ).dt.normalize().astype("datetime64[ns]")
    indicator["roe_filter"] = _numeric_column(indicator, "roe_5y_avg")
    for alt_col in ("roe", "weighted_roe", "cut_roe"):
        if alt_col in indicator.columns:
            indicator["roe_filter"] = indicator["roe_filter"].combine_first(
                _numeric_column(indicator, alt_col)
            )
    indicator["oper_revenue_yoy_filter"] = _numeric_column(indicator, "oper_revenue_yoy")
    indicator = indicator.dropna(subset=["effective_date"]).sort_values(
        ["htsc_code", "effective_date", "end_date"]
    )

    pieces: list[pd.DataFrame] = []
    for code, val_sub in valuation.groupby("htsc_code", sort=False):
        ind_sub = indicator[indicator["htsc_code"] == code]
        if ind_sub.empty:
            tmp = val_sub.copy()
            tmp["roe_filter"] = pd.NA
            tmp["oper_revenue_yoy_filter"] = pd.NA
            pieces.append(tmp)
            continue
        merged = pd.merge_asof(
            val_sub.sort_values("time"),
            ind_sub[
                ["effective_date", "roe_filter", "oper_revenue_yoy_filter"]
            ].sort_values("effective_date"),
            left_on="time",
            right_on="effective_date",
            direction="backward",
        )
        pieces.append(merged)

    if not pieces:
        return pd.DataFrame(columns=["htsc_code", "time", "pe_filter", "pb_filter", "roe_filter", "oper_revenue_yoy_filter"])
    base = pd.concat(pieces, ignore_index=True)
    return base[
        ["htsc_code", "time", "pe_filter", "pb_filter", "roe_filter", "oper_revenue_yoy_filter"]
    ]


def apply_base_threshold_filter(
    bt_df: pd.DataFrame,
    valuation_df: pd.DataFrame,
    indicator_df: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    out = bt_df.copy()
    if BUY_COL not in out.columns:
        out[BUY_COL] = 0.0
    out[BUY_COL] = pd.to_numeric(out[BUY_COL], errors="coerce").fillna(0.0)
    raw_buy_signals = int((out[BUY_COL] >= 1.0).sum())

    out["time"] = (
        pd.to_datetime(out["time"], errors="coerce")
        .dt.normalize()
        .astype("datetime64[ns]")
    )
    out["htsc_code"] = out["htsc_code"].astype(str).str.strip().str.upper()
    base = _prepare_base_frame(valuation_df, indicator_df)
    if base.empty:
        out[BUY_COL] = 0.0
        out["total_buy_signal"] = out[BUY_COL]
        return out, {
            "raw_buy_signals": raw_buy_signals,
            "kept_buy_signals": 0,
            "filtered_buy_signals": raw_buy_signals,
            "matched_base_rows": 0,
        }

    pieces: list[pd.DataFrame] = []
    for code, sub in out.sort_values(["htsc_code", "time"]).groupby("htsc_code", sort=False):
        base_sub = base[base["htsc_code"] == code].sort_values("time")
        if base_sub.empty:
            tmp = sub.copy()
            for col in ("pe_filter", "pb_filter", "roe_filter", "oper_revenue_yoy_filter"):
                tmp[col] = float("nan")
            pieces.append(tmp)
            continue
        merged = pd.merge_asof(
            sub.sort_values("time"),
            base_sub[["time", "pe_filter", "pb_filter", "roe_filter", "oper_revenue_yoy_filter"]],
            on="time",
            direction="backward",
        )
        pieces.append(merged)

    merged_out = pd.concat(pieces, ignore_index=True) if pieces else out
    pe_values = pd.to_numeric(merged_out["pe_filter"], errors="coerce")
    pass_mask = (
        (pe_values > PE_MIN_THRESHOLD)
        & (pe_values < PE_THRESHOLD)
        & (pd.to_numeric(merged_out["pb_filter"], errors="coerce") < PB_THRESHOLD)
        & (pd.to_numeric(merged_out["roe_filter"], errors="coerce") > ROE_THRESHOLD)
        & (
            pd.to_numeric(merged_out["oper_revenue_yoy_filter"], errors="coerce")
            > OPER_REVENUE_YOY_THRESHOLD
        )
    )
    merged_out[BUY_COL] = merged_out[BUY_COL].where(pass_mask, 0.0)
    merged_out["total_buy_signal"] = merged_out[BUY_COL]
    kept_buy_signals = int((merged_out[BUY_COL] >= 1.0).sum())
    stats = {
        "raw_buy_signals": raw_buy_signals,
        "kept_buy_signals": kept_buy_signals,
        "filtered_buy_signals": max(0, raw_buy_signals - kept_buy_signals),
        "matched_base_rows": int(pass_mask.notna().sum()),
        "thresholds": {
            "pe_gt": PE_MIN_THRESHOLD,
            "pe_lt": PE_THRESHOLD,
            "pb_lt": PB_THRESHOLD,
            "roe_gt": ROE_THRESHOLD,
            "oper_revenue_yoy_gt": OPER_REVENUE_YOY_THRESHOLD,
        },
    }
    return merged_out.sort_values(["time", "htsc_code"]).reset_index(drop=True), stats
