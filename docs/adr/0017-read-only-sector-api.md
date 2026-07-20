---
status: accepted
date: 2026-07-16
---

# 统一HTML通过现有本地服务的只读板块API访问数据

固定板块研究HTML不直接读取Parquet，而是在现有`127.0.0.1:8000` API服务中新增只读`/api/sector/*`路由，由DuckDB/Polars查询`D:\database\sector_information`及现有行情库。第一版不提供网页运行、重试、删除或修改接口，批量研究继续由Python命令显式触发。

## Consequences

- 底层Parquet字段和分区可以演进，只要API契约保持兼容。
- 网页误触不会启动512板块研究或与写入任务并发。
- 每个响应明确返回数据日期、运行批次、是否沿用旧结果和模式版本。
- 大历史表使用日期裁剪和游标分页，不把全量数据一次发送到浏览器。
