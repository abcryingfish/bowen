# 因子分类目录

`factor_catalog.json` 用于记录前端因子分组、核心因子和展示顺序。因子列名或目录名变化时，需要同时检查 `ZXW因子/ZXW策略技术因子生成.py`、对应 bundle、`可视化/market_data_service.py` 及相关测试。

因子说明文档：`因子说明.md`。该文档是精选核心因子说明，不是 `factor_catalog.json` 的完整镜像。

当前目录只维护 Markdown 与 JSON，不再包含 Word 构建脚本。若以后恢复 `.docx` 产物，应单独提供生成脚本并在此记录可复现命令。
