from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("sector_state_label_audit.py")
SPEC = importlib.util.spec_from_file_location("sector_state_label_audit", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_horizons_are_fixed() -> None:
    assert MODULE.HORIZONS == ("ultra_short", "5d", "20d")
