"""技术子组面板生成器的确定性测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


_MODULE_PATH = Path(__file__).with_name("sector_technical_subgroup_stage.py")
_SPEC = importlib.util.spec_from_file_location(
    "sector_technical_subgroup_stage", _MODULE_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

audit_subgroup = _MODULE.audit_subgroup
build_market_matrices = _MODULE.build_market_matrices
extract_target_rows = _MODULE.extract_target_rows


def test_extract_target_rows_follows_key_order_and_keeps_missing() -> None:
    matrix = pd.DataFrame(
        [[1.0, 2.0], [3.0, 4.0]],
        index=pd.to_datetime(["2025-01-02", "2025-01-03"]),
        columns=["881001", "885001"],
    )
    keys = pd.DataFrame(
        {
            "htsc_code": ["885001", "881001", "886999"],
            "time": pd.to_datetime(["2025-01-03", "2025-01-02", "2025-01-02"]),
        }
    )
    values = extract_target_rows(matrix, keys)
    assert np.allclose(values[:2], [4.0, 1.0])
    assert np.isnan(values[2])


def test_build_market_matrices_preserves_invalid_bar_mask() -> None:
    market = pd.DataFrame(
        {
            "htsc_code": ["881001", "881001", "885001"],
            "time": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-03"]),
            "open": [10.0, 11.0, 20.0],
            "high": [11.0, 12.0, 21.0],
            "low": [9.0, 10.0, 19.0],
            "close": [10.5, 11.5, 20.5],
            "volume": [100.0, 110.0, 200.0],
        }
    )
    matrices, valid = build_market_matrices(market)
    assert not valid.loc[pd.Timestamp("2025-01-02"), "885001"]
    assert valid.loc[pd.Timestamp("2025-01-03"), "885001"]
    assert matrices["volume"].loc[pd.Timestamp("2025-01-02"), "885001"] == 0.0


def test_audit_subgroup_only_hard_excludes_constant_and_future_name() -> None:
    frame = pd.DataFrame(
        {
            "valid": [0.0, 1.0, np.nan],
            "constant": [1.0, 1.0, 1.0],
            "future_signal": [0.0, 1.0, 2.0],
        }
    )
    audit, report = audit_subgroup(
        frame, "TEST", ["valid", "constant", "future_signal"]
    )
    eligible = set(audit.loc[audit["eligible_for_model"], "feature"])
    assert eligible == {"valid"}
    assert report["eligible_features"] == 1
