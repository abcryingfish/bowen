"""审计五类状态标签与未来V2变化目标的关系。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


DEFAULT_LABEL_PATH = Path("outputs/sector_peak_valley_ml/stage_an_state_labels_5class/sector_state_labels.parquet")
DEFAULT_TARGET_PATH = Path(r"D:\database\sector_peak_valley_ml\targets_v1\v2_change_targets.parquet")
DEFAULT_OUTPUT_PATH = Path("outputs/sector_peak_valley_ml/stage_as_state_label_audit_5class")
HORIZONS = ("ultra_short", "5d", "20d")
FAMILIES = ("881", "885", "886")


def run_audit(*, label_path: Path = DEFAULT_LABEL_PATH, target_path: Path = DEFAULT_TARGET_PATH, output_path: Path = DEFAULT_OUTPUT_PATH) -> dict[str, object]:
    labels = pd.read_parquet(label_path)
    targets = pd.read_parquet(target_path, columns=["htsc_code", "time", *(f"delta_{side}_{horizon}" for horizon in HORIZONS for side in ("peak", "valley"))])
    for frame in (labels, targets):
        frame["htsc_code"] = frame["htsc_code"].astype(str).str.strip().str.upper()
        frame["time"] = pd.to_datetime(frame["time"], errors="coerce").dt.floor("D")
    frame = labels.merge(targets, on=["htsc_code", "time"], how="inner", validate="one_to_one")
    frame["year"] = frame["time"].dt.year
    rows = []
    for horizon in HORIZONS:
        state_col = f"state_{horizon}"
        direction = frame[f"delta_valley_{horizon}"] - frame[f"delta_peak_{horizon}"]
        for (year, state), block in frame.groupby(["year", state_col], dropna=False):
            rows.append({"breakdown": "year", "breakdown_value": int(year), "horizon": horizon, "state": state, "rows": len(block), "peak_mean": block[f"delta_peak_{horizon}"].mean(), "valley_mean": block[f"delta_valley_{horizon}"].mean(), "direction_mean": direction.loc[block.index].mean()})
        for state, block in frame.groupby(state_col, dropna=False):
            rows.append({"breakdown": "overall", "breakdown_value": "all", "horizon": horizon, "state": state, "rows": len(block), "peak_mean": block[f"delta_peak_{horizon}"].mean(), "valley_mean": block[f"delta_valley_{horizon}"].mean(), "direction_mean": direction.loc[block.index].mean()})
        for family, block_family in frame.groupby("sector_family"):
            for state, block in block_family.groupby(state_col, dropna=False):
                rows.append({"breakdown": "sector_family", "breakdown_value": family, "horizon": horizon, "state": state, "rows": len(block), "peak_mean": block[f"delta_peak_{horizon}"].mean(), "valley_mean": block[f"delta_valley_{horizon}"].mean(), "direction_mean": direction.loc[block.index].mean()})
    metrics = pd.DataFrame(rows)
    output_path.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(output_path / "state_label_metrics.csv", index=False, encoding="utf-8-sig")
    distributions = frame[[f"state_{h}" for h in HORIZONS] + ["state_consensus"]].apply(lambda s: s.value_counts(dropna=False).to_dict()).to_dict()
    report = {"version": "v2_five_state", "label_path": str(label_path), "target_path": str(target_path), "rows": len(frame), "metrics": str(output_path / "state_label_metrics.csv"), "distributions": distributions}
    (output_path / "state_label_audit_manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="审计板块五类状态标签")
    parser.add_argument("--label-path", type=Path, default=DEFAULT_LABEL_PATH)
    parser.add_argument("--target-path", type=Path, default=DEFAULT_TARGET_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    run_audit(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
