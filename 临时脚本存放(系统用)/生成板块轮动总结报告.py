"""生成可离线交付的板块轮动静态 HTML 报告。"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MARKET_GLOB = "D:/database/index_data_daily/year=*/month=*/merged.parquet"
UNIVERSE_PATH = Path(r"D:\database\index_data_daily\_meta\ths_level1_universe.parquet")
PROBABILITY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "sector_peak_valley_ml"
    / "stage_ax_daily_signal"
    / "sector_probability_latest_15.parquet"
)
OUTPUT_PATH = PROJECT_ROOT / "可视化" / "板块轮动" / "板块轮动总结报告_20260821.html"
IMAGE_SOURCE_PATH = (
    PROJECT_ROOT / "可视化" / "板块轮动" / "板块轮动总结报告_图片版_20260821.html"
)
ONE_PAGE_SOURCE_PATH = (
    PROJECT_ROOT / "可视化" / "板块轮动" / "板块轮动一页总结_20260821.html"
)

PREFIX_META = {
    "881": {"title": "粗行业", "description": "一级行业景气与资金风格观察"},
    "885": {"title": "早期细分概念", "description": "较早建立的主题与细分赛道"},
    "886": {"title": "后期细分概念", "description": "较新主题与交易型细分赛道"},
}
HORIZONS = {
    "ultra_short": "超短（1-3日）",
    "5d": "短期（5日）",
    "20d": "中期（20日）",
}


def load_names() -> dict[str, str]:
    frame = pd.read_parquet(UNIVERSE_PATH, columns=["htsc_code", "name"])
    return dict(
        zip(
            frame["htsc_code"].astype(str).str.strip().str.upper(),
            frame["name"].astype(str).str.strip(),
        )
    )


def load_recent_returns() -> pd.DataFrame:
    query = f"""
    WITH raw AS (
        SELECT
            UPPER(TRIM(CAST(htsc_code AS VARCHAR))) AS htsc_code,
            CAST(time AS TIMESTAMP) AS time,
            TRY_CAST(close AS DOUBLE) AS close
        FROM read_parquet('{MARKET_GLOB}', hive_partitioning=true, union_by_name=true)
        WHERE LEFT(UPPER(TRIM(CAST(htsc_code AS VARCHAR))), 3) IN ('881', '885', '886')
    ), valid AS (
        SELECT htsc_code, time, MAX(close) AS close
        FROM raw
        WHERE close IS NOT NULL AND close > 0
        GROUP BY 1, 2
    ), ranked AS (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY htsc_code ORDER BY time DESC) AS reverse_rank
        FROM valid
    ), selected AS (
        SELECT * FROM ranked WHERE reverse_rank <= 20
    )
    SELECT
        htsc_code,
        ARG_MIN(close, time) AS first_close,
        ARG_MAX(close, time) AS last_close,
        MIN(time) AS first_time,
        MAX(time) AS last_time,
        COUNT(*) AS point_count
    FROM selected
    GROUP BY 1
    HAVING COUNT(*) >= 2
    ORDER BY 1
    """
    frame = duckdb.sql(query).df()
    frame["return_pct"] = (frame["last_close"] / frame["first_close"] - 1.0) * 100.0
    frame.loc[frame["point_count"] < 20, "return_pct"] = np.nan
    return frame


def load_report_data() -> tuple[dict[str, object], dict[str, object]]:
    names = load_names()
    returns = load_recent_returns()
    probabilities = pd.read_parquet(PROBABILITY_PATH)
    probabilities["htsc_code"] = probabilities["htsc_code"].astype(str).str.strip().str.upper()
    probabilities["time"] = pd.to_datetime(probabilities["time"]).dt.floor("D")
    as_of = probabilities["time"].max()
    if probabilities["time"].nunique() != 1:
        raise ValueError("最新概率文件包含多个交易日")

    frame = probabilities.merge(returns, on="htsc_code", how="left", validate="one_to_one")
    frame["prefix"] = frame["htsc_code"].str[:3]
    frame["name"] = frame["htsc_code"].map(names).fillna(frame["htsc_code"])
    if set(frame["prefix"].unique()) != set(PREFIX_META):
        raise ValueError("报告缺少 881/885/886 中的某个分类")

    for horizon in HORIZONS:
        frame[f"{horizon}_bullish"] = (
            frame[f"{horizon}_prob_valley_bullish"]
            + frame[f"{horizon}_prob_sideways_bullish"]
        )
        frame[f"{horizon}_bearish"] = (
            frame[f"{horizon}_prob_peak_bearish"]
            + frame[f"{horizon}_prob_sideways_bearish"]
        )
        frame[f"{horizon}_volatile"] = frame[
            f"{horizon}_prob_two_sided_high_volatility"
        ]
        frame[f"{horizon}_direction"] = (
            frame[f"{horizon}_bullish"] - frame[f"{horizon}_bearish"]
        )
        total = (
            frame[f"{horizon}_bullish"]
            + frame[f"{horizon}_bearish"]
            + frame[f"{horizon}_volatile"]
        )
        if float((total - 1.0).abs().max()) > 1e-10:
            raise ValueError(f"{horizon} 概率合计不为1")

    bins = [-np.inf, -10, -5, 0, 5, 10, np.inf]
    labels = ["≤ -10%", "-10%~-5%", "-5%~0%", "0%~5%", "5%~10%", "≥ 10%"]
    report: dict[str, object] = {}
    summary_rows = []
    for prefix, meta in PREFIX_META.items():
        group = frame.loc[frame["prefix"].eq(prefix)].copy()
        group = group.sort_values("return_pct", ascending=False)
        valid_returns = group.dropna(subset=["return_pct"]).copy()
        distribution = pd.cut(valid_returns["return_pct"], bins=bins, labels=labels).value_counts(sort=False)
        horizon_summary = {}
        for horizon, label in HORIZONS.items():
            horizon_summary[horizon] = {
                "label": label,
                "bullish": float(group[f"{horizon}_bullish"].mean()),
                "bearish": float(group[f"{horizon}_bearish"].mean()),
                "volatile": float(group[f"{horizon}_volatile"].mean()),
                "bullish_consensus": float((group[f"{horizon}_direction"] > 0).mean()),
                "top_bullish": records_for_json(
                    group.nlargest(8, f"{horizon}_direction"), horizon
                ),
                "top_bearish": records_for_json(
                    group.nsmallest(8, f"{horizon}_direction"), horizon
                ),
            }
        items = []
        for _, row in group.iterrows():
            item = {
                "code": str(row["htsc_code"]),
                "name": str(row["name"]),
                "return_pct": (
                    float(row["return_pct"]) if pd.notna(row["return_pct"]) else None
                ),
                "return_points": (
                    int(row["point_count"]) if pd.notna(row["point_count"]) else 0
                ),
            }
            for horizon in HORIZONS:
                item[horizon] = {
                    "bullish": float(row[f"{horizon}_bullish"]),
                    "bearish": float(row[f"{horizon}_bearish"]),
                    "volatile": float(row[f"{horizon}_volatile"]),
                    "direction": float(row[f"{horizon}_direction"]),
                }
            items.append(item)
        payload = {
            **meta,
            "prefix": prefix,
            "count": int(len(group)),
            "return_coverage": int(len(valid_returns)),
            "median_return": float(valid_returns["return_pct"].median()),
            "mean_return": float(valid_returns["return_pct"].mean()),
            "positive_rate": float((valid_returns["return_pct"] > 0).mean()),
            "dispersion": float(valid_returns["return_pct"].std()),
            "best": compact_row(valid_returns.iloc[0]),
            "worst": compact_row(valid_returns.iloc[-1]),
            "leaders": [compact_row(row) for _, row in valid_returns.head(10).iterrows()],
            "laggards": [compact_row(row) for _, row in valid_returns.tail(10).iloc[::-1].iterrows()],
            "insufficient_history": [
                {
                    "code": str(row["htsc_code"]),
                    "name": str(row["name"]),
                    "points": int(row["point_count"]) if pd.notna(row["point_count"]) else 0,
                }
                for _, row in group.loc[group["return_pct"].isna()].iterrows()
            ],
            "distribution": [
                {"label": str(label), "count": int(distribution.loc[label])} for label in labels
            ],
            "horizons": horizon_summary,
            "items": items,
        }
        report[prefix] = payload
        summary_rows.append(payload)

    strongest = max(summary_rows, key=lambda item: item["median_return"])
    weakest = min(summary_rows, key=lambda item: item["median_return"])
    horizon_leaders = {
        horizon: max(summary_rows, key=lambda item: item["horizons"][horizon]["bullish"])[
            "prefix"
        ]
        for horizon in HORIZONS
    }
    meta = {
        "as_of": as_of.strftime("%Y-%m-%d"),
        "window_start": pd.to_datetime(frame["first_time"]).min().strftime("%Y-%m-%d"),
        "window_end": pd.to_datetime(frame["last_time"]).max().strftime("%Y-%m-%d"),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_count": int(len(frame)),
        "strongest_prefix": strongest["prefix"],
        "strongest_title": strongest["title"],
        "weakest_prefix": weakest["prefix"],
        "weakest_title": weakest["title"],
        "horizon_leaders": horizon_leaders,
    }
    return meta, report


def compact_row(row: pd.Series) -> dict[str, object]:
    return {
        "code": str(row["htsc_code"]),
        "name": str(row["name"]),
        "return_pct": float(row["return_pct"]),
    }


def records_for_json(frame: pd.DataFrame, horizon: str) -> list[dict[str, object]]:
    return [
        {
            "code": str(row["htsc_code"]),
            "name": str(row["name"]),
            "bullish": float(row[f"{horizon}_bullish"]),
            "bearish": float(row[f"{horizon}_bearish"]),
            "direction": float(row[f"{horizon}_direction"]),
        }
        for _, row in frame.iterrows()
    ]


def build_html(meta: dict[str, object], report: dict[str, object]) -> str:
    embedded = json.dumps(
        {"meta": meta, "families": report}, ensure_ascii=False, separators=(",", ":")
    ).replace("</", "<\\/")
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>板块轮动20日总结报告 · {meta["as_of"]}</title>
<link rel="icon" href="data:,">
<style>
:root{{--paper:#fffef8;--white:#fff;--ink:#24231f;--muted:#6f6a5d;--line:#e7dfc6;--yellow:#f6c945;--yellow-soft:#fff3bd;--yellow-pale:#fff9df;--green:#16856b;--red:#c44b43;--gray:#a59f90;--shadow:0 8px 24px rgba(54,45,18,.08)}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:"Microsoft YaHei","PingFang SC",Arial,sans-serif;letter-spacing:0}}button,input{{font:inherit;letter-spacing:0}}button{{cursor:pointer}}
.topbar{{height:8px;background:var(--yellow)}}.masthead{{max-width:1280px;margin:0 auto;padding:32px 28px 22px;display:flex;justify-content:space-between;gap:24px;align-items:flex-start;border-bottom:1px solid var(--line)}}
.eyebrow{{font-size:12px;font-weight:800;color:#8a6b00;text-transform:uppercase;margin-bottom:8px}}h1{{font-size:clamp(28px,4vw,48px);line-height:1.08;margin:0 0 12px;font-weight:850}}.subtitle{{margin:0;color:var(--muted);font-size:15px;line-height:1.8;max-width:760px}}.report-meta{{min-width:220px;text-align:right;color:var(--muted);font-size:13px;line-height:1.8}}.report-meta strong{{display:block;color:var(--ink);font-size:18px}}.print-btn{{border:1px solid #d7b83f;background:var(--yellow-pale);color:#5f4b00;padding:8px 12px;border-radius:6px;margin-top:10px;font-weight:700}}
.shell{{max-width:1280px;margin:0 auto;padding:0 28px 56px}}.executive{{padding:26px 0 28px;display:grid;grid-template-columns:1.25fr .75fr;gap:28px;border-bottom:1px solid var(--line)}}.executive h2,.section-title h2{{margin:0;font-size:22px}}.executive p{{margin:12px 0 0;line-height:1.85;color:#4f4b42}}.scope-note{{background:var(--yellow-pale);border-left:4px solid var(--yellow);padding:16px 18px;line-height:1.7;color:#5c512d}}
.family-overview{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;padding:22px 0}}.overview-card{{border:1px solid var(--line);background:var(--white);border-radius:8px;padding:16px;min-width:0}}.overview-card header{{display:flex;justify-content:space-between;gap:12px;align-items:baseline}}.overview-card header strong{{font-size:18px}}.overview-card header span{{font-size:12px;color:var(--muted)}}.overview-return{{font-size:28px;font-weight:850;margin:12px 0 5px}}.overview-card small{{color:var(--muted)}}
.tabs{{display:flex;gap:0;border-bottom:1px solid var(--line);margin-top:4px;overflow:auto}}.tab{{border:0;border-bottom:3px solid transparent;background:transparent;padding:15px 22px;color:var(--muted);white-space:nowrap}}.tab strong{{font-size:17px;margin-right:7px}}.tab.active{{color:var(--ink);border-bottom-color:var(--yellow);background:var(--yellow-pale)}}
.family-head{{padding:28px 0 18px;display:flex;justify-content:space-between;gap:20px;align-items:end}}.family-head h2{{font-size:28px;margin:0 0 6px}}.family-head p{{margin:0;color:var(--muted)}}.family-badge{{font-size:13px;color:#755a00;background:var(--yellow-soft);padding:7px 10px;border-radius:5px;font-weight:700}}
.metric-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:30px}}.metric{{border-top:3px solid var(--yellow);background:var(--white);padding:15px;border-radius:0 0 7px 7px;box-shadow:var(--shadow)}}.metric span{{font-size:12px;color:var(--muted)}}.metric strong{{display:block;font-size:25px;margin-top:8px}}.metric small{{display:block;color:var(--muted);margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.section{{padding:28px 0;border-top:1px solid var(--line)}}.section-title{{display:flex;justify-content:space-between;gap:16px;align-items:end;margin-bottom:18px}}.section-title p{{margin:0;color:var(--muted);font-size:13px}}.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:28px}}.three-col{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}
.dist-chart{{height:238px;display:flex;align-items:end;gap:10px;padding:18px 14px 0;border-left:1px solid var(--line);border-bottom:1px solid var(--line);background:var(--white)}}.dist-col{{height:100%;flex:1;display:flex;flex-direction:column;justify-content:end;align-items:center;min-width:0}}.dist-col strong{{font-size:12px;margin-bottom:6px}}.dist-bar{{width:min(48px,75%);min-height:2px;background:var(--yellow);border-radius:4px 4px 0 0}}.dist-col span{{height:42px;padding-top:8px;font-size:10px;color:var(--muted);text-align:center}}
.rank-panel{{background:var(--white);border:1px solid var(--line);border-radius:8px;padding:14px}}.rank-panel h3{{font-size:15px;margin:0 0 10px}}.rank-row{{display:grid;grid-template-columns:26px 1fr auto;gap:8px;align-items:center;padding:7px 0;border-top:1px solid #f1eddf;font-size:12px}}.rank-row:first-of-type{{border-top:0}}.rank-index{{color:#a27a00;font-weight:800}}.rank-name{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.positive{{color:var(--green)}}.negative{{color:var(--red)}}
.prob-card{{background:var(--white);border:1px solid var(--line);border-top:4px solid var(--yellow);border-radius:8px;padding:16px}}.prob-card h3{{margin:0;font-size:16px}}.prob-card .consensus{{font-size:12px;color:var(--muted);margin:6px 0 16px}}.prob-line{{margin:12px 0}}.prob-line header{{display:flex;justify-content:space-between;font-size:12px;margin-bottom:5px}}.track{{height:9px;background:#efece3;border-radius:5px;overflow:hidden}}.fill{{height:100%;border-radius:5px}}.fill.bull{{background:var(--green)}}.fill.bear{{background:var(--red)}}.fill.vol{{background:var(--gray)}}
.direction-controls{{display:flex;gap:8px;flex-wrap:wrap}}.horizon-btn{{border:1px solid var(--line);background:var(--white);padding:7px 10px;border-radius:5px;color:var(--muted)}}.horizon-btn.active{{background:var(--yellow);border-color:var(--yellow);color:#3e330e;font-weight:800}}
.table-wrap{{overflow:auto;border:1px solid var(--line);background:var(--white)}}table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{padding:10px 12px;border-bottom:1px solid #eee9da;text-align:right;white-space:nowrap}}th{{position:sticky;top:0;background:var(--yellow-pale);color:#5c512d;font-weight:800}}th:nth-child(-n+2),td:nth-child(-n+2){{text-align:left}}tbody tr:hover{{background:#fffbee}}details{{margin-top:20px}}summary{{cursor:pointer;color:#6f5900;font-weight:800;padding:10px 0}}
.method{{font-size:13px;line-height:1.8;color:var(--muted)}}.footer{{border-top:1px solid var(--line);padding:22px 0;color:var(--muted);font-size:12px;display:flex;justify-content:space-between;gap:18px}}
@media(max-width:900px){{.masthead,.executive,.family-head,.section-title,.footer{{display:block}}.report-meta{{text-align:left;margin-top:18px}}.executive,.two-col{{grid-template-columns:1fr}}.family-overview,.three-col{{grid-template-columns:1fr}}.metric-grid{{grid-template-columns:1fr 1fr}}.scope-note{{margin-top:18px}}}}
@media(max-width:560px){{.masthead,.shell{{padding-left:16px;padding-right:16px}}.metric-grid{{grid-template-columns:1fr}}.tabs{{margin-left:-16px;margin-right:-16px}}.tab{{padding:13px 15px}}h1{{font-size:30px}}}}
@media print{{.topbar{{height:4px}}.print-btn,.tabs,.direction-controls,details summary{{display:none}}body{{background:#fff}}.shell,.masthead{{max-width:none}}.overview-card,.metric,.prob-card,.rank-panel{{box-shadow:none;break-inside:avoid}}.section{{break-inside:avoid}}details{{display:block}}details>div{{display:block!important}}}}
</style>
</head>
<body>
<div class="topbar"></div>
<header class="masthead">
  <div><div class="eyebrow">Sector Rotation / Static Brief</div><h1>板块轮动 20 日总结报告</h1><p class="subtitle">覆盖 881 粗行业、885 早期细分概念与 886 后期细分概念，结合最近 20 个交易日区间收益和峰谷模型三周期概率，提供可直接分享的静态观察快照。</p></div>
  <div class="report-meta"><strong>数据截至 {meta["as_of"]}</strong><span>收益区间 {meta["window_start"]} - {meta["window_end"]}</span><br><span>生成时间 {meta["generated_at"]}</span><br><button class="print-btn" type="button" onclick="window.print()" title="打印或另存为 PDF">打印 / PDF</button></div>
</header>
<main class="shell">
  <section class="executive"><div><h2>执行摘要</h2><p id="executive-copy"></p></div><aside class="scope-note"><strong>口径说明</strong><br>上涨概率 = 波谷看涨 + 震荡看涨；下跌概率 = 波峰看跌 + 震荡看跌；高波概率单列。概率反映事件分类倾向，不代表预期收益幅度。</aside></section>
  <section id="family-overview" class="family-overview" aria-label="分类概览"></section>
  <nav id="tabs" class="tabs" aria-label="板块分类"></nav>
  <div id="report-content"></div>
  <section class="section method"><div class="section-title"><h2>方法与限制</h2></div><p>收益率采用每个板块最近 20 个有效交易日的首尾收盘价计算，不进行个股复权，也不以当前成分股回算板块指数。模型概率来自同一交易日的已训练峰谷模型静态推理快照。881、885、886 的板块数量和名称以本地同花顺一级板块清单为准。</p><p>本报告用于横截面比较和研究沟通，不构成交易建议。概念板块存在主题交叉，分类之间不可直接视为互斥投资组合。</p></section>
  <footer class="footer"><span>板块轮动研究工作台 · 静态报告</span><span>共 {meta["total_count"]} 个板块 · 数据快照不可自动更新</span></footer>
</main>
<script id="report-data" type="application/json">{embedded}</script>
<script>
const DATA=JSON.parse(document.getElementById('report-data').textContent);let activePrefix='881',activeHorizon='ultra_short';
const pct=(v,d=1)=>`${{v>=0?'+':''}}${{Number(v).toFixed(d)}}%`;const ret=v=>v==null?'历史不足':pct(v);const prob=v=>`${{(Number(v)*100).toFixed(1)}}%`;const tone=v=>v==null?'':(v>=0?'positive':'negative');
function executive(){{const m=DATA.meta, leader=h=>DATA.families[m.horizon_leaders[h]];document.getElementById('executive-copy').innerHTML=`最近20个交易日，<strong>${{m.strongest_prefix}} ${{m.strongest_title}}</strong>的板块中位收益领先，<strong>${{m.weakest_prefix}} ${{m.weakest_title}}</strong>相对偏弱。模型横截面平均看涨概率最高的分类分别为：超短 <strong>${{leader('ultra_short').prefix}} ${{leader('ultra_short').title}}</strong>、短期 <strong>${{leader('5d').prefix}} ${{leader('5d').title}}</strong>、中期 <strong>${{leader('20d').prefix}} ${{leader('20d').title}}</strong>。建议结合收益扩散度与看涨共识比例判断轮动是否具备广度。`;}}
function overview(){{document.getElementById('family-overview').innerHTML=Object.values(DATA.families).map(f=>`<article class="overview-card"><header><strong>${{f.prefix}} · ${{f.title}}</strong><span>${{f.count}} 个</span></header><div class="overview-return ${{tone(f.median_return)}}">${{pct(f.median_return)}}</div><small>20日中位收益 · 收益覆盖 ${{f.return_coverage}}/${{f.count}}</small></article>`).join('');}}
function tabs(){{document.getElementById('tabs').innerHTML=Object.values(DATA.families).map(f=>`<button class="tab ${{f.prefix===activePrefix?'active':''}}" data-prefix="${{f.prefix}}"><strong>${{f.prefix}}</strong>${{f.title}}</button>`).join('');document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{{activePrefix=b.dataset.prefix;activeHorizon='ultra_short';render(true);}});}}
function rankRows(items,valueKey='return_pct',isProbability=false){{return items.map((x,i)=>`<div class="rank-row"><span class="rank-index">${{String(i+1).padStart(2,'0')}}</span><span class="rank-name" title="${{x.code}}">${{x.name}}</span><strong class="${{tone(x[valueKey])}}">${{isProbability?pct(x[valueKey]*100):pct(x[valueKey])}}</strong></div>`).join('');}}
function probabilityCards(f){{return Object.entries(f.horizons).map(([key,h])=>`<article class="prob-card"><h3>${{h.label}}</h3><div class="consensus">${{prob(h.bullish_consensus)}} 的板块看涨概率高于看跌</div>${{[['bullish','上涨概率','bull'],['bearish','下跌概率','bear'],['volatile','高波概率','vol']].map(([k,l,c])=>`<div class="prob-line"><header><span>${{l}}</span><strong>${{prob(h[k])}}</strong></header><div class="track"><div class="fill ${{c}}" style="width:${{h[k]*100}}%"></div></div></div>`).join('')}}</article>`).join('');}}
function distribution(f){{const max=Math.max(...f.distribution.map(x=>x.count),1);return `<div class="dist-chart">${{f.distribution.map(x=>`<div class="dist-col"><strong>${{x.count}}</strong><div class="dist-bar" style="height:${{Math.max(3,x.count/max*160)}}px"></div><span>${{x.label}}</span></div>`).join('')}}</div>`;}}
function directionSection(f){{const h=f.horizons[activeHorizon];return `<div class="section-title"><div><h2>模型方向排名</h2><p>方向差 = 上涨概率 - 下跌概率</p></div><div class="direction-controls">${{Object.entries(f.horizons).map(([k,v])=>`<button class="horizon-btn ${{k===activeHorizon?'active':''}}" data-horizon="${{k}}">${{v.label}}</button>`).join('')}}</div></div><div class="two-col"><div class="rank-panel"><h3>看涨倾向领先</h3>${{rankRows(h.top_bullish,'direction',true)}}</div><div class="rank-panel"><h3>看跌倾向领先</h3>${{rankRows(h.top_bearish,'direction',true)}}</div></div>`;}}
function fullTable(f){{return `<details><summary>查看 ${{f.count}} 个板块全量明细</summary><div class="table-wrap"><table><thead><tr><th>板块</th><th>代码</th><th>20日收益</th><th>超短涨/跌</th><th>短期涨/跌</th><th>中期涨/跌</th></tr></thead><tbody>${{f.items.map(x=>`<tr><td>${{x.name}}</td><td>${{x.code}}</td><td class="${{tone(x.return_pct)}}">${{ret(x.return_pct)}}</td>${{['ultra_short','5d','20d'].map(h=>`<td>${{prob(x[h].bullish)}} / ${{prob(x[h].bearish)}}</td>`).join('')}}</tr>`).join('')}}</tbody></table></div></details>`;}}
function render(shouldScroll=false){{const f=DATA.families[activePrefix];tabs();const historyNote=f.insufficient_history.length?` · ${{f.insufficient_history.map(x=>`${{x.name}}仅${{x.points}}日`).join('、')}}`:' ';document.getElementById('report-content').innerHTML=`<section class="family-head"><div><h2>${{f.prefix}} · ${{f.title}}</h2><p>${{f.description}}</p></div><span class="family-badge">${{f.count}} 个板块 · 收益覆盖 ${{f.return_coverage}}</span></section><section class="metric-grid"><article class="metric"><span>20日中位收益</span><strong class="${{tone(f.median_return)}}">${{pct(f.median_return)}}</strong><small>平均 ${{pct(f.mean_return)}}</small></article><article class="metric"><span>上涨板块占比</span><strong>${{prob(f.positive_rate)}}</strong><small>完整20日样本中的比例</small></article><article class="metric"><span>领涨板块</span><strong class="positive">${{pct(f.best.return_pct)}}</strong><small>${{f.best.name}}</small></article><article class="metric"><span>领跌板块</span><strong class="negative">${{pct(f.worst.return_pct)}}</strong><small>${{f.worst.name}}</small></article></section><section class="section"><div class="section-title"><h2>20日收益概览</h2><p>横截面标准差 ${{f.dispersion.toFixed(2)}} 个百分点${{historyNote}}</p></div><div class="two-col">${{distribution(f)}}<div class="two-col"><div class="rank-panel"><h3>领涨前十</h3>${{rankRows(f.leaders)}}</div><div class="rank-panel"><h3>领跌前十</h3>${{rankRows(f.laggards)}}</div></div></div></section><section class="section"><div class="section-title"><h2>三周期涨跌概率</h2><p>分类内板块概率的等权平均</p></div><div class="three-col">${{probabilityCards(f)}}</div></section><section class="section" id="direction-section">${{directionSection(f)}}</section><section class="section"><div class="section-title"><h2>全量板块明细</h2><p>按20日收益从高到低排列</p></div>${{fullTable(f)}}</section>`;document.querySelectorAll('.horizon-btn').forEach(b=>b.onclick=()=>{{activeHorizon=b.dataset.horizon;document.getElementById('direction-section').innerHTML=directionSection(f);document.querySelectorAll('.horizon-btn').forEach(x=>x.onclick=b.onclick);}});if(shouldScroll)window.scrollTo({{top:document.getElementById('tabs').offsetTop-8,behavior:'smooth'}});}}
executive();overview();render(false);
</script>
</body>
</html>'''


def _format_return(value: float) -> str:
    return f"{value:+.1f}%"


def _format_probability(value: float) -> str:
    return f"{value * 100:.1f}%"


def _rank_list(items: list[dict[str, object]]) -> str:
    rows = []
    for index, item in enumerate(items[:5], start=1):
        value = float(item["return_pct"])
        tone = "up" if value >= 0 else "down"
        rows.append(
            f'<div class="rank-row"><b>{index:02d}</b><span>{escape(str(item["name"]))}</span>'
            f'<strong class="{tone}">{_format_return(value)}</strong></div>'
        )
    return "".join(rows)


def _distribution_chart(family: dict[str, object]) -> str:
    distribution = list(family["distribution"])
    maximum = max((int(item["count"]) for item in distribution), default=1)
    columns = []
    for item in distribution:
        count = int(item["count"])
        height = max(4, round(count / maximum * 112))
        columns.append(
            '<div class="dist-col">'
            f'<b>{count}</b><i style="height:{height}px"></i>'
            f'<span>{escape(str(item["label"]))}</span></div>'
        )
    return "".join(columns)


def _probability_cards(family: dict[str, object]) -> str:
    cards = []
    for horizon in HORIZONS:
        item = family["horizons"][horizon]
        cards.append(
            '<article class="prob-card">'
            f'<header><h3>{escape(str(item["label"]))}</h3>'
            f'<span>{_format_probability(float(item["bullish_consensus"]))} 板块偏多</span></header>'
            f'<div class="prob-row"><span>上涨</span><i><em class="bull" style="width:{float(item["bullish"]) * 100:.2f}%"></em></i><b>{_format_probability(float(item["bullish"]))}</b></div>'
            f'<div class="prob-row"><span>下跌</span><i><em class="bear" style="width:{float(item["bearish"]) * 100:.2f}%"></em></i><b>{_format_probability(float(item["bearish"]))}</b></div>'
            f'<div class="prob-row"><span>高波</span><i><em class="volatile" style="width:{float(item["volatile"]) * 100:.2f}%"></em></i><b>{_format_probability(float(item["volatile"]))}</b></div>'
            '</article>'
        )
    return "".join(cards)


def build_image_html(meta: dict[str, object], report: dict[str, object]) -> str:
    overview_cards = []
    family_sections = []
    for prefix, family in report.items():
        overview_cards.append(
            '<article class="overview-card">'
            f'<header><b>{prefix} · {escape(str(family["title"]))}</b><span>{family["count"]} 个</span></header>'
            f'<strong>{_format_return(float(family["median_return"]))}</strong>'
            f'<p>20日中位收益 · 上涨占比 {_format_probability(float(family["positive_rate"]))}</p>'
            '</article>'
        )
        insufficient = family["insufficient_history"]
        history_note = ""
        if insufficient:
            labels = "、".join(
                f'{escape(str(item["name"]))}仅{int(item["points"])}日'
                for item in insufficient
            )
            history_note = f'<span class="history-note">{labels}</span>'
        family_sections.append(
            '<section class="family">'
            '<div class="family-title">'
            f'<div><span>FAMILY {prefix}</span><h2>{prefix} · {escape(str(family["title"]))}</h2><p>{escape(str(family["description"]))}</p></div>'
            f'<b>{family["count"]} 个板块</b></div>'
            '<div class="metric-strip">'
            f'<div><span>20日中位收益</span><strong class="up">{_format_return(float(family["median_return"]))}</strong></div>'
            f'<div><span>上涨板块占比</span><strong>{_format_probability(float(family["positive_rate"]))}</strong></div>'
            f'<div><span>领涨板块</span><strong class="up">{_format_return(float(family["best"]["return_pct"]))}</strong><small>{escape(str(family["best"]["name"]))}</small></div>'
            f'<div><span>领跌板块</span><strong class="down">{_format_return(float(family["worst"]["return_pct"]))}</strong><small>{escape(str(family["worst"]["name"]))}</small></div>'
            '</div>'
            '<div class="family-main">'
            '<div class="returns-panel"><header><h3>20日收益分布</h3>'
            f'<span>标准差 {float(family["dispersion"]):.2f} 个百分点</span></header>'
            f'<div class="distribution">{_distribution_chart(family)}</div>{history_note}</div>'
            f'<div class="rank-panel"><h3>领涨前五</h3>{_rank_list(family["leaders"])}</div>'
            f'<div class="rank-panel"><h3>领跌前五</h3>{_rank_list(family["laggards"])}</div>'
            '</div>'
            f'<div class="prob-grid">{_probability_cards(family)}</div>'
            '</section>'
        )

    horizon_leader_text = "、".join(
        f'{label.split("（")[0]} {meta["horizon_leaders"][horizon]}'
        for horizon, label in HORIZONS.items()
    )
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>板块轮动图片报告</title><link rel="icon" href="data:,">
<style>
:root{{--paper:#fffdf5;--white:#fff;--ink:#24221d;--muted:#746e60;--line:#e8dfc4;--yellow:#f4c63d;--yellow-pale:#fff6cb;--up:#087f68;--down:#c4473f;--gray:#9d988d}}*{{box-sizing:border-box}}html,body{{margin:0;background:var(--paper);color:var(--ink);font-family:"Microsoft YaHei","PingFang SC",Arial,sans-serif;letter-spacing:0}}body{{width:1440px}}.top{{height:9px;background:var(--yellow)}}main{{width:1280px;margin:0 auto;padding:44px 0 54px}}.report-head{{display:grid;grid-template-columns:1fr 300px;gap:50px;padding-bottom:30px;border-bottom:1px solid var(--line)}}.eyebrow{{font-size:12px;font-weight:800;color:#816500}}h1{{font-size:48px;line-height:1.1;margin:10px 0 14px}}.report-head p{{margin:0;color:var(--muted);font-size:16px;line-height:1.8;max-width:820px}}.meta{{text-align:right;font-size:14px;color:var(--muted);line-height:1.9}}.meta b{{display:block;color:var(--ink);font-size:21px}}.summary{{display:grid;grid-template-columns:1.35fr .65fr;gap:30px;padding:28px 0;border-bottom:1px solid var(--line)}}.summary h2{{font-size:24px;margin:0 0 12px}}.summary p{{font-size:16px;line-height:1.9;margin:0}}.note{{background:var(--yellow-pale);border-left:4px solid var(--yellow);padding:18px 20px;font-size:14px;line-height:1.75}}.overview{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;padding:24px 0 8px}}.overview-card{{background:var(--white);border:1px solid var(--line);border-radius:7px;padding:17px}}.overview-card header{{display:flex;justify-content:space-between;align-items:center}}.overview-card header b{{font-size:18px}}.overview-card header span,.overview-card p{{font-size:12px;color:var(--muted)}}.overview-card>strong{{display:block;color:var(--up);font-size:31px;margin:10px 0 4px}}.overview-card p{{margin:0}}.family{{margin-top:30px;padding-top:28px;border-top:2px solid var(--yellow);break-inside:avoid}}.family-title{{display:flex;align-items:end;justify-content:space-between;margin-bottom:18px}}.family-title span{{font-size:11px;color:#8d7100;font-weight:800}}.family-title h2{{font-size:30px;margin:5px 0}}.family-title p{{margin:0;color:var(--muted)}}.family-title>b{{background:var(--yellow-pale);padding:8px 12px;border-radius:5px;color:#6e5700}}.metric-strip{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.metric-strip>div{{background:var(--white);border-top:3px solid var(--yellow);padding:14px 16px;min-height:102px}}.metric-strip span{{display:block;color:var(--muted);font-size:12px}}.metric-strip strong{{display:block;font-size:25px;margin-top:8px}}.metric-strip small{{display:block;color:var(--muted);margin-top:3px}}.up{{color:var(--up)}}.down{{color:var(--down)}}.family-main{{display:grid;grid-template-columns:1.25fr .8fr .8fr;gap:14px;margin-top:14px}}.returns-panel,.rank-panel,.prob-card{{background:var(--white);border:1px solid var(--line);padding:15px;border-radius:7px}}.returns-panel>header{{display:flex;justify-content:space-between}}.returns-panel h3,.rank-panel h3,.prob-card h3{{font-size:15px;margin:0}}.returns-panel header span{{font-size:11px;color:var(--muted)}}.distribution{{height:154px;display:flex;align-items:end;gap:9px;border-bottom:1px solid var(--line);margin-top:10px}}.dist-col{{flex:1;height:145px;display:flex;flex-direction:column;justify-content:end;align-items:center}}.dist-col b{{font-size:11px;margin-bottom:4px}}.dist-col i{{display:block;width:65%;background:var(--yellow);border-radius:3px 3px 0 0}}.dist-col span{{font-size:9px;color:var(--muted);height:25px;padding-top:5px}}.history-note{{display:block;font-size:10px;color:var(--muted);margin-top:6px}}.rank-row{{display:grid;grid-template-columns:24px 1fr auto;gap:8px;padding:7px 0;border-top:1px solid #f0ebdc;font-size:12px}}.rank-row:first-of-type{{margin-top:7px}}.rank-row>b{{color:#977600}}.rank-row span{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.prob-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:14px}}.prob-card{{border-top:4px solid var(--yellow)}}.prob-card header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}}.prob-card header span{{font-size:10px;color:var(--muted)}}.prob-row{{display:grid;grid-template-columns:35px 1fr 48px;gap:8px;align-items:center;margin-top:8px;font-size:11px}}.prob-row i{{height:8px;background:#efebe1;border-radius:4px;overflow:hidden}}.prob-row em{{display:block;height:100%}}.bull{{background:var(--up)}}.bear{{background:var(--down)}}.volatile{{background:var(--gray)}}.prob-row b{{text-align:right}}footer{{display:flex;justify-content:space-between;border-top:1px solid var(--line);margin-top:34px;padding-top:18px;color:var(--muted);font-size:11px}}
</style></head><body><div class="top"></div><main>
<header class="report-head"><div><div class="eyebrow">SECTOR ROTATION / 20-DAY BRIEF</div><h1>板块轮动总结报告</h1><p>881 粗行业、885 早期细分概念与 886 后期细分概念的最近20个交易日收益表现，以及峰谷模型超短、短期和中期概率概览。</p></div><div class="meta"><b>数据截至 {meta["as_of"]}</b><span>收益区间 {meta["window_start"]} - {meta["window_end"]}</span><br><span>生成时间 {meta["generated_at"]}</span></div></header>
<section class="summary"><div><h2>执行摘要</h2><p>最近20个交易日，<b>{meta["strongest_prefix"]} {escape(str(meta["strongest_title"]))}</b>的板块中位收益领先，<b>{meta["weakest_prefix"]} {escape(str(meta["weakest_title"]))}</b>相对偏弱。模型平均看涨概率领先分类为：<b>{horizon_leader_text}</b>。收益扩散度与看涨共识需结合观察。</p></div><aside class="note"><b>概率口径</b><br>上涨 = 波谷看涨 + 震荡看涨<br>下跌 = 波峰看跌 + 震荡看跌<br>高波概率单列，不代表收益幅度。</aside></section>
<section class="overview">{''.join(overview_cards)}</section>
{''.join(family_sections)}
<footer><span>板块轮动研究工作台 · 静态图片报告</span><span>共 {meta["total_count"]} 个板块 · 模型概率仅作研究参考</span></footer>
</main></body></html>'''


def _one_page_probability_rows(family: dict[str, object]) -> str:
    rows = []
    for horizon in HORIZONS:
        item = family["horizons"][horizon]
        rows.append(
            '<section class="period">'
            f'<header><h3>{escape(str(item["label"]))}</h3>'
            f'<span>{_format_probability(float(item["bullish_consensus"]))} 板块偏多</span></header>'
            '<div class="stack">'
            f'<i class="bull" style="width:{float(item["bullish"]) * 100:.3f}%"></i>'
            f'<i class="bear" style="width:{float(item["bearish"]) * 100:.3f}%"></i>'
            f'<i class="volatile" style="width:{float(item["volatile"]) * 100:.3f}%"></i>'
            '</div>'
            '<div class="period-values">'
            f'<span><i class="dot bull"></i>上涨 <b>{_format_probability(float(item["bullish"]))}</b></span>'
            f'<span><i class="dot bear"></i>下跌 <b>{_format_probability(float(item["bearish"]))}</b></span>'
            f'<span><i class="dot volatile"></i>高波 <b>{_format_probability(float(item["volatile"]))}</b></span>'
            '</div></section>'
        )
    return "".join(rows)


def build_one_page_html(meta: dict[str, object], report: dict[str, object]) -> str:
    family_columns = []
    for prefix, family in report.items():
        insufficient = family["insufficient_history"]
        note = ""
        if insufficient:
            note = " · " + "、".join(
                f'{escape(str(item["name"]))}仅{int(item["points"])}日'
                for item in insufficient
            )
        family_columns.append(
            '<article class="family-column">'
            '<header class="family-head">'
            f'<div><span>{prefix}</span><h2>{escape(str(family["title"]))}</h2></div>'
            f'<b>{family["count"]} 个板块</b></header>'
            '<section class="return-summary">'
            '<div class="main-return"><span>20日中位收益</span>'
            f'<strong>{_format_return(float(family["median_return"]))}</strong>'
            f'<small>平均 {_format_return(float(family["mean_return"]))} · 上涨占比 {_format_probability(float(family["positive_rate"]))}</small></div>'
            '<div class="return-extremes">'
            f'<div><span>领涨</span><b class="up">{escape(str(family["best"]["name"]))}</b><strong class="up">{_format_return(float(family["best"]["return_pct"]))}</strong></div>'
            f'<div><span>领跌</span><b class="down">{escape(str(family["worst"]["name"]))}</b><strong class="down">{_format_return(float(family["worst"]["return_pct"]))}</strong></div>'
            '</div></section>'
            '<div class="return-range"><span>20日收益区间</span><div><i class="loss" style="width:18%"></i><i class="gain" style="width:82%"></i></div>'
            f'<small>{_format_return(float(family["worst"]["return_pct"]))} 至 {_format_return(float(family["best"]["return_pct"]))} · 横截面标准差 {float(family["dispersion"]):.2f}个百分点{note}</small></div>'
            '<div class="periods">'
            f'{_one_page_probability_rows(family)}'
            '</div></article>'
        )

    leaders = " / ".join(
        f'{label.split("（")[0]} {meta["horizon_leaders"][horizon]}'
        for horizon, label in HORIZONS.items()
    )
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>板块轮动一页总结</title><link rel="icon" href="data:,">
<style>
:root{{--paper:#fffdf6;--white:#fff;--ink:#24221d;--muted:#736d60;--line:#e6ddc2;--yellow:#f4c63d;--yellow-pale:#fff4bf;--bull:#07816a;--bear:#c84a42;--volatile:#9c978c}}*{{box-sizing:border-box}}html,body{{margin:0;width:1920px;height:1080px;overflow:hidden;background:var(--paper);color:var(--ink);font-family:"Microsoft YaHei","PingFang SC",Arial,sans-serif;letter-spacing:0}}.top{{height:8px;background:var(--yellow)}}main{{width:1760px;height:1072px;margin:0 auto;padding:38px 0 28px;display:flex;flex-direction:column}}.report-head{{display:grid;grid-template-columns:1fr auto;gap:60px;align-items:start;padding-bottom:22px;border-bottom:1px solid var(--line)}}.eyebrow{{font-size:12px;font-weight:800;color:#806500}}h1{{font-size:42px;line-height:1;margin:10px 0 12px}}.report-head p{{font-size:15px;line-height:1.7;color:var(--muted);margin:0;max-width:1100px}}.meta{{text-align:right;color:var(--muted);font-size:13px;line-height:1.8}}.meta b{{display:block;color:var(--ink);font-size:20px}}.summary-line{{display:flex;justify-content:space-between;gap:30px;align-items:center;padding:14px 18px;margin:16px 0;background:var(--yellow-pale);border-left:4px solid var(--yellow);font-size:14px}}.summary-line strong{{font-size:15px}}.summary-line span{{color:var(--muted)}}.family-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;flex:1;min-height:0}}.family-column{{background:var(--white);border:1px solid var(--line);border-top:4px solid var(--yellow);border-radius:7px;padding:20px 22px;display:flex;flex-direction:column;min-width:0}}.family-head{{display:flex;justify-content:space-between;align-items:center;padding-bottom:14px;border-bottom:1px solid var(--line)}}.family-head>div{{display:flex;align-items:baseline;gap:10px}}.family-head span{{font-size:28px;font-weight:850}}.family-head h2{{font-size:20px;margin:0}}.family-head>b{{font-size:12px;color:#715900;background:var(--yellow-pale);padding:7px 9px;border-radius:4px}}.return-summary{{display:grid;grid-template-columns:1fr 1fr;gap:18px;padding:17px 0 14px}}.main-return>span,.return-extremes span,.return-range>span{{display:block;font-size:11px;color:var(--muted)}}.main-return>strong{{display:block;font-size:41px;color:var(--bull);margin:8px 0 2px}}.main-return small{{font-size:11px;color:var(--muted)}}.return-extremes{{display:grid;gap:8px}}.return-extremes>div{{display:grid;grid-template-columns:34px 1fr auto;gap:6px;align-items:center;border-bottom:1px solid #f0ebdd;padding-bottom:7px;font-size:11px}}.return-extremes b{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.return-extremes strong{{font-size:13px}}.up{{color:var(--bull)}}.down{{color:var(--bear)}}.return-range{{padding:10px 0 15px;border-bottom:1px solid var(--line)}}.return-range>div{{height:8px;display:flex;margin:7px 0 6px;border-radius:4px;overflow:hidden;background:#eeeae0}}.return-range i{{display:block;height:100%}}.loss{{background:var(--bear)}}.gain{{background:var(--bull)}}.return-range small{{font-size:10px;color:var(--muted)}}.periods{{display:grid;gap:10px;padding-top:14px}}.period{{padding:10px 0;border-bottom:1px solid #f0ebdd}}.period:last-child{{border-bottom:0}}.period header{{display:flex;justify-content:space-between;align-items:baseline}}.period h3{{font-size:15px;margin:0}}.period header span{{font-size:10px;color:var(--muted)}}.stack{{height:12px;display:flex;margin:8px 0;border-radius:6px;overflow:hidden;background:#eeeae0}}.stack i{{display:block;height:100%}}.bull{{background:var(--bull)}}.bear{{background:var(--bear)}}.volatile{{background:var(--volatile)}}.period-values{{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;font-size:11px}}.period-values span{{display:flex;align-items:center;gap:5px;color:var(--muted)}}.period-values b{{margin-left:auto;color:var(--ink)}}.dot{{width:7px;height:7px;border-radius:50%;flex:0 0 7px}}footer{{display:flex;justify-content:space-between;align-items:center;padding-top:14px;margin-top:14px;border-top:1px solid var(--line);font-size:11px;color:var(--muted)}}footer b{{color:var(--ink)}}
</style></head><body><div class="top"></div><main>
<header class="report-head"><div><div class="eyebrow">SECTOR ROTATION / ONE-PAGE BRIEF</div><h1>板块轮动一页总结</h1><p>最近20个交易日收益表现与峰谷模型三周期概率。上涨概率 = 波谷看涨 + 震荡看涨；下跌概率 = 波峰看跌 + 震荡看跌；高波概率单列。</p></div><div class="meta"><b>数据截至 {meta["as_of"]}</b><span>收益区间 {meta["window_start"]} - {meta["window_end"]}</span><br><span>覆盖 {meta["total_count"]} 个板块</span></div></header>
<section class="summary-line"><strong>20日中位收益领先：{meta["strongest_prefix"]} {escape(str(meta["strongest_title"]))}；相对偏弱：{meta["weakest_prefix"]} {escape(str(meta["weakest_title"]))}</strong><span>平均看涨概率领先分类：{leaders}</span></section>
<section class="family-grid">{''.join(family_columns)}</section>
<footer><span>板块轮动研究工作台 · 静态数据快照</span><span><b>说明：</b>概率反映事件分类倾向，不代表预期收益幅度，不构成交易建议。</span></footer>
</main></body></html>'''


def main() -> None:
    meta, report = load_report_data()
    output = OUTPUT_PATH.with_name(f"板块轮动总结报告_{str(meta['as_of']).replace('-', '')}.html")
    image_source = IMAGE_SOURCE_PATH.with_name(
        f"板块轮动总结报告_图片版_{str(meta['as_of']).replace('-', '')}.html"
    )
    one_page_source = ONE_PAGE_SOURCE_PATH.with_name(
        f"板块轮动一页总结_{str(meta['as_of']).replace('-', '')}.html"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_html(meta, report), encoding="utf-8")
    image_source.write_text(build_image_html(meta, report), encoding="utf-8")
    one_page_source.write_text(build_one_page_html(meta, report), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "image_source": str(image_source),
                "one_page_source": str(one_page_source),
                "meta": meta,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
