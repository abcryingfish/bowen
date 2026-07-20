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
| `D:\database\qmt_turnover_data` | `获得股票日频换手率.py` | QMT 日 K `volume` + `qmt_company_data/table=Capital` 的 `circulating_capital` 计算换手率 |
| `D:\database\qmt_company_data\table=factor_fundamental_valuation` | `获得市值数据.py` | `get_stock_valuation` 估值字段；与 market_equity 同属财报父目录 |
| `D:\database\stock_adj_daily_raw` | `qmt获得股票日频复权因子.py` | QMT 原始除权除息事件，按 `event_date` 年月分区 |
| `D:\database\stock_adj_daily` | `qmt获得股票日频复权因子.py` | 处理后的复权分段 `adj_factor_segments.parquet` + 每日展开宽表 `wide_xdy` |
| `D:\database\stock_basic_data_mins` | `获得股票分钟级数据.py` | 1min K 线 |
| `D:\database\index_data_daily` | `获得指数日频数据.py` | 默认 000001.SH / 399001.SZ |
| `D:\database\index_data_daily` | `获得同花顺1级指数日频数据.py` | 同花顺软件一级512指数，代码后缀 `.THS`，15:30后允许写当天 |
| `D:\database\signal_daily` | 因子 notebook + `增量信号保存.py` | `factor=*/year=*/month=*/` |

## Shared partition layout (most daily scripts)

- Hive-style: `{base_dir}/year=YYYY/month=MM/{timestamp}_year_YYYY_month_MM.parquet`
- After run: rebuild `merged.parquet` per touched month; dedupe key **`htsc_code` + `time`** (keep last).
- Date column on disk: **`time`** (API `trading_day` mapped to day-truncated datetime).
- DuckDB read pattern: `read_parquet('{base}/year=*/month=*/merged.parquet', hive_partitioning=1, union_by_name=true)`

## QMT 复权数据三层结构

`qmt获得股票日频复权因子.py` 维护三层数据，默认起点为 `2010-01-01`：

| 层级 | 路径 | 作用 |
|------|------|------|
| raw 原始事件 | `D:\database\stock_adj_daily_raw\year=YYYY\month=MM\merged.parquet` | 保存 QMT `get_divid_factors` 原始除权除息事件，如 `event_date`、`interest`、`stockBonus`、`stockGift`、`allotNum`、`allotPrice`、`dr` |
| segments 分段 | `D:\database\stock_adj_daily\adj_factor_segments.parquet` | 将 raw 事件转换为 `htsc_code + begin_date + end_date + xdy` 连续区间 |
| wide_xdy 每日展开 | `D:\database\stock_adj_daily\wide_xdy\year=YYYY\month=MM\merged.parquet` | 将 segments 展开为按月宽表，列为日期，供 `ZXW因子/ZXW策略技术因子生成.py` 快速读取并做比例后复权 |

加工链路：`raw` → `adj_factor_segments.parquet` → `wide_xdy`。  
删除或改复权起点时要三层同步：只删 `wide_xdy/year<YYYY` 不够，`adj_factor_segments.parquet` 里早期分段仍可能在重建时重新展开到后续日期；如果要彻底改变起点，应先过滤 raw/segments，再重建 `wide_xdy`。

当前本地口径已按 `2010-01-01` 起点处理：raw 与 `wide_xdy` 最小年份为 2010，segments 中 `begin_date < 2010-01-01` 的行应为 0。正常增量运行不会补回 2010 年前数据；只有手动传入类似 `--no-incremental --default-start 2004-01-01` 才会重新请求早期事件。

## Scripts (edit in place; preserve incremental + partition layout unless task says otherwise)

