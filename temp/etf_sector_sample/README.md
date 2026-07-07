# ETF 板块分类样例

生成时间：2026-07-07 09:29:54

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
