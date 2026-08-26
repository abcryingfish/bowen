"""对测试期五类走势概率做事后可靠性审计。

该脚本只用于测试期评估，不参与模型训练、概率校准或阈值选择。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss


DEFAULT_PROBABILITY = Path(
    "outputs/sector_peak_valley_ml/stage_ap_state_probabilities_5class/"
    "sector_state_probabilities.parquet"
)
DEFAULT_TARGET = Path(r"D:\database\sector_peak_valley_ml\targets_v1\v2_change_targets.parquet")
DEFAULT_OUTPUT = Path("outputs/sector_peak_valley_ml/stage_aq_state_probability_audit_5class")
JOIN_KEYS = ["htsc_code", "time"]
HORIZONS = ("ultra_short", "5d", "20d")
STATE_NAMES = ("波谷看涨", "波峰看跌", "双向高波", "横盘看涨", "横盘看跌")
STATE_CODES = {
    "波谷看涨": "valley_bullish",
    "波峰看跌": "peak_bearish",
    "双向高波": "two_sided_high_volatility",
    "横盘看涨": "sideways_bullish",
    "横盘看跌": "sideways_bearish",
}
WEIGHTS = {"ultra_short": 0.5, "5d": 0.3, "20d": 0.2}
TARGETS = tuple(
    f"delta_{side}_{horizon}"
    for horizon in HORIZONS
    for side in ("peak", "valley")
)


def classify_quadrant(peak_rank: pd.Series, valley_rank: pd.Series) -> pd.Series:
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


def multiclass_brier(probabilities: pd.DataFrame, labels: pd.Series) -> float:
    encoded = pd.get_dummies(labels).reindex(columns=STATE_NAMES, fill_value=0.0)
    return float(((probabilities[list(STATE_NAMES)].to_numpy() - encoded.to_numpy()) ** 2).sum(axis=1).mean())


def consensus_state(states: pd.DataFrame) -> pd.Series:
    scores = pd.DataFrame(0.0, index=states.index, columns=STATE_NAMES)
    valid_count = pd.Series(0, index=states.index, dtype="int64")
    for horizon, weight in WEIGHTS.items():
        valid_count = valid_count.add(states[f"actual_state_{horizon}"].notna().astype(int), fill_value=0)
        for state in STATE_NAMES:
            scores[state] += states[f"actual_state_{horizon}"].eq(state).astype(float) * weight
    result = pd.Series(pd.NA, index=states.index, dtype="string")
    valid = valid_count > 0
    valid_scores = scores.loc[valid].to_numpy()
    result.loc[valid] = np.asarray(STATE_NAMES, dtype=object)[valid_scores.argmax(axis=1)]
    return result


def reliability_table(
    probabilities: pd.DataFrame,
    labels: pd.Series,
    *,
    horizon: str,
    scope: str,
) -> pd.DataFrame:
    rows = []
    bins = np.linspace(0.0, 1.0, 11)
    for state in STATE_NAMES:
        probability = probabilities[state]
        observed = labels.eq(state).astype(float)
        bucket = pd.cut(probability, bins=bins, include_lowest=True, labels=False)
        for bucket_id, block in pd.DataFrame({"probability": probability, "observed": observed, "bucket": bucket}).groupby("bucket", dropna=True):
            if block.empty:
                continue
            rows.append({
                "scope": scope,
                "horizon": horizon,
                "state": state,
                "probability_bin": int(bucket_id) + 1,
                "predicted_mean": float(block.probability.mean()),
                "observed_rate": float(block.observed.mean()),
                "rows": int(len(block)),
            })
    return pd.DataFrame(rows)


def _metrics(probabilities: pd.DataFrame, labels: pd.Series, *, horizon: str, scope: str) -> dict[str, object]:
    valid = labels.notna() & probabilities[list(STATE_NAMES)].notna().all(axis=1)
    probabilities = probabilities.loc[valid, list(STATE_NAMES)]
    labels = labels.loc[valid]
    if probabilities.empty or labels.nunique() < 2:
        raise ValueError(f"{scope}/{horizon}有效样本不足")
    predicted = probabilities.idxmax(axis=1)
    encoded_labels = labels.map({state: index for index, state in enumerate(STATE_NAMES)})
    return {
        "scope": scope,
        "horizon": horizon,
        "rows": int(len(labels)),
        "log_loss": float(log_loss(encoded_labels, probabilities, labels=list(range(len(STATE_NAMES))))),
        "multiclass_brier": multiclass_brier(probabilities, labels),
        "top1_accuracy": float(predicted.eq(labels).mean()),
        "mean_max_probability": float(probabilities.max(axis=1).mean()),
    }


def run_audit(*, probability_path: Path = DEFAULT_PROBABILITY, target_path: Path = DEFAULT_TARGET, output_path: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    probabilities = pd.read_parquet(probability_path)
    target = pd.read_parquet(target_path, columns=[*JOIN_KEYS, *TARGETS])
    for frame in (probabilities, target):
        frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
        frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    frame = probabilities.merge(target, on=JOIN_KEYS, how="inner", validate="one_to_one")
    frame["year"] = frame["time"].dt.year
    actual_states = {}
    for horizon in HORIZONS:
        peak_rank = frame[f"delta_peak_{horizon}"].groupby(frame["time"]).rank(method="average", pct=True)
        valley_rank = frame[f"delta_valley_{horizon}"].groupby(frame["time"]).rank(method="average", pct=True)
        actual_states[horizon] = classify_quadrant(peak_rank, valley_rank)
        frame[f"actual_state_{horizon}"] = actual_states[horizon]
    frame["actual_state_consensus"] = consensus_state(frame)

    metrics = []
    reliability = []
    for horizon in HORIZONS:
        probability_columns = [f"prob_{horizon}_{STATE_CODES[state]}" for state in STATE_NAMES]
        probability_frame = frame[probability_columns].copy()
        probability_frame.columns = STATE_NAMES
        labels = frame[f"actual_state_{horizon}"]
        metrics.append(_metrics(probability_frame, labels, horizon=horizon, scope="overall"))
        reliability.append(reliability_table(probability_frame, labels, horizon=horizon, scope="overall"))
        for year, block in frame.groupby("year", sort=True):
            p = block[probability_columns].copy()
            p.columns = STATE_NAMES
            metrics.append(_metrics(p, block[f"actual_state_{horizon}"], horizon=horizon, scope=str(year)))
            reliability.append(reliability_table(p, block[f"actual_state_{horizon}"], horizon=horizon, scope=str(year)))

    consensus_columns = [f"prob_consensus_{STATE_CODES[state]}" for state in STATE_NAMES]
    consensus_probabilities = frame[consensus_columns].copy()
    consensus_probabilities.columns = STATE_NAMES
    metrics.append(_metrics(consensus_probabilities, frame["actual_state_consensus"], horizon="consensus", scope="overall"))
    reliability.append(reliability_table(consensus_probabilities, frame["actual_state_consensus"], horizon="consensus", scope="overall"))
    for year, block in frame.groupby("year", sort=True):
        p = block[consensus_columns].copy()
        p.columns = STATE_NAMES
        metrics.append(_metrics(p, block["actual_state_consensus"], horizon="consensus", scope=str(year)))
        reliability.append(reliability_table(p, block["actual_state_consensus"], horizon="consensus", scope=str(year)))

    output_path.mkdir(parents=True, exist_ok=True)
    metrics_frame = pd.DataFrame(metrics)
    reliability_frame = pd.concat(reliability, ignore_index=True)
    metrics_frame.to_csv(output_path / "state_probability_metrics.csv", index=False, encoding="utf-8-sig")
    reliability_frame.to_csv(output_path / "state_probability_reliability.csv", index=False, encoding="utf-8-sig")
    distributions = {
        f"actual_state_{horizon}": {
            str(key): int(value)
            for key, value in frame[f"actual_state_{horizon}"].value_counts(dropna=False).items()
        }
        for horizon in (*HORIZONS, "consensus")
    }
    manifest = {
        "version": "v2_five_state_retrospective_test_audit",
        "probability_input": str(probability_path),
        "target_input": str(target_path),
        "test_only": True,
        "used_for_training_or_tuning": False,
        "rows_joined": int(len(frame)),
        "metrics": str(output_path / "state_probability_metrics.csv"),
        "reliability": str(output_path / "state_probability_reliability.csv"),
        "distributions": distributions,
    }
    (output_path / "state_probability_audit_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="审计测试期五类走势概率")
    parser.add_argument("--probability-path", type=Path, default=DEFAULT_PROBABILITY)
    parser.add_argument("--target-path", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT)
    run_audit(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
