from __future__ import annotations

import ast
import json
import os
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest


SCRIPT_PATH = Path(__file__).with_name("ZXW策略技术因子生成.py")
FUNCTION_NAMES = {
    "_batch_watermark_path",
    "_load_batch_watermark",
    "_get_batch_complete_date",
    "_write_batch_watermark_atomic",
    "_sanitize_factor_dir_name",
    "_validate_factor_frames_for_batch",
    "compact_signal_daily_parts",
    "_finalize_factor_batch",
}


def _load_functions() -> dict:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8-sig"), filename=str(SCRIPT_PATH))
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in FUNCTION_NAMES
    ]
    namespace = {
        "Path": Path,
        "pd": pd,
        "json": json,
        "os": os,
        "datetime": datetime,
        "BATCH_WATERMARK_FILE": "factor_batch_watermark.json",
        "INVALID_FACTOR_PATH_CHARS": re.compile(r'[\\/:*?"<>|]'),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SCRIPT_PATH), "exec"), namespace)
    return namespace


def test_batch_watermark_round_trip_uses_utf8_json(tmp_path: Path) -> None:
    functions = _load_functions()
    assert functions["_load_batch_watermark"](str(tmp_path)) is None

    payload = {
        "status": "complete",
        "last_complete_date": "2026-07-29",
        "factor_count": 2,
        "note": "整批因子完成",
    }
    path = functions["_write_batch_watermark_atomic"](str(tmp_path), payload)

    assert path == tmp_path / "_meta" / "factor_batch_watermark.json"
    assert functions["_load_batch_watermark"](str(tmp_path)) == payload
    assert "整批因子完成" in path.read_text(encoding="utf-8")
    assert not list(path.parent.glob("*.tmp"))


def test_get_batch_complete_date_validates_complete_payload(tmp_path: Path) -> None:
    functions = _load_functions()
    assert functions["_get_batch_complete_date"](str(tmp_path)) is None

    functions["_write_batch_watermark_atomic"](
        str(tmp_path),
        {"status": "complete", "last_complete_date": "2026-07-24"},
    )
    assert functions["_get_batch_complete_date"](str(tmp_path)) == pd.Timestamp("2026-07-24")

    functions["_write_batch_watermark_atomic"](
        str(tmp_path),
        {"status": "running", "last_complete_date": "2026-07-24"},
    )
    with pytest.raises(ValueError, match="status"):
        functions["_get_batch_complete_date"](str(tmp_path))

    functions["_write_batch_watermark_atomic"](
        str(tmp_path),
        {"status": "complete", "last_complete_date": "not-a-date"},
    )
    with pytest.raises(ValueError, match="last_complete_date"):
        functions["_get_batch_complete_date"](str(tmp_path))


def test_batch_validation_does_not_scan_or_reject_partial_code_columns() -> None:
    functions = _load_functions()
    target_date = pd.Timestamp("2026-07-29")
    frames = {
        "dif": pd.DataFrame({"688825.SH": [1.0]}, index=[target_date]),
    }

    summary = functions["_validate_factor_frames_for_batch"](
        factor_dfs_dict=frames,
        factor_name_map_dict={"DIF": "dif"},
        target_date=target_date,
        all_market_codes={"000001.SZ", "688825.SH"},
        ths_codes={"881001.THS"},
        ths_only_factor_keys=set(),
    )

    assert summary == {"factor_count": 1, "all_market_factor_count": 1, "ths_factor_count": 0}


def test_batch_validation_rejects_missing_factor_frame() -> None:
    functions = _load_functions()

    with pytest.raises(ValueError, match="DEA.*未生成"):
        functions["_validate_factor_frames_for_batch"](
            factor_dfs_dict={
                "dif": pd.DataFrame(
                    {"000001.SZ": [1.0]},
                    index=[pd.Timestamp("2026-07-29")],
                )
            },
            factor_name_map_dict={"DIF": "dif", "DEA": "dea"},
            target_date=pd.Timestamp("2026-07-29"),
            all_market_codes={"000001.SZ"},
            ths_codes=set(),
            ths_only_factor_keys=set(),
        )


def test_batch_validation_uses_ths_scope_for_industry_factors() -> None:
    functions = _load_functions()
    target_date = pd.Timestamp("2026-07-29")
    frames = {
        "dif": pd.DataFrame(
            {"000001.SZ": [1.0], "688825.SH": [2.0], "881001.THS": [3.0]},
            index=[target_date],
        ),
        "industry_profit_yoy_mcap": pd.DataFrame(
            {"881001.THS": [0.2]},
            index=[target_date],
        ),
    }

    summary = functions["_validate_factor_frames_for_batch"](
        factor_dfs_dict=frames,
        factor_name_map_dict={
            "DIF": "dif",
            "行业净利润改善率_市值加权": "industry_profit_yoy_mcap",
        },
        target_date=target_date,
        all_market_codes={"000001.SZ", "688825.SH", "881001.THS"},
        ths_codes={"881001.THS"},
        ths_only_factor_keys={"industry_profit_yoy_mcap"},
    )

    assert summary == {"factor_count": 2, "all_market_factor_count": 1, "ths_factor_count": 1}


