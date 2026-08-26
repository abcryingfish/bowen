#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Read-only connectivity check for the project-local Neo4j instance."""
from __future__ import annotations

import os
import sys

from neo4j import GraphDatabase


URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")


def _configure_utf8_output() -> None:
    """让 Windows PowerShell 下的中文诊断输出保持 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _configure_utf8_output()
    print(f"连接：{URI}")
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    try:
        driver.verify_connectivity()
        with driver.session(database=DATABASE) as session:
            # db.name() 在 Neo4j 2026 已不再是可用的 Cypher 函数；
            # 数据库名称已由 session 明确指定，因此只需验证查询即可。
            record = session.run("RETURN 1 AS ok").single()
        print(f"连接成功：ok={record['ok']} database={DATABASE}")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
