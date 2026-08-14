from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.mark.parametrize(
    ("module_name", "window", "factor_dir"),
    [
        ("生成5日动量因子", 5, "factor=stock_momentum_5d"),
        ("生成20日动量因子", 20, "factor=stock_momentum_20d"),
    ],
)
def test_stock_momentum_scripts_use_adjusted_close_and_isolated_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    window: int,
    factor_dir: str,
) -> None:
    module = importlib.import_module(module_name)
    dates = pd.bdate_range("2026-01-01", periods=35)
    prices = pd.DataFrame(
        {"000001.SZ": np.arange(100.0, 135.0)},
        index=dates,
    )
    captured: dict[str, object] = {}

    def fake_load_adjusted_close(**kwargs):
        captured.update(kwargs)
        return prices

    output_dir = tmp_path / factor_dir
    monkeypatch.setattr(module, "load_adjusted_close", fake_load_adjusted_close)
    monkeypatch.setattr(module, "OUTPUT_DIR", output_dir)

    result = module.rebuild_factor(start_date=dates[window], end_date=dates[-1])
    files = sorted(output_dir.rglob("merged.parquet"))
    actual = pd.concat([pd.read_parquet(path) for path in files], ignore_index=True)
    expected = prices.div(prices.shift(window)).sub(1.0).loc[dates[window]:]
    expected = expected.rename_axis("time").stack(future_stack=True).rename("value").reset_index()
    expected.columns = ["time", "htsc_code", "value"]

    assert result["rows"] == len(expected)
    assert files
    assert captured["start_date"] < dates[window]
    pd.testing.assert_frame_equal(
        actual.sort_values(["time", "htsc_code"]).reset_index(drop=True),
        expected.sort_values(["time", "htsc_code"]).reset_index(drop=True),
    )


def test_generator_builds_stock_momentum_before_publishing_watermark() -> None:
    source = (Path(__file__).resolve().parent / "ZXW策略技术因子生成.py").read_text(encoding="utf-8")

    five_day_call = source.index("rebuild_stock_momentum_5d(")
    twenty_day_call = source.index("rebuild_stock_momentum_20d(")
    watermark_call = source.index("_finalize_factor_batch(", twenty_day_call)
    monitor_call = source.index("run_after_factor_generation(", watermark_call)

    assert five_day_call < watermark_call < monitor_call
    assert twenty_day_call < watermark_call < monitor_call
    assert 'return "2010-01-01"' in source
    assert "to_period(\"M\").start_time" in source
    assert "if _stock_momentum_5d_start is not None" in source
    assert "if _stock_momentum_20d_start is not None" in source
