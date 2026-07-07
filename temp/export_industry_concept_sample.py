# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from xtquant import xtdata


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "temp" / "industry_concept_sample"


def classify_sector(name: str) -> str:
    if name.startswith("GICS"):
        return "GICS行业"
    if name.startswith("SW") or "SW" in name:
        return "申万行业/指数"
    if name.startswith("THY"):
        return "通达信行业"
    if name.startswith("TGN") or name.startswith("TDGN") or name.startswith("GN") or "概念" in name:
        return "概念"
    if name.startswith("ETF"):
        return "ETF分类"
    if name.endswith("A股") or name.endswith("B股") or "沪深" in name or "深证" in name or "上证" in name:
        return "市场板块"
    return "其他"


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    snapshot_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    snapshot_date = datetime.now().strftime("%Y-%m-%d")

    xtdata.download_sector_data()
    sectors = list(xtdata.get_sector_list())

    selected_sector_names = [
        "沪深A股",
        "沪深京A股",
        "GICS1金融",
        "GICS2银行",
        "SW1银行",
        "SW2半导体",
        "SW3机器人",
        "THY2白酒",
        "TGNDeepSeek概念",
        "TDGN5G概念",
        "GN机器人",
        "新能源车",
    ]
    selected_sector_names = [name for name in selected_sector_names if name in sectors]

    sector_rows = []
    for idx, name in enumerate(sectors, 1):
        sector_rows.append(
            {
                "idx": idx,
                "sector_name": name,
                "sector_kind_guess": classify_sector(name),
                "source_api": "xtdata.get_sector_list",
                "snapshot_time": snapshot_time,
            }
        )

    write_csv(OUT / "sector_list_all.csv", sector_rows)
    (OUT / "sector_list_all.json").write_text(
        json.dumps(sector_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    constituent_rows = []
    summary_rows = []
    for sector_name in selected_sector_names:
        codes = list(xtdata.get_stock_list_in_sector(sector_name) or [])
        markets = Counter((code.split(".")[-1] if "." in code else "") for code in codes)
        summary_rows.append(
            {
                "snapshot_date": snapshot_date,
                "snapshot_time": snapshot_time,
                "sector_name": sector_name,
                "sector_kind_guess": classify_sector(sector_name),
                "stock_count": len(codes),
                "markets": json.dumps(dict(markets), ensure_ascii=False, sort_keys=True),
                "source_api": "xtdata.get_stock_list_in_sector",
            }
        )
        for rank, code in enumerate(codes, 1):
            constituent_rows.append(
                {
                    "snapshot_date": snapshot_date,
                    "snapshot_time": snapshot_time,
                    "sector_name": sector_name,
                    "sector_kind_guess": classify_sector(sector_name),
                    "rank_in_return": rank,
                    "stock_code": code,
                    "market": code.split(".")[-1] if "." in code else "",
                    "source_api": "xtdata.get_stock_list_in_sector",
                }
            )

    write_csv(OUT / "sample_sector_summary.csv", summary_rows)
    write_csv(OUT / "sample_sector_constituents.csv", constituent_rows)
    (OUT / "sample_sector_constituents.json").write_text(
        json.dumps(constituent_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    metadata = {
        "snapshot_time": snapshot_time,
        "doc_url": "https://dict.thinktrader.net/dictionary/industry.html?id=7kT126#获取行业概念数据",
        "apis_used": [
            "xtdata.download_sector_data()",
            "xtdata.get_sector_list()",
            "xtdata.get_stock_list_in_sector(sector_name)",
        ],
        "important_note": "这些接口没有日期参数，返回的是本地下载后的当前行业/概念/板块分类快照；不能直接按日期获取最近几天历史成分。这里按 snapshot_time 保存当前样例。",
        "sector_count": len(sectors),
        "selected_sector_count": len(selected_sector_names),
        "selected_sectors": selected_sector_names,
        "output_files": [
            "sector_list_all.csv",
            "sector_list_all.json",
            "sample_sector_summary.csv",
            "sample_sector_constituents.csv",
            "sample_sector_constituents.json",
            "metadata.json",
            "README.md",
        ],
    }
    (OUT / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    readme = f"""# 行业概念数据样例

生成时间：{snapshot_time}

来源接口：

- `xtdata.download_sector_data()`：下载/刷新本地行业板块数据。
- `xtdata.get_sector_list()`：返回所有可用板块名称，本次共 `{len(sectors)}` 个。
- `xtdata.get_stock_list_in_sector(sector_name)`：按板块名返回成分股代码列表。

注意：这些接口没有开始日期/结束日期参数，返回的是当前本地板块分类快照，不是日频历史成分数据；所以这里不能真实导出“最近几天每天一份”的历史变化，只能按 `snapshot_time` 保存当前快照。

文件说明：

- `sector_list_all.csv` / `sector_list_all.json`：全量板块/行业/概念名称清单。
- `sample_sector_summary.csv`：抽样板块的成分股数量和市场分布。
- `sample_sector_constituents.csv` / `.json`：抽样板块成分股明细。
- `metadata.json`：接口、生成时间、样例范围说明。

CSV 使用 `utf-8-sig`，方便 Excel 直接打开中文。
"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")

    print(f"OUT={OUT}")
    print(f"sector_count={len(sectors)}")
    print(f"selected_sectors={selected_sector_names}")
    print(f"constituent_rows={len(constituent_rows)}")


if __name__ == "__main__":
    main()
