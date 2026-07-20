#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import polars as pl
import requests


BASE = Path(r"D:\database\sector_information")
SEARCH_URL = "https://search-api-web.eastmoney.com/search/jsonp"
ANN_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
REPORT_URL = "https://reportapi.eastmoney.com/report/list"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.eastmoney.com/"}


def content_hash(*values: object) -> str:
    return hashlib.sha256("\x1f".join(str(v or "") for v in values).encode("utf-8")).hexdigest()


def request_json(session: requests.Session, url: str, params: dict, jsonp: bool = False) -> dict:
    last: Exception | None = None
    for attempt in range(4):
        try:
            response = session.get(url, params=params, headers=HEADERS, timeout=20)
            response.raise_for_status()
            text = response.text.strip()
            if jsonp:
                match = re.match(r"^[^(]+\((.*)\)\s*$", text, re.S)
                if not match:
                    raise ValueError("invalid JSONP")
                return json.loads(match.group(1))
            return response.json()
        except Exception as exc:
            last = exc
            time.sleep((2**attempt) + random.random())
    raise RuntimeError(f"request failed: {url}: {last}")


def search_sector(name: str, kind: str, page_size: int) -> list[dict]:
    keyword = f"{name} 政策" if kind == "policy" else name
    payload = {
        "uid": "", "keyword": keyword, "type": ["cmsArticleWebOld"], "client": "web",
        "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default", "pageIndex": 1, "pageSize": page_size, "preTag": "", "postTag": ""}},
    }
    with requests.Session() as session:
        data = request_json(session, SEARCH_URL, {"cb": "jQuery", "param": json.dumps(payload, ensure_ascii=False)}, jsonp=True)
    results = data.get("result", {}).get("cmsArticleWebOld", [])
    return [item for item in results if name in f"{item.get('title') or ''} {item.get('content') or ''}"]


def fetch_announcements(codes: list[str], page_size: int) -> list[dict]:
    out: list[dict] = []
    with requests.Session() as session:
        for start in range(0, len(codes), 50):
            stock_list = ",".join(code.split(".", 1)[0] for code in codes[start:start + 50])
            data = request_json(session, ANN_URL, {"sr": -1, "page_size": page_size, "page_index": 1, "ann_type": "A", "client_source": "web", "stock_list": stock_list})
            out.extend(data.get("data", {}).get("list", []))
            time.sleep(0.08)
    return out


