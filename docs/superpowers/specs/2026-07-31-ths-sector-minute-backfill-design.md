# 同花顺板块分钟全量回溯设计

## 目标

新增独立脚本 `工具/获得同花顺板块分钟级数据.py`，从同花顺行情接口获取客户端当前可识别的全部 THS 软件一级板块 1 分钟 K 线。请求起点统一为 `2010-01-01`，接口没有有效数据的时段不落盘；最终数据写入 `D:\database\index_data_mins`，格式与现有股票分钟仓兼容，并支持以后按同一脚本做增量更新和新增板块历史回补。

本次不修改股票分钟数据业务逻辑，不使用 xtquant 获取 THS 数据，不使用 SQLite，也不把全量数据写入 Git 仓库。

## 数据源与边界

- 行情接口：同花顺网页客户端 `single_kline`，周期 `min_1`，市场 `48`。
- 一次请求只处理一个 THS 代码；多代码请求已验证返回空。
- 服务端存在单请求行数上限，年度请求会截断；正式回溯按自然月切窗，避免静默缺行。
- 每个代码从 `2010-01-01` 开始探测。某月无数据记录为已完成空窗口，不写行情行。
- 当天未收盘时，全量任务默认只写最近一个完整交易日；显式参数可允许抓取当前未完成交易日。
- 认证优先读取 CLI 参数或 `THS_FUYAO_AUTH` 环境变量，并保留当前网页公开认证值作为兼容后备；认证失败必须终止并明确报错，不能把空响应当作无历史。

## 标的发现与新增板块

每次运行读取 `D:\同花顺\同花顺\stockname\stockname_48_0.txt`，使用 `gb18030` 解码，收集六位代码且前缀为 `881/882/885/886` 的板块。当前快照为 512 个，但不再把 512 或各前缀数量作为硬性断言。

当前列表与 `D:\database\index_data_mins\_meta\ths_level1_universe.parquet` 比较：

- 新增代码：加入当前任务，并从 2010 年开始寻找全部有效分钟历史。
- 名称变化：更新元数据，历史行情代码不变。
- 消失代码：保留已落盘历史，在元数据中标记 `is_active=false`，默认不再请求。
- 重复代码、非法代码或空名称：作为数据源异常终止，不静默忽略。

元数据至少包含 `htsc_code/name/pinyin_initials/security_type/security_id/exchange/is_active/first_seen_at/last_seen_at`。

## Parquet 结构

沿用股票分钟仓的日分区：

```text
D:\database\index_data_mins
  year=YYYY\month=MM\day=DD\merged.parquet
  _meta\ths_level1_universe.parquet
  _meta\ths_minute_download_state.parquet
  _meta\failed_ths_minute_requests_*.txt
```

行情列顺序和类型：

| 列 | 类型 | 规则 |
|---|---|---|
| `htsc_code` | String | 六位代码加 `.THS` |
| `time` | Datetime(us) | 上海时区解释后存无时区分钟值 |
| `close/open/high/low` | Float64 | 价格必填 |
| `volume/amount` | Float64 | 源接口缺失时保留 null，不填 0 |
| `date` | String | 统一 `YYYY-MM-DD` |
| `pre_close` | Float32 | 同一代码上一分钟 close，跨请求窗口连续 |
| `change` | Float32 | `close - pre_close` |
| `pct_chg` | Float32 | `change / pre_close * 100`，分母为 0 时 null |
| `__index_level_0__` | Int64 | 同一代码按时间从 0 递增的兼容序号 |

主键为 `(htsc_code, time)`，合并冲突保留最后一次下载值。写入采用 Zstandard 压缩、临时文件加原子替换。分区目录最终只保留 `merged.parquet`；中间 `part_*.parquet` 在合并成功后删除。

## 下载与断点续跑

任务按月份推进，每个月对当前有效代码做有限并发请求。每批结果转换后先写日分区临时 part 文件，月度完成或程序退出前重建受影响日期的 `merged.parquet`。

`ths_minute_download_state.parquet` 记录 `(htsc_code, year_month, status, row_count, first_time, last_time, updated_at, error)`：

- `success`：窗口有数据并已写入。
- `empty`：接口明确成功但窗口无数据。
- `failed`：超时、认证、结构异常或校验失败，后续运行必须重试。

状态文件批量原子更新，不承担行情存储。重启后跳过 `success/empty` 窗口，仅执行缺失和失败窗口；这样无须 SQLite，也不会反复请求 2010 年以来的空月份。

## 连续指标处理

接口原始 OHLCV 先落成标准行，再按代码和时间排序计算衍生列。每个代码月初第一条需要读取本地该代码在窗口开始前最后一条 close 作为 `pre_close`；如果不存在，只有该代码历史第一条的三个衍生值允许为空。

重叠重跑后，对受影响代码从重叠起点重新计算，避免更新某分钟 close 后后续 `pre_close/change/pct_chg` 失去连续性。

## 校验与失败策略

- 响应状态、代码、字段映射与时间范围必须正确；认证失败和响应结构变化直接失败。
- `time` 必须严格位于请求窗口并按分钟去重。
- `high >= max(open, close)`、`low <= min(open, close)`、`high >= low`。
- 非空的 `volume/amount` 必须非负。
- 每日常见 241 或 242 条只作告警，不作为硬失败条件；停牌、历史口径和当日未完成均可能不同。
- 写入后抽查 Parquet schema、唯一键、首尾时间、代码覆盖率和状态表一致性。
- 单窗口指数退避重试；最终失败写 UTF-8 BOM 文本清单并返回非零退出码。

## CLI 与入口

首版提供：`--base-dir`、`--default-start`、`--end`、`--codes`、`--workers`、`--timeout`、`--retries`、`--auth-token`、`--include-current-day`、`--dry-run`、`--rebuild-only`。

脚本完成独立验证后，在 `全量数据更新_合并入口.py` 增加单独阶段 `ths_index_mins`，不替换现有 `stock_mins`。全量首次运行可用 `--codes` 小范围试跑，再对完整动态标的表执行。

## 测试与验收

实现按测试驱动进行：先覆盖月窗口、客户端标的解析和差异、响应解析、空窗口与失败区分、跨窗口衍生列、日分区幂等合并、状态恢复。随后用两个代码和一个历史月份写入临时目录做接口烟雾测试，确认 schema 与股票分钟仓一致后，才启动 `D:\database\index_data_mins` 全量任务。

全量启动前必须满足：单元测试通过、烟雾测试无重复键、Parquet 列名和类型完全一致、失败窗口可重试、新增代码会从 2010 年回补、现有代码重启不会重复请求已完成窗口。
