import importlib.util
from datetime import date
from pathlib import Path

import polars as pl


def load_qmt_adj_module():
    module_path = Path(__file__).parent / "工具" / "qmt获得股票日频复权因子.py"
    spec = importlib.util.spec_from_file_location("qmt_adj_factor_daily", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect_month_frames(frames):
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames.values(), how="vertical_relaxed").sort(["htsc_code", "time"])


def test_build_adj_factor_daily_uses_cumulative_backward_factor_and_2010_cutoff():
    module = load_qmt_adj_module()
    seg = pl.DataFrame(
        {
            "htsc_code": ["000001.SZ", "000001.SZ", "000001.SZ", "000002.SZ"],
            "begin_date": [date(2009, 12, 30), date(2010, 1, 3), date(2010, 1, 5), date(2010, 1, 2)],
            "end_date": [date(2010, 1, 2), date(2010, 1, 4), date(2010, 1, 6), date(2010, 1, 4)],
            "xdy": [2.0, 3.0, 3.0, 5.0],
        }
    )

    frames = module.build_monthly_adj_factor_daily_frames(
        seg,
        start_date=date(2010, 1, 1),
    )
    out = collect_month_frames(frames)

    assert out.to_dicts() == [
        {"htsc_code": "000001.SZ", "time": date(2010, 1, 1), "adj_factor": 2.0},
        {"htsc_code": "000001.SZ", "time": date(2010, 1, 2), "adj_factor": 2.0},
        {"htsc_code": "000001.SZ", "time": date(2010, 1, 3), "adj_factor": 6.0},
        {"htsc_code": "000001.SZ", "time": date(2010, 1, 4), "adj_factor": 6.0},
        {"htsc_code": "000001.SZ", "time": date(2010, 1, 5), "adj_factor": 6.0},
        {"htsc_code": "000001.SZ", "time": date(2010, 1, 6), "adj_factor": 6.0},
        {"htsc_code": "000002.SZ", "time": date(2010, 1, 2), "adj_factor": 5.0},
        {"htsc_code": "000002.SZ", "time": date(2010, 1, 3), "adj_factor": 5.0},
        {"htsc_code": "000002.SZ", "time": date(2010, 1, 4), "adj_factor": 5.0},
    ]


def test_write_adj_factor_daily_replaces_only_affected_codes(tmp_path):
    module = load_qmt_adj_module()
    base_dir = tmp_path / "stock_adj_daily"
    month_dir = base_dir / module.ADJ_FACTOR_DAILY_DIR_NAME / "year=2010" / "month=01"
    month_dir.mkdir(parents=True)
    old = pl.DataFrame(
        {
            "htsc_code": ["000001.SZ", "000003.SZ"],
            "time": [date(2010, 1, 2), date(2010, 1, 2)],
            "adj_factor": [1.0, 7.0],
        }
    )
    old.write_parquet(str(month_dir / "merged.parquet"))
    new_frames = {
        (2010, 1): pl.DataFrame(
            {
                "htsc_code": ["000001.SZ", "000001.SZ"],
                "time": [date(2010, 1, 2), date(2010, 1, 3)],
                "adj_factor": [2.0, 3.0],
            }
        )
    }

    touched = module.write_monthly_adj_factor_daily_frames(
        new_frames,
        base_dir=str(base_dir),
        replace_codes={"000001.SZ"},
    )

    assert touched == 1
    saved = pl.read_parquet(str(month_dir / "merged.parquet")).sort(["htsc_code", "time"])
    assert saved.to_dicts() == [
        {"htsc_code": "000001.SZ", "time": date(2010, 1, 2), "adj_factor": 2.0},
        {"htsc_code": "000001.SZ", "time": date(2010, 1, 3), "adj_factor": 3.0},
        {"htsc_code": "000003.SZ", "time": date(2010, 1, 2), "adj_factor": 7.0},
    ]
