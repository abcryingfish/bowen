from models.style_portfolio_monitor.smoke_check import build_parser, validate_smoke_result


def test_smoke_script_is_read_only_by_default_and_requires_explicit_write_flag():
    args = build_parser().parse_args([])
    assert args.write is False
    assert args.model_ids == []


def test_smoke_validation_requires_two_legs_and_balanced_accounting():
    valid = {"legs": {"high": {"cash": 100, "market_value": 900, "total_asset": 1000}, "low": {"cash": 200, "market_value": 800, "total_asset": 1000}}}
    assert validate_smoke_result(valid)["ok"] is True
    valid["legs"]["high"]["cash"] = -1
    assert validate_smoke_result(valid)["ok"] is False
