# -*- coding: utf-8 -*-
"""原生 Python 获取 xtquant 历史数据示例。"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from xtquant import xtdata

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


OUTPUT_DIR = Path(__file__).resolve().parent
DEFAULT_CODE = "600519.SH"
DEFAULT_START = "20260611"
DEFAULT_END = "20260611"
DEFAULT_PERIOD = "tick"


def normalize_period(period: str) -> str:
    period = str(period).strip()
    if period == "tick":
        return period
    if "d" in period:
        return "1d"
    if "m" in period:
        if int(period[0]) < 5:
            return "1m"
        return "5m"
    raise ValueError(f"周期参数错误: {period}")


def fetch_history(code: str, period: str, start_date: str, end_date: str) -> pd.DataFrame:
    period = normalize_period(period)
    code = code.strip().upper()
    print(f"下载历史数据: code={code}, period={period}, start={start_date}, end={end_date}")
    xtdata.download_history_data(code, period, start_date, end_date)

    data = xtdata.get_market_data_ex(
        field_list=[],
        stock_list=[code],
        period=period,
        start_time=start_date,
        end_time=end_date,
        count=-1,
        dividend_type="none",
        fill_data=False,
    )
    if not isinstance(data, dict) or code not in data:
        raise RuntimeError(f"未返回 {code} 数据，返回类型: {type(data).__name__}")

    df = data[code]
    if df is None or len(df) == 0:
        raise RuntimeError(f"{code} 返回空数据")

    df = df.copy()
    df.insert(0, "code", code)
    df = df.reset_index()
    if "time" in df.columns:
        df = df.rename(columns={"time": "time_raw"})
        time_series = pd.to_numeric(df["time_raw"], errors="coerce")
        df.insert(
            2,
            "time",
            pd.to_datetime(time_series, unit="ms", errors="coerce", utc=True)
            .dt.tz_convert("Asia/Shanghai")
            .dt.tz_localize(None),
        )
    return df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="下载并读取 xtquant 历史数据")
    parser.add_argument("--code", default=DEFAULT_CODE, help="股票代码，默认 600519.SH")
    parser.add_argument("--start", default=DEFAULT_START, help="开始日期，格式 YYYYMMDD 或 YYYYMMDDHHMMSS")
    parser.add_argument("--end", default=DEFAULT_END, help="结束日期，格式 YYYYMMDD 或 YYYYMMDDHHMMSS")
    parser.add_argument("--period", default=DEFAULT_PERIOD, help="周期：tick / 1m / 5m / 1d")
    parser.add_argument("--no-save", action="store_true", help="只打印，不保存 CSV")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = fetch_history(args.code, args.period, args.start, args.end)
    print(f"获取完成: {len(df)} 行")
    print(df.head())
    print(df.tail())

    if not args.no_save:
        safe_code = args.code.replace(".", "_").upper()
        output_path = OUTPUT_DIR / (
            f"history_{safe_code}_{args.period}_{args.start}_{args.end}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"已保存: {output_path}")


if __name__ == "__main__":
    main()
