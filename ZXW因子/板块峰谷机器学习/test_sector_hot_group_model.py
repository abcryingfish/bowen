"""热点短历史切分测试。"""
from __future__ import annotations
import importlib.util
from pathlib import Path
import pandas as pd
_PATH=Path(__file__).with_name('sector_hot_group_model.py')
_SPEC=importlib.util.spec_from_file_location('sector_hot_group_model',_PATH); assert _SPEC and _SPEC.loader
_M=importlib.util.module_from_spec(_SPEC); _SPEC.loader.exec_module(_M)
def test_purge_is_before_split():
    dates=pd.bdate_range('2025-08-01',periods=150); split=dates[100]
    assert _M.purge_train_end(dates,split,43)==dates[56]
