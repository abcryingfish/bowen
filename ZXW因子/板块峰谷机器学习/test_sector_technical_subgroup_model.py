"""技术子组LightGBM训练切分的确定性测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


_MODULE_PATH = Path(__file__).with_name("sector_technical_subgroup_model.py")
_SPEC = importlib.util.spec_from_file_location(
    "sector_technical_subgroup_model", _MODULE_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

make_oof_splits = _MODULE.make_oof_splits
purge_train_end = _MODULE.purge_train_end


def test_purge_train_end_uses_trading_sequence() -> None:
    dates = pd.bdate_range("2022-01-03", periods=100)
    boundary = dates[80]
    assert purge_train_end(dates, boundary, 10) == dates[69]


def test_oof_splits_keep_requested_gap_and_no_2023_validation() -> None:
    dates = pd.bdate_range("2016-01-01", "2023-02-01")
    splits = make_oof_splits(dates, 43)
    assert [split["year"] for split in splits] == [2019, 2020, 2021, 2022]
    for split in splits:
        prior = dates[dates < split["validation_start"]]
        assert split["train_end"] == prior[-44]
        assert split["train_end"] < split["validation_start"]
