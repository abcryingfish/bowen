# Agent instructions — `工具/` (华泰 Insight + 本地 Parquet)

> 全仓库目录地图见 [`../AGENTS.md`](../AGENTS.md)。

## Scope

- Working directory context: `python_venv/工具/` (this folder).
- Default Python (Windows): `c:\Users\Administrator\Desktop\python_venv\.venv\Scripts\python.exe`
- Default data roots: under `D:\database\...` unless CLI `--base-dir` overrides.
- Before edits: assume Insight login may be required for live pulls; confirm `BASE_DIR` / `--base-dir` and stock universe source (API vs CSV vs notebook `BASE_PATH`) when behavior depends on them.

## Data roots (script → default path)

| Default path | Written by | Notes |
|--------------|------------|-------|
| `D:\database\stock_basic_data_daily` | `获得股票日频数据.py` | 日 K OHLCV；`time` + `htsc_code` |
| `D:\database\stock_financial_statements\market_equity_data` | `获得股票日频换手率.py` | `get_daily_basic` 全字段；原目录名 `stock_liquidity_data` / `stock_temp_data` 已废弃 |
| `D:\database\stock_financial_statements\stock_valuation_data` | `获得市值数据.py` | `get_stock_valuation` 估值字段；与 market_equity 同属财报父目录 |
| `D:\database\stock_adj_daily` | `获得股票日频复权因子.py` | `adj_factor_segments.parquet`（+ 可选 wide） |
| `D:\database\stock_basic_data_mins` | `获得股票分钟级数据.py` | 1min K 线 |
| `D:\database\index_data_daily` | `获得指数日频数据.py` | 默认 000001.SH / 399001.SZ |
| `D:\database\signal_daily` | 因子 notebook + `增量信号保存.py` | `factor=*/year=*/month=*/` |

## Shared partition layout (most daily scripts)

- Hive-style: `{base_dir}/year=YYYY/month=MM/{timestamp}_year_YYYY_month_MM.parquet`
- After run: rebuild `merged.parquet` per touched month; dedupe key **`htsc_code` + `time`** (keep last).
- Date column on disk: **`time`** (API `trading_day` mapped to day-truncated datetime).
- DuckDB read pattern: `read_parquet('{base}/year=*/month=*/merged.parquet', hive_partitioning=1, union_by_name=true)`

## Scripts (edit in place; preserve incremental + partition layout unless task says otherwise)

| Path | API / source | Purpose |
|------|----------------|---------|
| `获得股票日频数据.py` | `get_all_stocks_info` + batch daily K | All-market daily OHLCV → `stock_basic_data_daily`; exports universe CSV with pinyin. |
| `获得股票日频换手率.py` | `get_all_stocks_info` + `get_daily_basic` | Per-stock incremental daily basic (incl. turnover, volume, market val) → `stock_financial_statements/market_equity_data`. |
| `获得市值数据.py` | `get_all_stocks_info` + `get_stock_valuation` | Per-stock incremental valuation only → `stock_financial_statements/stock_valuation_data`. Saves: `htsc_code`, `exchange`, `time`, `pe`, `pettm`, `pb`, `pc`, `pcttm`, `ps`, `psttm`, `floating_market_val`, `total_market_val`. **Does not** save `avg_vol_per_deal`, `avg_value_per_deal`, price/name fields. |
| `获得股票日频复权因子.py` | `get_adj_factor` (xdy segments) | Segments → `adj_factor_segments.parquet`; optional `--emit-wide`. Respect `end_date` open segment vs `--adj-end`. |
| `获得股票分钟级数据.py` | `signal_daily` pool + `stock_basic_data_daily` years + `get_kline` | Serial 1 stock × 1 year; default `--max-year 2025`; → `stock_basic_data_mins`. |
| `获得指数日频数据.py` | `get_kline` (one index per call) | Default indices 000001.SH / 399001.SZ → `index_data_daily`. |
| `增量信号保存.py` | local `part_*.parquet` | Merge under `factor=*/year=*/month=*` → `merged.parquet`; dedupe `time + htsc_code`; **old value wins**. |
| `export_index_lists_from_doc.py` | INSIGHT index doc markdown | Export Shanghai/SZ/Shenwan L3 index lists to CSV (no live pull). |
| `各类数据检查.ipynb` | DuckDB | Sanity checks over daily / liquidity / index / signal / adj paths. |

## Downstream consumers (do not break paths silently)

- `ZXW因子/筹码结构因子.py` → reads turnover from `D:\database\stock_financial_statements\market_equity_data` (`DEFAULT_TURNOVER_BASE_DIR`).
- `ZXW因子/ZXW策略技术因子生成.ipynb` → `TURNOVER_BASE_PATH` same as above.
- Renaming `market_equity_data` or `stock_financial_statements/stock_valuation_data` requires grep repo + update notebook constants.

## Dependencies

- Python: `polars`, `pandas`, `duckdb` (daily scripts use duckdb for scan/merge).
- Live market: `insight_python` (华泰 Insight SDK).
- Optional: `pypinyin` (日频 universe export in `获得股票日频数据.py`).

## Constraints (unless user explicitly overrides)

- Do not replace “stock pool must come from API” in `获得股票日频数据.py` / `获得股票日频换手率.py` / `获得市值数据.py` without explicit user request.
- Minute script: stock pool from `signal_daily` (reference factor), years filtered by `stock_basic_data_daily` — do not revert to hard-coded CSV pool without user ask.
- Keep merge semantics in `增量信号保存.py` unless user asks to change priority/key.
- `market_equity_data` and `stock_financial_statements/stock_valuation_data` are **separate** stores under the same parent; overlapping columns (e.g. market cap) may exist in both until user consolidates.