def fetch_reports(days: int) -> list[dict]:
    end = date.today()
    begin = end - timedelta(days=days)
    out: list[dict] = []
    with requests.Session() as session:
        page = 1
        while True:
            data = request_json(session, REPORT_URL, {"industryCode": "*", "pageSize": 100, "pageNo": page, "beginTime": begin.isoformat(), "endTime": end.isoformat(), "qType": 1, "pageNum": page, "pageNumber": page})
            out.extend(data.get("data") or [])
            if page >= int(data.get("TotalPage") or 1):
                break
            page += 1
            time.sleep(0.1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", default=str(BASE))
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--news-per-sector", type=int, default=8)
    parser.add_argument("--policy-per-sector", type=int, default=5)
    parser.add_argument("--announcements-per-batch", type=int, default=100)
    parser.add_argument("--report-days", type=int, default=90)
    args = parser.parse_args()
    base = Path(args.base_dir)
    assessments = pl.read_parquet(base / "current" / "assessments.parquet").to_pandas()
    members = pl.read_parquet(base / "constituent_snapshots_eligible" / "analysis_date=*" / "part-*.parquet").to_pandas()
    fetched_at = datetime.now(timezone(timedelta(hours=8))).isoformat()
    rows: list[dict] = []

    jobs = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for item in assessments[["sector_code", "sector_name"]].to_dict("records"):
            jobs.append((item, "news", executor.submit(search_sector, item["sector_name"], "news", args.news_per_sector)))
            jobs.append((item, "policy", executor.submit(search_sector, item["sector_name"], "policy", args.policy_per_sector)))
        for item, kind, future in jobs:
            try:
                results = future.result()
            except Exception as exc:
                rows.append({"entity_id": item["sector_code"], "evidence_type": kind, "status": "fetch_failed", "title": str(exc), "published_at": None, "fetched_at": fetched_at, "source": "东方财富", "url": None, "summary": None, "content_hash": content_hash(item["sector_code"], kind, str(exc))})
                continue
            for value in results:
                rows.append({"entity_id": item["sector_code"], "evidence_type": kind, "status": "active", "title": value.get("title"), "published_at": value.get("date"), "fetched_at": fetched_at, "source": value.get("mediaName") or "东方财富", "url": value.get("url"), "summary": value.get("content"), "content_hash": content_hash(value.get("code"), value.get("title"), value.get("date"))})

    codes = sorted(set(members["stock_code"].dropna().astype(str)))
    for value in fetch_announcements(codes, args.announcements_per_batch):
        linked = [f"{code.get('stock_code')}.{'SH' if code.get('market_code') == '1' else 'SZ'}" for code in value.get("codes", [])]
        rows.append({"entity_id": None, "evidence_type": "announcement", "status": "active", "title": value.get("title"), "published_at": value.get("notice_date"), "fetched_at": fetched_at, "source": "东方财富公告", "url": f"https://data.eastmoney.com/notices/detail/{linked[0].split('.')[0] if linked else ''}/{value.get('art_code')}.html", "summary": json.dumps({"art_code": value.get("art_code"), "stock_codes": linked, "columns": value.get("columns")}, ensure_ascii=False), "content_hash": content_hash(value.get("art_code"), value.get("title"))})

    names = assessments[["sector_code", "sector_name"]].to_dict("records")
    for value in fetch_reports(args.report_days):
        haystack = f"{value.get('title', '')} {value.get('industryName', '')}"
        matches = [x["sector_code"] for x in names if str(x["sector_name"]) in haystack]
        rows.append({"entity_id": matches[0] if len(matches) == 1 else None, "evidence_type": "research_report", "status": "active", "title": value.get("title"), "published_at": value.get("publishDate"), "fetched_at": fetched_at, "source": value.get("orgName") or "东方财富研报", "url": f"https://data.eastmoney.com/report/info/{value.get('infoCode')}.html", "summary": json.dumps({"industry_name": value.get("industryName"), "rating": value.get("emRatingName"), "researcher": value.get("researcher"), "pages": value.get("attachPages")}, ensure_ascii=False), "content_hash": content_hash(value.get("infoCode"), value.get("title"))})

    frame = pl.from_pandas(pd.DataFrame(rows)).unique(subset=["content_hash", "entity_id"], keep="last")
    day = date.today().isoformat()
    out = base / "evidence" / f"fetched_date={day}" / "part-000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(out, compression="zstd")
    current = base / "current" / "evidence.parquet"
    frame.write_parquet(current, compression="zstd")
    direct_links = frame.filter(pl.col("entity_id").is_not_null()).select([
        pl.col("content_hash").alias("evidence_id"),
        pl.col("entity_id").alias("sector_code"),
        pl.lit("direct_search_match").alias("link_method"),
    ])
    announcement_rows: list[dict] = []
    for value in frame.filter(pl.col("evidence_type") == "announcement").select(["content_hash", "summary"]).iter_rows(named=True):
        try:
            stock_codes = json.loads(value["summary"] or "{}").get("stock_codes", [])
        except json.JSONDecodeError:
            stock_codes = []
        announcement_rows.extend({"evidence_id": value["content_hash"], "stock_code": code} for code in stock_codes)
    if announcement_rows:
        ann = pl.from_dicts(announcement_rows)
        member_links = pl.from_pandas(members[["sector_code", "stock_code"]].drop_duplicates())
        ann_links = ann.join(member_links, on="stock_code", how="inner").select([
            "evidence_id", "sector_code", pl.lit("constituent_announcement").alias("link_method")
        ])
        links = pl.concat([direct_links, ann_links], how="vertical").unique()
    else:
        links = direct_links
    link_out = base / "claim_evidence_links" / f"fetched_date={day}" / "part-000.parquet"
    link_out.parent.mkdir(parents=True, exist_ok=True)
    links.write_parquet(link_out, compression="zstd")
    links.write_parquet(base / "current" / "claim_evidence_links.parquet", compression="zstd")
    print(json.dumps({"fetched_date": day, "records": frame.height, "sector_links": links.height, "by_type": frame.group_by("evidence_type").len().sort("evidence_type").to_dicts()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
