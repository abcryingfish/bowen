from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).with_name("sector_state_stability_audit.py")
SPEC = importlib.util.spec_from_file_location("sector_state_stability_audit", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_pairwise_agreement() -> None:
    frame = pd.DataFrame({
        "state_ultra_short": ["A", "A", "B"],
        "state_5d": ["A", "B", "B"],
        "state_20d": ["A", "B", "A"],
    })
    result = MODULE.pairwise_agreement(frame)
    assert result.loc[0, "agreement_rate"] == 2 / 3
