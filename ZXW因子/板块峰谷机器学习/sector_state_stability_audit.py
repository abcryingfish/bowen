"""审计板块五类状态标签的跨周期一致性与时间稳定性。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_LABEL_PATH = Path("outputs/sector_peak_valley_ml/stage_an_state_labels_5class/sector_state_labels.parquet")
DEFAULT_OUTPUT_PATH = Path("outputs/sector_peak_valley_ml/stage_at_state_stability_audit_5class")
HORIZONS = ("ultra_short", "5d", "20d")
STATE_COLUMNS = tuple(f"state_{horizon}" for horizon in HORIZONS)


def load_labels(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    required = {"htsc_code", "time", "sector_family", *STATE_COLUMNS, "state_consensus", "state_consensus_agreement"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"状态标签缺少字段: {sorted(missing)}")
    frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    if frame[["htsc_code", "time"]].isna().any().any() or frame.duplicated(["htsc_code", "time"]).any():
        raise ValueError("状态标签主键为空或重复")
    return frame.sort_values(["htsc_code", "time"]).reset_index(drop=True)


def pairwise_agreement(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for left_index, left in enumerate(HORIZONS):
        for right in HORIZONS[left_index + 1 :]:
            same = frame[f"state_{left}"].eq(frame[f"state_{right}"])
            rows.append({"left_horizon": left, "right_horizon": right, "agreement_rate": float(same.mean()), "rows": int(same.notna().sum())})
    return pd.DataFrame(rows)


def transition_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for horizon in [*HORIZONS, "consensus"]:
        column = f"state_{horizon}"
        ordered = frame[["htsc_code", "time", column]].sort_values(["htsc_code", "time"]).copy()
        ordered["previous_time"] = ordered.groupby("htsc_code")["time"].shift(1)
        ordered["previous_state"] = ordered.groupby("htsc_code")[column].shift(1)
        # 允许周末/停牌间隔，但把真正的缺失日期从连续状态统计中排除。
        ordered["is_transition_observation"] = ordered["previous_state"].notna()
        ordered["is_transition"] = ordered["is_transition_observation"] & ordered[column].ne(ordered["previous_state"])
        transitions = ordered.loc[ordered["is_transition_observation"]]
        runs = []
        for _, group in ordered.groupby("htsc_code", sort=False):
            values = group[column].dropna().tolist()
            if not values:
                continue
            current = values[0]
            length = 1
            for value in values[1:]:
                if value == current:
                    length += 1
                else:
                    runs.append(length)
                    current, length = value, 1
            runs.append(length)
        rows.append({
            "horizon": horizon,
            "rows": int(len(ordered)),
            "transition_observations": int(len(transitions)),
            "transition_count": int(transitions["is_transition"].sum()),
            "transition_rate": float(transitions["is_transition"].mean()) if len(transitions) else np.nan,
            "median_run_length": float(np.median(runs)) if runs else np.nan,
            "mean_run_length": float(np.mean(runs)) if runs else np.nan,
            "p90_run_length": float(np.quantile(runs, 0.9)) if runs else np.nan,
        })
    return pd.DataFrame(rows)


def transition_by_family(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for horizon in [*HORIZONS, "consensus"]:
        column = f"state_{horizon}"
        for family, group in frame.groupby("sector_family", sort=True):
            ordered = group.sort_values(["htsc_code", "time"]).copy()
            previous = ordered.groupby("htsc_code")[column].shift(1)
            valid = previous.notna()
            rows.append({"horizon": horizon, "sector_family": family, "transition_observations": int(valid.sum()), "transition_count": int((valid & ordered[column].ne(previous)).sum()), "transition_rate": float((valid & ordered[column].ne(previous)).sum() / valid.sum()) if valid.sum() else np.nan})
    return pd.DataFrame(rows)


def run_audit(*, label_path: Path = DEFAULT_LABEL_PATH, output_path: Path = DEFAULT_OUTPUT_PATH) -> dict[str, object]:
    frame = load_labels(label_path)
    pairwise = pairwise_agreement(frame)
    stability = transition_summary(frame)
    family = transition_by_family(frame)
    agreement_distribution = frame["state_consensus_agreement"].value_counts(normalize=True).sort_index().to_dict()
    output_path.mkdir(parents=True, exist_ok=True)
    pairwise.to_csv(output_path / "state_pairwise_agreement.csv", index=False, encoding="utf-8-sig")
    stability.to_csv(output_path / "state_transition_summary.csv", index=False, encoding="utf-8-sig")
    family.to_csv(output_path / "state_transition_by_family.csv", index=False, encoding="utf-8-sig")
    report = {
        "version": "v2_five_state",
        "label_path": str(label_path),
        "rows": int(len(frame)),
        "pairwise_agreement": pairwise.to_dict(orient="records"),
        "stability": stability.to_dict(orient="records"),
        "consensus_agreement_distribution": {str(key): float(value) for key, value in agreement_distribution.items()},
        "outputs": {"pairwise": str(output_path / "state_pairwise_agreement.csv"), "stability": str(output_path / "state_transition_summary.csv"), "family": str(output_path / "state_transition_by_family.csv")},
    }
    (output_path / "state_stability_manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="审计板块状态标签稳定性")
    parser.add_argument("--label-path", type=Path, default=DEFAULT_LABEL_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    run_audit(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
