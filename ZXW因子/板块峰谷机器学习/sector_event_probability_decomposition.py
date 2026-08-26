"""导出五类峰谷事件及其可加总事件的概率分解。

本脚本只读取已经生成的部署概率，不训练模型，也不读取未来标签。
五类基础事件互斥且合计为 1；派生事件只是这些基础事件的集合，因此
可以逐项看到“一个事件由哪些基础事件组成”。
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
    "outputs/sector_peak_valley_ml/stage_ar_deployment_probabilities_5class/"
    "sector_probability_history.parquet"
)
DEFAULT_OUTPUT = Path(
    "outputs/sector_peak_valley_ml/stage_aw_event_probability_decomposition"
)
KEYS = ["htsc_code", "time", "sector_family"]
HORIZONS = ("ultra_short", "5d", "20d", "consensus")
STATES = (
    ("valley_bullish", "波谷看涨"),
    ("peak_bearish", "波峰看跌"),
    ("two_sided_high_volatility", "双向高波"),
    ("sideways_bullish", "横盘看涨"),
    ("sideways_bearish", "横盘看跌"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prob(frame: pd.DataFrame, horizon: str, state: str) -> pd.Series:
    return pd.to_numeric(frame[f"prob_{horizon}_{state}"], errors="coerce")


def build_decomposition(*, input_path: Path = DEFAULT_INPUT, output_path: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    frame = pd.read_parquet(input_path)
    missing = set(KEYS)
    for horizon in HORIZONS:
        missing.update(f"prob_{horizon}_{state}" for state, _ in STATES)
    missing = missing.difference(frame.columns)
    if missing:
        raise ValueError(f"部署概率缺少字段: {sorted(missing)}")
    frame = frame.copy()
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    if frame[KEYS].isna().any().any() or frame.duplicated(KEYS).any():
        raise ValueError("部署概率主键为空或重复")

    result = frame[KEYS].copy()
    # 每个周期都输出基础五类事件和派生事件；consensus 是最终建议口径。
    for horizon in HORIZONS:
        prefix = f"{horizon}_"
        for state, name in STATES:
            result[f"{prefix}prob_{state}"] = _prob(frame, horizon, state)
            result[f"{prefix}{name}概率"] = result[f"{prefix}prob_{state}"]

        valley = result[f"{prefix}prob_valley_bullish"]
        peak = result[f"{prefix}prob_peak_bearish"]
        high = result[f"{prefix}prob_two_sided_high_volatility"]
        sideways_bull = result[f"{prefix}prob_sideways_bullish"]
        sideways_bear = result[f"{prefix}prob_sideways_bearish"]

        # 派生事件：每一个都明确记录其组成项，避免把汇总概率误认为新模型输出。
        result[f"{prefix}看涨概率"] = valley + sideways_bull
        result[f"{prefix}看跌概率"] = peak + sideways_bear
        result[f"{prefix}横盘概率"] = sideways_bull + sideways_bear
        result[f"{prefix}方向性事件概率"] = valley + peak
        result[f"{prefix}双向高波概率"] = high
        result[f"{prefix}非高波概率"] = 1.0 - high
        result[f"{prefix}看涨_波谷看涨组成"] = valley
        result[f"{prefix}看涨_横盘看涨组成"] = sideways_bull
        result[f"{prefix}看跌_波峰看跌组成"] = peak
        result[f"{prefix}看跌_横盘看跌组成"] = sideways_bear
        result[f"{prefix}横盘_横盘看涨组成"] = sideways_bull
        result[f"{prefix}横盘_横盘看跌组成"] = sideways_bear
        result[f"{prefix}方向性_波谷看涨组成"] = valley
        result[f"{prefix}方向性_波峰看跌组成"] = peak

    result = result.sort_values(["time", "htsc_code"]).reset_index(drop=True)
    output_path.mkdir(parents=True, exist_ok=True)
    parquet_path = output_path / "sector_event_probability_decomposition.parquet"
    latest_path = output_path / "sector_event_probability_decomposition_latest.parquet"
    csv_path = output_path / "sector_event_probability_decomposition_latest.csv"
    # 最终部署口径：只保留三个独立周期的五类事件，共15个概率。
    # consensus 仍保留在完整分解文件中，供研究审计，不进入最终决策输入。
    final_path = output_path / "sector_probability_final_15.parquet"
    final_latest_path = output_path / "sector_probability_final_15_latest.parquet"
    final_csv_path = output_path / "sector_probability_final_15_latest.csv"
    latest = result.loc[result["time"].eq(result["time"].max())].copy()
    for path, data in ((parquet_path, result), (latest_path, latest)):
        pl.from_pandas(data, include_index=False).write_parquet(path, compression="zstd")
    latest.to_csv(csv_path, index=False, encoding="utf-8-sig")
    final_columns = [*KEYS]
    for horizon in ("ultra_short", "5d", "20d"):
        final_columns.extend(
            f"{horizon}_prob_{state}" for state, _ in STATES
        )
    final = result[final_columns].copy()
    final_latest = final.loc[final["time"].eq(final["time"].max())].copy()
    for path, data in ((final_path, final), (final_latest_path, final_latest)):
        pl.from_pandas(data, include_index=False).write_parquet(path, compression="zstd")
    final_latest.to_csv(final_csv_path, index=False, encoding="utf-8-sig")

    # 数值校验：基础五类和应为 1；派生项只允许来自基础项，不能凭空产生概率。
    validation = {}
    for horizon in HORIZONS:
        cols = [f"{horizon}_prob_{state}" for state, _ in STATES]
        error = (result[cols].sum(axis=1) - 1.0).abs()
        validation[horizon] = {
            "rows": int(len(result)),
            "max_base_sum_abs_error": float(error.max()),
            "min_probability": float(result[cols].min().min()),
            "max_probability": float(result[cols].max().max()),
        }
        if validation[horizon]["max_base_sum_abs_error"] > 1e-8:
            raise ValueError(f"{horizon}五类基础概率未归一化")

    field_description = {
        "base_events": {
            "波谷看涨": "基础事件：波峰变化排名低、波谷变化排名高",
            "波峰看跌": "基础事件：波峰变化排名高、波谷变化排名低",
            "双向高波": "基础事件：波峰、波谷变化排名都高",
            "横盘看涨": "基础事件：两者都低，且波谷排名高于波峰排名",
            "横盘看跌": "基础事件：两者都低，且波峰排名高于或等于波谷排名",
        },
        "derived_events": {
            "看涨": "波谷看涨 + 横盘看涨",
            "看跌": "波峰看跌 + 横盘看跌",
            "横盘": "横盘看涨 + 横盘看跌",
            "方向性事件": "波谷看涨 + 波峰看跌",
            "双向高波": "双向高波（基础事件本身）",
            "非高波": "1 - 双向高波",
        },
        "final_deployment": {
            "periods": {
                "ultra_short": "超短：1-3个交易日加权整合",
                "5d": "短期：5个交易日",
                "20d": "中期：20个交易日",
            },
            "event_count": 15,
            "probability_columns": [
                f"{horizon}_prob_{state}"
                for horizon in ("ultra_short", "5d", "20d")
                for state, _ in STATES
            ],
            "row_sum_policy": "每个周期的五类事件概率分别合计为1；三个周期之间不合计为1。",
            "consensus_usage": "不作为最终部署输入，仅保留在完整审计分解文件中。",
        },
        "probability_note": "derived_events 是基础五类概率的集合，不是重新训练的概率模型；consensus 是独立校准的最终共识口径。",
        "factor_contribution_note": "本文件展示事件概率的组成，不把因子组贡献伪装成概率。因子组只能先解释六个连续峰谷分；若需概率层贡献，应另行使用校准器的 SHAP/反事实解释。",
    }
    description_path = output_path / "field_description.json"
    description_path.write_text(json.dumps(field_description, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "version": "v1_event_probability_decomposition",
        "input": str(input_path),
        "input_sha256": sha256_file(input_path),
        "output": str(parquet_path),
        "latest": str(latest_path),
        "latest_csv": str(csv_path),
        "final_15": str(final_path),
        "final_15_latest": str(final_latest_path),
        "final_15_latest_csv": str(final_csv_path),
        "field_description": str(description_path),
        "rows": int(len(result)),
        "latest_time": result["time"].max().strftime("%Y-%m-%d"),
        "validation": validation,
        "base_events": [name for _, name in STATES],
        "derived_events": field_description["derived_events"],
        "output_sha256": {
            "output": sha256_file(parquet_path),
            "latest": sha256_file(latest_path),
            "latest_csv": sha256_file(csv_path),
            "final_15": sha256_file(final_path),
            "final_15_latest": sha256_file(final_latest_path),
            "final_15_latest_csv": sha256_file(final_csv_path),
            "field_description": sha256_file(description_path),
        },
    }
    (output_path / "event_probability_decomposition_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="导出五类事件及其派生事件概率分解")
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT)
    build_decomposition(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
