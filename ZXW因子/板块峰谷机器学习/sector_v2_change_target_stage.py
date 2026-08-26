"""生成三周期板块 V2 峰谷变化目标。

所有周期都按训练面板的全局交易日历定位未来日期，而不是按某个板块
自身的有效观测条数 ``shift``。这样 ``5d`` 和 ``20d`` 在不同板块缺失
观测时仍然表示同一个全市场交易日窗口；如果目标板块在该交易日没有
标签，则目标保持缺失，不把更晚日期误当成目标日期。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl


DEFAULT_PANEL_PATH = Path(r"D:\database\sector_peak_valley_ml\panel\panel.parquet")
DEFAULT_OUTPUT_PATH = Path(
    r"D:\database\sector_peak_valley_ml\targets_v1\v2_change_targets.parquet"
)
DEFAULT_REPORT_PATH = Path("outputs/sector_peak_valley_ml/stage_m_v2_change_targets")

KEYS = ["htsc_code", "time"]
SOURCE_TARGETS = ("peak_strength_ex_post", "valley_strength_ex_post")
ULTRA_SHORT_WEIGHTS = {1: 0.5, 2: 0.3, 3: 0.2}
HORIZONS = {"ultra_short": (1, 2, 3), "5d": (5,), "20d": (20,)}
GENERATOR_VERSION = "v2_trading_calendar"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_source_labels(panel_path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(panel_path, columns=[*KEYS, *SOURCE_TARGETS])
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    if frame[KEYS].isna().any().any():
        raise ValueError("V2 来源标签主键包含缺失值")
    if frame.duplicated(KEYS).any():
        raise ValueError("V2 来源标签存在重复主键")
    for column in SOURCE_TARGETS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        finite = frame[column].replace([np.inf, -np.inf], np.nan).dropna()
        if ((finite < 0.0) | (finite > 1.0)).any():
            raise ValueError(f"{column} 超出 [0, 1]")
    return frame.sort_values(["htsc_code", "time"]).reset_index(drop=True)


def _future_label_by_trading_calendar(
    values: pd.DataFrame,
    source_column: str,
    horizon_days: int,
    calendar: pd.DatetimeIndex,
) -> pd.Series:
    """按全局交易日历取得每行未来第 ``horizon_days`` 个交易日的标签。

    ``values`` 已按板块和日期排序，但不同板块可能缺少某些全局交易日。
    先将当前日期映射到全局日历，再用 ``(板块, 目标日期)`` 精确回查，
    因而不会因为板块自身缺行而把未来窗口缩短。
    """

    if horizon_days <= 0:
        raise ValueError("未来交易日步数必须为正数")
    if source_column not in values:
        raise ValueError(f"缺少标签字段: {source_column}")

    positions = pd.Series(
        np.arange(len(calendar), dtype=np.int64), index=calendar
    )
    current_positions = values["time"].map(positions)
    future_time = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    valid = current_positions.notna() & (
        current_positions + horizon_days < len(calendar)
    )
    if valid.any():
        target_positions = current_positions.loc[valid].to_numpy(dtype=np.int64)
        future_time.loc[valid] = calendar[target_positions + horizon_days]

    lookup = values.set_index(["htsc_code", "time"])[source_column]
    query_keys = pd.MultiIndex.from_arrays(
        [values["htsc_code"].to_numpy(), future_time.to_numpy()]
    )
    return pd.Series(
        lookup.reindex(query_keys).to_numpy(dtype=float),
        index=values.index,
        name=f"future_{source_column}_{horizon_days}d",
    )


def build_v2_change_targets(source: pd.DataFrame) -> pd.DataFrame:
    required = {*KEYS, *SOURCE_TARGETS}
    missing = required.difference(source.columns)
    if missing:
        raise ValueError(f"V2 来源标签缺少字段: {sorted(missing)}")
    values = source.sort_values(["htsc_code", "time"]).reset_index(drop=True).copy()
    if values.duplicated(KEYS).any():
        raise ValueError("V2 来源标签存在重复主键")

    result = values[KEYS].copy()
    calendar = pd.DatetimeIndex(values["time"].drop_duplicates().sort_values())
    if calendar.empty:
        raise ValueError("V2 来源标签没有可用交易日")
    for side in ("peak", "valley"):
        source_column = f"{side}_strength_ex_post"
        current_column = f"current_{side}_strength"
        result[current_column] = values[source_column]

        ultra_future = pd.Series(0.0, index=values.index, dtype=float)
        for days, weight in ULTRA_SHORT_WEIGHTS.items():
            ultra_future = ultra_future.add(
                weight
                * _future_label_by_trading_calendar(
                    values, source_column, days, calendar
                ),
                fill_value=np.nan,
            )
        result[f"future_{side}_strength_ultra_short"] = ultra_future
        result[f"delta_{side}_ultra_short"] = ultra_future - values[source_column]

        for days in (5, 20):
            future = _future_label_by_trading_calendar(
                values, source_column, days, calendar
            )
            result[f"future_{side}_strength_{days}d"] = future
            result[f"delta_{side}_{days}d"] = future - values[source_column]

    for horizon in HORIZONS:
        peak_future = result[f"future_peak_strength_{horizon}"]
        valley_future = result[f"future_valley_strength_{horizon}"]
        result[f"target_complete_{horizon}"] = peak_future.notna() & valley_future.notna()

    numeric_columns = [
        column
        for column in result.columns
        if column not in KEYS and not column.startswith("target_complete_")
    ]
    result[numeric_columns] = result[numeric_columns].replace([np.inf, -np.inf], np.nan)
    if result.duplicated(KEYS).any():
        raise ValueError("三周期 V2 目标生成后存在重复主键")
    return result.sort_values(["time", "htsc_code"]).reset_index(drop=True)


def target_columns() -> list[str]:
    return [
        f"delta_{side}_{horizon}"
        for horizon in HORIZONS
        for side in ("peak", "valley")
    ]


def audit_targets(targets: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    rows = []
    for column in target_columns():
        series = pd.to_numeric(targets[column], errors="coerce").dropna()
        valid = targets[column].notna()
        rows.append(
            {
                "target": column,
                "valid_rows": int(series.size),
                "coverage": float(series.size / len(targets)),
                "min_date": targets.loc[valid, "time"].min().strftime("%Y-%m-%d"),
                "max_date": targets.loc[valid, "time"].max().strftime("%Y-%m-%d"),
                "mean": float(series.mean()),
                "std": float(series.std()),
                "min": float(series.min()),
                "p01": float(series.quantile(0.01)),
                "p10": float(series.quantile(0.10)),
                "p50": float(series.quantile(0.50)),
                "p90": float(series.quantile(0.90)),
                "p99": float(series.quantile(0.99)),
                "max": float(series.max()),
                "near_zero_rate_abs_le_0_01": float((series.abs() <= 0.01).mean()),
            }
        )
    summary = pd.DataFrame(rows)
    correlations = targets[target_columns()].corr(method="spearman")
    report = {
        "generator_version": GENERATOR_VERSION,
        "rows": int(len(targets)),
        "codes": int(targets["htsc_code"].nunique()),
        "min_date": targets["time"].min().strftime("%Y-%m-%d"),
        "max_date": targets["time"].max().strftime("%Y-%m-%d"),
        "duplicate_keys": int(targets.duplicated(KEYS).sum()),
        "ultra_short_weights": {str(key): value for key, value in ULTRA_SHORT_WEIGHTS.items()},
        "target_formulas": {
            "ultra_short": "0.5*(V2[t+1 trading day]-V2[t]) + 0.3*(V2[t+2 trading days]-V2[t]) + 0.2*(V2[t+3 trading days]-V2[t])",
            "5d": "V2[t+5 global trading days]-V2[t]",
            "20d": "V2[t+20 global trading days]-V2[t]",
        },
        "trading_calendar_policy": "unique sorted dates from the full panel; future labels are looked up by (htsc_code, future_global_trading_date), and missing sector observations remain NaN",
        "target_price_policy": "V2 source uses continuous THS sector-index OHLC; stock constituent features use post-adjusted OHLC",
        "feature_exclusion": "all current/future/delta V2 columns are label-only and forbidden in X",
    }
    return summary, correlations, report


def generate_targets(
    *,
    panel_path: Path = DEFAULT_PANEL_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> dict:
    source = load_source_labels(panel_path)
    targets = build_v2_change_targets(source)
    summary, correlations, report = audit_targets(targets)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pl.from_pandas(targets, include_index=False).write_parquet(output_path, compression="zstd")
    report_path.mkdir(parents=True, exist_ok=True)
    summary.to_csv(report_path / "target_distribution.csv", index=False, encoding="utf-8-sig")
    correlations.to_csv(
        report_path / "target_spearman_correlation.csv", encoding="utf-8-sig"
    )

    report.update(
        {
            "source_panel": str(panel_path),
            "source_panel_sha256": sha256_file(panel_path),
            "output_path": str(output_path),
            "output_sha256": sha256_file(output_path),
            "target_summary": summary.to_dict(orient="records"),
        }
    )
    (report_path / "target_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="生成三周期板块 V2 峰谷变化目标")
    parser.add_argument("--panel-path", type=Path, default=DEFAULT_PANEL_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    generate_targets(**vars(args))


if __name__ == "__main__":
    main()
