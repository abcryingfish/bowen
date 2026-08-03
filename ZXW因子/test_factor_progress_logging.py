from __future__ import annotations

import ast
import unittest
from pathlib import Path

import pandas as pd


SCRIPT_PATH = Path(__file__).with_name("ZXW策略技术因子生成.py")
FUNCTION_NAMES = {
    "_format_factor_name_lines",
    "_format_date_range",
    "_format_execution_plan_lines",
    "_format_batch_finish_line",
    "_format_save_progress_line",
    "_build_factor_save_tasks",
    "_save_single_factor_task",
}


def _load_formatters() -> dict[str, object]:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8-sig"), filename=str(SCRIPT_PATH))
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTION_NAMES
    ]
    namespace = {
        "pd": pd,
        "Any": object,
        "_month_start_range": lambda _start, _end: [],
        "perf_counter": iter([100.0, 100.75]).__next__,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SCRIPT_PATH), "exec"), namespace)
    return namespace


class FactorProgressLoggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.functions = _load_formatters()

    def test_factor_name_lines_wrap_without_losing_names(self) -> None:
        lines = self.functions["_format_factor_name_lines"](
            ["DIF", "DEA", "MACD柱", "底背离", "顶背离"],
            per_line=3,
        )

        self.assertEqual(lines, [
            "[因子 1/2] DIF、DEA、MACD柱",
            "[因子 2/2] 底背离、顶背离",
        ])

    def test_execution_plan_lines_include_ranges_and_counts(self) -> None:
        lines = self.functions["_format_execution_plan_lines"](
            plan_idx=2,
            plan_total=5,
            bundle_label="macd",
            scope="all_market",
            target_keys=["dif", "dea"],
            code_count=7369,
            query_start=pd.Timestamp("2026-04-10"),
            plan_start=pd.Timestamp("2026-07-01"),
            plan_end=pd.Timestamp("2026-07-29"),
        )

        self.assertEqual(lines[0], "[计划] 批次 2/5：macd/all_market，因子=2，代码=7369")
        self.assertEqual(
            lines[1],
            "[区间] 计算=2026-04-10 ~ 2026-07-29，写入=2026-07-01 ~ 2026-07-29",
        )
        self.assertIn("dif、dea", "\n".join(lines))

    def test_batch_finish_line_reports_real_batch_elapsed(self) -> None:
        line = self.functions["_format_batch_finish_line"](
            plan_idx=2,
            plan_total=5,
            bundle_label="macd",
            scope="all_market",
            factor_count=35,
            elapsed_seconds=12.3456,
        )

        self.assertEqual(
            line,
            "[完成] 批次 2/5：macd/all_market，生成=35，耗时=12.35秒",
        )

    def test_save_progress_line_reports_range_and_elapsed(self) -> None:
        line = self.functions["_format_save_progress_line"](
            task_idx=3,
            task_total=289,
            factor_name="DIF",
            start_dt=pd.Timestamp("2026-07-01"),
            end_dt=pd.Timestamp("2026-07-29"),
            written_months=1,
            written_rows=152384,
            elapsed_seconds=0.824,
        )

        self.assertEqual(
            line,
            "[保存完成] 3/289 DIF，区间=2026-07-01 ~ 2026-07-29，月份=1，行数=152384，耗时=0.82秒",
        )

    def test_save_task_returns_range_and_elapsed_without_extra_scan(self) -> None:
        result = self.functions["_save_single_factor_task"]({
            "factor_name": "DIF",
            "factor_df": pd.DataFrame(),
            "base_dir": "unused",
            "start_dt": pd.Timestamp("2026-07-01"),
            "end_dt": pd.Timestamp("2026-07-29"),
        })

        self.assertEqual(result[:3], ("DIF", 0, 0))
        self.assertEqual(result[3], 0.75)
        self.assertEqual(result[4], pd.Timestamp("2026-07-01"))
        self.assertEqual(result[5], pd.Timestamp("2026-07-29"))

    def test_existing_factor_save_task_only_writes_date_tail(self) -> None:
        factor_df = pd.DataFrame(
            {
                "000001.SZ": [1.0, 2.0, 3.0],
                "688825.SH": [4.0, 5.0, 6.0],
            },
            index=pd.to_datetime(["2026-07-23", "2026-07-24", "2026-07-25"]),
        )

        tasks = self.functions["_build_factor_save_tasks"](
            ch_name="DIF",
            eng_name="dif",
            factor_df=factor_df,
            base_dir="unused",
            start_dt=pd.Timestamp("2026-07-01"),
            end_dt=pd.Timestamp("2026-07-25"),
            existing_last_dt=pd.Timestamp("2026-07-24"),
            existing_codes={"000001.SZ"},
        )

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["start_dt"], pd.Timestamp("2026-07-25"))
        self.assertEqual(tasks[0]["end_dt"], pd.Timestamp("2026-07-25"))
        self.assertEqual(list(tasks[0]["factor_df"].columns), ["000001.SZ", "688825.SH"])

    def test_current_factor_has_no_save_task(self) -> None:
        tasks = self.functions["_build_factor_save_tasks"](
            ch_name="DIF",
            eng_name="dif",
            factor_df=pd.DataFrame(
                {"000001.SZ": [1.0]},
                index=pd.to_datetime(["2026-07-25"]),
            ),
            base_dir="unused",
            start_dt=pd.Timestamp("2026-07-01"),
            end_dt=pd.Timestamp("2026-07-25"),
            existing_last_dt=pd.Timestamp("2026-07-25"),
            existing_codes=set(),
        )

        self.assertEqual(tasks, [])


if __name__ == "__main__":
    unittest.main()
