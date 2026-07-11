import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "可视化" / "market_data_service.py"
sys.path.append(str(MODULE_PATH.parent))

spec = importlib.util.spec_from_file_location("market_data_service_under_test", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


with patch.object(module, "_stock_universe_codes", return_value=["000001.SZ", "000002.SZ"]):
    with patch.object(module, "_get_cached_codes") as cached_codes:
        result = module._get_factor_export_rank_codes()
        assert result == ["000001.SZ", "000002.SZ"]
        cached_codes.assert_not_called()

with patch.object(module, "_stock_universe_codes", return_value=[]):
    with patch.object(module, "_get_cached_codes", return_value=["000003.SZ"]) as cached_codes:
        result = module._get_factor_export_rank_codes()
        assert result == ["000003.SZ"]
        cached_codes.assert_called_once_with(module.DAILY_BASE_PATH)

print("factor export rank code source tests passed")
