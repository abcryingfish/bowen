from __future__ import annotations

from typing import Any, Callable

from model_registry import resolve_model_id, run_registered_model

ProgressCallback = Callable[[str, int, str], None]


def _normalize_codes(raw_codes: Any) -> list[str]:
    if not isinstance(raw_codes, list):
        raise ValueError("codes 必须是数组")
    codes: list[str] = []
    seen: set[str] = set()
    for item in raw_codes:
        code = str(item or "").strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)
    if not codes:
        raise ValueError("至少需要输入一个回测标的")
    return codes


def _parse_date(value: Any, field_name: str) -> str:
    import pandas as pd

    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} 不能为空")
    try:
        ts = pd.Timestamp(text).floor("D")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"{field_name} 日期格式无效") from exc
    return ts.strftime("%Y-%m-%d")


def run_configured_backtest(config: dict[str, Any], progress_callback: ProgressCallback | None = None) -> dict[str, Any]:
    def progress(stage: str, value: int, message: str) -> None:
        if progress_callback:
            progress_callback(stage, value, message)

    progress("准备参数", 5, "校验回测参数")
    codes = _normalize_codes(config.get("codes"))
    start_date = _parse_date(config.get("start_date"), "start_date")
    end_date = _parse_date(config.get("end_date"), "end_date")
    if start_date >= end_date:
        raise ValueError("开始日期必须早于结束日期")

    frontend_buy_rules = config.get("buy_rules")
    frontend_sell_rules = config.get("sell_rules")
    frontend_buy_operator = str(config.get("buy_operator") or "and").strip().lower()
    frontend_sell_operator = str(config.get("sell_operator") or "or").strip().lower()
    if frontend_buy_operator not in ("and", "or"):
        frontend_buy_operator = "and"
    if frontend_sell_operator not in ("and", "or"):
        frontend_sell_operator = "or"
    run_name = str(config.get("run_name") or "").strip()
    model_id = resolve_model_id(config.get("adopt_model"))

    return run_registered_model(
        model_id=model_id,
        codes=codes,
        start_date=start_date,
        end_date=end_date,
        run_name=run_name,
        frontend_buy_rules=frontend_buy_rules,
        frontend_sell_rules=frontend_sell_rules,
        frontend_buy_operator=frontend_buy_operator,
        frontend_sell_operator=frontend_sell_operator,
        progress=progress,
    )
