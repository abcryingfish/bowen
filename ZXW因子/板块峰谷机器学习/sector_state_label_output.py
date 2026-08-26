"""将最终V2预测排名转换为五类板块状态标签。

五类定义（按每日横截面排名中位数0.5划分）：
1. 波谷看涨：波峰排名低、波谷排名高；
2. 波峰看跌：波峰排名高、波谷排名低；
3. 双向高波：波峰和波谷排名都高；
4. 横盘看涨：波峰和波谷排名都低，且波谷排名高于波峰排名；
5. 横盘看跌：波峰和波谷排名都低，且波峰排名高于或等于波谷排名。

这里的高低表示未来V2峰谷强度变化的横截面相对排名，不是直接收益涨跌。

标签只使用当前预测分的横截面排名，不读取未来V2标签或收益。
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
    "outputs/sector_peak_valley_ml/stage_ac_final_scores_oof_selected/sector_final_scores.parquet"
)
DEFAULT_OUTPUT = Path("outputs/sector_peak_valley_ml/stage_an_state_labels_5class")
KEYS = ["htsc_code", "time", "sector_family"]
HORIZONS = ("ultra_short", "5d", "20d")
STATE_NAMES = ("波谷看涨", "波峰看跌", "双向高波", "横盘看涨", "横盘看跌")
STATE_CODE = {name: index for index, name in enumerate(STATE_NAMES, 1)}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify_state(peak_rank: pd.Series, valley_rank: pd.Series) -> pd.Series:
    result = pd.Series(pd.NA, index=peak_rank.index, dtype="string")
    valid = peak_rank.notna() & valley_rank.notna()
    result.loc[valid & (peak_rank <= 0.5) & (valley_rank > 0.5)] = "波谷看涨"
    result.loc[valid & (peak_rank > 0.5) & (valley_rank <= 0.5)] = "波峰看跌"
    result.loc[valid & (peak_rank > 0.5) & (valley_rank > 0.5)] = "双向高波"
    result.loc[valid & (peak_rank <= 0.5) & (valley_rank <= 0.5)] = "横盘看跌"
    result.loc[
        valid
        & (peak_rank <= 0.5)
        & (valley_rank <= 0.5)
        & (valley_rank > peak_rank)
    ] = "横盘看涨"
    return result


def weighted_consensus(states: pd.DataFrame, horizons: tuple[str, ...] = HORIZONS) -> pd.Series:
    """按超短/5日/20日=0.5/0.3/0.2计算五类状态的加权多数票。"""
    weights = {"ultra_short": 0.5, "5d": 0.3, "20d": 0.2}
    scores = pd.DataFrame(0.0, index=states.index, columns=STATE_NAMES)
    for horizon in horizons:
        column = f"state_{horizon}"
        if column not in states:
            raise ValueError(f"缺少状态列: {column}")
        for state in STATE_NAMES:
            scores[state] += states[column].eq(state).astype(float) * weights[horizon]
    # 按固定STATE_NAMES顺序打破完全相同的票，保证结果可复现。
    return scores.idxmax(axis=1)


def build_state_labels(input_path: Path, output_path: Path) -> dict[str, object]:
    frame = pd.read_parquet(input_path)
    missing = set(KEYS)
    for horizon in HORIZONS:
        missing.update({f"peak_rank_{horizon}", f"valley_rank_{horizon}"})
    missing = missing.difference(frame.columns)
    if missing:
        raise ValueError(f"最终预测分缺少字段: {sorted(missing)}")
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    if frame[KEYS].isna().any().any() or frame.duplicated(KEYS).any():
        raise ValueError("最终预测分主键为空或重复")
    result = frame[KEYS].copy()
    for horizon in HORIZONS:
        peak = pd.to_numeric(frame[f"peak_rank_{horizon}"], errors="coerce")
        valley = pd.to_numeric(frame[f"valley_rank_{horizon}"], errors="coerce")
        result[f"peak_rank_{horizon}"] = peak
        result[f"valley_rank_{horizon}"] = valley
        result[f"direction_score_{horizon}"] = valley - peak
        result[f"level_score_{horizon}"] = (peak + valley) / 2.0 - 0.5
        result[f"state_{horizon}"] = classify_state(peak, valley)
        # 距离两个中位数决策边界越远，标签越稳定；范围归一到0~1。
        result[f"state_confidence_{horizon}"] = (
            2.0 * pd.concat([(peak - 0.5).abs(), (valley - 0.5).abs()], axis=1).min(axis=1)
        ).clip(0.0, 1.0)
        result[f"state_code_{horizon}"] = result[f"state_{horizon}"].map(STATE_CODE).astype("Int64")
    result["state_consensus"] = weighted_consensus(result)
    result["state_consensus_code"] = result["state_consensus"].map(STATE_CODE).astype("Int64")
    result["state_consensus_agreement"] = sum(
        result[f"state_{horizon}"].eq(result["state_consensus"]).astype(int)
        for horizon in HORIZONS
    ) / len(HORIZONS)

    output_path.mkdir(parents=True, exist_ok=True)
    output_file = output_path / "sector_state_labels.parquet"
    pl.from_pandas(result, include_index=False).write_parquet(output_file, compression="zstd")
    distributions = {
        column: result[column].value_counts(dropna=False).to_dict()
        for column in [*(f"state_{horizon}" for horizon in HORIZONS), "state_consensus"]
    }
    manifest = {
        "version": "v2_five_state",
        "input": str(input_path),
        "input_sha256": sha256_file(input_path),
        "output": str(output_file),
        "output_sha256": sha256_file(output_file),
        "rows": int(len(result)),
        "date_start": result["time"].min().strftime("%Y-%m-%d"),
        "date_end": result["time"].max().strftime("%Y-%m-%d"),
        "state_names": list(STATE_NAMES),
        "threshold": 0.5,
        "consensus_weights": {"ultra_short": 0.5, "5d": 0.3, "20d": 0.2},
        "distributions": distributions,
    }
    (output_path / "state_label_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="生成板块五类峰谷状态标签")
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build_state_labels(args.input_path, args.output_path)


if __name__ == "__main__":
    main()
