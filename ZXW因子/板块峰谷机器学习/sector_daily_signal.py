"""使用已训练模型生成板块最新交易日的15个事件概率。

本脚本只做推理，不训练、不读取未来标签、不重新拟合校准器。
最终输出为：超短、5日短期、20日中期 × 五类事件概率。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import polars as pl


FACTOR_GROUP_PATH = Path(r"D:\database\sector_peak_valley_ml\factor_groups_v1")
TECH_SUBGROUP_PATH = Path(r"D:\database\sector_peak_valley_ml\technical_subgroups_v1")
CORE_MODEL_PATH = Path(r"D:\database\sector_peak_valley_ml\models\core_groups_v1")
MARKET_STATE_MODEL_PATH = Path(r"D:\database\sector_peak_valley_ml\models\market_state_group_v1")
TECH_SUBGROUP_MODEL_PATH = Path(r"D:\database\sector_peak_valley_ml\models\technical_subgroups_v1")
TECH_GROUP_MODEL_PATH = Path(r"D:\database\sector_peak_valley_ml\models\technical_group_v1")
BLEND_MODEL_PATH = Path(r"D:\database\sector_peak_valley_ml\models\core_blend_oof_selected_v3")
STATE_MODEL_PATH = Path(r"D:\database\sector_peak_valley_ml\models\state_probability_v2_5class")
OUTPUT_PATH = Path("outputs/sector_peak_valley_ml/stage_ax_daily_signal")
PROBABILITY_HISTORY_DIRNAME = "sector_probability_history_15"
DIAGNOSTICS_HISTORY_DIRNAME = "sector_signal_diagnostics_history"
PARTITION_FILE_NAME = "merged.parquet"
PROBABILITY_BACKFILL_PATH = Path(
    "outputs/sector_peak_valley_ml/stage_aw_event_probability_decomposition/sector_probability_final_15.parquet"
)
FINAL_SCORE_BACKFILL_PATH = Path(
    "outputs/sector_peak_valley_ml/stage_x_final_scores_nested/sector_final_scores.parquet"
)
TECHNICAL_PREDICTION_BACKFILL_PATH = Path(
    "outputs/sector_peak_valley_ml/stage_q_technical_subgroup_models/predictions"
)
TECHNICAL_GROUP_BACKFILL_PATH = Path(
    "outputs/sector_peak_valley_ml/stage_r_technical_group_blend/technical_group_test_predictions.parquet"
)
CORE_GROUP_BACKFILL_PATH = Path(
    "outputs/sector_peak_valley_ml/stage_s_core_group_models/predictions"
)
MARKET_STATE_BACKFILL_PATH = Path(
    "outputs/sector_peak_valley_ml/stage_y_market_state_group_model/market_state_conditioned_test_predictions.parquet"
)

KEYS = ["htsc_code", "time", "sector_family"]
GROUPS = ("technical", "sideways_volatility", "relative_strength", "constituent_breadth", "leader_diffusion", "market_state_conditioned")
CORE_GROUP_FILES = GROUPS[1:]
INDICATORS = ("ADX", "AMA", "APO", "AROON", "BOLL", "CCI", "CMO", "DEMA", "MACD", "MFI", "MOM", "PPO", "ROC", "RSI", "STOCH", "ULTOSC", "WILLR", "WMA")
HORIZONS = ("ultra_short", "5d", "20d")
TARGETS = tuple(f"delta_{side}_{horizon}" for horizon in HORIZONS for side in ("peak", "valley"))
STATES = ("valley_bullish", "peak_bearish", "two_sided_high_volatility", "sideways_bullish", "sideways_bearish")
STATE_NAMES = {"valley_bullish": "波谷看涨", "peak_bearish": "波峰看跌", "two_sided_high_volatility": "双向高波", "sideways_bullish": "横盘看涨", "sideways_bearish": "横盘看跌"}


def _history_partition_root(output_path: Path, kind: str) -> Path:
    dirname = PROBABILITY_HISTORY_DIRNAME if kind == "probability" else DIAGNOSTICS_HISTORY_DIRNAME
    return output_path / dirname


def _monthly_partition_path(output_path: Path, kind: str, date_value: pd.Timestamp) -> Path:
    date_value = pd.Timestamp(date_value)
    return (
        _history_partition_root(output_path, kind)
        / f"year={date_value.year:04d}"
        / f"month={date_value.month:02d}"
        / PARTITION_FILE_NAME
    )


def _write_month_partition(frame: pd.DataFrame, output_path: Path, kind: str) -> list[Path]:
    """按 year/month 写入 merged.parquet；同月重复主键以新数据覆盖。"""
    if frame.empty:
        return []
    working = frame.copy()
    working["time"] = pd.to_datetime(working["time"], errors="coerce").dt.floor("D")
    working["htsc_code"] = working["htsc_code"].astype(str).str.strip().str.upper()
    working = working.dropna(subset=KEYS).drop_duplicates(KEYS, keep="last")
    touched: list[Path] = []
    for (year, month), current in working.groupby([working["time"].dt.year, working["time"].dt.month], sort=True):
        target = _history_partition_root(output_path, kind) / f"year={int(year):04d}" / f"month={int(month):02d}" / PARTITION_FILE_NAME
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            previous = pd.read_parquet(target)
            merged = pd.concat([previous, current], ignore_index=True, sort=False)
        else:
            merged = current.copy()
        merged = merged.drop_duplicates(KEYS, keep="last").sort_values(KEYS).reset_index(drop=True)
        temp = target.with_name(f"{target.name}.{os.getpid()}.{time.time_ns()}.tmp")
        pl.from_pandas(merged, include_index=False).write_parquet(temp, compression="zstd")
        temp.replace(target)
        touched.append(target)
    return touched


def _partition_files(output_path: Path, kind: str) -> list[Path]:
    return sorted(_history_partition_root(output_path, kind).glob("year=*/month=*/merged.parquet"))


def _partition_history_stats(output_path: Path, kind: str) -> dict[str, object]:
    files = _partition_files(output_path, kind)
    dates: list[pd.Timestamp] = []
    rows = 0
    for path in files:
        frame = pd.read_parquet(path, columns=KEYS)
        rows += len(frame)
        if not frame.empty:
            dates.extend(pd.to_datetime(frame["time"], errors="coerce").dropna().tolist())
    if not dates:
        return {"rows": rows, "dates": 0, "from": None, "to": None, "partitions": [str(p) for p in files]}
    return {
        "rows": rows,
        "dates": len(set(dates)),
        "from": min(dates).strftime("%Y-%m-%d"),
        "to": max(dates).strftime("%Y-%m-%d"),
        "partitions": [str(p) for p in files],
    }


def partitionize_existing_history(output_path: Path = OUTPUT_PATH) -> dict[str, object]:
    """把旧版单文件历史迁移为按月 merged.parquet；旧文件保留作回滚备份。"""
    result: dict[str, object] = {}
    probability_columns = KEYS + [
        f"{horizon}_prob_{state}" for horizon in HORIZONS for state in STATES
    ] + [f"{horizon}_{suffix}" for horizon in HORIZONS for suffix in ("most_likely_state", "event_strength")]
    for kind, legacy_name, columns in (
        ("probability", "sector_probability_history_15.parquet", probability_columns),
        ("diagnostics", "sector_signal_diagnostics_history.parquet", None),
    ):
        legacy = output_path / legacy_name
        if not legacy.exists():
            result[kind] = {"status": "missing", "path": str(legacy)}
            continue
        frame = pd.read_parquet(legacy, columns=columns)
        paths = _write_month_partition(frame, output_path, kind)
        result[kind] = {"status": "migrated", "rows": int(len(frame)), "partitions": [str(path) for path in paths]}
    manifest_path = output_path / "daily_signal_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        manifest.setdefault("files", {})["probability_history_partition_root"] = str(_history_partition_root(output_path, "probability"))
        manifest.setdefault("files", {})["diagnostics_history_partition_root"] = str(_history_partition_root(output_path, "diagnostics"))
        manifest["history_storage"] = "按 year=YYYY/month=MM/merged.parquet 分区；旧单文件仅保留作兼容备份"
        manifest["probability_history_partition_stats"] = _partition_history_stats(output_path, "probability")
        manifest["diagnostics_history_partition_stats"] = _partition_history_stats(output_path, "diagnostics")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalise(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    if frame[KEYS].isna().any().any() or frame.duplicated(KEYS).any():
        raise ValueError("因子输入主键为空或重复")
    return frame


def latest_rows(frame: pd.DataFrame, asof_date: pd.Timestamp | None) -> pd.DataFrame:
    date = pd.Timestamp(asof_date) if asof_date is not None else frame["time"].max()
    rows = frame.loc[frame["time"].eq(date)].copy()
    if rows.empty:
        raise ValueError(f"没有找到指定日期数据: {date:%Y-%m-%d}")
    return rows


def load_technical_scores(asof_date: pd.Timestamp | None) -> pd.DataFrame:
    base = None
    score_columns: dict[str, np.ndarray] = {}
    for indicator in INDICATORS:
        path = TECH_SUBGROUP_PATH / f"{indicator}.parquet"
        frame = normalise(pd.read_parquet(path))
        rows = latest_rows(frame, asof_date)
        if base is None:
            base = rows[KEYS].copy()
        elif not rows[KEYS].equals(base[KEYS]):
            rows = rows.merge(base[KEYS], on=KEYS, how="inner", validate="one_to_one")
        for target in TARGETS:
            model = lgb.Booster(model_file=str(TECH_SUBGROUP_MODEL_PATH / indicator / f"{target}.txt"))
            features = model.feature_name()
            missing = sorted(set(features).difference(rows.columns))
            if missing:
                raise ValueError(f"技术子组 {indicator} 缺少模型因子: {missing}")
            values = model.predict(rows[features])
            # 技术大组的第一层输入必须是当日横截面百分位排名。
            score_columns[f"score_{indicator}_{target}"] = (
                pd.Series(values, index=rows.index).rank(method="average", pct=True).to_numpy()
            )

    if base is None:
        raise RuntimeError("没有技术子组数据")
    result = pd.concat(
        [base.reset_index(drop=True), pd.DataFrame(score_columns)], axis=1
    )
    for target in TARGETS:
        model_info = joblib.load(TECH_GROUP_MODEL_PATH / f"{target}.joblib")
        features = model_info["features"]
        result[f"pred_{target}"] = model_info["model"].predict(result[features])
    return result


def load_core_scores(group_id: str, asof_date: pd.Timestamp | None) -> pd.DataFrame:
    frame = normalise(pd.read_parquet(FACTOR_GROUP_PATH / f"{group_id}.parquet"))
    rows = latest_rows(frame, asof_date)
    result = rows[KEYS].copy()
    for target in TARGETS:
        model_root = MARKET_STATE_MODEL_PATH if group_id == "market_state_conditioned" else CORE_MODEL_PATH / group_id
        model = lgb.Booster(model_file=str(model_root / f"{target}.txt"))
        features = model.feature_name()
        missing = sorted(set(features).difference(rows.columns))
        if missing:
            raise ValueError(f"核心组 {group_id} 缺少模型因子: {missing}")
        result[f"pred_{target}"] = model.predict(rows[features])
    return result


def build_continuous_scores(asof_date: pd.Timestamp | None) -> pd.DataFrame:
    frames = {"technical": load_technical_scores(asof_date)}
    frames.update({group: load_core_scores(group, asof_date) for group in CORE_GROUP_FILES})
    base = None
    for group, frame in frames.items():
        technical_subgroup_columns = (
            [column for column in frame.columns if column.startswith("score_")]
            if group == "technical"
            else []
        )
        current = frame[KEYS + technical_subgroup_columns + [f"pred_{target}" for target in TARGETS]].copy()
        current = current.rename(columns={f"pred_{target}": f"score_{group}_{target}" for target in TARGETS})
        base = current if base is None else base.merge(current, on=KEYS, how="inner", validate="one_to_one")
    if base is None or base.empty:
        raise RuntimeError("各因子组没有共同的最新板块截面")
    if base["time"].nunique() != 1:
        raise ValueError("不同因子组的最新日期不一致，请先完成当日因子更新")
    for target in TARGETS:
        model_info = joblib.load(BLEND_MODEL_PATH / f"{target}.joblib")
        features = model_info["features"]
        missing = sorted(set(features).difference(base.columns))
        if missing:
            raise ValueError(f"顶层组合 {target} 缺少组分: {missing}")
        # 顶层 Ridge 的输入是每日横截面百分位组分；所有组都输出排名，
        # 即使某一目标的固定组选择没有使用某个组，也方便审计比较。
        for group in GROUPS:
            source = f"score_{group}_{target}"
            base[f"rank_{group}_{target}"] = base[source].rank(method="average", pct=True)
        ranked = base[features].apply(lambda col: col.rank(method="average", pct=True))
        for group in GROUPS:
            contribution_column = f"contrib_{group}_{target}"
            base[contribution_column] = 0.0
        for feature, coefficient in zip(features, model_info["model"].coef_):
            group = feature.removeprefix("score_").removesuffix(f"_{target}")
            base[f"contrib_{group}_{target}"] = (
                ranked[feature].to_numpy(dtype=float) * float(coefficient)
            )
        base[f"blend_intercept_{target}"] = float(np.asarray(model_info["model"].intercept_).reshape(-1)[0])
        base[f"blend_rank_sum_{target}"] = ranked.sum(axis=1).to_numpy(dtype=float)
        base[f"pred_{target}"] = model_info["model"].predict(ranked)
    base["sector_family"] = base["htsc_code"].str[:3]
    return base


def rank_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame[KEYS].copy()
    for horizon in HORIZONS:
        peak = frame[f"pred_delta_peak_{horizon}"]
        valley = frame[f"pred_delta_valley_{horizon}"]
        result[f"peak_rank_{horizon}"] = peak.rank(method="average", pct=True)
        result[f"valley_rank_{horizon}"] = valley.rank(method="average", pct=True)
        result[f"direction_{horizon}"] = result[f"valley_rank_{horizon}"] - result[f"peak_rank_{horizon}"]
        result[f"direction_strength_{horizon}"] = result[f"direction_{horizon}"].abs()
        result[f"level_{horizon}"] = (result[f"peak_rank_{horizon}"] + result[f"valley_rank_{horizon}"]) / 2.0 - 0.5
    return result


def predict_probabilities(scores: pd.DataFrame) -> pd.DataFrame:
    ranked = rank_features(scores)
    output = scores[KEYS].copy()
    for horizon in HORIZONS:
        model_info = joblib.load(STATE_MODEL_PATH / f"state_probability_{horizon}.joblib")
        source_features = [f"peak_rank_{horizon}", f"valley_rank_{horizon}", f"direction_{horizon}", f"level_{horizon}"]
        features = ["peak", "valley", "direction", "level"]
        calibration_input = ranked[source_features].rename(columns=dict(zip(source_features, features)))
        probabilities = model_info["model"].predict_proba(calibration_input)
        classes = list(model_info["model"].named_steps["logit"].classes_)
        for state in STATES:
            values = np.zeros(len(output), dtype=float)
            class_name = STATE_NAMES[state]
            if class_name in classes:
                values = probabilities[:, classes.index(class_name)]
            output[f"{horizon}_prob_{state}"] = values
        columns = [f"{horizon}_prob_{state}" for state in STATES]
        row_sum = output[columns].sum(axis=1)
        if (row_sum <= 0).any() or not np.isfinite(row_sum).all():
            raise ValueError(f"{horizon}概率校准器没有返回有效类别")
        output[columns] = output[columns].div(row_sum, axis=0)
        output[f"{horizon}_most_likely_state"] = output[columns].idxmax(axis=1).map(
            {f"{horizon}_prob_{state}": STATE_NAMES[state] for state in STATES}
        )
        output[f"{horizon}_event_strength"] = output[columns].max(axis=1)
    return output.sort_values(["time", "htsc_code"]).reset_index(drop=True)


def backfill_probability_history(output_path: Path = OUTPUT_PATH) -> dict[str, object]:
    """用完整部署期概率结果初始化每日信号历史。

    stage_ax 是每日推理落库层，首次运行前不会自动包含历史；stage_aw
    已保存 2023 年以来的完整 15 事件概率，因此这里只回填概率历史，
    不伪造历史的 18 个技术子组和组贡献诊断。
    """
    source_path = Path(PROBABILITY_BACKFILL_PATH)
    if not source_path.exists():
        raise FileNotFoundError(f"历史概率源文件不存在: {source_path}")
    source = pd.read_parquet(source_path)
    source = source.copy()
    source["time"] = pd.to_datetime(source["time"], errors="coerce").dt.floor("D")
    source["htsc_code"] = source["htsc_code"].astype(str).str.strip().str.upper()
    source = source.dropna(subset=KEYS).drop_duplicates(KEYS, keep="last")
    for horizon in HORIZONS:
        columns = [f"{horizon}_prob_{state}" for state in STATES]
        source[f"{horizon}_most_likely_state"] = source[columns].idxmax(axis=1).map(
            {f"{horizon}_prob_{state}": STATE_NAMES[state] for state in STATES}
        )
        source[f"{horizon}_event_strength"] = source[columns].max(axis=1)
    source = source.sort_values(KEYS).reset_index(drop=True)
    output_path.mkdir(parents=True, exist_ok=True)
    partition_paths = _write_month_partition(source, output_path, "probability")
    latest_date = source["time"].max()
    latest = source.loc[source["time"].eq(latest_date)].copy()
    pl.from_pandas(latest, include_index=False).write_parquet(
        output_path / "sector_probability_latest_15.parquet", compression="zstd"
    )
    latest.to_csv(output_path / "sector_probability_latest_15.csv", index=False, encoding="utf-8-sig")
    manifest_path = output_path / "daily_signal_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        manifest["probability_history_rows"] = int(len(source))
        manifest["probability_history_dates"] = int(source["time"].nunique())
        manifest["probability_history_from"] = source["time"].min().strftime("%Y-%m-%d")
        manifest["probability_history_to"] = source["time"].max().strftime("%Y-%m-%d")
        manifest["probability_history_backfilled_from"] = str(source_path)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "source": str(source_path),
        "history": str(_history_partition_root(output_path, "probability")),
        "partitions_written": [str(path) for path in partition_paths],
        "rows": int(len(source)),
        "dates": int(source["time"].nunique()),
        "from": source["time"].min().strftime("%Y-%m-%d"),
        "to": source["time"].max().strftime("%Y-%m-%d"),
    }


def _load_prediction_union(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"历史预测文件不存在: {path}")
        frames.append(pd.read_parquet(path))
    frame = pd.concat(frames, ignore_index=True)
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    return frame.dropna(subset=KEYS).drop_duplicates(KEYS, keep="last")


def _load_prediction_columns(path: Path | list[Path], prefix: str) -> pd.DataFrame:
    """读取阶段预测文件，并统一改成每日诊断层的 score_<组>_<目标> 命名。"""
    paths = path if isinstance(path, list) else [path]
    frame = _load_prediction_union(paths)
    keep = KEYS + [f"pred_{target}" for target in TARGETS]
    missing = sorted(set(keep).difference(frame.columns))
    if missing:
        raise ValueError(f"历史预测文件缺少字段 {path}: {missing}")
    frame = frame[keep].copy()
    return frame.rename(columns={f"pred_{target}": f"score_{prefix}_{target}" for target in TARGETS})


def backfill_diagnostics_history(output_path: Path = OUTPUT_PATH) -> dict[str, object]:
    """从已落盘的各阶段测试预测重建完整历史诊断层。

    该回填覆盖部署测试期（2023-01-03 至当前阶段最新交易日）。
    它只使用已保存的模型预测和模型系数，不读取未来标签，也不重新训练。
    """
    if not FINAL_SCORE_BACKFILL_PATH.exists():
        raise FileNotFoundError(f"最终预测文件不存在: {FINAL_SCORE_BACKFILL_PATH}")
    blend_oof_path = Path("outputs/sector_peak_valley_ml/stage_w_core_group_blend_nested/core_blend_oof_predictions.parquet")
    blend_test_path = Path("outputs/sector_peak_valley_ml/stage_w_core_group_blend_nested/core_blend_test_predictions.parquet")
    final_scores = _load_prediction_union([blend_oof_path, blend_test_path])
    base = final_scores[KEYS].drop_duplicates(KEYS).copy()

    # 18 个技术子组原始预测分。
    for indicator in INDICATORS:
        paths = [
            TECHNICAL_PREDICTION_BACKFILL_PATH / f"{indicator}_oof.parquet",
            TECHNICAL_PREDICTION_BACKFILL_PATH / f"{indicator}_test.parquet",
        ]
        current = _load_prediction_columns(paths, indicator)
        base = base.merge(current, on=KEYS, how="inner", validate="one_to_one")

    # 技术大组、五个核心组和市场状态组预测分。
    group_paths = {
        "sideways_volatility": [CORE_GROUP_BACKFILL_PATH / "sideways_volatility_oof.parquet", CORE_GROUP_BACKFILL_PATH / "sideways_volatility_test.parquet"],
        "relative_strength": [CORE_GROUP_BACKFILL_PATH / "relative_strength_oof.parquet", CORE_GROUP_BACKFILL_PATH / "relative_strength_test.parquet"],
        "constituent_breadth": [CORE_GROUP_BACKFILL_PATH / "constituent_breadth_oof.parquet", CORE_GROUP_BACKFILL_PATH / "constituent_breadth_test.parquet"],
        "leader_diffusion": [CORE_GROUP_BACKFILL_PATH / "leader_diffusion_oof.parquet", CORE_GROUP_BACKFILL_PATH / "leader_diffusion_test.parquet"],
        "market_state_conditioned": [
            Path("outputs/sector_peak_valley_ml/stage_y_market_state_group_model/market_state_conditioned_oof_predictions.parquet"),
            Path("outputs/sector_peak_valley_ml/stage_y_market_state_group_model/market_state_conditioned_test_predictions.parquet"),
        ],
    }
    for group, path in group_paths.items():
        base = base.merge(_load_prediction_columns(path, group), on=KEYS, how="inner", validate="one_to_one")

    # 技术大组 OOF 文件早期存在未生成的空行；使用18个技术子组预测和已训练 Ridge
    # 重新构造，确保2019年也有一致的技术组输出。
    for target in TARGETS:
        model_info = joblib.load(TECH_GROUP_MODEL_PATH / f"{target}.joblib")
        features = list(model_info["features"])
        ranked_features = pd.DataFrame(index=base.index)
        for feature in features:
            ranked_features[feature] = base.groupby("time")[feature].rank(method="average", pct=True)
        base[f"score_technical_{target}"] = model_info["model"].predict(ranked_features)

    if base.filter(like="score_").isna().any().any():
        raise ValueError("历史诊断回填后存在缺失的组级或技术子组预测分")

    # 按每日板块横截面重建顶层 Ridge 的排名、贡献和连续预测分。
    for target in TARGETS:
        for group in GROUPS:
            source = f"score_{group}_{target}"
            base[f"rank_{group}_{target}"] = base.groupby("time")[source].rank(method="average", pct=True)

        model_info = joblib.load(BLEND_MODEL_PATH / f"{target}.joblib")
        features = list(model_info["features"])
        missing = sorted(set(features).difference(base.columns))
        if missing:
            raise ValueError(f"历史顶层 Ridge {target} 缺少字段: {missing}")
        ranked = pd.DataFrame(index=base.index)
        for feature in features:
            ranked[feature] = base.groupby("time")[feature].rank(method="average", pct=True)
        for group in GROUPS:
            base[f"contrib_{group}_{target}"] = 0.0
        for feature, coefficient in zip(features, model_info["model"].coef_):
            group = feature.removeprefix("score_").removesuffix(f"_{target}")
            base[f"contrib_{group}_{target}"] = ranked[feature].to_numpy(dtype=float) * float(coefficient)
        base[f"blend_intercept_{target}"] = float(np.asarray(model_info["model"].intercept_).reshape(-1)[0])
        base[f"blend_rank_sum_{target}"] = ranked.sum(axis=1).to_numpy(dtype=float)
        base[f"pred_{target}"] = model_info["model"].predict(ranked)

    # 连续预测分的横截面排名、方向分和方向强度。
    for horizon in HORIZONS:
        peak = f"pred_delta_peak_{horizon}"
        valley = f"pred_delta_valley_{horizon}"
        base[f"peak_rank_{horizon}"] = base.groupby("time")[peak].rank(method="average", pct=True)
        base[f"valley_rank_{horizon}"] = base.groupby("time")[valley].rank(method="average", pct=True)
        base[f"direction_{horizon}"] = base[f"valley_rank_{horizon}"] - base[f"peak_rank_{horizon}"]
        base[f"direction_strength_{horizon}"] = base[f"direction_{horizon}"].abs()
        base[f"level_{horizon}"] = (
            base[f"peak_rank_{horizon}"] + base[f"valley_rank_{horizon}"]
        ) / 2.0 - 0.5

    # 使用已经训练好的状态概率校准器，为 OOF + 测试期连续预测统一生成15事件概率。
    # 这样 2019-2022 不依赖只覆盖部署期的 stage_aw 概率文件。
    probabilities = base[KEYS].copy()
    for horizon in HORIZONS:
        columns = [f"{horizon}_prob_{state}" for state in STATES]
        model_info = joblib.load(STATE_MODEL_PATH / f"state_probability_{horizon}.joblib")
        calibration_input = base[
            [f"peak_rank_{horizon}", f"valley_rank_{horizon}", f"direction_{horizon}", f"level_{horizon}"]
        ].rename(
            columns={
                f"peak_rank_{horizon}": "peak",
                f"valley_rank_{horizon}": "valley",
                f"direction_{horizon}": "direction",
                f"level_{horizon}": "level",
            }
        )
        calibrated = model_info["model"].predict_proba(calibration_input)
        classes = list(model_info["model"].named_steps["logit"].classes_)
        for state in STATES:
            class_name = STATE_NAMES[state]
            values = np.zeros(len(probabilities), dtype=float)
            if class_name in classes:
                values = calibrated[:, classes.index(class_name)]
            probabilities[f"{horizon}_prob_{state}"] = values
        row_sum = probabilities[columns].sum(axis=1)
        if (row_sum <= 0).any() or not np.isfinite(row_sum).all():
            raise ValueError(f"{horizon}历史概率校准器没有返回有效类别")
        probabilities[columns] = probabilities[columns].div(row_sum, axis=0)
        probabilities[f"{horizon}_most_likely_state"] = probabilities[columns].idxmax(axis=1).map(
            {f"{horizon}_prob_{state}": STATE_NAMES[state] for state in STATES}
        )
        probabilities[f"{horizon}_event_strength"] = probabilities[columns].max(axis=1)
    base = base.merge(probabilities, on=KEYS, how="left", validate="one_to_one")

    base = base.sort_values(KEYS).reset_index(drop=True)
    output_path.mkdir(parents=True, exist_ok=True)
    probability_columns = KEYS + [
        column
        for column in base.columns
        if column.startswith(("ultra_short_prob_", "5d_prob_", "20d_prob_"))
        or column.endswith(("_most_likely_state", "_event_strength"))
    ]
    probability_history = base[probability_columns].copy()
    probability_partitions = _write_month_partition(probability_history, output_path, "probability")
    latest_probability = probability_history.loc[
        probability_history["time"].eq(probability_history["time"].max())
    ].copy()
    pl.from_pandas(latest_probability, include_index=False).write_parquet(
        output_path / "sector_probability_latest_15.parquet", compression="zstd"
    )
    latest_probability.to_csv(
        output_path / "sector_probability_latest_15.csv", index=False, encoding="utf-8-sig"
    )
    partition_paths = _write_month_partition(base, output_path, "diagnostics")
    diagnostics_history_path = _history_partition_root(output_path, "diagnostics")

    latest_date = base["time"].max()
    latest = base.loc[base["time"].eq(latest_date)].copy()
    pl.from_pandas(latest, include_index=False).write_parquet(
        output_path / "sector_signal_diagnostics_latest.parquet", compression="zstd"
    )
    pl.from_pandas(latest, include_index=False).write_parquet(
        output_path / f"sector_signal_diagnostics_{latest_date:%Y%m%d}.parquet", compression="zstd"
    )

    manifest_path = output_path / "daily_signal_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        manifest["diagnostics_history_rows"] = int(len(base))
        manifest["diagnostics_history_dates"] = int(base["time"].nunique())
        manifest["diagnostics_history_from"] = base["time"].min().strftime("%Y-%m-%d")
        manifest["diagnostics_history_to"] = base["time"].max().strftime("%Y-%m-%d")
        manifest["diagnostics_history_backfilled_from"] = {
            "technical_subgroups": str(TECHNICAL_PREDICTION_BACKFILL_PATH),
            "technical_group": str(TECHNICAL_GROUP_BACKFILL_PATH),
            "core_groups": str(CORE_GROUP_BACKFILL_PATH),
            "market_state_group": str(MARKET_STATE_BACKFILL_PATH),
            "blend": str(BLEND_MODEL_PATH),
            "probabilities": str(PROBABILITY_BACKFILL_PATH),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "history": str(diagnostics_history_path),
        "probability_partitions_written": [str(path) for path in probability_partitions],
        "partitions_written": [str(path) for path in partition_paths],
        "rows": int(len(base)),
        "dates": int(base["time"].nunique()),
        "columns": int(len(base.columns)),
        "from": base["time"].min().strftime("%Y-%m-%d"),
        "to": base["time"].max().strftime("%Y-%m-%d"),
    }


def run_daily(*, asof_date: str | None = None, output_path: Path = OUTPUT_PATH) -> dict[str, object]:
    parsed_date = pd.Timestamp(asof_date) if asof_date else None
    scores = build_continuous_scores(parsed_date)
    ranked_features = rank_features(scores)
    probabilities = predict_probabilities(scores)
    actual_date = pd.Timestamp(probabilities["time"].max())
    diagnostics = scores.merge(ranked_features, on=KEYS, how="inner", validate="one_to_one")
    diagnostics = diagnostics.merge(probabilities, on=KEYS, how="inner", validate="one_to_one")
    diagnostics = diagnostics.sort_values(["time", "htsc_code"]).reset_index(drop=True)
    reconstruction_errors = {}
    for target in TARGETS:
        contribution_columns = [f"contrib_{group}_{target}" for group in GROUPS]
        reconstructed = diagnostics[f"blend_intercept_{target}"] + diagnostics[contribution_columns].sum(axis=1)
        reconstruction_errors[target] = float((reconstructed - diagnostics[f"pred_{target}"]).abs().max())
        if reconstruction_errors[target] > 1e-8:
            raise ValueError(f"{target}顶层组合贡献无法重构预测分: {reconstruction_errors[target]}")
    output_path.mkdir(parents=True, exist_ok=True)
    latest_path = output_path / "sector_probability_latest_15.parquet"
    date_path = output_path / f"sector_probability_{actual_date:%Y%m%d}_15.parquet"
    csv_path = output_path / "sector_probability_latest_15.csv"
    diagnostics_latest_path = output_path / "sector_signal_diagnostics_latest.parquet"
    diagnostics_date_path = output_path / f"sector_signal_diagnostics_{actual_date:%Y%m%d}.parquet"
    diagnostics_description_path = output_path / "diagnostics_field_description.json"
    probability_partitions = _write_month_partition(probabilities, output_path, "probability")
    diagnostics_partitions = _write_month_partition(diagnostics, output_path, "diagnostics")
    for path, frame in ((latest_path, probabilities), (date_path, probabilities)):
        pl.from_pandas(frame, include_index=False).write_parquet(path, compression="zstd")
    for path in (diagnostics_latest_path, diagnostics_date_path):
        pl.from_pandas(diagnostics, include_index=False).write_parquet(path, compression="zstd")
    probabilities.to_csv(csv_path, index=False, encoding="utf-8-sig")
    diagnostics_description = {
        "score_layer": {
            "score_<group>_<target>": "各因子组模型对六个连续V2变化目标的原始预测分；technical组之前的score来自18个技术子组经横截面百分位排名后的技术大组Ridge输出。",
            "score_<indicator>_<target>": "18个技术指标子组的横截面百分位预测分，例如score_ADX_delta_peak_5d。",
            "rank_<group>_<target>": "顶层Ridge实际使用的各因子组横截面百分位排名。",
        },
        "blend_layer": {
            "contrib_<group>_<target>": "顶层Ridge对连续V2预测分的组级线性贡献=组排名×Ridge系数；不是事件概率贡献。",
            "blend_intercept_<target>": "顶层Ridge截距。",
            "pred_delta_<peak_or_valley>_<horizon>": "六个连续V2变化预测分。",
            "blend_reconstruction": "pred = 截距 + 六组贡献之和；未被该目标固定选择策略使用的组贡献为0。",
        },
        "probability_layer": {
            "peak_rank_<horizon>/valley_rank_<horizon>": "连续预测分在当日板块横截面的百分位排名。",
            "direction_<horizon>": "波谷排名 - 波峰排名。",
            "direction_strength_<horizon>": "方向强度=abs(direction)，越大表示波峰/波谷方向分化越明显。",
            "level_<horizon>": "波峰、波谷排名均值 - 0.5。",
            "<horizon>_prob_<state>": "对应周期五类事件概率；每个周期五类合计为1。",
            "<horizon>_most_likely_state": "五类事件中概率最高的事件，仅作辅助标签。",
            "<horizon>_event_strength": "五类事件概率中的最大值；越高表示事件分类更集中，不等同于收益幅度。",
        },
        "scope_note": "该诊断文件展示模型分数和组级线性贡献；它不等同于因果解释，也不表示某因子单独造成了事件概率变化。",
    }
    diagnostics_description_path.write_text(json.dumps(diagnostics_description, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "version": "v1_daily_inference_15_events",
        "asof_time": actual_date.strftime("%Y-%m-%d"),
        "rows": int(len(probabilities)),
        "event_count": 15,
        "periods": {"ultra_short": "超短1-3交易日", "5d": "短期5交易日", "20d": "中期20交易日"},
        "training_or_tuning": False,
        "model_paths": {"core_blend": str(BLEND_MODEL_PATH), "state_probability": str(STATE_MODEL_PATH)},
        "files": {
        "latest": str(latest_path), "date": str(date_path), "history": str(_history_partition_root(output_path, "probability")), "csv": str(csv_path),
        "diagnostics_latest": str(diagnostics_latest_path), "diagnostics_date": str(diagnostics_date_path),
            "diagnostics_history": str(_history_partition_root(output_path, "diagnostics")),
            "diagnostics_description": str(diagnostics_description_path),
        },
        "file_sha256": {
            "latest": sha256_file(latest_path), "date": sha256_file(date_path), "csv": sha256_file(csv_path),
            "diagnostics_latest": sha256_file(diagnostics_latest_path), "diagnostics_date": sha256_file(diagnostics_date_path),
            "history_partitions": [sha256_file(path) for path in probability_partitions],
            "diagnostics_history_partitions": [sha256_file(path) for path in diagnostics_partitions],
            "diagnostics_description": sha256_file(diagnostics_description_path),
        },
        "diagnostics_rows": int(len(diagnostics)),
        "probability_history": _partition_history_stats(output_path, "probability"),
        "diagnostics_history": _partition_history_stats(output_path, "diagnostics"),
        "diagnostics_columns": int(len(diagnostics.columns)),
        "blend_reconstruction_error_max": reconstruction_errors,
    }
    (output_path / "daily_signal_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="使用已训练模型生成板块最新15事件概率")
    parser.add_argument("--asof-date", default=None, help="指定交易日；默认使用共同最新日期")
    parser.add_argument("--output-path", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--backfill-history", action="store_true", help="用已有部署期15事件概率回填每日历史")
    parser.add_argument("--backfill-all-history", action="store_true", help="用各阶段已保存预测回填完整诊断历史")
    parser.add_argument("--partitionize-existing", action="store_true", help="将旧版单文件历史迁移为按月 merged.parquet")
    args = parser.parse_args()
    if args.partitionize_existing:
        print(json.dumps(partitionize_existing_history(args.output_path), ensure_ascii=False, indent=2))
        return
    if args.backfill_all_history:
        print(json.dumps(backfill_diagnostics_history(args.output_path), ensure_ascii=False, indent=2))
        return
    if args.backfill_history:
        print(json.dumps(backfill_probability_history(args.output_path), ensure_ascii=False, indent=2))
        return
    run_daily(asof_date=args.asof_date, output_path=args.output_path)


if __name__ == "__main__":
    main()
