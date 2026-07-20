from pathlib import Path
import duckdb

paths = [
    Path(r"D:\database\qmt_company_data\table=factor_fundamental_valuation\year=*/month=*/merged.parquet"),
    Path(r"D:\database\qmt_turnover_data\year=*/month=*/merged.parquet"),
]
for path in paths:
    print(path)
    rel = duckdb.sql("select * from read_parquet(?, hive_partitioning=true, union_by_name=true) limit 1", params=[str(path)])
    print(rel.columns)
    print(rel.df().to_string(index=False))
