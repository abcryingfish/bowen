# THS Sector Minute Chart Design

## Goal

Make every downloaded `.THS` sector searchable and viewable at `1min` in the existing quant chart page, with the same chart behavior as stocks. Keep daily THS data on the existing daily index path.

## Architecture

The market data service will classify `.THS` codes as index records but choose `D:\database\index_data_mins` for `1min` and `D:\database\index_data_daily` for `1day`. Minute partition discovery will include the index-minute root. Code search will include the THS universe for both intervals. The existing frontend interval selector and chart renderer will remain unchanged.

## Error handling and compatibility

Non-THS indexes remain daily-only unless their minute directory is explicitly populated. Stock and ETF routing is unchanged. Missing THS partitions use the existing market-data not-found response. All source files remain UTF-8 and API responses continue using the current JSON contract.

## Verification

Add regression tests for THS minute base-path selection, minute partition discovery, search visibility, and real Parquet query output. Run the focused tests, existing market-data tests, Python compilation, and a live API smoke query against one `.THS` code.
