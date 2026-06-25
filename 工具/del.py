from xtquant import xtdata

xtdata.download_sector_data()
print(xtdata.get_stock_list_in_sector("沪深A股")[:5])