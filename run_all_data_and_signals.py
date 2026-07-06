#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run data update and signal generation steps sequentially.

This file exists so the .bat launcher can stay ASCII-only. Windows cmd.exe can
misread Chinese paths inside batch files, while Python handles these paths
reliably.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LOG_ROOT = ROOT / "工具" / "logs"


STEPS = [
    ("01_stock_daily", [PYTHON, ROOT / "工具" / "获得股票日频数据.py"]),
    ("02_qmt_company", [PYTHON, ROOT / "工具" / "qmt公司数据获取.py"]),
    ("03_qmt_adj_factor", [PYTHON, ROOT / "工具" / "qmt获得股票日频复权因子.py"]),
    ("04_index_daily", [PYTHON, ROOT / "工具" / "获得指数日频数据.py"]),
    ("05_stock_minute", [PYTHON, ROOT / "工具" / "获得股票分钟级数据.py"]),
    ("06_qmt_turnover", [PYTHON, ROOT / "工具" / "获得股票日频换手率.py"]),
    (
        "07_zxw_factor_notebook",
        [
            PYTHON,
            "-m",
            "jupyter",
            "nbconvert",
            "--to",
            "notebook",
            "--execute",
            "--inplace",
            ROOT / "ZXW因子" / "ZXW策略技术因子生成.ipynb",
            "--ExecutePreprocessor.timeout=-1",
        ],
    ),
    ("08_merge_signal_daily", [PYTHON, ROOT / "工具" / "增量信号保存.py"]),
    ("09_morph_candlestick_signal", [PYTHON, ROOT / "工具" / "形态蜡烛信号生成.py"]),
    ("10_merge_morph_signal", [PYTHON, ROOT / "工具" / "形态面增量信号保存.py"]),
]


def stringify_command(command: list[object]) -> list[str]:
    return [str(part) for part in command]


def main() -> int:
    if not PYTHON.exists():
        print(f"[ERROR] Python not found: {PYTHON}")
        return 1

    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = LOG_ROOT / f"run_all_{run_ts}"
    log_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("One-click data and signal update")
    print(f"Root: {ROOT}")
    print(f"Python: {PYTHON}")
    print(f"Logs: {log_dir}")
    print("=" * 60)

    for step_name, raw_command in STEPS:
        command = stringify_command(raw_command)
        log_path = log_dir / f"{step_name}.log"
        print("-" * 60)
        print(f"[START] {step_name}")
        print("Command:", subprocess.list2cmdline(command))
        print(f"Log: {log_path}")

        with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
            log_file.write("=" * 60 + "\n")
            log_file.write(f"START {step_name}\n")
            log_file.write(f"Time: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            log_file.write("Command: " + subprocess.list2cmdline(command) + "\n")
            log_file.write("=" * 60 + "\n\n")
            log_file.flush()

            completed = subprocess.run(
                command,
                cwd=ROOT,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            log_file.write("\n" + "=" * 60 + "\n")
            log_file.write(f"END {step_name}\n")
            log_file.write(f"Time: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            log_file.write(f"ExitCode: {completed.returncode}\n")
            log_file.write("=" * 60 + "\n")

        if completed.returncode != 0:
            print(f"[FAIL] {step_name} exit={completed.returncode}")
            print(f"Check log: {log_path}")
            return completed.returncode

        print(f"[OK] {step_name}")

    print("=" * 60)
    print("[OK] All steps completed.")
    print(f"Logs: {log_dir}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
