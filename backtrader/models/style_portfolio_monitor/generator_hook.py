"""因子全部落盘后调用风格等权指数账本。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from .config import STYLE_MONITOR_DB_PATH
from .equal_weight_runner import (
    DEFAULT_ADJ_FACTOR_DAILY_DIR,
    DEFAULT_MARKET_BASE_DIR,
    DEFAULT_SIGNAL_BASE_DIR,
    run_equal_weight_update,
)


def _normalise_date(value: date | str | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def run_after_factor_generation(
    *,
    signal_base_dir: str | Path = DEFAULT_SIGNAL_BASE_DIR,
    market_base_dir: str | Path = DEFAULT_MARKET_BASE_DIR,
    through_date: date | str | None = None,
    database_path: str | Path = STYLE_MONITOR_DB_PATH,
    model_ids: Sequence[str] | None = None,
    progress: Callable[[str, int, str], None] | None = None,
    rebuild: bool = False,
) -> dict[str, Any]:
    """读取已落盘因子并更新无本金后复权等权指数账本。

    该入口只依赖持久化因子分区和行情分区，不接收因子生成器内存中的
    ``factor_dfs``，因此必须在普通因子、派生因子和 part 合并全部完成后调用。
    """
    result = run_equal_weight_update(
        model_ids=list(model_ids) if model_ids is not None else None,
        through_date=_normalise_date(through_date),
        database_path=database_path,
        signal_base_dir=signal_base_dir,
        market_base_dir=market_base_dir,
        progress=progress,
        rebuild=bool(rebuild),
    )
    failed = result.get("failed_models") or []
    if failed:
        details = "；".join(
            f"{item.get('model_id', 'unknown')}: {item.get('message', '')}"
            for item in failed
        )
        raise RuntimeError(f"风格等权指数账本更新失败: {details}")
    return result


__all__ = ["run_after_factor_generation"]
