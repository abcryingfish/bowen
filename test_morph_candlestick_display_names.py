from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PATTERN_FILE = ROOT / "形态趋势通道因子" / "蜡烛图无成交量.py"
META_FILE = ROOT / "形态趋势通道因子" / "morph_candlestick_meta.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pattern_names_have_complete_unique_chinese_display_names() -> None:
    pattern_module = _load_module("candlestick_patterns_display", PATTERN_FILE)
    meta_module = _load_module("candlestick_metadata_display", META_FILE)
    signal_names = set(pattern_module.Pattern().signal_strength)

    assert set(meta_module.SIGNAL_DISPLAY_NAME_ZH) == signal_names
    labels = list(meta_module.SIGNAL_DISPLAY_NAME_ZH.values())
    assert all(label.strip() for label in labels)
    assert len(labels) == len(set(labels))
    assert meta_module.SIGNAL_DISPLAY_NAME_ZH["engulfing_bullish"] == "看涨吞没"
    assert meta_module.SIGNAL_DISPLAY_NAME_ZH["three_crows"] == "三只乌鸦"


def test_manifest_contains_utf8_display_names(tmp_path: Path) -> None:
    meta_module = _load_module("candlestick_metadata_manifest_display", META_FILE)
    manifest = meta_module.build_pattern_manifest({"piercing": 0.7})
    path = meta_module.write_manifest(manifest, tmp_path)

    assert manifest["patterns"]["piercing"]["display_name"] == "刺透形态"
    assert "刺透形态" in path.read_text(encoding="utf-8")

