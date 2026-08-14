from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SCRIPT_PATH = Path(__file__).with_name("ZXW策略技术因子生成.py")


def _load_validator():
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8-sig"), filename=str(SCRIPT_PATH))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef)
        and item.name == "_validate_and_strip_adj_factor"
    )
    namespace = {"pd": pd, "np": np}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SCRIPT_PATH), "exec"), namespace)
    return namespace["_validate_and_strip_adj_factor"]


def test_non_stock_rows_do_not_require_stock_adjustment_factor() -> None:
    validate = _load_validator()
    frame = pd.DataFrame(
        {
            "htsc_code": ["000001.SH", "510300.SH"],
            "_zxw_adj_factor": [np.nan, np.nan],
        }
    )

    result = validate(frame, {"000001.SZ"})

    assert "_zxw_adj_factor" not in result.columns


def test_stock_rows_still_require_valid_adjustment_factor() -> None:
    validate = _load_validator()
    frame = pd.DataFrame(
        {
            "htsc_code": ["000001.SZ", "000002.SZ"],
            "_zxw_adj_factor": [1.25, np.nan],
        }
    )

    with pytest.raises(ValueError, match="000002.SZ"):
        validate(frame, {"000001.SZ", "000002.SZ"})


def test_market_sql_keeps_unadjusted_prices_when_factor_is_absent() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8-sig")
    assert "d.open * COALESCE(a.adj_factor, 1.0) AS open" in source
    assert "frame = _validate_and_strip_adj_factor(frame, _stock_source_code_set)" in source
