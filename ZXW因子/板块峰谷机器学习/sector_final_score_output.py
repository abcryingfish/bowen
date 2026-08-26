"""生成五组组合的最终连续V2预测分与方向分。

输出保留原始波峰/波谷预测分，并按交易日横截面生成百分位排名。
方向分定义为：波谷预测排名 - 波峰预测排名；不在本阶段强行切成五类，
避免用人为阈值丢失连续信息。
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
    "outputs/sector_peak_valley_ml/stage_ab_core_group_blend_oof_selected/core_blend_test_predictions.parquet"
)
DEFAULT_OUTPUT = Path("outputs/sector_peak_valley_ml/stage_ac_final_scores_oof_selected")
KEYS = ["htsc_code", "time", "sector_family"]
HORIZONS = {"ultra_short": "ultra_short", "5d": "5d", "20d": "20d"}
TARGETS = tuple(
    f"delta_{side}_{horizon}"
    for horizon in HORIZONS.values()
    for side in ("peak", "valley")
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_final_scores(input_path: Path, output_path: Path) -> dict[str, object]:
    frame = pd.read_parquet(input_path)
    missing = set(KEYS).difference(frame.columns)
    missing.update(f"pred_{target}" for target in TARGETS if f"pred_{target}" not in frame)
    if missing:
        raise ValueError(f"组合预测文件缺少字段: {sorted(missing)}")
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    if frame[KEYS].isna().any().any() or frame.duplicated(KEYS).any():
        raise ValueError("组合预测文件主键为空或重复")
    result = frame[KEYS].copy()
    for target in TARGETS:
        prediction = f"pred_{target}"
        result[prediction] = pd.to_numeric(frame[prediction], errors="coerce")

    for horizon in HORIZONS.values():
        peak = f"pred_delta_peak_{horizon}"
        valley = f"pred_delta_valley_{horizon}"
        peak_rank = f"peak_rank_{horizon}"
        valley_rank = f"valley_rank_{horizon}"
        direction = f"direction_score_{horizon}"
        result[peak_rank] = result[peak].groupby(result["time"]).rank(
            method="average", pct=True
        )
        result[valley_rank] = result[valley].groupby(result["time"]).rank(
            method="average", pct=True
        )
        result[direction] = result[valley_rank] - result[peak_rank]

    output_path.mkdir(parents=True, exist_ok=True)
    output_file = output_path / "sector_final_scores.parquet"
    pl.from_pandas(result, include_index=False).write_parquet(output_file, compression="zstd")
    manifest = {
        "version": "v3_oof_selected",
        "input": str(input_path),
        "input_sha256": sha256_file(input_path),
        "output": str(output_file),
        "output_sha256": sha256_file(output_file),
        "rows": int(len(result)),
        "date_start": result["time"].min().strftime("%Y-%m-%d"),
        "date_end": result["time"].max().strftime("%Y-%m-%d"),
        "targets": list(TARGETS),
        "direction_formula": "valley_rank - peak_rank",
        "five_class_label": "not assigned in this stage",
    }
    (output_path / "final_score_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="生成板块峰谷最终连续预测分")
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build_final_scores(args.input_path, args.output_path)


if __name__ == "__main__":
    main()
