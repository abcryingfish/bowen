"""网页 Optuna 任务：强点模型买入×卖出因子子集穷举。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

BACKTRADER_DIR = Path(__file__).resolve().parents[1] / "backtrader"
if str(BACKTRADER_DIR) not in sys.path:
    sys.path.append(str(BACKTRADER_DIR))

from models.zxw_strong_adjusted_only.optuna_study import run_optuna_strong_adjusted_study as _run

ProgressCallback = Callable[[str, int, str], None]
LogAppend = Callable[[str], None]


def run_optuna_strong_adjusted_study(
    payload: dict[str, Any],
    *,
    job_id: str = "",
    cancel_event=None,
    progress_callback: ProgressCallback | None = None,
    log_append: LogAppend | None = None,
) -> dict[str, Any]:
    return _run(
        payload,
        job_id=job_id,
        cancel_event=cancel_event,
        progress_callback=progress_callback,
        log_append=log_append,
    )