## CLI templates (replace paths)

```powershell
$py = c:\Users\Administrator\Desktop\python_venv\.venv\Scripts\python.exe

& $py 工具/获得股票日频数据.py --base-dir D:\database\stock_basic_data_daily
& $py 工具/获得股票日频换手率.py --base-dir D:\database\stock_financial_statements\market_equity_data
& $py 工具/获得市值数据.py --base-dir D:\database\stock_financial_statements\stock_valuation_data
& $py 工具/获得股票日频复权因子.py --base-dir D:\database\stock_adj_daily
& $py 工具/获得股票分钟级数据.py --max-year 2025
& $py 工具/获得指数日频数据.py --base-dir D:\database\index_data_daily
& $py 工具/增量信号保存.py --base-dir D:\database\signal_daily --factor <FACTOR> --year <Y> --month <M>
```

Common flags (liquidity / valuation / daily OHLC): `--default-start 2010-01-01`, `--end` (default today), `--listing-state 上市交易`, `--sleep-sec`.

## Task routing

- Daily OHLCV / universe CSV / pinyin search → `获得股票日频数据.py`
- Daily basic / turnover / liquidity fields → `获得股票日频换手率.py`
- PE/PB/PS/market cap valuation only → `获得市值数据.py`
- Adj factors / wide table / date semantics → `获得股票日频复权因子.py`
- Minute range / signal pool / year cap → `获得股票分钟级数据.py`
- Index daily K → `获得指数日频数据.py`
- Factor part merge / paths → `增量信号保存.py`
- Read-only checks / SQL on parquet → `各类数据检查.ipynb`

## 可复制提示词（中文，粘贴给 Cursor / 其他助手）

把方括号里的内容换成你的具体需求即可。

**通用（先读再改）**

> 请先阅读 `工具/AGENTS.md` 和我要改的文件【路径】。只做最小必要修改，保持现有 argparse、分区目录结构和增量语义；不要改 Insight 登录流程除非我明确说。任务：【描述】。

**日频 OHLC `获得股票日频数据.py`**

> 打开 `工具/获得股票日频数据.py`。在「股票池仍只从 API 拉取」的前提下完成：【例如改 `--base-dir` 默认值、listing 日期区间、日 K 结束日、批大小、错误重试、universe 导出】。改完说明我该如何运行一条示例命令。

**流动性 / 日 basic `获得股票日频换手率.py`**

> 打开 `工具/获得股票日频换手率.py`。数据根目录默认 `D:\database\stock_financial_statements\market_equity_data`（旧名 `stock_liquidity_data` / `stock_temp_data`）。任务：【改字段、起始日、增量逻辑、merged 重建】。保持逐只 `get_daily_basic` 与 API 股票池。

**估值 `获得市值数据.py`**

> 打开 `工具/获得市值数据.py`。接口 `get_stock_valuation`，只保留估值列（见 AGENTS.md 表格），`trading_day` 存为 `time`，默认 `D:\database\stock_financial_statements\stock_valuation_data`。任务：【描述】。不要写入 `avg_vol_per_deal` / `avg_value_per_deal` 除非我明确要求。

**复权因子 `获得股票日频复权因子.py`**

> 打开 `工具/获得股票日频复权因子.py`。说明当前增量与「末段延长到 `--adj-end`」的行为，然后帮我：【例如单票 `--htsc-code`、全量 `--no-incremental`、开 `--emit-wide`、用 `--skip-universe` + CSV、改日期区间】。不要悄悄改合并键语义。

**分钟线 `获得股票分钟级数据.py`**

> 打开 `工具/获得股票分钟级数据.py`。股票池来自 `signal_daily`，年份来自 `stock_basic_data_daily`，串行 1 票×1 年，默认 `--max-year 2025`。任务：【改 `BASE_DIR`、结束年、请求间隔、merged 重建】。说明对本地 parquet 的影响。

**指数日频 `获得指数日频数据.py`**

> 打开 `工具/获得指数日频数据.py`。任务：【改默认指数列表、日期区间、`--base-dir`、增量逻辑】。

**因子合并 `增量信号保存.py`**

> 打开 `工具/增量信号保存.py`。我的因子根目录是【路径】，分区是 `factor=*/year=*/month=*`，需要处理【全部 | 指定 factor/year/month】。确认 `time + htsc_code` 合并时旧值优先是否符合预期；给出对应命令行；若需改合并规则请先列出影响再改。

**Notebook `各类数据检查.ipynb`**

> 打开 `工具/各类数据检查.ipynb`。在不大改单元结构下完成：【例如改 `BASE_PATH` / `TEMP_DATA_BASE_PATH`（liquidity）/ 加 DuckDB 检查、导出样本 CSV】。路径与对应写入脚本的分区一致。

**排错 / 运行失败**

> 我运行【脚本名 + 参数】时报错如下：【粘贴 traceback】。请结合 `工具/AGENTS.md` 里该脚本的职责与约束，定位是路径、登录、接口还是数据格式问题，给出最小修复或排查步骤。

## Output

- Prefer minimal diffs; match existing style and argparse patterns.
- Do not add secrets or commit `.env`; if unsure about data paths, state assumption in reply.
- After path renames under `D:\database\`, grep whole repo for old folder names before claiming done.
