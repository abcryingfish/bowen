from __future__ import annotations

import argparse
import json
import math
import os
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import duckdb
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FACTOR_DIR = PROJECT_ROOT / "ZXW因子"
if str(FACTOR_DIR) not in sys.path:
    sys.path.insert(0, str(FACTOR_DIR))

from 筹码结构因子 import (  # noqa: E402
    CHOUMA_AC,
    CHOUMA_MIN_D,
    CHOUMA_USE_VOLUME,
    _update_chip_one_day_py,
)


DAILY_BASE_DIR = r"D:\database\stock_basic_data_daily"
TURNOVER_BASE_DIR = r"D:\database\stock_financial_statements\market_equity_data"
OUTPUT_DIR = PROJECT_ROOT / "筹码分布可视化"
DEFAULT_COST_PERCENTILES = (5, 15, 33, 50, 70, 85, 95)
PPM_SCALE = 1_000_000


def normalize_code(code: str) -> str:
    value = str(code).strip().upper()
    if not value:
        raise ValueError("股票代码不能为空")
    return value


def _parquet_glob(base_dir: str) -> str:
    return str(Path(base_dir) / "year=*" / "month=*" / "merged.parquet").replace("\\", "/")


def load_stock_data(
    code: str,
    *,
    daily_base_dir: str = DAILY_BASE_DIR,
    turnover_base_dir: str = TURNOVER_BASE_DIR,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    code = normalize_code(code)
    daily_glob = _parquet_glob(daily_base_dir)
    turnover_glob = _parquet_glob(turnover_base_dir)
    date_filters = []
    if start:
        date_filters.append(f"CAST(d.time AS DATE) >= DATE '{pd.Timestamp(start).date()}'")
    if end:
        date_filters.append(f"CAST(d.time AS DATE) <= DATE '{pd.Timestamp(end).date()}'")
    date_sql = ""
    if date_filters:
        date_sql = " AND " + " AND ".join(date_filters)

    query = f"""
    WITH daily AS (
        SELECT
            CAST(time AS TIMESTAMP) AS time,
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(volume AS DOUBLE) AS volume
        FROM read_parquet('{daily_glob}', hive_partitioning=1, union_by_name=true)
        WHERE UPPER(TRIM(CAST(htsc_code AS VARCHAR))) = '{code}'
    ),
    turnover AS (
        SELECT
            CAST(time AS TIMESTAMP) AS time,
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            CAST(turnover_rate AS DOUBLE) AS turnover_rate
        FROM read_parquet('{turnover_glob}', hive_partitioning=1, union_by_name=true)
        WHERE UPPER(TRIM(CAST(htsc_code AS VARCHAR))) = '{code}'
    )
    SELECT
        d.time,
        d.htsc_code,
        d.open,
        d.high,
        d.low,
        d.close,
        d.volume,
        COALESCE(t.turnover_rate, 0.0) AS turnover_rate
    FROM daily d
    LEFT JOIN turnover t
      ON d.time = t.time
     AND d.htsc_code = t.htsc_code
    WHERE TRUE
      {date_sql}
    ORDER BY d.time
    """
    con = duckdb.connect()
    try:
        df = con.execute(query).df()
    finally:
        con.close()

    if df.empty:
        raise ValueError(f"没有在 parquet 中找到 {code} 的日线数据")

    df["time"] = pd.to_datetime(df["time"], errors="coerce").dt.floor("D")
    df["htsc_code"] = df["htsc_code"].astype(str).str.strip().str.upper()
    df = df.dropna(subset=["time"]).drop_duplicates(subset=["time"], keep="last")
    df = df.sort_values("time").reset_index(drop=True)
    for col in ["open", "high", "low", "close", "volume", "turnover_rate"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    df["turnover_rate"] = df["turnover_rate"].fillna(0.0)
    return df


def compute_cost_marks(
    chip: np.ndarray,
    *,
    base_low: float,
    min_d: float,
    percentiles: Iterable[int] = DEFAULT_COST_PERCENTILES,
) -> dict[str, float]:
    total = float(np.sum(chip))
    marks: dict[str, float] = {}
    for percentile in percentiles:
        marks[str(int(percentile))] = 0.0
    if total <= 0.0:
        return marks

    targets = [float(p) / 100.0 for p in percentiles]
    ordered = list(zip([str(int(p)) for p in percentiles], targets))
    cum = 0.0
    pi = 0
    last_price = 0.0
    for b, mass in enumerate(chip):
        if mass <= 0.0:
            continue
        price = round(float(base_low + b * min_d), 2)
        last_price = price
        cum += float(mass) / total
        while pi < len(ordered) and cum > ordered[pi][1]:
            marks[ordered[pi][0]] = price
            pi += 1
    while pi < len(ordered):
        marks[ordered[pi][0]] = last_price
        pi += 1
    return marks


def make_distribution_payload(
    chip: np.ndarray,
    *,
    base_low: float,
    min_d: float,
    zero_threshold: float = 1e-12,
) -> dict[str, Any]:
    total = float(np.sum(chip))
    if total <= 0.0:
        return {"base": round(float(base_low), 4), "start": 0, "prices": [], "values": [], "total": 0.0}

    nonzero = np.flatnonzero(chip > zero_threshold)
    if nonzero.size == 0:
        return {"base": round(float(base_low), 4), "start": 0, "prices": [], "values": [], "total": total}

    start = int(nonzero[0])
    end = int(nonzero[-1])
    dist = chip[start : end + 1] / total
    values = np.rint(dist * PPM_SCALE).astype(np.int64).tolist()
    prices = [round(float(base_low + (start + i) * min_d), 2) for i in range(len(values))]
    return {
        "base": round(float(base_low), 4),
        "start": start,
        "prices": prices,
        "values": values,
        "total": total,
    }


def compute_chip_snapshots(
    df: pd.DataFrame,
    *,
    min_d: float = CHOUMA_MIN_D,
    ac: float = CHOUMA_AC,
    include_prices: bool = False,
) -> list[dict[str, Any]]:
    chip = np.zeros(0, dtype=np.float64)
    base_low = 0.0
    n_bins = 0
    snapshots: list[dict[str, Any]] = []

    for row in df.itertuples(index=False):
        high = float(row.high)
        low = float(row.low)
        close = float(row.close)
        turnover_pct = float(row.turnover_rate) if np.isfinite(row.turnover_rate) else 0.0
        volume = float(row.volume) if np.isfinite(row.volume) else np.nan
        if not (np.isfinite(high) and np.isfinite(low)):
            continue

        chip, base_low, n_bins = _update_chip_one_day_py(
            chip,
            base_low,
            n_bins,
            high,
            low,
            volume,
            turnover_pct / 100.0,
            min_d,
            ac,
            CHOUMA_USE_VOLUME,
        )
        payload = make_distribution_payload(chip, base_low=base_low, min_d=min_d)
        if not include_prices:
            payload.pop("prices", None)
        values = payload.get("values", [])
        max_value = max(values) if values else 0
        snapshots.append(
            {
                "date": pd.Timestamp(row.time).strftime("%Y-%m-%d"),
                "open": _finite_float(row.open),
                "high": _finite_float(row.high),
                "low": _finite_float(row.low),
                "close": _finite_float(close),
                "volume": _finite_float(volume),
                "turnover": _finite_float(turnover_pct),
                "base": payload["base"],
                "start": payload["start"],
                "values": values,
                "total": round(float(payload["total"]), 8),
                "max": int(max_value),
                "bins": len(values),
                "costs": compute_cost_marks(chip, base_low=base_low, min_d=min_d),
            }
        )
    return snapshots


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, 6)


def build_html(data: dict[str, Any]) -> str:
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{data['code']} 筹码分布可视化</title>
<style>
:root {{
  --bg: #080806;
  --panel: #12120f;
  --line: #b93224;
  --chip: #fff200;
  --chip-soft: rgba(255, 242, 0, .28);
  --text: #f4f1d2;
  --muted: #9d9a7d;
  --cyan: #49d9ff;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: radial-gradient(circle at 20% 0%, #25220c 0, #080806 42%, #020202 100%);
  color: var(--text);
  font-family: "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
}}
.wrap {{ max-width: 1280px; margin: 0 auto; padding: 18px; }}
.top {{
  display: flex; gap: 16px; align-items: flex-end; justify-content: space-between;
  border-bottom: 1px solid rgba(255,255,255,.1); padding-bottom: 14px; margin-bottom: 14px;
}}
h1 {{ margin: 0; font-size: 24px; letter-spacing: .04em; }}
.sub {{ color: var(--muted); margin-top: 6px; font-size: 13px; }}
.controls {{ background: rgba(18,18,15,.82); border: 1px solid rgba(255,255,255,.1); padding: 12px; border-radius: 14px; }}
.row {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
button {{
  background: #262316; color: var(--text); border: 1px solid rgba(255,255,255,.18);
  border-radius: 9px; padding: 7px 10px; cursor: pointer;
}}
button:hover {{ border-color: var(--chip); color: white; }}
input[type=range] {{ width: min(820px, 72vw); accent-color: var(--chip); }}
.date {{ color: var(--chip); font-size: 20px; min-width: 130px; font-weight: 700; }}
.grid {{ display: grid; grid-template-columns: minmax(0, 1fr) 270px; gap: 14px; }}
.chartBox {{
  position: relative; background: #000; border: 1px solid #5c1e18; border-left: 3px solid var(--line);
  border-right: 3px solid var(--line); border-radius: 10px; overflow: hidden;
}}
canvas {{ width: 100%; height: 760px; display: block; }}
.side {{
  background: rgba(18,18,15,.9); border: 1px solid rgba(255,255,255,.1); border-radius: 14px; padding: 12px;
}}
.kv {{ display: grid; grid-template-columns: 92px 1fr; gap: 7px; font-size: 13px; margin-bottom: 12px; }}
.kv span:nth-child(odd) {{ color: var(--muted); }}
.costs {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.costs td {{ padding: 5px 2px; border-bottom: 1px solid rgba(255,255,255,.08); }}
.costs td:first-child {{ color: var(--cyan); }}
.hint {{ color: var(--muted); font-size: 12px; line-height: 1.7; margin-top: 12px; }}
.tooltip {{
  position: absolute; pointer-events: none; display: none; background: rgba(0,0,0,.82);
  border: 1px solid rgba(255,255,255,.25); border-radius: 8px; padding: 6px 8px; font-size: 12px;
  color: #fff; transform: translate(10px, 10px);
}}
@media (max-width: 900px) {{
  .grid {{ grid-template-columns: 1fr; }}
  canvas {{ height: 620px; }}
  .top {{ display: block; }}
}}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div>
      <h1>{data['code']} 筹码分布详细可视化</h1>
      <div class="sub">完整价格档位分布 · minD={data['minD']} · 数据日数={len(data['days'])} · 生成时间={data['generatedAt']}</div>
    </div>
    <div class="sub">数据源：本地日线 parquet + market_equity_data 换手率</div>
  </div>
  <div class="controls">
    <div class="row">
      <button id="firstBtn">首日</button>
      <button id="prevBtn">上一日</button>
      <input id="daySlider" type="range" min="0" max="{max(len(data['days']) - 1, 0)}" value="{max(len(data['days']) - 1, 0)}" step="1">
      <button id="nextBtn">下一日</button>
      <button id="lastBtn">末日</button>
      <span class="date" id="dateText"></span>
      <button id="exportBtn">导出当前CSV</button>
    </div>
  </div>
  <div class="grid" style="margin-top:14px;">
    <div class="chartBox">
      <canvas id="chipCanvas"></canvas>
      <div class="tooltip" id="tooltip"></div>
    </div>
    <aside class="side">
      <div class="kv" id="metaBox"></div>
      <table class="costs" id="costTable"></table>
      <div class="hint">
        黄色横条为当前日期完整筹码价格分布；红线为当日收盘价；蓝线为 COST 分位价格。滑动上方滑块可逐日回看历史筹码演化。
      </div>
    </aside>
  </div>
</div>
<script>
const CHIP_DATA = {data_json};
const SCALE = {PPM_SCALE};
const canvas = document.getElementById('chipCanvas');
const ctx = canvas.getContext('2d');
const slider = document.getElementById('daySlider');
const dateText = document.getElementById('dateText');
const metaBox = document.getElementById('metaBox');
const costTable = document.getElementById('costTable');
const tooltip = document.getElementById('tooltip');
let current = Number(slider.value || 0);
let lastRender = null;

function resizeCanvas() {{
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  render();
}}

function clampIndex(i) {{
  return Math.max(0, Math.min(CHIP_DATA.days.length - 1, i));
}}

function priceAt(day, offset) {{
  return day.base + (day.start + offset) * CHIP_DATA.minD;
}}

function render() {{
  if (!CHIP_DATA.days.length) return;
  current = clampIndex(Number(slider.value || current));
  slider.value = String(current);
  const day = CHIP_DATA.days[current];
  const rect = canvas.getBoundingClientRect();
  const w = rect.width;
  const h = rect.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, w, h);

  const pad = {{ left: 68, right: 22, top: 22, bottom: 30 }};
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;
  const values = day.values || [];
  const minPrice = values.length ? priceAt(day, 0) : 0;
  const maxPrice = values.length ? priceAt(day, values.length - 1) : 1;
  const span = Math.max(maxPrice - minPrice, CHIP_DATA.minD);
  const maxVal = Math.max(day.max || 0, 1);

  ctx.strokeStyle = '#b93224';
  ctx.lineWidth = 1;
  ctx.strokeRect(pad.left, pad.top, plotW, plotH);

  ctx.fillStyle = 'rgba(255,255,255,.16)';
  ctx.font = '12px Microsoft YaHei';
  for (let i = 0; i <= 6; i++) {{
    const y = pad.top + plotH * i / 6;
    const price = maxPrice - span * i / 6;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + plotW, y);
    ctx.strokeStyle = 'rgba(255,255,255,.08)';
    ctx.stroke();
    ctx.fillStyle = '#9d9a7d';
    ctx.fillText(price.toFixed(2), 8, y + 4);
  }}

  ctx.fillStyle = '#fff200';
  const rowH = Math.max(1, plotH / Math.max(values.length, 1));
  for (let i = 0; i < values.length; i++) {{
    const v = values[i];
    if (!v) continue;
    const price = priceAt(day, i);
    const y = pad.top + (maxPrice - price) / span * plotH;
    const barW = Math.max(1, (v / maxVal) * plotW);
    ctx.fillRect(pad.left, y, barW, Math.max(1, rowH));
  }}

  drawPriceLine(day.close, '#ff4433', '收盘', minPrice, maxPrice, pad, plotW, plotH);
  Object.entries(day.costs || {{}}).forEach(([p, price]) => {{
    if (price > 0) drawPriceLine(price, '#49d9ff', 'C' + p, minPrice, maxPrice, pad, plotW, plotH, true);
  }});

  dateText.textContent = day.date;
  metaBox.innerHTML = [
    ['股票', CHIP_DATA.code],
    ['日期', day.date],
    ['开盘', fmt(day.open)],
    ['最高', fmt(day.high)],
    ['最低', fmt(day.low)],
    ['收盘', fmt(day.close)],
    ['成交量', fmt(day.volume)],
    ['换手率', fmt(day.turnover) + '%'],
    ['价格档位', String(day.bins)],
  ].map(([k, v]) => `<span>${{k}}</span><strong>${{v}}</strong>`).join('');
  costTable.innerHTML = '<tbody>' + Object.entries(day.costs || {{}})
    .map(([k, v]) => `<tr><td>COST(${{k}})</td><td>${{fmt(v)}}</td></tr>`).join('') + '</tbody>';
  lastRender = {{ day, pad, plotW, plotH, minPrice, maxPrice, span, maxVal, w, h }};
}}

function drawPriceLine(price, color, label, minPrice, maxPrice, pad, plotW, plotH, dashed=false) {{
  if (price == null || price < minPrice || price > maxPrice) return;
  const y = pad.top + (maxPrice - price) / Math.max(maxPrice - minPrice, CHIP_DATA.minD) * plotH;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = label === '收盘' ? 2 : 1;
  if (dashed) ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(pad.left, y);
  ctx.lineTo(pad.left + plotW, y);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.font = '12px Microsoft YaHei';
  ctx.fillText(`${{label}} ${{Number(price).toFixed(2)}}`, pad.left + plotW - 92, y - 4);
  ctx.restore();
}}

function fmt(v) {{
  if (v == null || !Number.isFinite(Number(v))) return '-';
  return Number(v).toLocaleString('zh-CN', {{ maximumFractionDigits: 4 }});
}}

function exportCurrentCsv() {{
  const day = CHIP_DATA.days[current];
  const rows = ['date,price,chip_ppm,chip_share'];
  for (let i = 0; i < day.values.length; i++) {{
    const price = priceAt(day, i).toFixed(2);
    const ppm = day.values[i] || 0;
    rows.push(`${{day.date}},${{price}},${{ppm}},${{(ppm / SCALE).toFixed(8)}}`);
  }}
  const blob = new Blob([rows.join('\\n')], {{ type: 'text/csv;charset=utf-8' }});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${{CHIP_DATA.code}}_${{day.date}}_chip_distribution.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}}

canvas.addEventListener('mousemove', (ev) => {{
  if (!lastRender) return;
  const r = canvas.getBoundingClientRect();
  const x = ev.clientX - r.left;
  const y = ev.clientY - r.top;
  const {{day, pad, plotH, minPrice, maxPrice, span}} = lastRender;
  if (x < pad.left || y < pad.top || y > pad.top + plotH) {{
    tooltip.style.display = 'none';
    return;
  }}
  const price = maxPrice - ((y - pad.top) / plotH) * span;
  const idx = Math.round((price - day.base) / CHIP_DATA.minD) - day.start;
  const ppm = idx >= 0 && idx < day.values.length ? day.values[idx] : 0;
  tooltip.style.display = 'block';
  tooltip.style.left = `${{ev.clientX - r.left}}px`;
  tooltip.style.top = `${{ev.clientY - r.top}}px`;
  tooltip.innerHTML = `价格：${{price.toFixed(2)}}<br>筹码占比：${{(ppm / SCALE * 100).toFixed(4)}}%<br>ppm：${{ppm}}`;
}});
canvas.addEventListener('mouseleave', () => tooltip.style.display = 'none');
slider.addEventListener('input', render);
document.getElementById('firstBtn').onclick = () => {{ slider.value = 0; render(); }};
document.getElementById('prevBtn').onclick = () => {{ slider.value = clampIndex(current - 1); render(); }};
document.getElementById('nextBtn').onclick = () => {{ slider.value = clampIndex(current + 1); render(); }};
document.getElementById('lastBtn').onclick = () => {{ slider.value = CHIP_DATA.days.length - 1; render(); }};
document.getElementById('exportBtn').onclick = exportCurrentCsv;
window.addEventListener('resize', resizeCanvas);
resizeCanvas();
</script>
</body>
</html>
"""


def write_visualization(
    code: str,
    df: pd.DataFrame,
    snapshots: list[dict[str, Any]],
    *,
    output_dir: Path = OUTPUT_DIR,
    min_d: float = CHOUMA_MIN_D,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    first_dt = pd.Timestamp(df["time"].iloc[0]).strftime("%Y%m%d")
    last_dt = pd.Timestamp(df["time"].iloc[-1]).strftime("%Y%m%d")
    filename = f"{code}_{first_dt}_{last_dt}_筹码分布.html"
    path = output_dir / filename
    data = {
        "code": code,
        "minD": float(min_d),
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "days": snapshots,
    }
    path.write_text(build_html(data), encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成单只股票的完整筹码分布可滑动 HTML。")
    parser.add_argument("--code", help="股票代码，例如 002555.SZ；不填则运行后提示输入")
    parser.add_argument("--start", help="可选：开始日期，例如 2020-01-01")
    parser.add_argument("--end", help="可选：结束日期，例如 2026-06-03")
    parser.add_argument("--daily-base-dir", default=DAILY_BASE_DIR, help="日线 parquet 根目录")
    parser.add_argument("--turnover-base-dir", default=TURNOVER_BASE_DIR, help="换手率 parquet 根目录")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="HTML 输出目录")
    parser.add_argument("--min-d", type=float, default=CHOUMA_MIN_D, help="价格档位精度，默认 0.01")
    parser.add_argument("--include-prices", action="store_true", help="在 HTML 数据中显式保存每个价格数组；文件会更大")
    parser.add_argument("--open", action="store_true", help="生成后自动用默认浏览器打开")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    code = args.code or input("请输入股票代码（例如 002555.SZ）：").strip()
    code = normalize_code(code)
    print(f"读取 {code} 日线和换手率数据...")
    df = load_stock_data(
        code,
        daily_base_dir=args.daily_base_dir,
        turnover_base_dir=args.turnover_base_dir,
        start=args.start,
        end=args.end,
    )
    print(f"读取完成：{len(df):,} 个交易日，区间 {df['time'].iloc[0].date()} ~ {df['time'].iloc[-1].date()}")
    print("递推计算完整筹码分布快照...")
    snapshots = compute_chip_snapshots(df, min_d=float(args.min_d), include_prices=bool(args.include_prices))
    if not snapshots:
        raise RuntimeError("没有生成任何筹码分布快照")
    out_path = write_visualization(
        code,
        df,
        snapshots,
        output_dir=Path(args.output_dir),
        min_d=float(args.min_d),
    )
    size_mb = os.path.getsize(out_path) / 1024 / 1024
    print(f"已生成：{out_path}")
    print(f"文件大小：{size_mb:.2f} MB")
    if args.open:
        webbrowser.open(out_path.resolve().as_uri())


if __name__ == "__main__":
    main()
