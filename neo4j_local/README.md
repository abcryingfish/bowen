# 项目内 Neo4j 本地实例

这个目录是从本机 Neo4j Desktop 附带的 Neo4j Enterprise 运行时和
`LLMproject_test\.venv` 复制出的独立实例，服务端数据不会写入源项目。

## 启动

在 PowerShell 中执行：

```powershell
cd C:\Users\Administrator\Desktop\python_venv\neo4j_local
.\start_neo4j.ps1
```

本机 Desktop 附带的是 Enterprise 运行时。若你确认接受 Neo4j 评估许可，首次启动使用：

```powershell
.\start_neo4j.ps1 -AcceptEvaluationLicense
```

脚本不会替你自动接受许可协议。

默认账号为 `neo4j`，默认本地开发密码为 `password123`。建议首次登录后立即修改密码，或先设置环境变量：

```powershell
$env:NEO4J_PASSWORD = "你的密码"
.\start_neo4j.ps1
```

启动后：

- Neo4j Browser：<http://127.0.0.1:7474>
- Bolt：`bolt://127.0.0.1:7687`
- 默认数据库：`neo4j`

## 停止和状态

```powershell
.\stop_neo4j.ps1
.\status_neo4j.ps1
```

## Python 驱动

复制的环境位于 `neo4j_local\.venv`，版本为 `neo4j 5.28.4`：

```powershell
.\.venv\Scripts\python.exe .\verify_neo4j.py
```

## 导入黄金概念客观图谱

黄金板块的客观 staging 数据位于 `D:\database\sector_information\_staging\gold_885530_20260821`。
Neo4j 已导入板块、81 只成分股、带快照范围的 `MEMBER_OF`、近五年日频行情观察和涨跌窗口：

```powershell
.\import_gold_graph.ps1
```

如需先检查文件和行数但不写库：

```powershell
.\import_gold_graph.ps1 -DryRun
```

本次 staging 的语义研究状态是 `research_blocked`、证据数为 0，
因此脚本不会虚构 `Event`、`Evidence` 或 `IMPACTS` 原因关系；后续补齐证据后可增量导入。

Browser 查看语句保存在 `gold_graph_queries.cypher`。首次打开建议执行：

```cypher
MATCH p=(stock:Stock)-[:MEMBER_OF]->(sector:Sector {sector_name: '黄金概念'})
RETURN p
LIMIT 100;
```

前端不要直接连接 Bolt。正确链路是：`前端 -> 可视化/api_server.py -> neo4j Python driver -> Neo4j`。

## 数据目录

- `data`：数据库文件
- `logs`：服务日志
- `import`：`LOAD CSV` 等导入文件
- `backups`：备份和事务日志输出
- `server`：只读运行时副本

不要把 `data`、`logs` 或密码文件提交到 Git。该实例仅绑定 `127.0.0.1`。
