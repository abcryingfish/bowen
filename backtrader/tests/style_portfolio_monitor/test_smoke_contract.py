from models.style_portfolio_monitor.smoke_check import build_parser, validate_smoke_result


def test_smoke_script_is_read_only_by_default_and_requires_explicit_write_flag():
    args = build_parser().parse_args([])
    assert args.write is False
    assert args.model_ids == []


def test_smoke_validation_requires_successful_theoretical_index_output():
    valid = {"completed_models": ["growth_raw"], "failed_models": [], "processed_days": {"growth_raw": 1}}
    assert validate_smoke_result(valid)["ok"] is True
    valid["failed_models"] = [{"model_id": "growth_raw", "message": "失败"}]
    assert validate_smoke_result(valid)["ok"] is False


def test_smoke_validation_accepts_model_already_at_target_date():
    result = {
        "completed_models": ["growth_raw"],
        "skipped_models": ["growth_raw"],
        "failed_models": [],
        "processed_days": {"growth_raw": 0},
    }

    assert validate_smoke_result(result)["ok"] is True
