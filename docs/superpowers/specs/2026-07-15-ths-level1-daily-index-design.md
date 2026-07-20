# 同花顺一级指数日线设计

## 范围

仅获取同花顺客户端“软件一级”512个指数的日线 OHLCV，不获取分钟数据，不保存成分股快照，不修改 ZXW 因子逻辑。

## 指数集合

名称表来自 `D:\同花顺\同花顺\stockname\stockname_48_0.txt`，GB18030 解码。纳入前缀为 `881`、`882`、`885`、`886`，数量必须分别为 90、33、293、96，合计512。输出代码使用 `<六位代码>.THS`。

## 行情来源与字段

同花顺年度接口：`https://d.10jqka.com.cn/v6/line/48_<代码>/01/<年份>.js`。记录顺序为日期、开盘、最高、最低、收盘、成交量、成交额。标准化为现有 `index_data_daily` 的12列：`htsc_code,time,exchange,security_type,security_id,frequency,open,close,high,low,volume,value`。

## 保存

目标为 `D:\database\index_data_daily\year=YYYY\month=MM\merged.parquet`，Parquet ZSTD。主键为 `htsc_code + time`。新批次先写临时分区文件，再与旧 merged 合并；同键新值覆盖旧值，使用临时 merged 原子替换，成功后删除临时分区文件。

## 增量

无本地数据的代码从 `--default-start`（默认 `2010-01-01`）开始。已有数据的代码从本地最大日期当天重拉，以修正最后一天，再补到截止日。网络请求按涉及年份发送，返回后按实际起止日过滤。中间历史缺口由 `--audit-gaps` 检查报告，本次不自动全历史重拉。

## 截止时间

默认以 Asia/Shanghai 本地时间判断。交易日15:30及以后允许截止到当天；15:30以前截止到前一工作日。接口未返回目标日期时不制造空行，下次运行自动补齐。显式 `--end YYYY-MM-DD` 用于测试和补数，不受15:30限制。

## 集成

新增 `工具/获得同花顺1级指数日频数据.py`。在 `工具/全量数据更新_合并入口.py` 的普通指数阶段后增加 `ths_level1_index_daily` 阶段，并提供 `--ths-level1-index-daily-args` 透传参数。

## 验证

自动测试覆盖512口径、年度JSONP解析、15:30边界、最后一天重叠增量、新值覆盖合并和合并入口 dry-run。独立实跑后核对代码数、日期、主键重复、OHLC关系和中文名称源。随后只清理 `htsc_code LIKE '%.THS'` 的本次数据，保留原有指数，再从合并入口完整运行。
