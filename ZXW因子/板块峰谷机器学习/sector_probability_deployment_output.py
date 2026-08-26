"""整理五类走势概率的部署读取文件。

只读取已生成的概率文件，不读取V2标签、不训练模型、不调整参数。
输出全历史副本、最新交易日快照和字段说明，供前端或策略层直接读取。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl


DEFAULT_INPUT = Path(
    "outputs/sector_peak_valley_ml/stage_ap_state_probabilities_5class/"
    "sector_state_probabilities.parquet"
)
DEFAULT_OUTPUT = Path("outputs/sector_peak_valley_ml/stage_ar_deployment_probabilities_5class")
KEYS = ["htsc_code", "time", "sector_family"]
HORIZONS = ("ultra_short", "5d", "20d", "consensus")
STATE_CODES = ("valley_bullish", "peak_bearish", "two_sided_high_volatility", "sideways_bullish", "sideways_bearish")
DIRECTION_CODES = ("bullish", "bearish", "high_volatility")
BINARY_DIRECTION_CODES = ("up", "down")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probability_columns(horizon: str) -> list[str]:
    return [f"prob_{horizon}_{state}" for state in STATE_CODES]


def direction_probability_columns(horizon: str) -> list[str]:
    return [f"prob_{horizon}_{direction}" for direction in DIRECTION_CODES]


def binary_direction_probability_columns(horizon: str) -> list[str]:
    return [f"prob_{horizon}_{direction}" for direction in BINARY_DIRECTION_CODES]


def validate_probability_frame(frame: pd.DataFrame) -> dict[str, object]:
    missing = set(KEYS)
    for horizon in HORIZONS:
        missing.update(probability_columns(horizon))
        missing.update(direction_probability_columns(horizon))
    missing = missing.difference(frame.columns)
    if missing:
        raise ValueError(f"概率文件缺少字段: {sorted(missing)}")
    if frame[KEYS].isna().any().any() or frame.duplicated(KEYS).any():
        raise ValueError("概率文件主键为空或重复")
    sums = {}
    for horizon in HORIZONS:
        values = frame[probability_columns(horizon)].apply(pd.to_numeric, errors="coerce")
        if values.isna().any().any() or not np.isfinite(values.to_numpy()).all():
            raise ValueError(f"{horizon}概率包含空值或非有限值")
        if (values.to_numpy() < -1e-12).any() or (values.to_numpy() > 1.0 + 1e-12).any():
            raise ValueError(f"{horizon}概率超出[0,1]")
        error = (values.sum(axis=1) - 1.0).abs()
        sums[horizon] = {"max_abs_error": float(error.max()), "rows": int(len(values))}
        if float(error.max()) > 1e-8:
            raise ValueError(f"{horizon}概率未归一化，最大误差={float(error.max())}")
        direction_values = frame[direction_probability_columns(horizon)].apply(
            pd.to_numeric, errors="coerce"
        )
        if direction_values.isna().any().any() or not np.isfinite(direction_values.to_numpy()).all():
            raise ValueError(f"{horizon}方向概率包含空值或非有限值")
        if (direction_values.to_numpy() < -1e-12).any() or (
            direction_values.to_numpy() > 1.0 + 1e-12
        ).any():
            raise ValueError(f"{horizon}方向概率超出[0,1]")
        direction_error = (direction_values.sum(axis=1) - 1.0).abs()
        sums[horizon]["direction_max_abs_error"] = float(direction_error.max())
        if float(direction_error.max()) > 1e-8:
            raise ValueError(
                f"{horizon}方向概率未归一化，最大误差={float(direction_error.max())}"
            )
        binary_values = frame[binary_direction_probability_columns(horizon)].apply(
            pd.to_numeric, errors="coerce"
        )
        if binary_values.isna().any().any() or not np.isfinite(binary_values.to_numpy()).all():
            raise ValueError(f"{horizon}二元方向概率包含空值或非有限值")
        if (binary_values.to_numpy() < -1e-12).any() or (
            binary_values.to_numpy() > 1.0 + 1e-12
        ).any():
            raise ValueError(f"{horizon}二元方向概率超出[0,1]")
        binary_error = (binary_values.sum(axis=1) - 1.0).abs()
        sums[horizon]["binary_direction_max_abs_error"] = float(binary_error.max())
        if float(binary_error.max()) > 1e-8:
            raise ValueError(
                f"{horizon}二元方向概率未归一化，最大误差={float(binary_error.max())}"
            )
    return sums


def build_deployment_output(input_path: Path = DEFAULT_INPUT, output_path: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    frame = pd.read_parquet(input_path)
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    if frame["time"].isna().any():
        raise ValueError("概率文件包含无法解析的时间")
    validation = validate_probability_frame(frame)
    frame = frame.sort_values(["time", "htsc_code"]).reset_index(drop=True)
    latest_time = pd.Timestamp(frame["time"].max())
    latest = frame.loc[frame["time"].eq(latest_time)].copy()
    output_path.mkdir(parents=True, exist_ok=True)
    history_path = output_path / "sector_probability_history.parquet"
    latest_path = output_path / "sector_probability_latest.parquet"
    latest_date_path = output_path / f"sector_probability_{latest_time:%Y%m%d}.parquet"
    latest_csv_path = output_path / "sector_probability_latest.csv"
    for path, data in ((history_path, frame), (latest_path, latest), (latest_date_path, latest)):
        pl.from_pandas(data, include_index=False).write_parquet(path, compression="zstd")
    latest.to_csv(latest_csv_path, index=False, encoding="utf-8-sig")
    field_description = {
        "prob_<horizon>_<state>": "对应周期和走势状态的校准概率，五类之和为1",
        "prob_<horizon>_bullish": "看涨汇总概率=波谷看涨+横盘看涨",
        "prob_<horizon>_bearish": "看跌汇总概率=波峰看跌+横盘看跌",
        "prob_<horizon>_high_volatility": "双向高波概率",
        "prob_<horizon>_up/down": "二元方向展示概率；up=bullish+0.5*high_volatility，down=bearish+0.5*high_volatility",
        "prob_consensus_<state>": "独立校准的共识概率，建议作为最终展示概率",
        "prob_consensus_bullish/bearish/high_volatility": "共识口径下的看涨/看跌/双向高波汇总概率，三者之和为1",
        "prob_consensus_weighted_<state>": "三个周期概率按0.5/0.3/0.2直接加权的未校准参考值",
        "max_probability_<horizon>": "该周期五类概率中的最大值",
        "most_likely_state_<horizon>": "最大概率对应的状态，仅作辅助显示，不替代概率列",
    }
    (output_path / "field_description.json").write_text(
        json.dumps(field_description, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    files = {
        "history": history_path,
        "latest": latest_path,
        "latest_date": latest_date_path,
        "latest_csv": latest_csv_path,
        "field_description": output_path / "field_description.json",
    }
    manifest = {
        "version": "v2_five_state_deployment_snapshot",
        "input": str(input_path),
        "input_sha256": sha256_file(input_path),
        "history_rows": int(len(frame)),
        "latest_time": latest_time.strftime("%Y-%m-%d"),
        "latest_rows": int(len(latest)),
        "files": {name: str(path) for name, path in files.items()},
        "file_sha256": {name: sha256_file(path) for name, path in files.items()},
        "probability_validation": validation,
        "label_input": None,
        "training_or_tuning": False,
    }
    (output_path / "deployment_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="生成板块走势概率部署快照")
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT)
    build_deployment_output(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
