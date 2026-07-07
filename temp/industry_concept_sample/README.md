# 行业概念数据样例

生成时间：2026-07-06 22:59:42

来源接口：

- `xtdata.download_sector_data()`：下载/刷新本地行业板块数据。
- `xtdata.get_sector_list()`：返回所有可用板块名称，本次共 `7095` 个。
- `xtdata.get_stock_list_in_sector(sector_name)`：按板块名返回成分股代码列表。

注意：这些接口没有开始日期/结束日期参数，返回的是当前本地板块分类快照，不是日频历史成分数据；所以这里不能真实导出“最近几天每天一份”的历史变化，只能按 `snapshot_time` 保存当前快照。

文件说明：

- `sector_list_all.csv` / `sector_list_all.json`：全量板块/行业/概念名称清单。
- `sample_sector_summary.csv`：抽样板块的成分股数量和市场分布。
- `sample_sector_constituents.csv` / `.json`：抽样板块成分股明细。
- `metadata.json`：接口、生成时间、样例范围说明。

CSV 使用 `utf-8-sig`，方便 Excel 直接打开中文。
