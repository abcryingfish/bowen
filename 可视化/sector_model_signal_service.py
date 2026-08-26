"""读取板块峰谷模型每日信号，供前端只读展示。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SIGNAL_ROOT = PROJECT_ROOT / "outputs" / "sector_peak_valley_ml" / "stage_ax_daily_signal"
PROBABILITY_PATH = SIGNAL_ROOT / "sector_probability_history_15.parquet"
DIAGNOSTICS_PATH = SIGNAL_ROOT / "sector_signal_diagnostics_history.parquet"
PROBABILITY_PARTITION_ROOT = SIGNAL_ROOT / "sector_probability_history_15"
DIAGNOSTICS_PARTITION_ROOT = SIGNAL_ROOT / "sector_signal_diagnostics_history"

KEYS = ["htsc_code", "time", "sector_family"]
HORIZONS = ("ultra_short", "5d", "20d")
STATES = (
    "valley_bullish",
    "peak_bearish",
    "two_sided_high_volatility",
    "sideways_bullish",
    "sideways_bearish",
)
GROUPS = (
    "technical",
    "sideways_volatility",
    "relative_strength",
    "constituent_breadth",
    "leader_diffusion",
    "market_state_conditioned",
)
TARGETS = tuple(
    f"delta_{side}_{horizon}"
    for horizon in HORIZONS
    for side in ("peak", "valley")
)
SUMMARY_COLUMNS = [
    *KEYS,
    *[
        f"{horizon}_prob_{state}"
        for horizon in HORIZONS
        for state in STATES
    ],
    *[f"{horizon}_most_likely_state" for horizon in HORIZONS],
    *[f"{horizon}_event_strength" for horizon in HORIZONS],
]
HISTORY_COLUMNS = [
    *KEYS,
    *[f"{horizon}_prob_{state}" for horizon in HORIZONS for state in STATES],
    *[f"{horizon}_most_likely_state" for horizon in HORIZONS],
    *[f"{horizon}_event_strength" for horizon in HORIZONS],
    *[f"direction_{horizon}" for horizon in HORIZONS],
    *[f"direction_strength_{horizon}" for horizon in HORIZONS],
    *[f"pred_{target}" for target in TARGETS],
    *[f"peak_rank_{horizon}" for horizon in HORIZONS],
    *[f"valley_rank_{horizon}" for horizon in HORIZONS],
    *[f"level_{horizon}" for horizon in HORIZONS],
]
MODEL_HISTORY_COLUMNS = [
    *KEYS,
    *[f"{horizon}_prob_{state}" for horizon in HORIZONS for state in STATES],
    *[f"{horizon}_most_likely_state" for horizon in HORIZONS],
    *[f"{horizon}_event_strength" for horizon in HORIZONS],
]
_MODEL_HISTORY_FRAME_CACHE: tuple[tuple[tuple[str, int], ...], pd.DataFrame] | None = None


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _json_value(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def _normalise_code(code: str | None) -> str:
    value = str(code or "").strip().upper()
    if not value or not value.endswith(".THS") or value[:3] not in {"881", "882", "885", "886"}:
        raise ValueError("sector_code 必须是 881/882/885/886 开头的 .THS 板块代码")
    return value


def _normalise_date(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError("time 必须是 YYYY-MM-DD 日期")
    return pd.Timestamp(parsed).floor("D")


def _history_files(kind: str) -> list[Path]:
    root = PROBABILITY_PARTITION_ROOT if kind == "probability" else DIAGNOSTICS_PARTITION_ROOT
    files = sorted(root.glob("year=*/month=*/merged.parquet"))
    if files:
        return files
    legacy = PROBABILITY_PATH if kind == "probability" else DIAGNOSTICS_PATH
    return [legacy] if legacy.exists() else []


def _files_for_date(files: list[Path], date_value: pd.Timestamp | None) -> list[Path]:
    if date_value is None:
        return files
    expected = f"year={date_value.year:04d}/month={date_value.month:02d}/merged.parquet"
    matched = [path for path in files if expected.replace("/", "\\") in str(path) or expected in str(path).replace("\\", "/")]
    return matched or files


def _read_frames(files: list[Path], columns: list[str]) -> pd.DataFrame:
    frames = []
    for path in files:
        if not path.exists():
            continue
        frames.append(pd.read_parquet(path, columns=columns))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)


def _read_probability_rows(code: str | None, analysis_date: pd.Timestamp | None) -> pd.DataFrame:
    files = _history_files("probability")
    if not files:
        raise FileNotFoundError(f"每日概率分区不存在: {PROBABILITY_PARTITION_ROOT}")
    # 首页只需要最新月份；指定日期则只读取对应月份，避免扫描全部历史。
    if analysis_date is not None:
        files = _files_for_date(files, analysis_date)
    elif code:
        files = [files[-1]]
    else:
        files = [files[-1]]
    frame = _read_frames(files, SUMMARY_COLUMNS)
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    if code:
        frame = frame.loc[frame["htsc_code"].eq(code)]
    if analysis_date is not None:
        frame = frame.loc[frame["time"].eq(analysis_date)]
    elif code:
        latest = frame["time"].max()
        frame = frame.loc[frame["time"].eq(latest)]
    else:
        latest = frame["time"].max()
        frame = frame.loc[frame["time"].eq(latest)]
    return frame.sort_values(["time", "htsc_code"]).reset_index(drop=True)


def _read_diagnostics_row(code: str, analysis_date: pd.Timestamp | None) -> dict[str, Any] | None:
    files = _history_files("diagnostics")
    if not files:
        return None
    diagnostic_files = _files_for_date(files, analysis_date) if analysis_date is not None else [files[-1]]
    frames = [pd.read_parquet(path) for path in diagnostic_files if path.exists()]
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    frame = frame.loc[frame["htsc_code"].eq(code)]
    if analysis_date is not None:
        frame = frame.loc[frame["time"].eq(analysis_date)]
    else:
        frame = frame.loc[frame["time"].eq(frame["time"].max())]
    if frame.empty:
        return None
    return _records(frame.sort_values("time").tail(1))[0]


def _read_history(code: str, limit: int) -> list[dict[str, Any]]:
    files = _history_files("diagnostics")
    if not files:
        return []
    frame = _read_frames(files, HISTORY_COLUMNS)
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    frame = frame.loc[frame["htsc_code"].eq(code)].sort_values("time")
    return _records(frame.tail(max(1, min(limit, 2000))))


def query_sector_model_signal_history(*, sector_code: str, limit: int = 400) -> dict[str, Any]:
    """读取单个板块的轻量历史周期信号，供图表悬停本地切换。"""
    code = _normalise_code(sector_code)
    files = _history_files("probability")
    if not files:
        raise FileNotFoundError(f"每日概率分区不存在: {PROBABILITY_PARTITION_ROOT}")
    try:
        limit_value = max(1, min(int(limit), 2000))
    except (TypeError, ValueError) as exc:
        raise ValueError("limit 必须是整数") from exc
    global _MODEL_HISTORY_FRAME_CACHE
    signature = tuple((str(path), path.stat().st_mtime_ns) for path in files if path.exists())
    if _MODEL_HISTORY_FRAME_CACHE is None or _MODEL_HISTORY_FRAME_CACHE[0] != signature:
        _MODEL_HISTORY_FRAME_CACHE = (signature, _read_frames(files, MODEL_HISTORY_COLUMNS))
    frame = _MODEL_HISTORY_FRAME_CACHE[1].copy()
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    frame = frame.loc[frame["htsc_code"].eq(code)].sort_values("time")
    if frame.empty:
        raise FileNotFoundError("指定板块没有历史模型信号")
    rows = _records(frame.tail(limit_value))
    return {"data": {"items": rows, "latest_time": rows[-1]["time"]}, "meta": {"count": len(rows), "limit": limit_value}}


def query_sector_model_signals(
    *,
    sector_code: str | None = None,
    prefix: str | None = None,
    analysis_date: str | None = None,
    include_diagnostics: bool = False,
    include_history: bool = False,
    history_limit: int = 120,
) -> dict[str, Any]:
    code = _normalise_code(sector_code) if sector_code else None
    prefix_value = str(prefix or "").strip()
    if prefix_value and prefix_value not in {"881", "882", "885", "886"}:
        raise ValueError("prefix 必须是 881、882、885 或 886")
    parsed_date = _normalise_date(analysis_date)
    try:
        history_limit_value = max(1, min(int(history_limit), 2000))
    except (TypeError, ValueError) as exc:
        raise ValueError("history_limit 必须是整数") from exc
    rows = _read_probability_rows(code, parsed_date)
    if prefix_value:
        rows = rows.loc[rows["htsc_code"].str[:3].eq(prefix_value)]
    if rows.empty:
        raise FileNotFoundError("指定板块或日期没有模型信号")
    items = _records(rows)
    payload: dict[str, Any] = {
        "data": {
            "latest_time": _json_value(rows["time"].max()),
            "items": items,
        },
        "meta": {
            "source": str(PROBABILITY_PARTITION_ROOT if PROBABILITY_PARTITION_ROOT.exists() else PROBABILITY_PATH),
            "event_count": 15,
            "periods": {"ultra_short": "超短1-3交易日", "5d": "短期5交易日", "20d": "中期20交易日"},
            "diagnostics_available": bool(_history_files("diagnostics")),
        },
    }
    if code:
        payload["data"]["diagnostics"] = _read_diagnostics_row(code, parsed_date) if include_diagnostics else None
        if include_history:
            payload["data"]["history"] = _read_history(code, history_limit_value)
    return payload
