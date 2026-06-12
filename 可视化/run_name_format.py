"""与 index.html 一致的回测 run_name 日期前缀加工（服务端统一命名）。"""

from __future__ import annotations

from datetime import date
from typing import Any


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def build_run_name_date_prefix(start_date: str, end_date: str) -> str:
    """
    与前端 buildRunNameDatePrefix 对齐（结束日按含当日参与区间比较）。

    - 区间 > 1 自然年：YYYY_to_YYYY（如 2020_to_2022）
    - 区间 ≤ 1 年且同年：YYYYMM_to_MM（如 202401_to_06）
    - 区间 ≤ 1 年且跨年：YYYYMM_to_YYYYMM（如 202412_to_202502）
    """
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start is None or end is None:
        return ""
    if end < start:
        start, end = end, start

    one_year_after_start = date(start.year + 1, start.month, start.day)
    try:
        spans_more_than_one_year = end > one_year_after_start
    except ValueError:
        from datetime import timedelta

        spans_more_than_one_year = (end - start) > timedelta(days=365)

    if spans_more_than_one_year:
        return f"{start.year}_to_{end.year}"

    if start.year == end.year:
        return f"{start.year:04d}{start.month:02d}_to_{end.month:02d}"

    return f"{start.year:04d}{start.month:02d}_to_{end.year:04d}{end.month:02d}"


def build_payload_run_name(
    *,
    start_date: str,
    end_date: str,
    name_base: str,
) -> str:
    prefix = build_run_name_date_prefix(start_date, end_date)
    base = str(name_base or "").strip() or "回溯"
    return f"{prefix}{base}" if prefix else base


def apply_frontend_run_name_format(payload: dict[str, Any]) -> dict[str, Any]:
    """
    - 若 payload 含键 run_name_base（含空串）：按 start/end 生成 run_name，并移除 run_name_base。
    - 若 apply_run_name_date_prefix 为真：将现有 run_name 当作 base 再拼前缀。
    - 否则不修改 run_name（兼容 Openclaw 直接传完整名称）。
    """
    if not isinstance(payload, dict):
        return payload

    out = dict(payload)
    start = str(out.get("start_date") or "").strip()
    end = str(out.get("end_date") or "").strip()

    if "run_name_base" in out:
        base = str(out.get("run_name_base") or "").strip()
        out["run_name"] = build_payload_run_name(
            start_date=start,
            end_date=end,
            name_base=base,
        )
        out.pop("run_name_base", None)
        out.pop("apply_run_name_date_prefix", None)
        return out

    if out.get("apply_run_name_date_prefix"):
        base = str(out.get("run_name") or "").strip()
        out["run_name"] = build_payload_run_name(
            start_date=start,
            end_date=end,
            name_base=base,
        )
        out.pop("apply_run_name_date_prefix", None)

    return out
