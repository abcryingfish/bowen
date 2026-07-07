# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from xtquant import xtdata


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "temp" / "etf_sector_sample"
ETF_SECTORS = [
    "沪深ETF",
    "沪市ETF",
    "深市ETF",
    "ETF股票型",
    "ETF行业指数",
    "ETF主题指数",
    "ETF跨境型",
]


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
    available_sectors = set(xtdata.get_sector_list())

    all_rows = []
    summary_rows = []
    by_sector: dict[str, list[str]] = {}

    for sector_name in ETF_SECTORS:
        if sector_name not in available_sectors:
            codes = []
            exists = False
        else:
            codes = list(xtdata.get_stock_list_in_sector(sector_name) or [])
            exists = True
        by_sector[sector_name] = codes

        market_counts: dict[str, int] = {}
        for code in codes:
            market = code.split(".")[-1] if "." in code else ""
            market_counts[market] = market_counts.get(market, 0) + 1
        summary_rows.append(
            {
                "snapshot_date": snapshot_date,
                "snapshot_time": snapshot_time,
                "sector_name": sector_name,
                "exists_in_get_sector_list": exists,
                "etf_count": len(codes),
                "markets": json.dumps(market_counts, ensure_ascii=False, sort_keys=True),
                "source_api": "xtdata.get_stock_list_in_sector",
            }
        )

        sector_rows = []
        for rank, code in enumerate(codes, 1):
            row = {
                "snapshot_date": snapshot_date,
                "snapshot_time": snapshot_time,
                "sector_name": sector_name,
                "rank_in_return": rank,
                "etf_code": code,
                "market": code.split(".")[-1] if "." in code else "",
                "source_api": "xtdata.get_stock_list_in_sector",
            }
            all_rows.append(row)
            sector_rows.append(row)

        safe_name = sector_name.replace("/", "_")
        write_csv(OUT / f"{safe_name}.csv", sector_rows)
        (OUT / f"{safe_name}.json").write_text(
            json.dumps(sector_rows, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    write_csv(OUT / "etf_sector_summary.csv", summary_rows)
    write_csv(OUT / "etf_sector_members_all.csv", all_rows)
    (OUT / "etf_sector_members_all.json").write_text(
        json.dumps(all_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    metadata = {
        "snapshot_time": snapshot_time,
        "apis_used": [
            "xtdata.download_sector_data()",
            "xtdata.get_sector_list()",
            "xtdata.get_stock_list_in_sector(sector_name)",
        ],
        "note": "这些 ETF 分类返回的是当前本地板块快照中的 ETF 代码列表，不是 ETF 持仓成分股。",
        "sectors": ETF_SECTORS,
        "summary": summary_rows,
        "output_files": [
            "etf_sector_summary.csv",
            "etf_sector_members_all.csv",
            "etf_sector_members_all.json",
            *[f"{name}.csv" for name in ETF_SECTORS],
            *[f"{name}.json" for name in ETF_SECTORS],
            "metadata.json",
            "README.md",
        ],
    }
    (OUT / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    readme = f"""# ETF 板块分类样例

生成时间：{snapshot_time}

来源接口：

- `xtdata.download_sector_data()`
- `xtdata.get_sector_list()`
- `xtdata.get_stock_list_in_sector(sector_name)`

注意：这里保存的是 ETF 分类下的 ETF 产品代码列表，不是单只 ETF 的持仓成分股。

主要文件：

- `etf_sector_summary.csv`：7 个 ETF 分类的数量和市场分布。
- `etf_sector_members_all.csv`：7 个 ETF 分类合并明细。
- `沪深ETF.csv`、`沪市ETF.csv`、`深市ETF.csv` 等：每个分类单独明细。

CSV 使用 `utf-8-sig`，方便 Excel 直接打开中文。
"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")

    print(f"OUT={OUT}")
    for row in summary_rows:
        print(f"{row['sector_name']}: {row['etf_count']} {row['markets']}")
    print(f"all_rows={len(all_rows)}")


if __name__ == "__main__":
    main()
