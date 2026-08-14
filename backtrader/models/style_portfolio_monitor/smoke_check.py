"""Read-only source checks and optional real-data style monitor smoke run."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

from .config import MODEL_DEFINITIONS, STYLE_MONITOR_DB_PATH
from .data import StyleDataSource
from .equal_weight_runner import run_equal_weight_update
from .repository import StyleMonitorRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="风格组合监控真实数据检查")
    parser.add_argument("--write", action="store_true", help="显式写入理论等权指数账本")
    parser.add_argument("--model-id", dest="model_ids", action="append", default=[])
    parser.add_argument("--through-date")
    parser.add_argument("--database-path", type=Path, default=STYLE_MONITOR_DB_PATH)
    return parser


def validate_smoke_result(result: dict) -> dict:
    errors = []
    completed = result.get("completed_models")
    if not isinstance(completed, list):
        errors.append("缺少 completed_models")
    failed = result.get("failed_models") or []
    if failed:
        errors.append(f"存在失败模型: {len(failed)}")
    processed_days = result.get("processed_days") or {}
    for model_id in completed or []:
        try:
            processed = int(processed_days.get(model_id, 0))
        except (TypeError, ValueError):
            processed = 0
        if processed < 1:
            errors.append(f"{model_id} 未生成理论指数日期")
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
    result = run_equal_weight_update(
        model_ids=args.model_ids or None,
        through_date=date.fromisoformat(args.through_date) if args.through_date else None,
        database_path=args.database_path,
        signal_base_dir=source.signal_root,
        market_base_dir=source.market_root,
    )
    print(result)
    validation = validate_smoke_result(result)
    if not validation["ok"]:
        print("理论指数检查失败: " + "；".join(validation["errors"]))
        return 1
    repo = StyleMonitorRepository(args.database_path)
    for model_id in result.get("completed_models", []):
        summary = next(item for item in repo.query_summary()["models"] if item["model_id"] == model_id)
        print(f"{model_id}: 最新 {summary['latest_date']} 相对指数 {summary['relative_nav']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
