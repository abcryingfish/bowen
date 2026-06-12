from __future__ import annotations

import warnings
import unittest

import numpy as np
import pandas as pd

from 均线因子 import build_ma_class_zxw_bundle


class MovingAverageWarningTest(unittest.TestCase):
    def test_all_nan_windows_do_not_emit_runtime_warning(self) -> None:
        index = pd.date_range("2026-01-01", periods=5, freq="B")
        columns = ["000001.SZ", "000002.SZ"]
        close = pd.DataFrame(np.nan, index=index, columns=columns)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out = build_ma_class_zxw_bundle(close)

        all_nan_warnings = [
            item
            for item in caught
            if issubclass(item.category, RuntimeWarning)
            and "All-NaN slice encountered" in str(item.message)
        ]
        self.assertEqual(all_nan_warnings, [])
        self.assertIn("factor_dfs", out)


if __name__ == "__main__":
    unittest.main()
