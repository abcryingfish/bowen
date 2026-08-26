"""将板块峰谷连续预测分转换为五类走势概率。

概率不是把五类标签硬切出来，而是使用开发期嵌套 OOF 预测训练一个
多分类 Logistic 校准器。测试期只使用校准器和最终模型预测，不读取
测试期 V2 标签。每个周期输出五类概率，并按超短/5日/20日权重生成
共识概率。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import polars as pl
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures


DEFAULT_OOF = Path(
    "outputs/sector_peak_valley_ml/stage_ab_core_group_blend_oof_selected/"
    "core_blend_oof_predictions.parquet"
)
DEFAULT_TEST = Path(
    "outputs/sector_peak_valley_ml/stage_ab_core_group_blend_oof_selected/"
    "core_blend_test_predictions.parquet"
)
DEFAULT_TARGET = Path(r"D:\database\sector_peak_valley_ml\targets_v1\v2_change_targets.parquet")
DEFAULT_SCORE = Path(
    "outputs/sector_peak_valley_ml/stage_ac_final_scores_oof_selected/sector_final_scores.parquet"
)
DEFAULT_OUTPUT = Path("outputs/sector_peak_valley_ml/stage_ap_state_probabilities_5class")
DEFAULT_MODEL_PATH = Path(r"D:\database\sector_peak_valley_ml\models\state_probability_v2_5class")

KEYS = ["htsc_code", "time", "sector_family"]
JOIN_KEYS = ["htsc_code", "time"]
HORIZONS = ("ultra_short", "5d", "20d")
TARGETS = tuple(
    f"delta_{side}_{horizon}"
    for horizon in HORIZONS
    for side in ("peak", "valley")
)
STATE_NAMES = ("波谷看涨", "波峰看跌", "双向高波", "横盘看涨", "横盘看跌")
STATE_CODES = {
    "波谷看涨": "valley_bullish",
    "波峰看跌": "peak_bearish",
    "双向高波": "two_sided_high_volatility",
    "横盘看涨": "sideways_bullish",
    "横盘看跌": "sideways_bearish",
}
CONSENSUS_WEIGHTS = {"ultra_short": 0.5, "5d": 0.3, "20d": 0.2}
TEST_START = pd.Timestamp("2023-01-01")
OOF_YEARS = (2021, 2022)
PURGE_BARS = {"ultra_short": 43, "5d": 45, "20d": 60}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_keys(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["htsc_code"] = result["htsc_code"].astype(str).str.strip().str.upper()
    result["time"] = pd.to_datetime(result["time"], errors="coerce").dt.floor("D")
    if result[JOIN_KEYS].isna().any().any() or result.duplicated(JOIN_KEYS).any():
        raise ValueError("输入数据主键为空或重复")
    return result


def _rank_features(frame: pd.DataFrame, prefix: str = "pred_") -> pd.DataFrame:
    """按交易日把六个连续预测转换为跨板块百分位特征。"""
    result = frame[[*JOIN_KEYS, "sector_family"]].copy()
    for horizon in HORIZONS:
        peak = pd.to_numeric(frame[f"{prefix}delta_peak_{horizon}"], errors="coerce")
        valley = pd.to_numeric(frame[f"{prefix}delta_valley_{horizon}"], errors="coerce")
        peak_rank = peak.groupby(frame["time"]).rank(method="average", pct=True)
        valley_rank = valley.groupby(frame["time"]).rank(method="average", pct=True)
        result[f"peak_rank_{horizon}"] = peak_rank
        result[f"valley_rank_{horizon}"] = valley_rank
        result[f"direction_{horizon}"] = valley_rank - peak_rank
        result[f"level_{horizon}"] = (peak_rank + valley_rank) / 2.0 - 0.5
    return result


def classify_quadrant(peak_rank: pd.Series, valley_rank: pd.Series) -> pd.Series:
    """使用与状态标签层相同的中位数五状态定义。"""
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


def _purged_train_end(dates: pd.DatetimeIndex, boundary: pd.Timestamp, bars: int) -> pd.Timestamp:
    prior = dates[dates < boundary]
    if len(prior) <= bars:
        raise ValueError(f"历史不足以排除{bars}个交易日的标签窗口")
    return pd.Timestamp(prior[-bars - 1])


def _calibration_features(frame: pd.DataFrame, horizon: str) -> pd.DataFrame:
    columns = [
        f"peak_rank_{horizon}",
        f"valley_rank_{horizon}",
        f"direction_{horizon}",
        f"level_{horizon}",
    ]
    return frame[columns].rename(columns=dict(zip(columns, ("peak", "valley", "direction", "level"))))


def _consensus_calibration_features(frame: pd.DataFrame) -> pd.DataFrame:
    columns = []
    renamed = []
    for horizon in HORIZONS:
        columns.extend([
            f"peak_rank_{horizon}",
            f"valley_rank_{horizon}",
            f"direction_{horizon}",
            f"level_{horizon}",
        ])
        renamed.extend([
            f"{horizon}_peak",
            f"{horizon}_valley",
            f"{horizon}_direction",
            f"{horizon}_level",
        ])
    return frame[columns].rename(columns=dict(zip(columns, renamed)))


def _weighted_state_consensus(states: pd.DataFrame) -> pd.Series:
    scores = pd.DataFrame(0.0, index=states.index, columns=STATE_NAMES)
    valid_count = pd.Series(0, index=states.index, dtype="int64")
    for horizon, weight in CONSENSUS_WEIGHTS.items():
        valid_count = valid_count.add(states[horizon].notna().astype(int), fill_value=0)
        for state in STATE_NAMES:
            scores[state] += states[horizon].eq(state).astype(float) * weight
    result = pd.Series(pd.NA, index=states.index, dtype="string")
    valid = valid_count > 0
    result.loc[valid] = np.asarray(STATE_NAMES, dtype=object)[scores.loc[valid].to_numpy().argmax(axis=1)]
    return result


def _fit_calibrator(features: pd.DataFrame, labels: pd.Series) -> Pipeline:
    """低复杂度二次特征 + 多项 Logistic，输出可比较的五类概率。"""
    model = Pipeline(
        [
            ("poly", PolynomialFeatures(degree=2, include_bias=False)),
            (
                "logit",
                LogisticRegression(
                    C=1.0,
                    max_iter=1000,
                    random_state=42,
                ),
            ),
        ]
    )
    model.fit(features, labels)
    return model


def _predict_all_states(model: Pipeline, features: pd.DataFrame) -> pd.DataFrame:
    probabilities = model.predict_proba(features)
    classes = list(model.named_steps["logit"].classes_)
    result = pd.DataFrame(0.0, index=features.index, columns=STATE_NAMES)
    for index, state in enumerate(classes):
        result[state] = probabilities[:, index]
    # 避免浮点误差导致输出行和不等于1。
    result = result.div(result.sum(axis=1).replace(0.0, np.nan), axis=0).fillna(0.0)
    return result


def add_direction_probabilities(
    result: pd.DataFrame,
    *,
    prefix: str,
) -> pd.DataFrame:
    """把五类状态概率汇总为看涨、看跌和双向高波三类概率。"""

    required = [f"{prefix}_{STATE_CODES[state]}" for state in STATE_NAMES]
    missing = sorted(set(required).difference(result.columns))
    if missing:
        raise ValueError(f"无法生成方向概率，缺少字段: {missing}")
    output = result.copy()
    output[f"{prefix}_bullish"] = output[f"{prefix}_{STATE_CODES['波谷看涨']}"] + output[
        f"{prefix}_{STATE_CODES['横盘看涨']}"
    ]
    output[f"{prefix}_bearish"] = output[f"{prefix}_{STATE_CODES['波峰看跌']}"] + output[
        f"{prefix}_{STATE_CODES['横盘看跌']}"
    ]
    output[f"{prefix}_high_volatility"] = output[
        f"{prefix}_{STATE_CODES['双向高波']}"
    ]
    # 二元方向展示：双向高波本身没有方向，采用中性 50%/50% 分摊，
    # 使 up/down 仍然严格相加为 1；三类字段保留原始歧义信息。
    output[f"{prefix}_up"] = output[f"{prefix}_bullish"] + 0.5 * output[
        f"{prefix}_high_volatility"
    ]
    output[f"{prefix}_down"] = output[f"{prefix}_bearish"] + 0.5 * output[
        f"{prefix}_high_volatility"
    ]
    return output


def build_state_probabilities(
    *,
    oof_path: Path = DEFAULT_OOF,
    test_path: Path = DEFAULT_TEST,
    target_path: Path = DEFAULT_TARGET,
    score_path: Path = DEFAULT_SCORE,
    output_path: Path = DEFAULT_OUTPUT,
    model_path: Path = DEFAULT_MODEL_PATH,
) -> dict[str, object]:
    oof_raw = _normalise_keys(pd.read_parquet(oof_path))
    test_raw = _normalise_keys(pd.read_parquet(test_path))
    target = _normalise_keys(pd.read_parquet(target_path, columns=[*JOIN_KEYS, *TARGETS]))
    for frame, name in ((oof_raw, "OOF"), (test_raw, "测试")):
        missing = {f"pred_{target_name}" for target_name in TARGETS}.difference(frame.columns)
        if missing:
            raise ValueError(f"{name}预测文件缺少字段: {sorted(missing)}")

    oof = _rank_features(oof_raw)
    test = _rank_features(test_raw)
    oof = oof.merge(target[JOIN_KEYS + list(TARGETS)], on=JOIN_KEYS, how="inner", validate="one_to_one")
    oof_dates = pd.DatetimeIndex(oof["time"].dropna().unique()).sort_values()
    train_rows = []
    models = {}
    actual_states = {}
    model_path.mkdir(parents=True, exist_ok=True)
    for horizon in HORIZONS:
        peak_target = f"delta_peak_{horizon}"
        valley_target = f"delta_valley_{horizon}"
        actual_peak = oof[peak_target].groupby(oof["time"]).rank(method="average", pct=True)
        actual_valley = oof[valley_target].groupby(oof["time"]).rank(method="average", pct=True)
        actual_state = classify_quadrant(actual_peak, actual_valley)
        actual_states[horizon] = actual_state
        feature_frame = _calibration_features(oof, horizon)
        train_end = _purged_train_end(oof_dates, TEST_START, PURGE_BARS[horizon])
        valid = (
            oof["time"].dt.year.isin(OOF_YEARS)
            & (oof["time"] <= train_end)
            & actual_state.notna()
            & feature_frame.notna().all(axis=1)
        )
        if int(valid.sum()) < 1000 or actual_state.loc[valid].nunique() < 4:
            raise RuntimeError(f"{horizon}概率校准训练样本不足或缺少五类状态")
        calibrator = _fit_calibrator(feature_frame.loc[valid], actual_state.loc[valid])
        models[horizon] = calibrator
        model_file = model_path / f"state_probability_{horizon}.joblib"
        joblib.dump(
            {
                "model": calibrator,
                "horizon": horizon,
                "train_end": train_end.strftime("%Y-%m-%d"),
                "train_rows": int(valid.sum()),
                "states": list(STATE_NAMES),
            },
            model_file,
        )
        train_rows.append({
            "horizon": horizon,
            "train_end": train_end.strftime("%Y-%m-%d"),
            "train_rows": int(valid.sum()),
            "classes": int(actual_state.loc[valid].nunique()),
        })

    consensus_model = None
    consensus_actual = _weighted_state_consensus(pd.DataFrame(actual_states))
    consensus_features = _consensus_calibration_features(oof)
    consensus_train_end = _purged_train_end(oof_dates, TEST_START, max(PURGE_BARS.values()))
    consensus_valid = (
        oof["time"].dt.year.isin(OOF_YEARS)
        & (oof["time"] <= consensus_train_end)
        & consensus_actual.notna()
        & consensus_features.notna().all(axis=1)
    )
    if int(consensus_valid.sum()) < 1000 or consensus_actual.loc[consensus_valid].nunique() < 4:
        raise RuntimeError("共识概率校准训练样本不足或缺少五类状态")
    consensus_model = _fit_calibrator(consensus_features.loc[consensus_valid], consensus_actual.loc[consensus_valid])
    joblib.dump(
        {
            "model": consensus_model,
            "horizon": "consensus",
            "train_end": consensus_train_end.strftime("%Y-%m-%d"),
            "train_rows": int(consensus_valid.sum()),
            "states": list(STATE_NAMES),
        },
        model_path / "state_probability_consensus.joblib",
    )
    train_rows.append({
        "horizon": "consensus",
        "train_end": consensus_train_end.strftime("%Y-%m-%d"),
        "train_rows": int(consensus_valid.sum()),
        "classes": int(consensus_actual.loc[consensus_valid].nunique()),
    })

    if score_path.exists():
        result = _normalise_keys(pd.read_parquet(score_path))
        result = result.merge(test[[*JOIN_KEYS]], on=JOIN_KEYS, how="inner", validate="one_to_one")
    else:
        result = test[[*KEYS]].copy()
    result = result.drop_duplicates(JOIN_KEYS).set_index(JOIN_KEYS)
    probability_tables = {}
    for horizon, calibrator in models.items():
        features = _calibration_features(test, horizon)
        probabilities = _predict_all_states(calibrator, features)
        probabilities.index = pd.MultiIndex.from_frame(test[JOIN_KEYS])
        probability_tables[horizon] = probabilities
        for state in STATE_NAMES:
            result[f"prob_{horizon}_{STATE_CODES[state]}"] = probabilities[state]
        result = add_direction_probabilities(result, prefix=f"prob_{horizon}")
        result[f"most_likely_state_{horizon}"] = probabilities.idxmax(axis=1).to_numpy()
        result[f"max_probability_{horizon}"] = probabilities.max(axis=1).to_numpy()

    for state in STATE_NAMES:
        column = f"prob_consensus_weighted_{STATE_CODES[state]}"
        result[column] = sum(
            CONSENSUS_WEIGHTS[horizon] * probability_tables[horizon][state]
            for horizon in HORIZONS
        ).to_numpy()
    result = add_direction_probabilities(result, prefix="prob_consensus_weighted")
    consensus_probabilities = _predict_all_states(
        consensus_model, _consensus_calibration_features(test)
    )
    consensus_probabilities.index = pd.MultiIndex.from_frame(test[JOIN_KEYS])
    for state in STATE_NAMES:
        result[f"prob_consensus_{STATE_CODES[state]}"] = consensus_probabilities[state]
    result = add_direction_probabilities(result, prefix="prob_consensus")
    consensus_columns = [f"prob_consensus_{STATE_CODES[state]}" for state in STATE_NAMES]
    result["most_likely_state_consensus"] = result[consensus_columns].idxmax(axis=1).map(
        {f"prob_consensus_{STATE_CODES[state]}": state for state in STATE_NAMES}
    )
    result["max_probability_consensus"] = result[consensus_columns].max(axis=1)
    result = result.reset_index().sort_values(["time", "htsc_code"]).reset_index(drop=True)

    output_path.mkdir(parents=True, exist_ok=True)
    output_file = output_path / "sector_state_probabilities.parquet"
    pl.from_pandas(result, include_index=False).write_parquet(output_file, compression="zstd")
    manifest = {
        "version": "v2_five_state_calibrated_multinomial",
        "oof_input": str(oof_path),
        "test_input": str(test_path),
        "target_input": str(target_path),
        "score_input": str(score_path) if score_path.exists() else None,
        "output": str(output_file),
        "output_sha256": sha256_file(output_file),
        "rows": int(len(result)),
        "test_period": "2023+",
        "calibration_years": list(OOF_YEARS),
        "purge_bars": PURGE_BARS,
        "consensus_weights": CONSENSUS_WEIGHTS,
        "consensus_method": "独立多分类校准器；同时保留prob_consensus_weighted_*原始加权概率",
        "direction_probability_policy": "bullish=波谷看涨+横盘看涨; bearish=波峰看跌+横盘看跌; high_volatility=双向高波; each horizon and consensus aggregate sums to 1",
        "state_names": list(STATE_NAMES),
        "state_codes": STATE_CODES,
        "training": train_rows,
        "probability_columns_sum_to_one": True,
        "direction_probability_columns": {
            "bullish": "valley_bullish + sideways_bullish",
            "bearish": "peak_bearish + sideways_bearish",
            "high_volatility": "two_sided_high_volatility",
        },
        "direction_probability_columns_sum_to_one": True,
        "binary_direction_probability_policy": "up=bullish+0.5*high_volatility; down=bearish+0.5*high_volatility; neutral split is a display mapping, not a return probability",
        "binary_direction_probability_columns_sum_to_one": True,
    }
    (output_path / "state_probability_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="生成板块五类走势概率")
    parser.add_argument("--oof-path", type=Path, default=DEFAULT_OOF)
    parser.add_argument("--test-path", type=Path, default=DEFAULT_TEST)
    parser.add_argument("--target-path", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--score-path", type=Path, default=DEFAULT_SCORE)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    build_state_probabilities(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
