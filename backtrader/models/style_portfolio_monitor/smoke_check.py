"""Read-only source checks and optional real-data style monitor smoke run."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

from .config import MODEL_DEFINITIONS, STYLE_MONITOR_DB_PATH
from .data import StyleDataSource
from .repository import StyleMonitorRepository
from .service import run_incremental_update


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="风格组合监控真实数据检查")
    parser.add_argument("--write", action="store_true", help="显式写入增量账本")
    parser.add_argument("--model-id", dest="model_ids", action="append", default=[])
    parser.add_argument("--through-date")
    parser.add_argument("--database-path", type=Path, default=STYLE_MONITOR_DB_PATH)
    return parser


def validate_smoke_result(result: dict) -> dict:
    errors = []
    legs = result.get("legs", {})
    if set(legs) != {"high", "low"}:
        errors.append("缺少 high/low 两条腿")
    for name, leg in legs.items():
        cash = float(leg.get("cash", 0))
        market = float(leg.get("market_value", 0))
        total = float(leg.get("total_asset", 0))
        if cash < 0:
            errors.append(f"{name} 现金为负")
        if abs(cash + market - total) > 0.01:
            errors.append(f"{name} 账本不平")
    return {"ok": not errors, "errors": errors}


def inspect_sources(source: StyleDataSource) -> list[dict]:
    market_files = source._market_files(date(1900, 1, 1), date.today())
    if not market_files:
        raise RuntimeError(f"行情目录没有分区: {source.market_root}")
    market_schema = set(pq.ParquetFile(market_files[-1]).schema_arrow.names)
    missing = {"time", "htsc_code", "close", "volume", "value"} - market_schema
    if missing:
        raise RuntimeError(f"行情缺少列: {sorted(missing)}")
    report = []
    for model in MODEL_DEFINITIONS:
        files = source._factor_files(model.factor_name)
        if not files:
            raise RuntimeError(f"缺少因子目录: factor={model.factor_name}")
        latest = source.latest_common_date(model.factor_name)
        report.append({"model_id": model.model_id, "factor_name": model.factor_name, "partitions": len(files), "latest_common_date": latest.isoformat() if latest else None})
    return report


def main() -> int:
    args = build_parser().parse_args()
    source = StyleDataSource()
    report = inspect_sources(source)
    for item in report:
        print(f"{item['model_id']}: {item['factor_name']} | 分区 {item['partitions']} | 共同最新 {item['latest_common_date']}")
    if not args.write:
        print("只读检查通过")
        return 0
    result = run_incremental_update(model_ids=args.model_ids or None, through_date=date.fromisoformat(args.through_date) if args.through_date else None, database_path=args.database_path, data_source=source)
    print(result)
    repo = StyleMonitorRepository(args.database_path)
    for model_id in result.get("completed_models", []):
        summary = next(item for item in repo.query_summary()["models"] if item["model_id"] == model_id)
        print(f"{model_id}: 最新 {summary['latest_date']} 相对净值 {summary['relative_nav']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
