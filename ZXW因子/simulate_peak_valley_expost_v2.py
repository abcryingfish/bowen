"""Generate a read-only 300265 ex-post peak/valley comparison report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from peak_valley_expost_annotation_v2 import annotate_peak_valley_ex_post


DEFAULT_DATA_ROOT = Path(r"D:\database\stock_basic_data_daily")
DEFAULT_OUTPUT_DIR = Path("temp") / "peak_valley_v2_300265_v2only"

MANUAL_ANCHORS: dict[str, dict[str, list[str]]] = {
    "peak": {
        "positive": [
            "2012-06-20", "2012-12-10", "2012-12-26", "2013-07-02", "2013-07-04",
            "2013-07-16", "2013-10-21", "2013-11-05", "2014-08-14", "2014-12-16",
            "2015-04-22", "2015-06-02", "2015-07-23", "2016-10-26", "2017-03-06",
            "2017-04-06", "2017-06-20", "2017-07-27", "2018-08-28", "2018-11-05",
            "2019-03-06",
        ],
        "negative": ["2014-04-04", "2015-12-07", "2018-03-01"],
    },
    "valley": {
        "positive": [
            "2012-12-13", "2012-12-31", "2013-10-30", "2013-11-08", "2013-11-21",
            "2014-09-16", "2014-11-04", "2015-10-21", "2015-11-03", "2015-11-18",
            "2016-09-02", "2017-08-11", "2017-11-07", "2018-04-23", "2018-11-26",
        ],
        "negative": [
            "2012-08-14", "2013-09-18", "2014-04-10", "2015-12-14", "2016-08-03",
            "2016-11-14",
        ],
    },
}


def load_stock_frame(code: str, data_root: Path = DEFAULT_DATA_ROOT) -> pd.DataFrame:
    """Read one stock from partitioned parquet without touching production outputs."""

    import duckdb

    pattern = str(data_root / "**" / "*.parquet")
    connection = duckdb.connect(database=":memory:")
    try:
        frame = connection.execute(
            """
            SELECT htsc_code, time, high, low, close
            FROM read_parquet(?, hive_partitioning = true)
            WHERE htsc_code = ?
            ORDER BY time
            """,
            [pattern, code],
        ).df()
    finally:
        connection.close()
    if frame.empty:
        raise ValueError(f"未找到股票行情: {code} ({data_root})")
    return frame


def _prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    if "time" not in frame.columns:
        if isinstance(frame.index, pd.DatetimeIndex):
            frame["time"] = frame.index
        else:
            raise ValueError("行情数据需要 time 列或 DatetimeIndex")
    required = {"high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"行情数据缺少列: {sorted(missing)}")
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce")
    frame = frame.dropna(subset=["time", "high", "low", "close"])
    frame = frame.sort_values("time").drop_duplicates("time", keep="last")
    frame["high"] = pd.to_numeric(frame["high"], errors="coerce")
    frame["low"] = pd.to_numeric(frame["low"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["high", "low", "close"])
    return frame.reset_index(drop=True)


def _score_summary(series: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return {
        "count": int(values.size),
        "nonzero_fraction": float((values > 0).mean()) if len(values) else 0.0,
        "min": float(values.min()) if len(values) else None,
        "max": float(values.max()) if len(values) else None,
        "mean": float(values.mean()) if len(values) else None,
        "quantiles": {str(q): float(values.quantile(q)) for q in (0.5, 0.9, 0.95, 0.99)}
        if len(values) else {},
    }


def _anchor_ranks(
    comparison: pd.DataFrame,
    dates: list[str],
    score_column: str,
) -> list[dict[str, Any]]:
    ranked = comparison[score_column].rank(method="min", ascending=False)
    output = []
    for value in dates:
        date = pd.Timestamp(value)
        matches = comparison.index[comparison["date"] == date]
        if len(matches) == 0:
            output.append({"date": value, "present": False})
            continue
        row = int(matches[0])
        output.append(
            {
                "date": value,
                "present": True,
                "score": float(comparison.at[row, score_column]),
                "rank_desc": int(ranked.iloc[row]),
            }
        )
    return output


def _local_max_hits(comparison: pd.DataFrame, dates: list[str], score_column: str, tolerance: int) -> int:
    values = comparison[score_column]
    hits = 0
    for value in dates:
        date = pd.Timestamp(value)
        locations = np.flatnonzero(comparison["date"].eq(date).to_numpy())
        if len(locations) == 0:
            continue
        row = int(locations[0])
        left = max(0, row - tolerance)
        right = min(len(values), row + tolerance + 1)
        if values.iloc[row] >= values.iloc[left:right].max():
            hits += 1
    return hits


def run_simulation(
    frame: pd.DataFrame,
    anchors: dict[str, dict[str, list[str]]],
    output_dir: Path,
) -> dict[str, Path]:
    frame = _prepare_frame(frame)
    index = pd.DatetimeIndex(frame["time"])
    annotation = annotate_peak_valley_ex_post(
        pd.Series(frame["high"].to_numpy(), index=index),
        pd.Series(frame["low"].to_numpy(), index=index),
        pd.Series(frame["close"].to_numpy(), index=index),
    )
    comparison = pd.DataFrame(
        {
            "date": index,
            **annotation.reset_index(drop=True).to_dict(orient="series"),
        }
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison_path = output_dir / "peak_valley_v2_comparison.csv"
    summary_path = output_dir / "peak_valley_v2_summary.json"
    comparison.to_csv(comparison_path, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")

    summary: dict[str, Any] = {
        "code": str(frame["htsc_code"].dropna().iloc[0]) if "htsc_code" in frame.columns and frame["htsc_code"].notna().any() else None,
        "rows": int(len(comparison)),
        "date_start": index.min().strftime("%Y-%m-%d") if len(index) else None,
        "date_end": index.max().strftime("%Y-%m-%d") if len(index) else None,
        "score_distributions": {
            "peak_strength_ex_post": _score_summary(comparison["peak_strength_ex_post"]),
            "valley_strength_ex_post": _score_summary(comparison["valley_strength_ex_post"]),
        },
        "anchor_ranks": {
            "peak_positive": _anchor_ranks(comparison, anchors.get("peak", {}).get("positive", []), "peak_strength_ex_post"),
            "peak_explicit_negative": _anchor_ranks(comparison, anchors.get("peak", {}).get("negative", []), "peak_strength_ex_post"),
            "valley_positive": _anchor_ranks(comparison, anchors.get("valley", {}).get("positive", []), "valley_strength_ex_post"),
            "valley_explicit_negative": _anchor_ranks(comparison, anchors.get("valley", {}).get("negative", []), "valley_strength_ex_post"),
        },
        "local_max_hits": {
            str(tolerance): {
                "peak_positive": _local_max_hits(comparison, anchors.get("peak", {}).get("positive", []), "peak_strength_ex_post", tolerance),
                "valley_positive": _local_max_hits(comparison, anchors.get("valley", {}).get("positive", []), "valley_strength_ex_post", tolerance),
            }
            for tolerance in (1, 2, 5)
        },
        "confirm_delay": {
            "peak": _score_summary(comparison["peak_confirm_delay"]),
            "valley": _score_summary(comparison["valley_confirm_delay"]),
        },
        "notes": [
            "人工未列出的日期保持未知，不作为负样本。",
            "连续分数为事后标注，含未来信息，不是可预测特征。",
            "本脚本只生成 V2 事后标注，不写入 signal_daily。",
        ],
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"comparison_path": comparison_path, "summary_path": summary_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 300265 波峰波谷事后连续标注模拟报告")
    parser.add_argument("--code", default="300265.SZ")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    frame = load_stock_frame(args.code, args.data_root)
    result = run_simulation(frame, MANUAL_ANCHORS, args.output_dir)
    print(json.dumps({key: str(value) for key, value in result.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
