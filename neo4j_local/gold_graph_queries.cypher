// 1. 先看黄金概念板块及其 81 只成分股（推荐首次使用）
MATCH p=(stock:Stock)-[:MEMBER_OF]->(sector:Sector {sector_name: '黄金概念'})
RETURN p
ORDER BY stock.stock_code
LIMIT 100;

// 2. 看板块、涨跌窗口和成分股的总览
MATCH p=(sector:Sector {sector_name: '黄金概念'})-[r:HAS_MOVE_WINDOW]->(move:MoveWindow)
RETURN p
ORDER BY move.direction, move.window_days, move.rank
LIMIT 80;

// 3. 看黄金概念近五年行情观察（节点较多，建议 LIMIT）
MATCH p=(sector:Sector {sector_name: '黄金概念'})-[:HAS_MARKET_OBSERVATION]->(observation:MarketObservation)
RETURN p
ORDER BY observation.observed_at
LIMIT 200;

// 4. 查一个成分股的全部客观属性
MATCH (stock:Stock {stock_code: '600547.SH'})
RETURN stock;

// 5. 查看当前图谱的标签、关系类型和数量
CALL db.schema.visualization();

// 6. 查看研究状态；research_blocked 表示尚未导入语义原因证据
MATCH (sector:Sector {sector_name: '黄金概念'})
RETURN sector.sector_name AS sector,
       sector.research_status AS research_status,
       sector.evidence_count AS evidence_count,
       sector.objective_data_completed AS objective_data_completed,
       sector.semantic_research_completed AS semantic_research_completed;
