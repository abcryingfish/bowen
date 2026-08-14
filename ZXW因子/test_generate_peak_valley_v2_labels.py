from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from generate_peak_valley_v2_labels import _write_batch_parts
from peak_valley_expost_annotation_v2 import V2_FACTOR_NAME_MAP


def test_write_batch_parts_uses_chinese_v2_factor_directory_and_drops_nan(tmp_path: Path) -> None:
    dates = pd.date_range("2026-01-01", periods=2, freq="D")
    factor_key = next(iter(V2_FACTOR_NAME_MAP.values()))
    frames = {
        factor_key: pd.DataFrame({"000001.SZ": [0.25, np.nan]}, index=dates)
    }

    written = _write_batch_parts(
        frames,
        output_path=str(tmp_path),
        start_date=dates[0],
        end_date=dates[-1],
    )

    paths = list(tmp_path.rglob("part_v2_*.parquet"))
    assert written == 1
    assert len(paths) == 1
    assert paths[0].parts[-4] == f"factor={next(iter(V2_FACTOR_NAME_MAP))}"
