from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()


def _default_log_path() -> str:
    return str(Path(__file__).resolve().parents[1] / "temp" / "factor_debug_logs" / "factor_debug.jsonl")


def factor_debug_enabled() -> bool:
    return os.getenv("ZXW_FACTOR_DEBUG_LOG", "1") != "0"


def factor_debug_path() -> str:
    return os.getenv("ZXW_FACTOR_DEBUG_LOG_PATH", _default_log_path())


def factor_log(event: str, **fields: Any) -> None:
    if not factor_debug_enabled():
        return
    path = factor_debug_path()
    payload: dict[str, Any] = {
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "event": str(event),
        "pid": os.getpid(),
        "thread": threading.current_thread().name,
        "mono": round(time.perf_counter(), 6),
    }
    for key, value in fields.items():
        try:
            json.dumps(value, ensure_ascii=False)
            payload[str(key)] = value
        except TypeError:
            payload[str(key)] = repr(value)
    line = json.dumps(payload, ensure_ascii=False, default=str)
    with _LOCK:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
