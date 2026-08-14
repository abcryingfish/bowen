from __future__ import annotations

import importlib.util
from pathlib import Path

import polars as pl


SCRIPT_PATH = Path(__file__).with_name("迁移因子目录为英文ID.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("factor_directory_migration", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_month(root: Path, factor: str, rows: list[tuple[str, str, float]]) -> Path:
    month = root / f"factor={factor}" / "year=2026" / "month=08"
    month.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        rows,
        schema=["time", "htsc_code", "value"],
        orient="row",
    ).with_columns(pl.col("time").str.to_datetime()).write_parquet(month / "merged.parquet")
    return month


def test_rename_keeps_parquet_snapshot(tmp_path: Path) -> None:
    module = _load_module()
    _write_month(tmp_path, "中文因子", [("2026-08-03", "000001.SZ", 1.0)])

    action = module.migrate_factor(tmp_path, "中文因子", "stable_factor_id")

    assert action == "rename"
    assert not (tmp_path / "factor=中文因子").exists()
    assert (tmp_path / "factor=stable_factor_id" / "year=2026" / "month=08" / "merged.parquet").is_file()


def test_newer_source_replaces_fully_covered_destination(tmp_path: Path) -> None:
    module = _load_module()
    _write_month(tmp_path, "中文因子", [
        ("2026-08-02", "000001.SZ", 2.0),
        ("2026-08-03", "000001.SZ", 3.0),
    ])
    _write_month(tmp_path, "stable_factor_id", [
        ("2026-08-02", "000001.SZ", 1.0),
    ])

    action = module.migrate_factor(tmp_path, "中文因子", "stable_factor_id")
    result = pl.read_parquet(
        tmp_path / "factor=stable_factor_id" / "year=2026" / "month=08" / "merged.parquet"
    )

    assert action == "replace-covered"
    assert result["value"].to_list() == [2.0, 3.0]


def test_partial_source_falls_back_to_merge_without_losing_old_keys(tmp_path: Path) -> None:
    module = _load_module()
    _write_month(tmp_path, "中文因子", [
        ("2026-08-02", "000001.SZ", 2.0),
    ])
    _write_month(tmp_path, "stable_factor_id", [
        ("2026-08-01", "600000.SH", 1.0),
    ])

    action = module.migrate_factor(tmp_path, "中文因子", "stable_factor_id")
    result = pl.read_parquet(
        tmp_path / "factor=stable_factor_id" / "year=2026" / "month=08" / "merged.parquet"
    ).sort(["time", "htsc_code"])

    assert action == "merge"
    assert result["htsc_code"].to_list() == ["600000.SH", "000001.SZ"]
    assert result["value"].to_list() == [1.0, 2.0]


def test_case_only_name_uses_intermediate_directory(tmp_path: Path) -> None:
    module = _load_module()
    _write_month(tmp_path, "DEA", [("2026-08-03", "000001.SZ", 1.0)])

    action = module.migrate_factor(tmp_path, "DEA", "dea")

    assert action == "case-rename"
    assert {path.name for path in tmp_path.iterdir()} == {"factor=dea"}
