"""蜡烛图（无成交量）形态元数据：强度分档、K 线跨度、manifest。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LEVEL1_MAX = 0.5
LEVEL2_MAX = 0.7

MORPH_SOURCE_KEY = "candlestick_no_vol"
MANIFEST_FILE_NAME = "morph_candlestick_manifest.json"

SIGNAL_BAR_SPAN: dict[str, int] = {
    "harami_bullish": 2,
    "harami_bearish": 2,
    "morning_star_doji": 3,
    "hammer": 1,
    "hanging_man": 1,
    "engulfing_bullish": 2,
    "engulfing_bearish": 2,
    "dark_cloud_cover": 2,
    "piercing": 2,
    "morning_star": 3,
    "evening_star": 3,
    "evening_star_doji": 3,
    "abandoned_baby_bullish": 3,
    "abandoned_baby_bearish": 3,
    "harami_doji_bullish": 2,
    "harami_doji_bearish": 2,
    "tweezers_top": 2,
    "tweezers_bottom": 2,
    "belt_hold_bullish": 1,
    "belt_hold_bearish": 1,
    "counterattack_bullish": 2,
    "counterattack_bearish": 2,
    "two_crows": 3,
    "three_crows": 3,
    "three_white_soldiers": 3,
    "tower_top": 3,
    "tower_bottom": 3,
    "three_mountains": 3,
    "three_rivers": 3,
    "rising_three_methods": 5,
    "falling_three_methods": 5,
    "bullish_marubozu": 2,
    "bearish_marubozu": 2,
    "pregnant_marubozu": 2,
    "tombstone_marubozu": 2,
    "three_inside_up": 3,
    "three_inside_down": 3,
    "doji_pause": 3,
    "golden_needle_bottom": 1,
    "rocket_launch": 1,
    "man_jiang_hong": 10,
    "hanging_man_enhanced": 1,
    "heaven_line": 1,
    "dark_cloud_line": 2,
    "same_low_price": 2,
    "takuri": 1,
    "false_breakout_trap_bullish": 2,
    "false_breakout_trap_bearish": 2,
    "short_body_candle_bullish": 1,
    "short_body_candle_bearish": 1,
    "long_legged_doji_bullish": 1,
    "long_legged_doji_bearish": 1,
    "three_outside_up": 3,
    "three_outside_down": 3,
    "marubozu_bullish": 1,
    "marubozu_bearish": 1,
    "spinning_top_bullish": 1,
    "spinning_top_bearish": 1,
    "high_wave_bullish": 1,
    "high_wave_bearish": 1,
    "homing_pigeon_bullish": 2,
    "homing_pigeon_bearish": 2,
    "same_high_price": 2,
}


def strength_to_level(strength: float) -> str:
    magnitude = abs(float(strength))
    if magnitude < LEVEL1_MAX:
        return "level1"
    if magnitude < LEVEL2_MAX:
        return "level2"
    return "level3"


def get_bar_span(signal_name: str, default: int = 1) -> int:
    return max(1, int(SIGNAL_BAR_SPAN.get(str(signal_name), default)))


def build_pattern_manifest(signal_strength: dict[str, float]) -> dict[str, Any]:
    patterns: dict[str, Any] = {}
    for name, strength in sorted(signal_strength.items()):
        signed = float(strength)
        patterns[name] = {
            "level": strength_to_level(signed),
            "bar_span": get_bar_span(name),
            "default_strength": signed,
            "direction": "buy" if signed > 0 else "sell" if signed < 0 else "neutral",
        }
    return {
        "schema_version": 1,
        "source": MORPH_SOURCE_KEY,
        "level_rules": {
            "level1": f"0.1 <= abs(strength) < {LEVEL1_MAX}",
            "level2": f"{LEVEL1_MAX} <= abs(strength) < {LEVEL2_MAX}",
            "level3": f"abs(strength) >= {LEVEL2_MAX}",
        },
        "patterns": patterns,
    }


def patterns_for_level(manifest: dict[str, Any], level: str) -> list[str]:
    level_key = str(level or "").strip()
    patterns = manifest.get("patterns") or {}
    return sorted(
        name
        for name, meta in patterns.items()
        if isinstance(meta, dict) and str(meta.get("level") or "") == level_key
    )


def write_manifest(manifest: dict[str, Any], base_dir: Path) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / MANIFEST_FILE_NAME
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_manifest(base_dir: Path) -> dict[str, Any]:
    path = base_dir / MANIFEST_FILE_NAME
    if not path.is_file():
        return {"schema_version": 1, "source": MORPH_SOURCE_KEY, "patterns": {}}
    return json.loads(path.read_text(encoding="utf-8"))
