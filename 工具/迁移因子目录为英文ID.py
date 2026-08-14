# -*- coding: utf-8 -*-
"""将 signal_daily 因子目录统一迁移为稳定英文 ID。

默认仅输出 dry-run 计划；传入 ``--execute`` 才会修改数据。已有英文目录时按月
合并，中文源目录的数据优先，使用 ``time + htsc_code`` 去重。每个月写回后都会
复读校验，全部月份成功后才删除源目录。
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

import polars as pl


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FACTOR_MODULE_DIR = PROJECT_ROOT / "ZXW因子"
DEFAULT_BASE_DIR = Path(r"D:\database\signal_daily")
KEY_COLUMNS = ["time", "htsc_code"]
STABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
INVALID_FACTOR_PATH_CHARS = re.compile(r'[\\/:*?"<>|]')

BUNDLE_MODULES = (
    "MACD因子", "KDJ因子", "抄底因子", "洪抄底", "RSI", "OBV因子",
    "唐奇安下通道", "动态波动率通道", "筹码结构因子", "新HL占比",
    "布林带策略", "总买入信号_独立全量", "总卖出信号", "卖出MACD",
    "总卖出信号测试", "卖出因子_量能", "均线因子", "放量下跌因子",
    "通达信强底信号", "板块动量策略常用因子", "股票动量风格评分",
    "低波因子", "股票低波风格评分", "流动性因子", "股票流动性综合评分",
    "股票市场数据因子", "股票纯市值风格评分", "股票基本面原始因子",
    "股票价值标准化因子", "股票价值模型综合评分",
    "股票价值模型行业标准化评分", "股票价值模型多板块标准化评分",
    "股票成长原始因子", "股票成长标准化因子", "股票成长行业标准化因子",
    "股票成长多板块标准化因子", "股票红利原始因子", "股票红利标准化因子",
)

EXPLICIT_ALIASES = {
    "20_60日波动率比": "volatility_ratio_20_60d",
    "股票5日动量": "stock_momentum_5d",
    "股票20日动量": "stock_momentum_20d",
    "新粉丝占比（%）": "new_uid_rate",
    "老粉丝占比（%）": "old_uid_rate",
    "新粉丝占比变化": "new_uid_change_rank",
    "老粉丝占比变化": "old_uid_change_rank",
    "历史人气排名": "history_rank",
    "历史排名变化": "history_rank_change",
    "历史排名变化排名": "history_rank_change_rank",
    "人气热度分数": "hot_rank_score",
    "当日排名变化": "daily_rank_change",
    "小时排名变化": "hourly_rank_change",
    "市场股票总数": "market_stock_count",
    "行业PB历史分位_中位数": "industry_pb_percentile_median",
    "行业PB历史分位_市值加权": "industry_pb_percentile_mcap",
    "连续分红年数": "cash_dividend_consecutive_years",
    "连续分红年数_近5年": "cash_dividend_consecutive_years",
    "连续分红年数_百分位": "cash_dividend_consecutive_years_percentile",
    "连续分红年数_近5年_百分位": "cash_dividend_consecutive_years_percentile",
    "连续分红年数_标准分": "cash_dividend_consecutive_years_standard_score",
    "连续分红年数_近5年_标准分": "cash_dividend_consecutive_years_standard_score",
}
PRESERVED_UNMAPPED_NAMES = {"20日动量.backup_pre_adj_fix_20260811"}


def _sanitize_factor_name(name: str) -> str:
    return INVALID_FACTOR_PATH_CHARS.sub("_", str(name).strip()).rstrip(" .")


def _add_mapping(
    display_to_id: dict[str, str],
    display_name: Any,
    factor_id: Any,
) -> None:
    display = _sanitize_factor_name(str(display_name))
    stable_id = str(factor_id).strip()
    if not display or not stable_id or not STABLE_ID_PATTERN.fullmatch(stable_id):
        return
    existing = display_to_id.get(display)
    if existing is not None and existing != stable_id:
        raise ValueError(f"展示名映射冲突: {display} -> {existing} / {stable_id}")
    display_to_id[display] = stable_id


def build_factor_mapping(base_dir: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    cache_path = base_dir / "_meta" / "bundle_factor_catalog_cache.json"
    if cache_path.is_file():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        for factor_map in payload.get("catalog", {}).values():
            if isinstance(factor_map, dict):
                for display, factor_id in factor_map.items():
                    _add_mapping(mapping, display, factor_id)

    pure_path = base_dir / "_meta" / "pure_technical_factor_catalog_cache.json"
    if pure_path.is_file():
        payload = json.loads(pure_path.read_text(encoding="utf-8"))
        for factor_id, display in payload.get("factor_labels", {}).items():
            _add_mapping(mapping, display, factor_id)

    if str(FACTOR_MODULE_DIR) not in sys.path:
        sys.path.append(str(FACTOR_MODULE_DIR))
    for module_name in BUNDLE_MODULES:
        try:
            module = importlib.import_module(module_name)
            loader = getattr(module, "get_factor_catalog", None)
            catalog = loader() if callable(loader) else {}
        except Exception as exc:
            print(f"[WARN] 无法读取 {module_name} 因子目录: {exc}")
            continue
        factor_map = catalog.get("factor_name_map", {}) if isinstance(catalog, dict) else {}
        if isinstance(factor_map, dict):
            for display, factor_id in factor_map.items():
                _add_mapping(mapping, display, factor_id)

    try:
        label_module = importlib.import_module("peak_valley_expost_annotation_v2")
        label_map = getattr(label_module, "V2_FACTOR_NAME_MAP", {})
    except Exception as exc:
        print(f"[WARN] 无法读取 V2 标签目录: {exc}")
        label_map = {}
    if isinstance(label_map, dict):
        for display, factor_id in label_map.items():
            _add_mapping(mapping, display, factor_id)

    for display, factor_id in EXPLICIT_ALIASES.items():
        _add_mapping(mapping, display, factor_id)
    return mapping


def _factor_dirs(base_dir: Path) -> dict[str, Path]:
    return {
        path.name[len("factor="):]: path
        for path in base_dir.glob("factor=*")
        if path.is_dir()
    }


def build_migration_plan(base_dir: Path, mapping: dict[str, str]) -> tuple[list[tuple[str, str]], list[str]]:
    directories = _factor_dirs(base_dir)
    plan = sorted(
        (source_name, factor_id)
        for source_name, factor_id in mapping.items()
        if source_name in directories and source_name != factor_id
    )
    mapped_sources = {source for source, _ in plan}
    stable_ids = set(mapping.values())
    unmapped = sorted(
        name for name in directories
        if name not in mapped_sources
        and name not in stable_ids
        and name not in PRESERVED_UNMAPPED_NAMES
        and not STABLE_ID_PATTERN.fullmatch(name)
    )
    return plan, unmapped


def _month_key(path: Path) -> tuple[int, int]:
    return int(path.parent.name.split("=", 1)[1]), int(path.name.split("=", 1)[1])


def _month_dirs(factor_dir: Path) -> dict[tuple[int, int], Path]:
    return {
        _month_key(path): path
        for path in factor_dir.glob("year=*/month=*")
        if path.is_dir()
    }


def _normalize_frame(frame: pl.DataFrame, path: Path) -> pl.DataFrame:
    missing = [column for column in KEY_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"{path} 缺少主键列: {missing}")
    value_columns = [column for column in frame.columns if column not in KEY_COLUMNS]
    return frame.select(
        pl.col("time").cast(pl.Datetime("us")),
        pl.col("htsc_code").cast(pl.String).str.strip_chars().str.to_uppercase(),
        *[pl.col(column) for column in value_columns],
    )


def _read_month(month_dir: Path) -> pl.DataFrame:
    merged = month_dir / "merged.parquet"
    paths = ([merged] if merged.is_file() else []) + sorted(
        path for path in month_dir.glob("*.parquet") if path != merged
    )
    frames = [
        _normalize_frame(pl.read_parquet(str(path)), path)
        for path in paths if path.stat().st_size >= 12
    ]
    if not frames:
        raise ValueError(f"月份目录没有有效 parquet: {month_dir}")
    frame = pl.concat(frames, how="diagonal_relaxed")
    return frame.unique(subset=KEY_COLUMNS, keep="last", maintain_order=True).sort(KEY_COLUMNS)


def _validate_factor_dir(factor_dir: Path) -> tuple[int, int]:
    months = _month_dirs(factor_dir)
    rows = 0
    for month_dir in months.values():
        frame = _read_month(month_dir)
        if frame.select(pl.struct(KEY_COLUMNS).is_duplicated().any()).item():
            raise ValueError(f"主键去重失败: {month_dir}")
        rows += frame.height
    return len(months), rows


def _parquet_snapshot(factor_dir: Path) -> dict[str, int]:
    return {
        str(path.relative_to(factor_dir)): path.stat().st_size
        for path in factor_dir.rglob("*.parquet")
        if path.is_file()
    }


def _read_month_keys(month_dir: Path) -> pl.DataFrame:
    merged = month_dir / "merged.parquet"
    paths = ([merged] if merged.is_file() else []) + sorted(
        path for path in month_dir.glob("*.parquet") if path != merged
    )
    frames = [
        pl.read_parquet(str(path), columns=KEY_COLUMNS).select(
            pl.col("time").cast(pl.Datetime("us")),
            pl.col("htsc_code").cast(pl.String).str.strip_chars().str.to_uppercase(),
        )
        for path in paths if path.stat().st_size >= 12
    ]
    if not frames:
        raise ValueError(f"月份目录没有有效 parquet: {month_dir}")
    return pl.concat(frames, how="vertical_relaxed").unique(KEY_COLUMNS)


def _source_covers_destination(source: Path, destination: Path) -> bool:
    source_months = _month_dirs(source)
    for key, destination_month in _month_dirs(destination).items():
        source_month = source_months.get(key)
        if source_month is None:
            return False
        source_keys = _read_month_keys(source_month)
        destination_keys = _read_month_keys(destination_month)
        if destination_keys.join(source_keys, on=KEY_COLUMNS, how="anti").height:
            return False
    return True


def _replace_covered_destination(source: Path, destination: Path) -> None:
    source_snapshot = _parquet_snapshot(source)
    if not source_snapshot:
        raise ValueError(f"源目录没有 parquet: {source}")
    backup = destination.with_name(f".{destination.name}.migration_backup_{uuid.uuid4().hex}")
    destination.rename(backup)
    try:
        source.rename(destination)
        if _parquet_snapshot(destination) != source_snapshot:
            raise ValueError(f"替换后文件快照不一致: {destination}")
    except Exception:
        if destination.exists() and not source.exists():
            destination.rename(source)
        if backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    shutil.rmtree(backup)


def _merge_month(source_dir: Path, destination_dir: Path) -> None:
    source = _read_month(source_dir)
    destination = _read_month(destination_dir) if destination_dir.is_dir() else None
    combined = (
        pl.concat([destination, source], how="diagonal_relaxed")
        if destination is not None else source
    )
    merged = combined.unique(subset=KEY_COLUMNS, keep="last", maintain_order=True).sort(KEY_COLUMNS)
    missing_source_keys = source.select(KEY_COLUMNS).join(
        merged.select(KEY_COLUMNS), on=KEY_COLUMNS, how="anti"
    )
    if missing_source_keys.height:
        raise ValueError(f"合并后丢失源主键: {source_dir}")
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / "merged.parquet"
    temp = destination_dir / "merged.parquet.migration_tmp"
    merged.write_parquet(str(temp), compression="zstd")
    written = _normalize_frame(pl.read_parquet(str(temp)), temp)
    if written.height != merged.height:
        temp.unlink(missing_ok=True)
        raise ValueError(f"写回行数校验失败: {destination_dir}")
    if written.select(pl.struct(KEY_COLUMNS).is_duplicated().any()).item():
        temp.unlink(missing_ok=True)
        raise ValueError(f"写回后存在重复主键: {destination_dir}")
    temp.replace(target)
    for path in destination_dir.glob("*.parquet"):
        if path != target:
            path.unlink()


def migrate_factor(base_dir: Path, source_name: str, factor_id: str) -> str:
    source_requested = base_dir / f"factor={source_name}"
    destination_requested = base_dir / f"factor={factor_id}"
    source = source_requested.resolve()
    destination = destination_requested.resolve()
    resolved_base = base_dir.resolve()
    if source.parent != resolved_base or destination.parent != resolved_base:
        raise ValueError(f"迁移路径越界: {source_name} -> {factor_id}")
    if (
        str(source_requested.absolute()).casefold()
        == str(destination_requested.absolute()).casefold()
        and source_requested.name != destination_requested.name
    ):
        source_snapshot = _parquet_snapshot(source)
        temporary = resolved_base / f".{source.name}.case_rename_{uuid.uuid4().hex}"
        source.rename(temporary)
        try:
            temporary.rename(destination_requested)
        except Exception:
            if temporary.exists() and not source.exists():
                temporary.rename(source)
            raise
        if _parquet_snapshot(destination_requested) != source_snapshot:
            raise ValueError(f"仅大小写改名后校验失败: {source_name} -> {factor_id}")
        return "case-rename"
    if not destination.exists():
        source_snapshot = _parquet_snapshot(source)
        if not source_snapshot:
            raise ValueError(f"源目录没有 parquet: {source}")
        source.rename(destination)
        if _parquet_snapshot(destination) != source_snapshot:
            raise ValueError(f"原子改名后校验失败: {source_name} -> {factor_id}")
        return "rename"

    if _source_covers_destination(source, destination):
        _replace_covered_destination(source, destination)
        return "replace-covered"

    destination_months = _month_dirs(destination)
    for key, source_month_dir in _month_dirs(source).items():
        year, month = key
        target_month_dir = destination_months.get(
            key,
            destination / f"year={year:04d}" / f"month={month:02d}",
        )
        _merge_month(source_month_dir, target_month_dir)
    shutil.rmtree(source)
    return "merge"


def write_identity_catalog(base_dir: Path, mapping: dict[str, str]) -> Path:
    aliases: dict[str, list[str]] = {}
    for display_name, factor_id in mapping.items():
        aliases.setdefault(factor_id, [])
        if display_name not in aliases[factor_id]:
            aliases[factor_id].append(display_name)
    payload = {
        "version": 1,
        "storage": "stable_english_factor_id",
        "factor_labels": {factor_id: names[0] for factor_id, names in aliases.items()},
        "factor_aliases": aliases,
    }
    meta_dir = base_dir / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    path = meta_dir / "factor_identity_catalog.json"
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="统一 signal_daily 因子目录为英文稳定 ID")
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--execute", action="store_true", help="执行迁移；默认仅 dry-run")
    args = parser.parse_args()
    base_dir = args.base_dir.resolve()
    if not base_dir.is_dir():
        raise FileNotFoundError(f"因子根目录不存在: {base_dir}")

    mapping = build_factor_mapping(base_dir)
    plan, unmapped = build_migration_plan(base_dir, mapping)
    existing_targets = _factor_dirs(base_dir)
    merges = sum(factor_id in existing_targets for _, factor_id in plan)
    print(
        f"映射={len(mapping)}，待迁移目录={len(plan)}，"
        f"需合并={merges}，可原子改名={len(plan) - merges}，未映射={len(unmapped)}"
    )
    for source, factor_id in plan[:30]:
        action = "merge" if factor_id in existing_targets else "rename"
        print(f"[{action}] {source} -> {factor_id}")
    if len(plan) > 30:
        print(f"... 其余 {len(plan) - 30} 项省略")
    if unmapped:
        print("未映射中文目录: " + "、".join(unmapped))
    if not args.execute:
        print("DRY-RUN 完成；未修改任何数据。确认后使用 --execute。")
        return 0

    for index, (source, factor_id) in enumerate(plan, start=1):
        action = migrate_factor(base_dir, source, factor_id)
        print(f"[{index}/{len(plan)}] {action}: {source} -> {factor_id}")
    catalog_path = write_identity_catalog(base_dir, mapping)
    remaining_plan, remaining_unmapped = build_migration_plan(base_dir, mapping)
    if remaining_plan or remaining_unmapped:
        raise RuntimeError(
            f"迁移后仍有待处理目录: mapped={len(remaining_plan)}, unmapped={remaining_unmapped}"
        )
    print(f"迁移完成，身份目录: {catalog_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
