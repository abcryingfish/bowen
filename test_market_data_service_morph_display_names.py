from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
SERVICE_FILE = ROOT / "可视化" / "market_data_service.py"
sys.path.append(str(SERVICE_FILE.parent))
spec = importlib.util.spec_from_file_location("market_data_service_morph_labels", SERVICE_FILE)
assert spec and spec.loader
service = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = service
spec.loader.exec_module(service)


def test_morph_pattern_display_names_use_manifest_and_fallback() -> None:
    manifest = {
        "patterns": {
            "piercing": {"level": "level3", "display_name": "刺透形态"},
            "unknown_pattern": {"level": "level3"},
        }
    }

    assert service._morph_pattern_display_names(
        manifest,
        ["piercing", "unknown_pattern"],
    ) == {
        "piercing": "刺透形态",
        "unknown_pattern": "unknown_pattern",
    }


def test_morph_event_display_name_uses_same_mapping() -> None:
    manifest = {"patterns": {"piercing": {"display_name": "刺透形态"}}}

    assert service._morph_event_display_name(manifest, "piercing") == "刺透形态"
    assert service._morph_event_display_name(manifest, "unknown_pattern") == "unknown_pattern"
