#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""获取全市场股票列表（XSHG + XSHE），保存为 CSV。

调用 insight_python.query.get_all_stocks_info 获取全部上市交易股票，
合并沪深两市，保存到 C:\\Users\\Administrator\\Desktop\\python_venv\\工具\\stock_list.csv
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

import pandas as pd

# 确保能找到工具目录下的辅助模块
_TOOLS_DIR = r"C:\Users\Administrator\Desktop\python_venv\工具"
if _TOOLS_DIR not in sys.path:
    sys.path.append(_TOOLS_DIR)

from insight_python.com.insight import common
from insight_python.com.insight.market_service import market_service
from insight_python.com.insight.query import get_all_stocks_info


class insightmarketservice(market_service):
    def on_query_response(self, result):
        for response in iter(result):
            print(response)


def login() -> None:
    markets = insightmarketservice()
    user = "MDIL1_01042"
    password = "weS._+7atE4Vdr"
    common.login(markets, user, password, login_log=False)


def normalize_code(code: object) -> str:
    return str(code).strip().upper()


def fetch_market_universe(
    listing_start: datetime,
    listing_end: datetime,
    listing_state: str = "上市交易",
) -> pd.DataFrame:
    """获取 XSHG + XSHE 全部股票信息，合并为 DataFrame。"""
    frames: list[pd.DataFrame] = []
    for exchange in ("XSHG", "XSHE"):
        result = get_all_stocks_info(
            listing_date=[listing_start, listing_end],
            exchange=exchange,
            listing_state=listing_state,
        )
        if result is None or result.empty:
            print(f"{exchange} 无数据")
            continue
        frames.append(result)
        print(f"{exchange}: {len(result)} 只股票")

    if not frames:
        raise RuntimeError("沪深两市均未获取到数据，请检查网络或账号权限。")

    df = pd.concat(frames, ignore_index=True)

    # 统一代码格式
    if "htsc_code" in df.columns:
        df["htsc_code"] = df["htsc_code"].map(normalize_code)

    # listing_date 转为日期字符串
    if "listing_date" in df.columns:
        df["listing_date"] = pd.to_datetime(df["listing_date"], errors="coerce").dt.strftime("%Y-%m-%d")

    print(f"合并后共 {len(df)} 条记录（含重复代码的展示）")
    return df.reset_index(drop=True)


def main() -> None:
    out_dir = r"C:\Users\Administrator\Desktop\python_venv\工具"
    out_path = os.path.join(out_dir, "stock_list.csv")
    os.makedirs(out_dir, exist_ok=True)

    listing_start = datetime(1990, 1, 1)
    listing_end = datetime(2026, 6, 5)

    print("=" * 50)
    print("初始化连接...")
    login()
    common.config(False, False, False)

    print(f"\n获取全市场股票（{listing_start.date()} ~ {listing_end.date()}）...")
    df = fetch_market_universe(listing_start, listing_end, "上市交易")

    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n已保存到: {out_path}")
    print(f"共 {len(df)} 只股票")
    print("\n前 5 条预览:")
    print(df.head().to_string(index=False))

    common.fini()
    print("连接已释放。")


if __name__ == "__main__":
    main()
