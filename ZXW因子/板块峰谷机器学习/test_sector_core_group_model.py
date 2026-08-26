"""四个长期组模型的确定性测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

_PATH = Path(__file__).with_name("sector_core_group_model.py")
_SPEC = importlib.util.spec_from_file_location("sector_core_group_model", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_M = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_M)


def test_purge_is_trading_day_based():
    dates = pd.bdate_range("2022-01-03", periods=100)
    assert _M.purge_train_end(dates, dates[80], 10) == dates[69]


def test_group_and_target_counts_are_fixed():
    assert len(_M.GROUPS) == 4
    assert len(_M.TARGETS) == 6
