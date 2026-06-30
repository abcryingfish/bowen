from __future__ import annotations

import html
import json
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(r"D:\database")
OUT = Path(r"C:\Users\Administrator\Desktop\python_venv\temp\database_structure_summary.html")
SAMPLE_ROWS = 3


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
    normalized: list[str] = []
    for index, part in enumerate(rel_parts):
        if part.startswith("year="):
            normalized.append("year=*")
        elif part.startswith("month="):
            normalized.append("month=*")
        elif part.startswith("date="):
            normalized.append("date=*")
        elif index == len(rel_parts) - 1:
            normalized.append(normalize_file_name(part))
        else:
            normalized.append(part)
    return "/".join(normalized)


def infer_logical_name(pattern: str) -> str:
    parts = pattern.split("/")
    for part in parts:
        if part.startswith(("table=", "factor=", "run_tag=")):
            return part
    if len(parts) >= 2:
        return parts[1]
    return parts[0]


def partition_summary(paths: list[Path]) -> dict[str, Any]:
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
    return {
        "years": f"{min(years)}~{max(years)} ({len(years)}个)" if years else "",
        "months": f"{min(months)}~{max(months)} ({len(months)}个值)" if months else "",
        "named_parts": sorted(named_parts),
    }


def to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d %H:%M:%S").rstrip(" 00:00:00")
    try:
        if hasattr(value, "to_pydatetime"):
            return value.to_pydatetime().strftime("%Y-%m-%d %H:%M:%S").rstrip(" 00:00:00")
    except Exception:
        pass
    try:
        if hasattr(value, "item"):
            return value.item()
    except Exception:
        pass
    return value


def parquet_schema(con: duckdb.DuckDBPyConnection, sample: Path) -> list[dict[str, str]]:
    try:
        df = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(sample)]).df()
        return [
            {"name": str(row["column_name"]), "type": str(row["column_type"])}
            for _, row in df.iterrows()
        ]
    except Exception as exc:
        return [{"name": "__ERROR__", "type": str(exc).replace("\n", " ")}]


def parquet_sample_rows(con: duckdb.DuckDBPyConnection, sample: Path, limit: int = SAMPLE_ROWS) -> list[dict[str, Any]]:
    try:
        df = con.execute(f"SELECT * FROM read_parquet(?) LIMIT {limit}", [str(sample)]).df()
        return [
            {str(key): to_jsonable(value) for key, value in row.items()}
            for row in df.to_dict(orient="records")
        ]
    except Exception as exc:
        return [{"__ERROR__": str(exc).replace("\n", " ")}]


def collect_data() -> dict[str, Any]:
    con = duckdb.connect(database=":memory:")
    top_items = []
    datasets = []
    total_files = 0
    total_size = 0

    for top in sorted(ROOT.iterdir(), key=lambda item: item.name.lower()):
        if top.is_file():
            size = safe_size(top)
            total_files += 1
            total_size += size
            top_items.append(
                {
                    "name": top.name,
                    "kind": "file",
                    "dir_count": 0,
                    "file_count": 1,
                    "size": size,
                    "size_text": fmt_size(size),
                    "types": top.suffix.lower() or "<no_ext>",
                }
            )
            datasets.append(
                {
                    "name": top.name,
                    "summary": top_items[-1],
                    "tables": [],
                    "files": [{"path": top.relative_to(ROOT).as_posix(), "size": fmt_size(size)}],
                }
            )
            continue

        files = [path for path in top.rglob("*") if path.is_file()]
        dirs = [path for path in top.rglob("*") if path.is_dir()]
        size = sum(safe_size(path) for path in files)
        total_files += len(files)
        total_size += size
        ext = Counter(path.suffix.lower() or "<no_ext>" for path in files)
        top_summary = {
            "name": top.name,
            "kind": "dir",
            "dir_count": len(dirs),
            "file_count": len(files),
            "size": size,
            "size_text": fmt_size(size),
            "types": ", ".join(f"{key}:{count}" for key, count in ext.most_common()) or "-",
        }
        top_items.append(top_summary)

        parquet_files = [path for path in files if path.suffix.lower() == ".parquet"]
        tables = []
        if parquet_files:
            groups: dict[str, list[Path]] = defaultdict(list)
            for path in parquet_files:
                groups[normalize_pattern(path)].append(path)
            for pattern, paths in sorted(groups.items(), key=lambda item: item[0].lower()):
                sample = paths[0]
                schema = parquet_schema(con, sample)
                rows = parquet_sample_rows(con, sample)
                part = partition_summary(paths)
                tables.append(
                    {
                        "logical_name": infer_logical_name(pattern),
                        "pattern": pattern,
                        "file_count": len(paths),
                        "sample_file": sample.relative_to(ROOT).as_posix(),
                        "sample_size": fmt_size(safe_size(sample)),
                        "partition": part,
                        "schema": schema,
                        "sample_rows": rows,
                    }
                )

        sample_files = []
        if not parquet_files:
            for path in files[:20]:
                sample_files.append({"path": path.relative_to(ROOT).as_posix(), "size": fmt_size(safe_size(path))})
        datasets.append({"name": top.name, "summary": top_summary, "tables": tables, "files": sample_files})

    return {
        "root": str(ROOT),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_files": total_files,
        "total_size": total_size,
        "total_size_text": fmt_size(total_size),
        "top_items": top_items,
        "datasets": datasets,
    }


