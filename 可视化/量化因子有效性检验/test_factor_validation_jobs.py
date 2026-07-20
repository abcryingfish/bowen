from __future__ import annotations

import time
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
import factor_validation_service as service


class FactorValidationJobTests(unittest.TestCase):
    def test_job_records_result_after_background_runner_finishes(self) -> None:
        def runner(payload):
            time.sleep(0.05)
            return {"meta": {"factor": payload["factor"]}, "quality": {}}

        job = service.create_factor_validation_job({"factor": "RSI买入信号"}, runner=runner)
        self.assertIn(job["status"], {"queued", "running"})
        self.assertTrue(job["job_id"])

        finished = self._wait_for_terminal_job(job["job_id"])
        self.assertEqual(finished["status"], "done")
        self.assertEqual(finished["result"]["meta"]["factor"], "RSI买入信号")
        self.assertGreaterEqual(finished["elapsed_seconds"], 0)

    def test_job_records_error_after_background_runner_fails(self) -> None:
        def runner(_payload):
            raise service.FactorValidationInputError("factor 不能为空")

        job = service.create_factor_validation_job({"factor": ""}, runner=runner)
        failed = self._wait_for_terminal_job(job["job_id"])

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"]["code"], "INVALID_ARGUMENT")
        self.assertIn("factor", failed["error"]["message"])

    def _wait_for_terminal_job(self, job_id: str) -> dict:
        deadline = time.time() + 2
        while time.time() < deadline:
            job = service.get_factor_validation_job(job_id)
            if job["status"] in {"done", "failed"}:
                return job
            time.sleep(0.02)
        self.fail("job did not finish in time")


class PriceAdjustModeTests(unittest.TestCase):
    def test_read_price_frame_none_skips_adjustment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            parquet_path = self._write_price_fixture(Path(tmpdir))
            calls = []

            original_paths = service._build_month_partition_paths
            original_apply = service.apply_ohlc_adj_to_price_df
            service._build_month_partition_paths = lambda *_args, **_kwargs: [parquet_path.as_posix()]
            service.apply_ohlc_adj_to_price_df = lambda *args, **kwargs: calls.append((args, kwargs))
            try:
                df = service._read_price_frame(
                    pd.Timestamp("2026-01-01"),
                    pd.Timestamp("2026-01-02"),
                    ["000001.SZ"],
                    1,
                    "none",
                )
            finally:
                service._build_month_partition_paths = original_paths
                service.apply_ohlc_adj_to_price_df = original_apply

        self.assertEqual(calls, [])
        self.assertEqual(len(df), 2)
        self.assertEqual(df["close"].tolist(), [10.0, 11.0])

    def test_read_price_frame_backward_ratio_uses_adjustment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            parquet_path = self._write_price_fixture(Path(tmpdir))
            calls = []

            def fake_apply(price_df, **kwargs):
                calls.append(kwargs)
                adjusted = price_df.copy()
                adjusted["close"] = adjusted["close"] * 2
                return adjusted

            original_paths = service._build_month_partition_paths
            original_apply = service.apply_ohlc_adj_to_price_df
            service._build_month_partition_paths = lambda *_args, **_kwargs: [parquet_path.as_posix()]
            service.apply_ohlc_adj_to_price_df = fake_apply
            try:
                df = service._read_price_frame(
                    pd.Timestamp("2026-01-01"),
                    pd.Timestamp("2026-01-02"),
                    ["000001.SZ"],
                    1,
                    "backward_ratio",
                )
            finally:
                service._build_month_partition_paths = original_paths
                service.apply_ohlc_adj_to_price_df = original_apply

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["adj_mode"], "backward_ratio")
        self.assertEqual(df["close"].tolist(), [20.0, 22.0])

    def test_parse_price_adjust_mode_rejects_unknown_value(self) -> None:
        with self.assertRaises(service.FactorValidationInputError):
            service._parse_price_adjust_mode("forward_ratio")

    def _write_price_fixture(self, directory: Path) -> Path:
        path = directory / "merged.parquet"
        pd.DataFrame(
            [
                {"htsc_code": "000001.SZ", "time": "2026-01-01", "close": 10.0},
                {"htsc_code": "000001.SZ", "time": "2026-01-02", "close": 11.0},
            ]
        ).to_parquet(path)
        return path


