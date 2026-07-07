#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""顺序执行多个数据更新脚本的合并入口。

默认顺序：
1. 股票日频数据
2. 指数日频数据
3. ETF 日频数据
4. QMT 公司数据
5. QMT 日频复权因子
6. 股票分钟级数据
7. 股票日频换手率

换手率放最后，因为它依赖股票日 K 和 QMT Capital 股本数据。
"""
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


TOOLS_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Stage:
    key: str
    title: str
    script_name: str
    default_extra_args: tuple[str, ...] = ()


STAGES: tuple[Stage, ...] = (
    Stage("stock_daily", "股票日频数据", "获得股票日频数据.py"),
    Stage("index_daily", "指数日频数据", "获得指数日频数据.py"),
    Stage("etf_daily", "ETF 日频数据", "获得ETF日频数据.py"),
    Stage("qmt_company", "QMT 公司数据", "qmt公司数据获取.py"),
    Stage("qmt_adj", "QMT 日频复权因子", "qmt获得股票日频复权因子.py"),
    Stage("stock_mins", "股票分钟级数据", "获得股票分钟级数据.py"),
    Stage("turnover", "股票日频换手率", "获得股票日频换手率.py"),
)


STAGE_KEY_ALIASES = {
    "stock": "stock_daily",
    "daily": "stock_daily",
    "index": "index_daily",
    "etf": "etf_daily",
    "company": "qmt_company",
    "qmt": "qmt_company",
    "capital": "qmt_company",
    "adj": "qmt_adj",
    "mins": "stock_mins",
    "minute": "stock_mins",
    "turnover_rate": "turnover",
}


def _split_stage_args(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return shlex.split(text, posix=False)


def _normalize_stage_keys(values: list[str] | None) -> set[str]:
    if not values:
        return set()
    valid = {stage.key for stage in STAGES}
    result: set[str] = set()
    for raw in values:
        for item in str(raw).replace("，", ",").split(","):
            key = item.strip()
            if not key:
                continue
            key = STAGE_KEY_ALIASES.get(key, key)
            if key not in valid:
                raise ValueError(f"未知阶段: {item}；可选: {', '.join(valid)}")
            result.add(key)
    return result


def _build_stage_args(args: argparse.Namespace) -> dict[str, list[str]]:
    return {
        "stock_daily": _split_stage_args(args.stock_daily_args),
        "index_daily": _split_stage_args(args.index_daily_args),
        "etf_daily": _split_stage_args(args.etf_daily_args),
        "qmt_company": _split_stage_args(args.qmt_company_args),
        "qmt_adj": _split_stage_args(args.qmt_adj_args),
        "stock_mins": _split_stage_args(args.stock_mins_args),
        "turnover": _split_stage_args(args.turnover_args),
    }


def _selected_stages(args: argparse.Namespace) -> list[Stage]:
    only = _normalize_stage_keys(args.only)
    skip = _normalize_stage_keys(args.skip)
    selected = []
    for stage in STAGES:
        if only and stage.key not in only:
            continue
        if stage.key in skip:
            continue
        selected.append(stage)
    return selected


def _command_text(command: list[str]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def run_stage(
    stage: Stage,
    *,
    python_exe: str,
    extra_args: list[str],
    dry_run: bool,
) -> int:
    script_path = TOOLS_DIR / stage.script_name
    if not script_path.exists():
        raise FileNotFoundError(f"脚本不存在: {script_path}")
    command = [
        python_exe,
        str(script_path),
        *stage.default_extra_args,
        *extra_args,
    ]
    print("\n" + "=" * 80)
    print(f"[STAGE] {stage.title} ({stage.key})")
    print(f"[CMD] {_command_text(command)}")
    print("=" * 80)
    if dry_run:
        return 0
    completed = subprocess.run(command, check=False)
    return int(completed.returncode)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="合并入口：顺序执行日频、指数、ETF、QMT 公司数据、复权因子、分钟线和换手率更新"
    )
    parser.add_argument("--python-exe", default=sys.executable, help="执行子脚本的 Python，默认当前解释器")
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="只运行指定阶段，可选 stock_daily,index_daily,etf_daily,qmt_company,qmt_adj,stock_mins,turnover",
    )
    parser.add_argument(
        "--skip",
        nargs="*",
        default=None,
        help="跳过指定阶段，取值同 --only",
    )
    parser.add_argument("--continue-on-error", action="store_true", help="某阶段失败后继续执行后续阶段")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要执行的命令，不真正运行")
    parser.add_argument("--stock-daily-args", default="", help="透传给 获得股票日频数据.py 的参数字符串")
    parser.add_argument("--index-daily-args", default="", help="透传给 获得指数日频数据.py 的参数字符串")
    parser.add_argument("--etf-daily-args", default="", help="透传给 获得ETF日频数据.py 的参数字符串")
    parser.add_argument("--qmt-company-args", default="", help="透传给 qmt公司数据获取.py 的参数字符串")
    parser.add_argument("--qmt-adj-args", default="", help="透传给 qmt获得股票日频复权因子.py 的参数字符串")
    parser.add_argument("--stock-mins-args", default="", help="透传给 获得股票分钟级数据.py 的参数字符串")
    parser.add_argument("--turnover-args", default="", help="透传给 获得股票日频换手率.py 的参数字符串")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selected = _selected_stages(args)
    stage_args = _build_stage_args(args)
    if not selected:
        raise ValueError("没有选中任何阶段，请检查 --only/--skip")

    failed: list[tuple[Stage, int]] = []
    print("执行顺序: " + " -> ".join(stage.key for stage in selected))
    if selected and selected[-1].key != "turnover" and not args.only:
        print("[WARN] 当前选择下换手率不是最后一个阶段，请确认 --skip 是否符合预期。")

    for stage in selected:
        rc = run_stage(
            stage,
            python_exe=str(args.python_exe),
            extra_args=stage_args.get(stage.key, []),
            dry_run=bool(args.dry_run),
        )
        if rc != 0:
            failed.append((stage, rc))
            print(f"[ERROR] 阶段失败: {stage.title} ({stage.key}) exit={rc}")
            if not args.continue_on_error:
                break

    if failed:
        print("\n失败阶段:")
        for stage, rc in failed:
            print(f"- {stage.key}: exit={rc}")
        raise SystemExit(1)

    print("\n全部选中阶段执行完成。")


if __name__ == "__main__":
    main()
