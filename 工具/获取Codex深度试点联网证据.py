#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
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
            time.sleep(2**attempt)
    raise RuntimeError(f"request failed: {url}: {last}")


def search_sector(name: str, kind: str, limit: int = 12) -> list[dict]:
    keyword = f"{name} 政策" if kind == "policy" else name
    payload = {
        "uid": "", "keyword": keyword, "type": ["cmsArticleWebOld"], "client": "web",
        "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default", "pageIndex": 1, "pageSize": limit, "preTag": "", "postTag": ""}},
    }
    with requests.Session() as session:
        result = request_json(session, SEARCH_URL, {"cb": "jQuery", "param": json.dumps(payload, ensure_ascii=False)}, jsonp=True)
    items = result.get("result", {}).get("cmsArticleWebOld", [])
    return [item for item in items if name in f"{item.get('title') or ''} {item.get('content') or ''}"]


def fetch_reports(days: int = 180) -> list[dict]:
    end = date(2026, 7, 18)
    begin = end - timedelta(days=days)
    out: list[dict] = []
    with requests.Session() as session:
        for page in range(1, 6):
            data = request_json(session, REPORT_URL, {"industryCode": "*", "pageSize": 100, "pageNo": page, "beginTime": begin.isoformat(), "endTime": end.isoformat(), "qType": 1, "pageNum": page, "pageNumber": page})
            out.extend(data.get("data") or [])
            if page >= int(data.get("TotalPage") or 1):
                break
    return out


def main() -> None:
    assessments = pl.read_parquet(BASE / "current" / "assessments.parquet").filter(pl.col("sector_code").is_in(PILOT_CODES))
    members = pl.read_parquet(BASE / "constituent_snapshots_eligible" / "analysis_date=2026-07-15" / "part-000.parquet")
    names = {row["sector_code"]: row["sector_name"] for row in assessments.select(["sector_code", "sector_name"]).to_dicts()}
    fetched_at = datetime.now(timezone(timedelta(hours=8))).isoformat()
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {}
        for code, name in names.items():
            futures[executor.submit(search_sector, name, "news")] = (code, "news")
            futures[executor.submit(search_sector, name, "policy")] = (code, "policy")
        for future in as_completed(futures):
            code, kind = futures[future]
            try:
                values = future.result()
            except Exception as exc:
                rows.append({"entity_id": code, "evidence_type": kind, "status": "fetch_failed", "title": str(exc), "published_at": None, "fetched_at": fetched_at, "source": "东方财富检索", "url": None, "summary": None, "content_hash": content_hash(code, kind, str(exc))})
                continue
            for value in values:
                rows.append({"entity_id": code, "evidence_type": kind, "status": "active", "title": value.get("title"), "published_at": value.get("date"), "fetched_at": fetched_at, "source": value.get("mediaName") or "东方财富检索", "url": value.get("url"), "summary": value.get("content"), "content_hash": content_hash(value.get("code"), value.get("title"), value.get("date"))})

    stock_codes = members.filter(pl.col("sector_code").is_in(PILOT_CODES)).get_column("stock_code").drop_nulls().unique().to_list()
    with requests.Session() as session:
        for start in range(0, len(stock_codes), 50):
            stock_list = ",".join(code.split(".", 1)[0] for code in stock_codes[start:start + 50])
            try:
                data = request_json(session, ANN_URL, {"sr": -1, "page_size": 100, "page_index": 1, "ann_type": "A", "client_source": "web", "stock_list": stock_list})
            except Exception:
                continue
            for value in data.get("data", {}).get("list", []):
                rows.append({"entity_id": None, "evidence_type": "announcement", "status": "active", "title": value.get("title"), "published_at": value.get("notice_date"), "fetched_at": fetched_at, "source": "东方财富公告", "url": f"https://data.eastmoney.com/notices/detail/{value.get('art_code')}.html", "summary": json.dumps(value, ensure_ascii=False), "content_hash": content_hash(value.get("art_code"), value.get("title"))})

    reports = fetch_reports()
    for value in reports:
        haystack = f"{value.get('title', '')} {value.get('industryName', '')}"
        for code, name in names.items():
            if name in haystack:
                rows.append({"entity_id": code, "evidence_type": "research_report", "status": "active", "title": value.get("title"), "published_at": value.get("publishDate"), "fetched_at": fetched_at, "source": value.get("orgName") or "东方财富研报", "url": f"https://data.eastmoney.com/report/info/{value.get('infoCode')}.html", "summary": json.dumps(value, ensure_ascii=False), "content_hash": content_hash(value.get("infoCode"), value.get("title"))})
                break

    output = pl.DataFrame(rows).unique(subset=["content_hash", "entity_id"])
    out_dir = BASE / "evidence" / f"analysis_date={ANALYSIS_DATE}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"pilot_network_{datetime.now().strftime('%Y%m%d_%H%M%S')}.parquet"
    output.write_parquet(path, compression="zstd")
    print(json.dumps({"path": str(path), "rows": output.height, "by_type": output.group_by("evidence_type").len().to_dicts()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
