from datetime import date

from models.style_portfolio_monitor import generator_hook


def test_run_after_factor_generation_uses_persisted_factor_paths(monkeypatch, tmp_path):
    calls = []

    def fake_runner(**kwargs):
        calls.append(kwargs)
        return {"completed_models": ["momentum_raw"]}

    monkeypatch.setattr(generator_hook, "run_equal_weight_update", fake_runner)

    result = generator_hook.run_after_factor_generation(
        signal_base_dir=tmp_path / "signal",
        market_base_dir=tmp_path / "market",
        through_date=date(2026, 1, 30),
        database_path=tmp_path / "ledger.duckdb",
        rebuild=True,
    )

    assert result == {"completed_models": ["momentum_raw"]}
    assert calls == [
        {
            "model_ids": None,
            "through_date": date(2026, 1, 30),
            "database_path": tmp_path / "ledger.duckdb",
            "signal_base_dir": tmp_path / "signal",
            "market_base_dir": tmp_path / "market",
            "progress": None,
            "rebuild": True,
        }
    ]