def render_value(value: Any) -> str:
    if value is None:
        return '<span class="muted">NULL</span>'
    text = str(value)
    return html.escape(text if len(text) <= 120 else text[:117] + "...")


def render_sample_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">没有样例行。</p>'
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    header = "".join(f"<th>{html.escape(key)}</th>" for key in keys)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{render_value(row.get(key))}</td>" for key in keys)
        body_rows.append(f"<tr>{cells}</tr>")
    return f'<div class="table-scroll"><table><thead><tr>{header}</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>'


def render_schema_table(schema: list[dict[str, str]]) -> str:
    rows = []
    for index, column in enumerate(schema, start=1):
        rows.append(
            "<tr>"
            f"<td class=\"num\">{index}</td>"
            f"<td><code>{html.escape(column['name'])}</code></td>"
            f"<td><code>{html.escape(column['type'])}</code></td>"
            "</tr>"
        )
    return (
        '<div class="table-scroll schema-scroll"><table>'
        "<thead><tr><th>#</th><th>字段名</th><th>类型</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def render_html(data: dict[str, Any]) -> str:
    dataset_cards = []
    nav_items = []
    for dataset in data["datasets"]:
        dataset_id = "ds-" + "".join(ch if ch.isalnum() else "-" for ch in dataset["name"]).strip("-").lower()
        nav_items.append(
            f'<a href="#{dataset_id}"><span>{html.escape(dataset["name"])}</span>'
            f'<small>{len(dataset["tables"])} 表 / {dataset["summary"]["file_count"]} 文件</small></a>'
        )
        tables_html = []
        for table_index, table in enumerate(dataset["tables"], start=1):
            named_parts = table["partition"]["named_parts"]
            named_text = ", ".join(named_parts[:12]) + (f", ... 共{len(named_parts)}个" if len(named_parts) > 12 else "")
            partition_bits = [
                bit
                for bit in [table["partition"]["years"], table["partition"]["months"], named_text]
                if bit
            ]
            partition_text = "；".join(partition_bits) or "无明显分区"
            tables_html.append(
                f"""
                <section class="table-card" data-search="{html.escape((dataset['name'] + ' ' + table['logical_name'] + ' ' + table['pattern']).lower())}">
                    <div class="table-head">
                        <div>
                            <p class="eyebrow">表 {table_index}</p>
                            <h3>{html.escape(table['logical_name'])}</h3>
                        </div>
                        <span class="pill">{len(table['schema'])} 字段</span>
                    </div>
                    <dl class="meta-grid">
                        <div><dt>逻辑路径</dt><dd><code>{html.escape(table['pattern'])}</code></dd></div>
                        <div><dt>文件数</dt><dd>{table['file_count']}</dd></div>
                        <div><dt>样例文件</dt><dd><code>{html.escape(table['sample_file'])}</code></dd></div>
                        <div><dt>样例大小</dt><dd>{table['sample_size']}</dd></div>
                        <div><dt>分区</dt><dd>{html.escape(partition_text)}</dd></div>
                    </dl>
                    <details open>
                        <summary>字段与类型</summary>
                        {render_schema_table(table['schema'])}
                    </details>
                    <details>
                        <summary>样例数据（最多 {SAMPLE_ROWS} 行）</summary>
                        {render_sample_table(table['sample_rows'])}
                    </details>
                </section>
                """
            )
        files_html = ""
        if dataset["files"]:
            files_html = "<ul class=\"file-list\">" + "".join(
                f"<li><code>{html.escape(item['path'])}</code><span>{item['size']}</span></li>"
                for item in dataset["files"]
            ) + "</ul>"
        dataset_cards.append(
            f"""
            <section id="{dataset_id}" class="dataset-card">
                <div class="dataset-head">
                    <div>
                        <p class="eyebrow">数据集</p>
                        <h2>{html.escape(dataset['name'])}</h2>
                    </div>
                    <div class="dataset-stats">
                        <span>{dataset['summary']['file_count']} 文件</span>
                        <span>{dataset['summary']['size_text']}</span>
                        <span>{len(dataset['tables'])} parquet 表</span>
                    </div>
                </div>
                <p class="types">文件类型：{html.escape(dataset['summary']['types'])}</p>
                {files_html}
                <div class="tables-wrap">{''.join(tables_html) if tables_html else '<p class="empty">没有 parquet 表。</p>'}</div>
            </section>
            """
        )

    top_rows = "".join(
        "<tr>"
        f"<td><code>{html.escape(item['name'])}</code></td>"
        f"<td>{html.escape(item['kind'])}</td>"
        f"<td class=\"num\">{item['dir_count']}</td>"
        f"<td class=\"num\">{item['file_count']}</td>"
        f"<td>{item['size_text']}</td>"
        f"<td>{html.escape(item['types'])}</td>"
        "</tr>"
        for item in data["top_items"]
    )
    payload = html.escape(json.dumps({"generated_at": data["generated_at"]}, ensure_ascii=False))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>D:\\database 数据结构总览</title>
<style>
:root {{
  color-scheme: light;
  --bg: #f6f7f9;
  --panel: #ffffff;
  --text: #20242a;
  --muted: #67707d;
  --line: #d9dee7;
  --accent: #0f766e;
  --accent-soft: #e2f2ef;
  --code: #f1f4f8;
  --warn: #8a5a00;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
}}
.layout {{
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  min-height: 100vh;
}}
aside {{
  position: sticky;
  top: 0;
  height: 100vh;
  padding: 20px;
  background: #111827;
  color: #f9fafb;
  overflow: auto;
}}
aside h1 {{
  margin: 0 0 8px;
  font-size: 20px;
  line-height: 1.25;
}}
aside p {{ margin: 0 0 16px; color: #cbd5e1; font-size: 13px; }}
.search {{
  width: 100%;
  height: 38px;
  border: 1px solid #334155;
  border-radius: 6px;
  background: #0f172a;
  color: #fff;
  padding: 0 10px;
  margin-bottom: 16px;
}}
.nav-list {{ display: grid; gap: 6px; }}
.nav-list a {{
  display: grid;
  gap: 2px;
  text-decoration: none;
  color: #f8fafc;
  padding: 9px 10px;
  border-radius: 6px;
  background: rgba(255,255,255,0.05);
}}
.nav-list a:hover {{ background: rgba(255,255,255,0.12); }}
.nav-list small {{ color: #aab4c2; }}
main {{ padding: 28px; overflow: hidden; }}
.hero {{
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 22px;
  margin-bottom: 18px;
}}
.hero h1 {{ margin: 0 0 8px; font-size: 28px; }}
.hero p {{ margin: 0; color: var(--muted); }}
.stats {{
  display: grid;
  grid-template-columns: repeat(4, minmax(120px, 1fr));
  gap: 10px;
  margin-top: 18px;
}}
.stat {{
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
  background: #fbfcfe;
}}
.stat span {{ display: block; color: var(--muted); font-size: 12px; }}
.stat strong {{ display: block; margin-top: 5px; font-size: 20px; }}
.dataset-card, .table-card {{
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
}}
.dataset-card {{ margin: 18px 0; padding: 18px; }}
.dataset-head, .table-head {{
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}}
.dataset-head h2, .table-head h3 {{ margin: 0; }}
.eyebrow {{
  margin: 0 0 4px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
}}
.dataset-stats {{ display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }}
.dataset-stats span, .pill {{
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 4px 9px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 13px;
  font-weight: 700;
}}
.types {{ color: var(--muted); margin: 10px 0 0; }}
.tables-wrap {{ display: grid; gap: 14px; margin-top: 14px; }}
.table-card {{ padding: 16px; }}
.meta-grid {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 12px 0;
}}
.meta-grid div {{
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 9px;
  min-width: 0;
}}
dt {{ color: var(--muted); font-size: 12px; margin-bottom: 4px; }}
dd {{ margin: 0; overflow-wrap: anywhere; }}
code {{
  background: var(--code);
  padding: 2px 4px;
  border-radius: 4px;
  font-family: Consolas, "Cascadia Mono", monospace;
  font-size: 12px;
}}
details {{ border-top: 1px solid var(--line); padding-top: 10px; margin-top: 10px; }}
summary {{ cursor: pointer; font-weight: 700; color: #26313f; }}
.table-scroll {{ overflow: auto; max-height: 460px; border: 1px solid var(--line); border-radius: 6px; margin-top: 10px; }}
.schema-scroll {{ max-height: 360px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ border-bottom: 1px solid var(--line); padding: 7px 9px; text-align: left; vertical-align: top; white-space: nowrap; }}
th {{ position: sticky; top: 0; background: #eef2f7; z-index: 1; }}
td.num, th.num {{ text-align: right; }}
.muted, .empty {{ color: var(--muted); }}
.file-list {{ display: grid; gap: 6px; padding-left: 0; list-style: none; }}
.file-list li {{ display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--line); padding: 7px 0; }}
.hidden {{ display: none !important; }}
@media (max-width: 900px) {{
  .layout {{ grid-template-columns: 1fr; }}
  aside {{ position: relative; height: auto; }}
  main {{ padding: 16px; }}
  .stats, .meta-grid {{ grid-template-columns: 1fr; }}
  .dataset-head, .table-head {{ display: grid; }}
}}
</style>
</head>
<body>
<div class="layout">
  <aside>
    <h1>D:\\database</h1>
    <p>生成时间：{html.escape(data['generated_at'])}</p>
    <input id="search" class="search" placeholder="搜索目录、表名、字段路径">
    <nav class="nav-list">{''.join(nav_items)}</nav>
  </aside>
  <main>
    <section class="hero">
      <h1>数据结构总览</h1>
      <p>根目录：<code>{html.escape(data['root'])}</code>。样例数据只读取每类表的样例文件前 {SAMPLE_ROWS} 行。</p>
      <div class="stats">
        <div class="stat"><span>顶层项</span><strong>{len(data['top_items'])}</strong></div>
        <div class="stat"><span>文件数</span><strong>{data['total_files']}</strong></div>
        <div class="stat"><span>总大小</span><strong>{data['total_size_text']}</strong></div>
        <div class="stat"><span>逻辑 parquet 表</span><strong>{sum(len(ds['tables']) for ds in data['datasets'])}</strong></div>
      </div>
    </section>
    <section class="dataset-card">
      <div class="dataset-head"><div><p class="eyebrow">汇总</p><h2>顶层目录</h2></div></div>
      <div class="table-scroll">
        <table>
          <thead><tr><th>名称</th><th>类型</th><th>子目录数</th><th>文件数</th><th>大小</th><th>文件类型</th></tr></thead>
          <tbody>{top_rows}</tbody>
        </table>
      </div>
    </section>
    {''.join(dataset_cards)}
  </main>
</div>
<script type="application/json" id="report-meta">{payload}</script>
<script>
const search = document.getElementById('search');
const cards = Array.from(document.querySelectorAll('.table-card'));
search.addEventListener('input', () => {{
  const keyword = search.value.trim().toLowerCase();
  cards.forEach(card => {{
    const haystack = (card.dataset.search || '') + ' ' + card.innerText.toLowerCase();
    card.classList.toggle('hidden', keyword && !haystack.includes(keyword));
  }});
}});
</script>
</body>
</html>"""


def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f"{ROOT} 不存在")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = collect_data()
    OUT.write_text(render_html(data), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
