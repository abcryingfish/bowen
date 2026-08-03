from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parent
ZXW_FACTOR_DIR = PROJECT_ROOT / "ZXW因子"


def _load_hong_module(relative_path: str, module_name: str):
    sys.path.insert(0, str(ZXW_FACTOR_DIR))
    try:
        path = PROJECT_ROOT / relative_path
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(ZXW_FACTOR_DIR))


@pytest.fixture(params=[
    ("ZXW因子/洪抄底.py", "hong_bottom_main"),
    ("ZXW因子-股票池ETF分类/洪抄底.py", "hong_bottom_etf"),
])
def hong_module(request):
    relative_path, module_name = request.param
    return _load_hong_module(relative_path, module_name)


def _build_bundle(module, lows: list[float], highs: list[float] | None = None):
    index = pd.RangeIndex(len(lows))
    columns = ["TEST"]
    low = pd.DataFrame({"TEST": lows}, index=index, dtype=float)
    high = pd.DataFrame({"TEST": highs if highs is not None else lows}, index=index, dtype=float)
    return module.build_bottom_fishing_factor_bundle(O=low, H=high, L=low, C=low)


def test_ultra_mini_bottom_starts_on_fourth_row_and_scores_point_25(hong_module):
    bundle = _build_bundle(hong_module, [103, 104, 105, 100])

    ultra = bundle["factor_dfs"]["hong_ultra_mini_bottom"]["TEST"]
    score = bundle["factor_dfs"]["hong_bottom_fishing_score"]["TEST"]

    assert ultra.tolist() == [False, False, False, True]
    assert score.tolist() == [0.0, 0.0, 0.0, 0.25]
    assert bundle["factor_name_map"]["洪超迷你底"] == "hong_ultra_mini_bottom"


def test_ultra_mini_bottom_expires_at_exactly_five_percent_rebound(hong_module):
    bundle = _build_bundle(
        hong_module,
        lows=[103, 104, 105, 100, 102, 101],
        highs=[103, 104, 105, 100, 104.9, 105],
    )

    score = bundle["factor_dfs"]["hong_bottom_fishing_score"]["TEST"]

    assert score.iloc[4] == pytest.approx(0.25)
    assert score.iloc[5] == 0.0


def test_mini_bottom_keeps_point_5_priority_over_ultra_mini(hong_module):
    bundle = _build_bundle(hong_module, [110, 111, 112, 113, 114, 115, 116, 100])

    factors = bundle["factor_dfs"]
    assert bool(factors["hong_ultra_mini_bottom"].iloc[-1, 0]) is True
    assert bool(factors["hong_mini_bottom"].iloc[-1, 0]) is True
    assert factors["hong_bottom_fishing_score"].iloc[-1, 0] == pytest.approx(0.5)


def test_ultra_mini_bottom_is_registered_for_catalog_and_frontends():
    catalog = json.loads((PROJECT_ROOT / "因子分类/factor_catalog.json").read_text(encoding="utf-8"))
    hong_group = next(group for group in catalog["groups"] if group["group_id"] == "hong_bottom_fishing_class")
    assert "洪超迷你底" in hong_group["children"]

    for relative_path in (
        "可视化/market_data_service.py",
        "可视化/量化因子有效性检验/factor_validation_service.py",
    ):
        source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert '"洪超迷你底": ("hong_ultra_mini_bottom",)' in source
