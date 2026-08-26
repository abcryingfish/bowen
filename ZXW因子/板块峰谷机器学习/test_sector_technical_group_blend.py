"""技术大组分数合成与评价的确定性测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


_MODULE_PATH = Path(__file__).with_name("sector_technical_group_blend.py")
_SPEC = importlib.util.spec_from_file_location("sector_technical_group_blend", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

evaluate_quintiles = _MODULE.evaluate_quintiles
purge_train_end = _MODULE.purge_train_end


def test_meta_purge_uses_required_number_of_prior_trading_dates() -> None:
    dates = pd.bdate_range("2019-01-01", "2023-01-10")
    prior = dates[dates < pd.Timestamp("2023-01-01")]
    assert purge_train_end(dates, pd.Timestamp("2023-01-01"), 60) == prior[-61]


def test_prediction_quintiles_follow_increasing_actual() -> None:
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(["2023-01-03"] * 100),
            "actual": np.arange(100, dtype=float),
            "prediction": np.arange(100, dtype=float),
        }
    )
    result = evaluate_quintiles(frame, "actual", "prediction").set_index("quintile")
    assert result.loc[5, "mean"] > result.loc[1, "mean"]
    assert result["valid_days"].eq(1).all()
