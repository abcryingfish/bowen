from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

BASE = Path(r"D:\database\sector_information")


def _read(name: str, limit: int = 10000) -> list[dict[str, Any]]:
    path = BASE / name / "analysis_date=*" / "part-*.parquet"
    if not path.parent.parent.exists():
        return []
    query = "select * from read_parquet(?, hive_partitioning=true, union_by_name=true) order by analysis_date desc limit ?"
    rows = duckdb.sql(query, params=[str(path), limit]).fetchall()
    cols = duckdb.sql(query, params=[str(path), 1]).columns
    return [dict(zip(cols, row)) for row in rows]


def _jsonable(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return value


def list_entities(limit: int = 600) -> dict[str, Any]:
    rows = _read("assessments", limit)
    for row in rows:
        row["classification_facets"] = json.loads(row.pop("classification_facets_json", "{}"))
        for key, value in list(row.items()):
            row[key] = _jsonable(value)
    return {"api_version": "sector_api.v1", "data": rows, "meta": {"count": len(rows)}}


def dashboard(sector_code: str) -> dict[str, Any]:
    rows = [row for row in _read("assessments", 600) if str(row.get("sector_code")) == sector_code]
    if not rows:
        return {"api_version": "sector_api.v1", "data": None, "error": {"code": "NOT_FOUND", "message": "未找到板块"}}
    dims = [row for row in _read("dimension_scores", 10000) if str(row.get("sector_code")) == sector_code]
    row = rows[0]
    row["classification_facets"] = json.loads(row.pop("classification_facets_json", "{}"))
    row["dimension_scores"] = dims
    return {"api_version": "sector_api.v1", "data": {k: _jsonable(v) for k, v in row.items()}}