class MorphFactorTests(unittest.TestCase):
    def test_parse_morph_factor_name_keeps_level_and_pattern(self) -> None:
        self.assertEqual(
            service._parse_morph_factor_name("morph/level2/刺透形态"),
            ("level2", "刺透形态"),
        )
        self.assertIsNone(service._parse_morph_factor_name("普通因子"))

    def test_read_morph_factor_uses_start_date_and_max_value_per_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            partition = base / "events" / "year=2026" / "month=01"
            partition.mkdir(parents=True)
            parquet_path = partition / "merged.parquet"
            pd.DataFrame(
                [
                    {
                        "htsc_code": "000001.SZ",
                        "start_time": "2026-01-05 09:31:00",
                        "time": "2026-01-06 15:00:00",
                        "signal_name": "吞没形态",
                        "value": 2.0,
                        "level": "level1",
                    },
                    {
                        "htsc_code": "000001.SZ",
                        "start_time": "2026-01-05 10:02:00",
                        "time": "2026-01-06 15:00:00",
                        "signal_name": "吞没形态",
                        "value": 5.0,
                        "level": "level1",
                    },
                ]
            ).to_parquet(parquet_path)
            original = service.MORPH_CANDLESTICK_BASE_PATH
            service.MORPH_CANDLESTICK_BASE_PATH = base
            try:
                result = service._read_morph_factor_frame(
                    "level1", "吞没形态", pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-31"), ["000001.SZ"]
                )
            finally:
                service.MORPH_CANDLESTICK_BASE_PATH = original

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["time"], pd.Timestamp("2026-01-05"))
        self.assertEqual(result.iloc[0]["value"], 5.0)

    def test_list_factors_includes_each_morph_pattern_in_morph_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "morph_candlestick_manifest.json").write_text(
                '{"patterns": {"吞没形态": {"level": "level1"}, "刺透形态": {"level": "level2"}}}',
                encoding="utf-8",
            )
            original_base = service.MORPH_CANDLESTICK_BASE_PATH
            original_signal = service.SIGNAL_DAILY_BASE_PATH
            service.MORPH_CANDLESTICK_BASE_PATH = base
            service.SIGNAL_DAILY_BASE_PATH = base / "ordinary"
            try:
                payload = service.list_factor_validation_factors()
            finally:
                service.MORPH_CANDLESTICK_BASE_PATH = original_base
                service.SIGNAL_DAILY_BASE_PATH = original_signal

        morph_group = next(group for group in payload["groups"] if group["group_id"] == "morph")
        self.assertEqual(morph_group["children"], ["morph/level1/吞没形态", "morph/level2/刺透形态"])

    def test_list_morph_factors_uses_event_names_and_levels_when_events_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "morph_candlestick_manifest.json").write_text(
                '{"patterns": {"manifest_only": {"level": "level1"}}}',
                encoding="utf-8",
            )
            partition = base / "events" / "year=2026" / "month=01"
            partition.mkdir(parents=True)
            pd.DataFrame(
                [
                    {"signal_name": "actual_pattern", "level": "level2"},
                    {"signal_name": "actual_pattern", "level": "level3"},
                ]
            ).to_parquet(partition / "merged.parquet")
            original_base = service.MORPH_CANDLESTICK_BASE_PATH
            service.MORPH_CANDLESTICK_BASE_PATH = base
            try:
                factors = service._load_available_morph_factors()
            finally:
                service.MORPH_CANDLESTICK_BASE_PATH = original_base

        self.assertEqual(factors, ["morph/level2/actual_pattern", "morph/level3/actual_pattern"])


if __name__ == "__main__":
    unittest.main()