| Path | API / source | Purpose |
|------|----------------|---------|
| `获得股票日频数据.py` | `get_all_stocks_info` + batch daily K | All-market daily OHLCV → `stock_basic_data_daily`; exports universe CSV with pinyin. |
| `获得股票日频换手率.py` | local QMT daily K + Capital | 本地计算 `turnover_rate = volume / circulating_capital * 100` → `qmt_turnover_data`. |
| `qmt公司数据获取.py` | QMT company data + daily close | Per-stock incremental valuation only → `qmt_company_data/table=factor_fundamental_valuation`. Saves: `htsc_code`, `exchange`, `time`, `pe`, `pettm`, `pb`, `pc`, `pcttm`, `ps`, `psttm`, `floating_market_val`, `total_market_val`. **Does not** save `avg_vol_per_deal`, `avg_value_per_deal`, price/name fields. |
| `qmt获得股票日频复权因子.py` | QMT `get_divid_factors` | Raw events → `stock_adj_daily_raw`; segments → `stock_adj_daily\adj_factor_segments.parquet`; daily wide table → `stock_adj_daily\wide_xdy`. |
| `获得股票分钟级数据.py` | `signal_daily` pool + `stock_basic_data_daily` years + `get_kline` | Serial 1 stock × 1 year; default `--max-year 2025`; → `stock_basic_data_mins`. |
| `获得指数日频数据.py` | `get_kline` (one index per call) | Default indices 000001.SH / 399001.SZ → `index_data_daily`. |
| `获得同花顺1级指数日频数据.py` | 同花顺年度日线接口 + 客户端名称表 | 软件一级512指数 → `index_data_daily`；前缀881/882/885/886；按每只本地末日重叠增量。 |
| `增量信号保存.py` | local `part_*.parquet` | Merge under `factor=*/year=*/month=*` → `merged.parquet`; dedupe `time + htsc_code`; **old value wins**. |
| `export_index_lists_from_doc.py` | INSIGHT index doc markdown | Export Shanghai/SZ/Shenwan L3 index lists to CSV (no live pull). |
| `各类数据检查.ipynb` | DuckDB | Sanity checks over daily / liquidity / index / signal / adj paths. |

## Downstream consumers (do not break paths silently)

- `ZXW因子/筹码结构因子.py` → reads turnover from `D:\database\qmt_turnover_data` (`DEFAULT_TURNOVER_BASE_DIR`).
- `ZXW因子/ZXW策略技术因子生成.ipynb` → `TURNOVER_BASE_PATH` same as above.
- Renaming `qmt_turnover_data` or `qmt_company_data/table=factor_fundamental_valuation` requires grep repo + update notebook constants.

## Dependencies

- Python: `polars`, `pandas`, `duckdb` (daily scripts use duckdb for scan/merge).
- Live market: `insight_python` (华泰 Insight SDK).
- Optional: `pypinyin` (日频 universe export in `获得股票日频数据.py`).

## Constraints (unless user explicitly overrides)

- Do not replace “stock pool must come from API” in `获得股票日频数据.py` / `获得股票日频换手率.py` / `获得市值数据.py` without explicit user request.
- Minute script: stock pool from `signal_daily` (reference factor), years filtered by `stock_basic_data_daily` — do not revert to hard-coded CSV pool without user ask.
- Keep merge semantics in `增量信号保存.py` unless user asks to change priority/key.
- `qmt_turnover_data` and `qmt_company_data/table=factor_fundamental_valuation` are separate QMT-derived stores; overlapping columns (e.g. market cap) may exist in both until user consolidates.

## CLI templates (replace paths)

```powershell
$py = c:\Users\Administrator\Desktop\python_venv\.venv\Scripts\python.exe

& $py 工具/获得股票日频数据.py --base-dir D:\database\stock_basic_data_daily
& $py 工具/获得股票日频换手率.py --base-dir D:\database\qmt_turnover_data
& $py 工具/获得市值数据.py --base-dir D:\database\qmt_company_data\table=factor_fundamental_valuation
& $py 工具/获得股票日频复权因子.py --base-dir D:\database\stock_adj_daily
& $py 工具/获得股票分钟级数据.py --max-year 2025
& $py 工具/获得指数日频数据.py --base-dir D:\database\index_data_daily
& $py 工具/获得同花顺1级指数日频数据.py --base-dir D:\database\index_data_daily
& $py 工具/增量信号保存.py --base-dir D:\database\signal_daily --factor <FACTOR> --year <Y> --month <M>
```

Common flags (liquidity / valuation / daily OHLC): `--default-start 2010-01-01`, `--end` (default today), `--listing-state 上市交易`, `--sleep-sec`.

## Task routing

- Daily OHLCV / universe CSV / pinyin search → `获得股票日频数据.py`
- QMT turnover fields → `获得股票日频换手率.py`
- QMT PE/PB/ROE/revenue/market cap valuation → `获得市值数据.py`
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

**QMT 换手率 `获得股票日频换手率.py`**

> 打开 `工具/获得股票日频换手率.py`。数据根目录默认 `D:\database\qmt_turnover_data`。换手率由本地 `stock_basic_data_daily.volume` 与 `qmt_company_data/table=Capital.circulating_capital` 计算得到。任务：【改字段、起始日、merged 重建】。不要再恢复 Insight `get_daily_basic` 逻辑。

**估值 `获得市值数据.py`**

> 打开 `工具/获得市值数据.py`。接口 `get_stock_valuation`，只保留估值列（见 AGENTS.md 表格），`trading_day` 存为 `time`，默认 `D:\database\qmt_company_data\table=factor_fundamental_valuation`。任务：【描述】。不要写入 `avg_vol_per_deal` / `avg_value_per_deal` 除非我明确要求。

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