def test_finalize_does_not_write_watermark_when_compaction_fails(tmp_path: Path) -> None:
    functions = _load_functions()
    writer_called = False

    def fail_compaction(**_kwargs):
        raise RuntimeError("compact failed")

    def record_writer(_base_dir, _payload):
        nonlocal writer_called
        writer_called = True

    with pytest.raises(RuntimeError, match="compact failed"):
        functions["_finalize_factor_batch"](
            base_dir=str(tmp_path),
            factor_dfs_dict={"dif": pd.DataFrame({"000001.SZ": [1.0]}, index=[pd.Timestamp("2026-07-29")])},
            factor_name_map_dict={"DIF": "dif"},
            target_date=pd.Timestamp("2026-07-29"),
            all_market_codes={"000001.SZ"},
            ths_codes=set(),
            ths_only_factor_keys=set(),
            compact_func=fail_compaction,
            watermark_writer=record_writer,
        )

    assert writer_called is False


def test_parallel_compaction_raises_after_any_month_fails(tmp_path: Path) -> None:
    functions = _load_functions()
    month_dirs = [tmp_path / "2026-06", tmp_path / "2026-07"]

    class ImmediateFuture:
        def __init__(self, func, *args):
            try:
                self.value = func(*args)
                self.error = None
            except Exception as exc:
                self.value = None
                self.error = exc

        def result(self):
            if self.error is not None:
                raise self.error
            return self.value

    class ImmediateExecutor:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def submit(self, func, *args):
            return ImmediateFuture(func, *args)

    def compact_month(month_dir, _keep_parts):
        if month_dir == month_dirs[1]:
            raise OSError("disk full")
        return month_dir, 1, 10

    namespace = functions["compact_signal_daily_parts"].__globals__
    namespace.update(
        {
            "_signal_part_resolve_target_month_dirs": lambda **_kwargs: month_dirs,
            "_signal_part_compact_month_partition_task": compact_month,
            "ThreadPoolExecutor": ImmediateExecutor,
            "as_completed": list,
        }
    )

    with pytest.raises(RuntimeError, match="2026-07.*disk full"):
        functions["compact_signal_daily_parts"](base_dir=str(tmp_path), workers=2)


def test_finalize_writes_complete_watermark_after_compaction(tmp_path: Path) -> None:
    functions = _load_functions()
    calls: list[str] = []
    written_payload: dict | None = None

    def compact(**_kwargs):
        calls.append("compact")

    def write(_base_dir, payload):
        nonlocal written_payload
        calls.append("write")
        written_payload = payload
        return tmp_path / "_meta" / "factor_batch_watermark.json"

    functions["_finalize_factor_batch"](
        base_dir=str(tmp_path),
        factor_dfs_dict={"dif": pd.DataFrame({"000001.SZ": [1.0]}, index=[pd.Timestamp("2026-07-29")])},
        factor_name_map_dict={"DIF": "dif"},
        target_date=pd.Timestamp("2026-07-29"),
        all_market_codes={"000001.SZ"},
        ths_codes=set(),
        ths_only_factor_keys=set(),
        compact_func=compact,
        watermark_writer=write,
    )

    assert calls == ["compact", "write"]
    assert written_payload is not None
    assert written_payload["status"] == "complete"
    assert written_payload["last_complete_date"] == "2026-07-29"
    assert written_payload["factor_count"] == 1


def test_finalize_uses_common_persisted_date_for_partial_update(tmp_path: Path) -> None:
    functions = _load_functions()
    written_payload: dict | None = None

    def write(_base_dir, payload):
        nonlocal written_payload
        written_payload = payload
        return tmp_path / "_meta" / "factor_batch_watermark.json"

    functions["_finalize_factor_batch"](
        base_dir=str(tmp_path),
        factor_dfs_dict={
            "dif": pd.DataFrame(
                {"000001.SZ": [1.0]},
                index=[pd.Timestamp("2026-07-29")],
            )
        },
        factor_name_map_dict={"DIF": "dif"},
        managed_factor_name_map={"DIF": "dif", "DEA": "dea"},
        target_date=pd.Timestamp("2026-07-29"),
        current_complete_date=pd.Timestamp("2026-07-24"),
        all_market_codes={"000001.SZ"},
        ths_codes=set(),
        ths_only_factor_keys=set(),
        compact_func=lambda **_kwargs: None,
        factor_last_date_loader=lambda _base_dir: {
            "DIF": pd.Timestamp("2026-07-29"),
            "DEA": pd.Timestamp("2026-07-28"),
        },
        watermark_writer=write,
    )

    assert written_payload is not None
    assert written_payload["last_complete_date"] == "2026-07-28"
    assert written_payload["factor_count"] == 2


