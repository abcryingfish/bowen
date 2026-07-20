#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

import polars as pl
import requests


BASE = Path(r"D:\database\sector_information")
ANALYSIS_DATE = "2026-07-18"
PILOT_CODES = [
    "881101.THS", "882001.THS", "885462.THS", "886065.THS",
    "886069.THS", "886072.THS", "886086.THS", "886095.THS",
    "886101.THS", "886102.THS", "886109.THS", "886111.THS",
]
URL = "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax"


def fetch(code: str) -> dict:
    number, exchange = code.split(".", 1)
    market = "SH" if exchange == "SH" else "SZ"
    response = requests.get(URL, params={"code": f"{market}{number}"}, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    response.raise_for_status()
    payload = response.json()
    basic = payload.get("jbzl") or {}
    return {
        "stock_code": code,
        "company_name": basic.get("gsmc"),
        "industry": basic.get("sshy"),
        "sw_industry": basic.get("sszjhhy"),
        "company_summary": basic.get("gsjj"),
        "business_scope": basic.get("jyfw"),
        "source_url": f"{URL}?code={market}{number}",
        "fetched_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
    }


def main() -> None:
    members = pl.read_parquet(BASE / "constituent_snapshots_eligible" / "analysis_date=2026-07-15" / "part-000.parquet")
    stocks = members.filter(pl.col("sector_code").is_in(PILOT_CODES)).get_column("stock_code").drop_nulls().unique().to_list()
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(fetch, stock): stock for stock in stocks}
        for future in as_completed(futures):
            stock = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:
                rows.append({"stock_code": stock, "company_name": None, "industry": None, "sw_industry": None, "company_summary": None, "business_scope": None, "source_url": None, "fetched_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "error": str(exc)})
    frame = pl.DataFrame(rows).with_columns(pl.lit(ANALYSIS_DATE).alias("analysis_date"))
    out_dir = BASE / "company_business_profiles" / f"analysis_date={ANALYSIS_DATE}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "pilot_profiles.parquet"
    frame.write_parquet(path, compression="zstd")
    print(json.dumps({"path": str(path), "requested": len(stocks), "rows": frame.height, "successful": frame.filter(pl.col("company_summary").is_not_null()).height}, ensure_ascii=False))


if __name__ == "__main__":
    main()
