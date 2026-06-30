from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import duckdb


ROOT = Path(r"D:\database")
OUT = Path(r"C:\Users\Administrator\Desktop\python_venv\temp\database_structure_report.md")


def fmt_size(value: int) -> str:
    size = float(value)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{size:.2f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024
    return f"{size:.2f}TB"


def safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def normalize_file_name(name: str) -> str:
    path = Path(name)
    stem = path.stem
    parts = stem.split("_")
    prefix: list[str] = []
    for part in parts:
        if part.isdigit() and len(part) >= 6:
            break
        prefix.append(part)
    if prefix and len(prefix) < len(parts):
        return "_".join(prefix) + "_*" + path.suffix
    return name


def normalize_pattern(path: Path) -> str:
    rel_parts = path.relative_to(ROOT).as_posix().split("/")
    out: list[str] = []
    for index, part in enumerate(rel_parts):
        if part.startswith("year="):
            out.append("year=*")
        elif part.startswith("month="):
            out.append("month=*")
        elif part.startswith("date="):
            out.append("date=*")
        elif index == len(rel_parts) - 1:
            out.append(normalize_file_name(part))
        else:
            out.append(part)
    return "/".join(out)


def parquet_schema(con: duckdb.DuckDBPyConnection, path: Path) -> list[tuple[str, str]]:
    try:
        df = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).df()
        return [(str(row["column_name"]), str(row["column_type"])) for _, row in df.iterrows()]
    except Exception as exc:
        return [("__ERROR__", str(exc).replace("\n", " "))]


def schema_text(schema: list[tuple[str, str]]) -> str:
    text = ", ".join(f"`{name}` {typ}" for name, typ in schema)
    if len(text) > 2500:
        return text[:2500] + " ..."
    return text


def partition_summary(paths: list[Path]) -> str:
    years: set[str] = set()
    months: set[str] = set()
    named_parts: set[str] = set()
    for path in paths:
        for part in path.parts:
            if part.startswith("year="):
                years.add(part.split("=", 1)[1])
            elif part.startswith("month="):
                months.add(part.split("=", 1)[1])
            elif part.startswith(("factor=", "table=", "run_tag=")):
                named_parts.add(part)
    bits: list[str] = []
    if years:
        bits.append(f"year: {min(years)}~{max(years)} ({len(years)}个)")
    if months:
        bits.append(f"month: {min(months)}~{max(months)} ({len(months)}个值)")
    if named_parts:
        values = sorted(named_parts)
        shown = ", ".join(values[:20])
        if len(values) > 20:
            shown += f", ... 共{len(values)}个"
        bits.append(shown)
    return "; ".join(bits) if bits else "无明显 hive 分区"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(database=":memory:")
    lines: list[str] = [
        "# D:\\database 数据与结构清单",
        "",
        "> 自动扫描生成：汇总顶层目录、文件类型、parquet 逻辑结构和字段；相同结构的时间戳文件已合并展示。",
        "",
    ]
    if not ROOT.exists():
        lines.append("D:\\database 不存在。")
        OUT.write_text("\n".join(lines), encoding="utf-8")
        return

    top_infos = []
    total_files = 0
    total_size = 0
    for top in sorted(ROOT.iterdir(), key=lambda item: item.name.lower()):
        if top.is_file():
            size = safe_size(top)
            total_files += 1
            total_size += size
            top_infos.append((top.name, "file", 0, 1, size, top.suffix.lower() or "<no_ext>"))
            continue
        files = [path for path in top.rglob("*") if path.is_file()]
        size = sum(safe_size(path) for path in files)
        total_files += len(files)
        total_size += size
        ext = Counter(path.suffix.lower() or "<no_ext>" for path in files)
        ext_text = ", ".join(f"{key}:{count}" for key, count in ext.most_common(6))
        dir_count = sum(1 for path in top.rglob("*") if path.is_dir())
        top_infos.append((top.name, "dir", dir_count, len(files), size, ext_text))

    lines.extend(
        [
            f"- 顶层项数：{len(top_infos)}",
            f"- 总文件数：{total_files}",
            f"- 总大小：{fmt_size(total_size)}",
            "",
            "## 顶层汇总",
            "",
            "| 名称 | 类型 | 子目录数 | 文件数 | 大小 | 文件类型 |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    for name, typ, dir_count, file_count, size, ext_text in top_infos:
        lines.append(f"| `{name}` | {typ} | {dir_count} | {file_count} | {fmt_size(size)} | {ext_text or '-'} |")
    lines.append("")

    for top in sorted(ROOT.iterdir(), key=lambda item: item.name.lower()):
        lines.extend([f"## {top.name}", ""])
        if top.is_file():
            lines.extend([f"- 文件：`{top}`", f"- 大小：{fmt_size(safe_size(top))}", ""])
            continue

        files = [path for path in top.rglob("*") if path.is_file()]
        parquet_files = [path for path in files if path.suffix.lower() == ".parquet"]
        ext = Counter(path.suffix.lower() or "<no_ext>" for path in files)
        lines.append(f"- 文件数：{len(files)}")
        lines.append(f"- 大小：{fmt_size(sum(safe_size(path) for path in files))}")
        lines.append(f"- 文件类型：{', '.join(f'{key}:{count}' for key, count in ext.most_common()) if ext else '无文件'}")
        if parquet_files:
            lines.append(f"- parquet 文件数：{len(parquet_files)}")
            lines.append(f"- 分区概况：{partition_summary(parquet_files)}")
            groups: dict[str, list[Path]] = defaultdict(list)
            for path in parquet_files:
                groups[normalize_pattern(path)].append(path)
            lines.extend(["", "| 逻辑路径/结构 | 文件数 | 样例文件 | 字段 |", "|---|---:|---|---|"])
            for pattern, paths in sorted(groups.items(), key=lambda item: item[0].lower()):
                sample = paths[0]
                schema = schema_text(parquet_schema(con, sample))
                lines.append(f"| `{pattern}` | {len(paths)} | `{sample.relative_to(ROOT).as_posix()}` | {schema} |")
        elif files:
            lines.append("- 文件样例：")
            for path in files[:20]:
                lines.append(f"  - `{path.relative_to(ROOT).as_posix()}` ({fmt_size(safe_size(path))})")
        lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