def test_finalize_all_null_target_date_counts_as_persisted_progress(tmp_path: Path) -> None:
    functions = _load_functions()
    written_payload: dict | None = None

    def write(_base_dir, payload):
        nonlocal written_payload
        written_payload = payload
        return tmp_path / "_meta" / "factor_batch_watermark.json"

    functions["_finalize_factor_batch"](
        base_dir=str(tmp_path),
        factor_dfs_dict={
            "dif": pd.DataFrame(
                {"000001.SZ": [float("nan")]},
                index=[pd.Timestamp("2026-07-29")],
            )
        },
        factor_name_map_dict={"DIF": "dif"},
        managed_factor_name_map={"DIF": "dif"},
        target_date=pd.Timestamp("2026-07-29"),
        all_market_codes={"000001.SZ"},
        ths_codes=set(),
        ths_only_factor_keys=set(),
        compact_func=lambda **_kwargs: None,
        factor_last_date_loader=lambda _base_dir: {
            "DIF": pd.Timestamp("2026-07-29"),
        },
        watermark_writer=write,
    )

    assert written_payload is not None
    assert written_payload["last_complete_date"] == "2026-07-29"


def test_finalize_preserves_watermark_when_managed_factor_has_no_persisted_date(
    tmp_path: Path,
) -> None:
    functions = _load_functions()
    calls: list[str] = []

    functions["_finalize_factor_batch"](
        base_dir=str(tmp_path),
        factor_dfs_dict={
            "dif": pd.DataFrame(
                {"000001.SZ": [1.0]},
                index=[pd.Timestamp("2026-07-29")],
            )
        },
        factor_name_map_dict={"DIF": "dif"},
        managed_factor_name_map={"DIF": "dif", "DEA": "dea"},
        target_date=pd.Timestamp("2026-07-29"),
        current_complete_date=pd.Timestamp("2026-07-24"),
        all_market_codes={"000001.SZ"},
        ths_codes=set(),
        ths_only_factor_keys=set(),
        compact_func=lambda **_kwargs: calls.append("compact"),
        factor_last_date_loader=lambda _base_dir: {
            "DIF": pd.Timestamp("2026-07-29"),
        },
        watermark_writer=lambda *_args: calls.append("write"),
    )

    assert calls == ["compact"]


def test_finalize_empty_managed_catalog_preserves_existing_watermark(
    tmp_path: Path,
) -> None:
    functions = _load_functions()
    calls: list[str] = []

    path = functions["_finalize_factor_batch"](
        base_dir=str(tmp_path),
        factor_dfs_dict={},
        factor_name_map_dict={},
        managed_factor_name_map={},
        target_date=pd.Timestamp("2026-07-29"),
        current_complete_date=pd.Timestamp("2026-07-24"),
        all_market_codes={"000001.SZ"},
        ths_codes=set(),
        ths_only_factor_keys=set(),
        compact_func=lambda **_kwargs: calls.append("compact"),
        factor_last_date_loader=lambda _base_dir: calls.append("load") or {},
        watermark_writer=lambda *_args: calls.append("write"),
    )

    assert calls == []
    assert path == tmp_path / "_meta" / "factor_batch_watermark.json"


def test_finalize_call_builds_managed_catalog_from_all_enabled_bundles() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8-sig")
    managed_block = source.split("_managed_factor_name_map =", 1)[1].split(
        "_finalize_factor_batch(", 1
    )[0]

    assert "for bundle_name in SELECTED_BUNDLES" in managed_block
    assert "for bundle_name in selected_bundles_for_compute" not in managed_block


def test_finalize_is_noop_when_watermark_already_covers_target(tmp_path: Path) -> None:
    functions = _load_functions()

    def unexpected_call(**_kwargs):
        raise AssertionError("无需补写时不应合并或重写水位")

    path = functions["_finalize_factor_batch"](
        base_dir=str(tmp_path),
        factor_dfs_dict={},
        factor_name_map_dict={},
        target_date=pd.Timestamp("2026-07-29"),
        current_complete_date=pd.Timestamp("2026-07-29"),
        all_market_codes={"000001.SZ"},
        ths_codes=set(),
        ths_only_factor_keys=set(),
        compact_func=unexpected_call,
        watermark_writer=unexpected_call,
    )

    assert path == tmp_path / "_meta" / "factor_batch_watermark.json"


def test_finalize_preserves_stale_watermark_when_plan_is_empty(tmp_path: Path) -> None:
    functions = _load_functions()
    calls: list[str] = []
    def unexpected_call(**_kwargs):
        calls.append("unexpected")

    path = functions["_finalize_factor_batch"](
        base_dir=str(tmp_path),
        factor_dfs_dict={},
        factor_name_map_dict={},
        target_date=pd.Timestamp("2026-07-29"),
        current_complete_date=pd.Timestamp("2026-07-24"),
        all_market_codes={"000001.SZ"},
        ths_codes=set(),
        ths_only_factor_keys=set(),
        compact_func=unexpected_call,
        watermark_writer=unexpected_call,
    )

    assert calls == []
    assert path == tmp_path / "_meta" / "factor_batch_watermark.json"
