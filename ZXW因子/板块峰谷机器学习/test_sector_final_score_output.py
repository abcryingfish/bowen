from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).with_name("sector_final_score_output.py")
SPEC = importlib.util.spec_from_file_location("sector_final_score_output", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_direction_score_is_valley_rank_minus_peak_rank(tmp_path: Path) -> None:
    rows = []
    for code, peak, valley in (("881001", 1.0, 3.0), ("881002", 2.0, 2.0), ("881003", 3.0, 1.0)):
        row = {"htsc_code": code, "time": "2026-01-02", "sector_family": "881"}
        for target in MODULE.TARGETS:
            row[f"pred_{target}"] = peak if "peak" in target else valley
        rows.append(row)
    source = tmp_path / "input.parquet"
    pd.DataFrame(rows).to_parquet(source, index=False)
    manifest = MODULE.build_final_scores(source, tmp_path / "out")
    result = pd.read_parquet(tmp_path / "out" / "sector_final_scores.parquet")
    assert manifest["rows"] == 3
    assert result.loc[0, "direction_score_ultra_short"] > 0
    assert result.loc[2, "direction_score_ultra_short"] < 0
