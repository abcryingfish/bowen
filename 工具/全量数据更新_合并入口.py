#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""顺序执行多个数据更新脚本的合并入口。

默认顺序：
1. 股票日频数据
2. 指数日频数据
3. 同花顺板块、成分股及一级指数日频数据
4. ETF 日频数据
5. QMT 公司数据
6. QMT 日频复权因子
7. 股票分钟级数据
8. 同花顺板块分钟级数据
9. 股票日频换手率
10. 股票粉丝特征增量

换手率依赖股票日 K 和 QMT Capital 股本数据；粉丝特征增量作为最终阶段执行。
"""
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable


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


@dataclass(frozen=True)
class OutputCheck:
    stage_key: str
    title: str
    default_base_dir: str
    base_arg_names: tuple[str, ...] = ("--base-dir",)
    subdir: str = ""
    align_to_stock_daily: bool = True
    code_suffix: str = ""
    exclude_code_suffix: bool = False
    factor_names: tuple[str, ...] = ()


STAGES: tuple[Stage, ...] = (
    Stage("stock_daily", "股票日频数据", "获得股票日频数据.py"),
    Stage("index_daily", "指数日频数据", "获得指数日频数据.py"),
    Stage("ths_level1_index_daily", "同花顺板块和成分股", "获得同花顺板块和成分股.py"),
    Stage("etf_daily", "ETF 日频数据", "获得ETF日频数据.py"),
    Stage("qmt_company", "QMT 公司数据", "qmt公司数据获取.py"),
    Stage("qmt_adj", "QMT 日频复权因子", "qmt获得股票日频复权因子.py"),
    Stage("stock_mins", "股票分钟级数据", "获得股票分钟级数据.py"),
    Stage("ths_index_mins", "同花顺板块分钟级数据", "获得同花顺板块分钟级数据.py"),
    Stage("turnover", "股票日频换手率", "获得股票日频换手率.py"),
    Stage("stock_fans", "股票粉丝特征增量", "获得股票粉丝特征.py", ("--sleep-sec", "0.5")),
)


STAGE_KEY_ALIASES = {
    "stock": "stock_daily",
    "daily": "stock_daily",
    "index": "index_daily",
    "ths": "ths_level1_index_daily",
    "ths_index": "ths_level1_index_daily",
    "etf": "etf_daily",
    "company": "qmt_company",
    "qmt": "qmt_company",
    "capital": "qmt_company",
    "adj": "qmt_adj",
    "mins": "stock_mins",
    "minute": "stock_mins",
    "ths_mins": "ths_index_mins",
    "ths_minute": "ths_index_mins",
    "turnover_rate": "turnover",
    "fans": "stock_fans",
    "stock_fans_factor": "stock_fans",
}

# Fuyao 认证尚未配置时，默认不阻断其他全量数据阶段；需要时可通过 --only 显式运行。
DEFAULT_SKIP_STAGES = {"ths_index_mins"}


OUTPUT_CHECKS: tuple[OutputCheck, ...] = (
    OutputCheck("stock_daily", "股票日线", r"D:\database\stock_basic_data_daily", align_to_stock_daily=False),
    OutputCheck(
        "index_daily",
        "普通指数日线",
        r"D:\database\index_data_daily",
        code_suffix=".THS",
        exclude_code_suffix=True,
    ),
    OutputCheck(
        "ths_level1_index_daily",
        "同花顺板块日线",
        r"D:\database\index_data_daily",
        base_arg_names=("--index-base-dir", "--base-dir"),
        code_suffix=".THS",
    ),
    OutputCheck("etf_daily", "ETF 日线", r"D:\database\ETF_basic_data_daily"),
    OutputCheck(
        "qmt_company",
        "QMT 日频估值",
        r"D:\database\qmt_company_data",
        subdir="table=factor_fundamental_valuation",
    ),
    OutputCheck(
        "qmt_adj",
        "QMT 日频复权因子",
        r"D:\database\stock_adj_daily",
        base_arg_names=("--final-base-dir",),
        subdir="adj_factor_daily",
    ),
    OutputCheck(
        "stock_mins",
        "股票分钟线",
        r"D:\database\stock_basic_data_mins",
        align_to_stock_daily=False,
    ),
    OutputCheck(
        "ths_index_mins",
        "同花顺板块分钟线",
        r"D:\database\index_data_mins",
        align_to_stock_daily=False,
        code_suffix=".THS",
    ),
    OutputCheck("turnover", "股票换手率及市值", r"D:\database\qmt_turnover_data"),
    OutputCheck(
        "stock_fans",
        "股票粉丝及人气因子",
        r"D:\database\signal_daily",
        base_arg_names=("--output-dir",),
        factor_names=(
            "new_uid_rate",
            "old_uid_rate",
            "new_uid_change_rank",
            "old_uid_change_rank",
            "history_rank",
        ),
    ),
)


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
        "ths_level1_index_daily": _split_stage_args(args.ths_level1_index_daily_args),
        "etf_daily": _split_stage_args(args.etf_daily_args),
        "qmt_company": _split_stage_args(args.qmt_company_args),
        "qmt_adj": _split_stage_args(args.qmt_adj_args),
        "stock_mins": _split_stage_args(args.stock_mins_args),
        "ths_index_mins": _split_stage_args(args.ths_index_mins_args),
        "turnover": _split_stage_args(args.turnover_args),
        "stock_fans": _split_stage_args(args.stock_fans_args),
    }


def _argument_value(arguments: Iterable[str], option_names: tuple[str, ...]) -> str | None:
    values = [str(value) for value in arguments]
    for index, value in enumerate(values):
        for option_name in option_names:
            if value == option_name and index + 1 < len(values):
                return values[index + 1].strip().strip('"').strip("'")
            prefix = option_name + "="
            if value.startswith(prefix):
                return value[len(prefix):].strip().strip('"').strip("'")
    return None


def _output_base_dir(check: OutputCheck, stage_args: dict[str, list[str]]) -> Path:
    override = _argument_value(stage_args.get(check.stage_key, []), check.base_arg_names)
    base_dir = Path(override or check.default_base_dir)
    return base_dir / check.subdir if check.subdir else base_dir


def _partition_number(path: Path, prefix: str) -> int:
    try:
        return int(path.name.split("=", 1)[1]) if path.name.startswith(prefix + "=") else -1
    except (IndexError, ValueError):
        return -1


def _latest_merged_path(base_dir: Path) -> Path | None:
    current = base_dir
    if not current.exists():
        return None
    for prefix in ("year", "month", "day"):
        partitions = [
            path
            for path in current.glob(f"{prefix}=*")
            if path.is_dir() and _partition_number(path, prefix) >= 0
        ]
        if not partitions:
            break
        current = max(partitions, key=lambda path: _partition_number(path, prefix))
    merged_path = current / "merged.parquet"
    if merged_path.is_file():
        return merged_path
    direct_files = [path for path in current.glob("*.parquet") if path.is_file()]
    return max(direct_files, key=lambda path: path.stat().st_mtime_ns) if direct_files else None


def _read_latest_date(
    con,
    parquet_path: Path,
    code_suffix: str = "",
    exclude_code_suffix: bool = False,
) -> date | None:
    suffix_filter = ""
    parameters: list[object] = [str(parquet_path)]
    if code_suffix:
        operator = "NOT LIKE" if exclude_code_suffix else "LIKE"
        suffix_filter = f" WHERE UPPER(TRIM(CAST(htsc_code AS VARCHAR))) {operator} ?"
        parameters.append("%" + code_suffix.upper())
    value = con.execute(
        "SELECT MAX(CAST(time AS DATE)) FROM read_parquet(?)" + suffix_filter,
        parameters,
    ).fetchone()[0]
    return value


def _scan_output_latest_date(
    con,
    check: OutputCheck,
    stage_args: dict[str, list[str]],
) -> tuple[date | None, str]:
    base_dir = _output_base_dir(check, stage_args)
    if check.factor_names:
        dates: list[date] = []
        missing: list[str] = []
        for factor_name in check.factor_names:
            path = _latest_merged_path(base_dir / f"factor={factor_name}")
            if path is None:
                missing.append(factor_name)
                continue
            latest_date = _read_latest_date(con, path)
            if latest_date is None:
                missing.append(factor_name)
            else:
                dates.append(latest_date)
        detail = f"{len(dates)}/{len(check.factor_names)} 个因子有数据"
        if missing:
            detail += "，缺少=" + ",".join(missing)
        return (min(dates) if dates and not missing else None), detail

    path = _latest_merged_path(base_dir)
    if path is None:
        return None, f"未找到 parquet：{base_dir}"
    latest_date = _read_latest_date(
        con,
        path,
        check.code_suffix,
        check.exclude_code_suffix,
    )
    return latest_date, str(path)


def print_data_update_summary(
    *,
    selected_stages: list[Stage],
    stage_results: dict[str, int],
    stage_args: dict[str, list[str]],
    dry_run: bool,
) -> None:
    print("\n" + "=" * 80)
    print("数据更新结果汇总（仅打印，不写本地状态文件）")
    print("=" * 80)
    if dry_run:
        print("演练模式：所有阶段均未真正执行，不检查落盘日期。")
        return

    try:
        import duckdb
    except ImportError as exc:
        print(f"[WARN] 缺少 duckdb，无法检查落盘日期：{exc}")
        return

    selected_keys = {stage.key for stage in selected_stages}
    incomplete: list[str] = []
    with duckdb.connect(database=":memory:") as con:
        stock_check = next(check for check in OUTPUT_CHECKS if check.stage_key == "stock_daily")
        try:
            stock_latest, _ = _scan_output_latest_date(con, stock_check, stage_args)
        except Exception as exc:
            stock_latest = None
            print(f"[WARN] 股票日线基准日期检查失败：{exc}")
        print(f"对齐基准：股票日线最新日期={stock_latest or '未知'}")

        for check in OUTPUT_CHECKS:
            selected = check.stage_key in selected_keys
            return_code = stage_results.get(check.stage_key)
            try:
                latest_date, detail = _scan_output_latest_date(con, check, stage_args)
            except Exception as exc:
                latest_date, detail = None, f"检查失败：{exc}"

            if not selected:
                status = "未选择"
            elif return_code is None:
                status = "未执行"
                incomplete.append(check.title)
            elif return_code != 0:
                status = f"执行失败(exit={return_code})"
                incomplete.append(check.title)
            elif latest_date is None:
                status = "未发现完整输出"
                incomplete.append(check.title)
            elif check.align_to_stock_daily and stock_latest is not None and latest_date < stock_latest:
                status = f"日期未对齐（落后 {(stock_latest - latest_date).days} 天）"
                incomplete.append(check.title)
            elif check.align_to_stock_daily and stock_latest is not None:
                status = "完成，日期已对齐"
            else:
                status = "完成，日期仅供参考"

            date_text = latest_date.isoformat() if latest_date is not None else "无"
            print(f"[{status}] {check.title}：最新日期={date_text}；{detail}")

    if incomplete:
        print("[WARN] 本次未完全更新：" + "、".join(dict.fromkeys(incomplete)))
    else:
        print("[OK] 本次选中的日频数据均执行成功并完成日期对齐。")


def _selected_stages(args: argparse.Namespace) -> list[Stage]:
    only = _normalize_stage_keys(args.only)
    skip = _normalize_stage_keys(args.skip)
    if not only:
        skip.update(DEFAULT_SKIP_STAGES)
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
        description="合并入口：顺序执行日频、指数、同花顺板块和成分股、ETF、QMT 公司数据、复权因子、分钟线和换手率更新"
    )
    parser.add_argument("--python-exe", default=sys.executable, help="执行子脚本的 Python，默认当前解释器")
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="只运行指定阶段，可选 stock_daily,index_daily,ths_level1_index_daily,etf_daily,qmt_company,qmt_adj,stock_mins,turnover,stock_fans",
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
    parser.add_argument(
        "--ths-level1-index-daily-args",
        default="",
        help="透传给 获得同花顺板块和成分股.py 的参数字符串",
    )
    parser.add_argument("--etf-daily-args", default="", help="透传给 获得ETF日频数据.py 的参数字符串")
    parser.add_argument("--qmt-company-args", default="", help="透传给 qmt公司数据获取.py 的参数字符串")
    parser.add_argument("--qmt-adj-args", default="", help="透传给 qmt获得股票日频复权因子.py 的参数字符串")
    parser.add_argument("--stock-mins-args", default="", help="透传给 获得股票分钟级数据.py 的参数字符串")
    parser.add_argument(
        "--ths-index-mins-args",
        default="",
        help="透传给 获得同花顺板块分钟级数据.py 的参数字符串",
    )
    parser.add_argument("--turnover-args", default="", help="透传给 获得股票日频换手率.py 的参数字符串")
    parser.add_argument("--stock-fans-args", default="", help="透传给 获得股票粉丝特征.py 的参数字符串")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selected = _selected_stages(args)
    stage_args = _build_stage_args(args)
    if not selected:
        raise ValueError("没有选中任何阶段，请检查 --only/--skip")

    failed: list[tuple[Stage, int]] = []
    stage_results: dict[str, int] = {}
    print("执行顺序: " + " -> ".join(stage.key for stage in selected))
    if selected and selected[-1].key != "stock_fans" and not args.only:
        print("[WARN] 当前选择下股票粉丝特征增量不是最后一个阶段，请确认 --skip 是否符合预期。")

    try:
        for stage in selected:
            rc = run_stage(
                stage,
                python_exe=str(args.python_exe),
                extra_args=stage_args.get(stage.key, []),
                dry_run=bool(args.dry_run),
            )
            stage_results[stage.key] = rc
            if rc != 0:
                failed.append((stage, rc))
                print(f"[ERROR] 阶段失败: {stage.title} ({stage.key}) exit={rc}")
                if not args.continue_on_error:
                    break
    finally:
        print_data_update_summary(
            selected_stages=selected,
            stage_results=stage_results,
            stage_args=stage_args,
            dry_run=bool(args.dry_run),
        )

    if failed:
        print("\n失败阶段:")
        for stage, rc in failed:
            print(f"- {stage.key}: exit={rc}")
        raise SystemExit(1)

    print("\n全部选中阶段执行完成。")


if __name__ == "__main__":
    main()
