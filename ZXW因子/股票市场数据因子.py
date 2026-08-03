"""股票日频总市值、流通市值和换手率因子。"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


BUNDLE_ID = "stock_market_data"
DEFAULT_TURNOVER_GLOB = (
    r"D:\database\qmt_turnover_data\year=*\month=*\merged.parquet"
)
FACTOR_NAME_MAP = {
    "总市值": "total_market_value",
    "流通市值": "floating_market_value",
    "自由流通市值": "free_float_market_value",
    "换手率": "turnover_rate",
    "ln_自由流通市值": "ln_free_float_market_value",
}
SOURCE_COLUMN_MAP = {
    "total_market_value": "total_market_val",
    "floating_market_value": "floating_market_val",
    "free_float_market_value": "free_float_market_val",
    "turnover_rate": "turnover_rate",
    "ln_free_float_market_value": "free_float_market_val",
}


def get_factor_catalog() -> dict[str, dict[str, str]]:
    """返回主生成器自动规划使用的因子目录。"""
    return {"factor_name_map": dict(FACTOR_NAME_MAP)}


def get_factor_lookback_config() -> dict[str, object]:
    """三个字段均为当日值，不需要额外回看窗口。"""
    return {
        "bundle_id": BUNDLE_ID,
        "bundle_lookback_days": 0,
        "factor_lookback_days": {
            factor_key: 0 for factor_key in SOURCE_COLUMN_MAP
        },
    }


def _normalize_code(value: object) -> str:
    return str(value or "").strip().upper()


def _validate_source_columns(
    con: duckdb.DuckDBPyConnection,
    source: str | list[str],
) -> None:
    available = {
        str(row[0])
        for row in con.execute(
            "DESCRIBE SELECT * FROM read_parquet(?, union_by_name=true)",
            [source],
        ).fetchall()
    }
    required = ["htsc_code", "time", *SOURCE_COLUMN_MAP.values()]
    missing = [column for column in required if column not in available]
    if missing:
        raise ValueError(
            "qmt_turnover_data 缺少字段: "
            f"{', '.join(missing)}；请先按新口径重建源数据"
        )


def _resolve_source_paths(
    source_glob: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> tuple[list[str], str]:
    """将标准年月通配符收窄为查询区间内的 merged 文件。"""
    normalized = str(source_glob).replace("\\", "/")
    marker = "/year=*/month=*/merged.parquet"
    if not normalized.endswith(marker):
        return [str(source_glob)], str(source_glob)

    root = Path(normalized[: -len(marker)])
    partition_paths: list[tuple[tuple[int, int], Path]] = []
    for path in root.glob("year=*/month=*/merged.parquet"):
        try:
            year = int(path.parent.parent.name.split("=", 1)[1])
            month = int(path.parent.name.split("=", 1)[1])
        except (IndexError, ValueError):
            continue
        partition_paths.append(((year, month), path))
    if not partition_paths:
        return [str(source_glob)], str(source_glob)

    start_key = (int(pd.Timestamp(start_date).year), int(pd.Timestamp(start_date).month))
    end_key = (int(pd.Timestamp(end_date).year), int(pd.Timestamp(end_date).month))
    query_paths = [
        str(path)
        for key, path in sorted(partition_paths)
        if start_key <= key <= end_key
    ]
    latest_path = str(max(partition_paths, key=lambda item: item[0])[1])
    return query_paths, latest_path


def build_stock_market_data_factor_bundle(
    C: pd.DataFrame,
    *,
    stock_codes: set[str] | list[str] | tuple[str, ...],
    source_glob: str = DEFAULT_TURNOVER_GLOB,
) -> dict[str, object]:
    """读取日频源字段并对齐为当前计算批次的股票矩阵。"""
    index = pd.DatetimeIndex(pd.to_datetime(C.index)).floor("D")
    market_codes = {_normalize_code(code) for code in C.columns}
    target_codes = sorted(
        market_codes
        & {_normalize_code(code) for code in stock_codes if _normalize_code(code)}
    )
    factor_dfs = {
        factor_key: pd.DataFrame(index=index, columns=target_codes, dtype=float)
        for factor_key in SOURCE_COLUMN_MAP
    }
    if index.empty or not target_codes:
        return {
            "bundle_id": BUNDLE_ID,
            "factor_dfs": factor_dfs,
            "factor_name_map": dict(FACTOR_NAME_MAP),
        }

    query_paths, latest_source_path = _resolve_source_paths(
        source_glob,
        index.min(),
        index.max(),
    )
    if not query_paths:
        raise ValueError(
            "qmt_turnover_data 请求区间没有可读取的年月分区："
            f"{index.min().date()} ~ {index.max().date()}，"
            "停止生成市值和换手率因子以避免空值推进水位"
        )
    placeholders = ", ".join("?" for _ in target_codes)
    query = f"""
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            CAST(time AS DATE) AS time,
            TRY_CAST(total_market_val AS DOUBLE) AS total_market_val,
            TRY_CAST(floating_market_val AS DOUBLE) AS floating_market_val,
            TRY_CAST(free_float_market_val AS DOUBLE) AS free_float_market_val,
            TRY_CAST(turnover_rate AS DOUBLE) AS turnover_rate
        FROM read_parquet(?, union_by_name=true)
        WHERE CAST(time AS DATE) BETWEEN ? AND ?
          AND UPPER(TRIM(CAST(htsc_code AS VARCHAR))) IN ({placeholders})
        ORDER BY time, htsc_code
    """
    with duckdb.connect(database=":memory:") as con:
        query_source = query_paths[0] if len(query_paths) == 1 else query_paths
        _validate_source_columns(con, query_source)
        source_max_date = con.execute(
            """
            SELECT MAX(CAST(time AS DATE))
            FROM read_parquet(?, union_by_name=true)
            """,
            [latest_source_path],
        ).fetchone()[0]
        required_end_date = index.max().date()
        if source_max_date is None or source_max_date < required_end_date:
            source_date_text = str(source_max_date) if source_max_date is not None else "无数据"
            raise ValueError(
                "qmt_turnover_data 尚未更新到 "
                f"{required_end_date}（当前最新 {source_date_text}），"
                "停止生成市值和换手率因子以避免空值推进水位"
            )
        source_dates = {
            pd.Timestamp(row[0])
            for row in con.execute(
                """
                SELECT DISTINCT CAST(time AS DATE) AS time
                FROM read_parquet(?, union_by_name=true)
                WHERE CAST(time AS DATE) BETWEEN ? AND ?
                """,
                [query_source, index.min().date(), index.max().date()],
            ).fetchall()
            if row[0] is not None
        }
        params = [
            query_source,
            index.min().date(),
            index.max().date(),
            *target_codes,
        ]
        source = con.execute(query, params).df()

    source["time"] = pd.to_datetime(source["time"], errors="coerce").dt.floor("D")
    source["htsc_code"] = source["htsc_code"].map(_normalize_code)
    source = source.dropna(subset=["time"]).drop_duplicates(
        subset=["time", "htsc_code"],
        keep="last",
    )
    active_dates = set(
        index[C.reindex(columns=target_codes).notna().any(axis=1)]
    )
    missing_active_dates = sorted(active_dates - source_dates)
    if missing_active_dates:
        preview = "、".join(str(day.date()) for day in missing_active_dates[:5])
        suffix = "..." if len(missing_active_dates) > 5 else ""
        raise ValueError(
            "qmt_turnover_data 缺少有股票行情的交易日："
            f"{preview}{suffix}，停止生成市值和换手率因子以避免空值推进水位"
        )
    for factor_key, source_column in SOURCE_COLUMN_MAP.items():
        wide = source.pivot(
            index="time",
            columns="htsc_code",
            values=source_column,
        )
        values = wide.reindex(index=index, columns=target_codes).astype(float)
        if factor_key == "ln_free_float_market_value":
            values = np.log(values.where(values > 0))
        factor_dfs[factor_key] = values

    return {
        "bundle_id": BUNDLE_ID,
        "factor_dfs": factor_dfs,
        "factor_name_map": dict(FACTOR_NAME_MAP),
    }
