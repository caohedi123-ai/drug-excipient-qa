# -*- coding: utf-8 -*-
"""在容器内手动执行 setup() 捕获完整异常"""
import traceback
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver

CONN = "postgresql://postgres:PharmaKB_2024_Secure_Pw@postgres:5432/pharma_kb"

try:
    pool = ConnectionPool(conninfo=CONN, max_size=5, open=True, timeout=15)
    saver = PostgresSaver(pool)
    print("PostgresSaver 创建成功")
    saver.setup()
    print("setup() 成功!")
    # 验证
    import psycopg
    conn = psycopg.connect(CONN, autocommit=True)
    cur = conn.cursor()
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
    print("表:", [r[0] for r in cur.fetchall()])
    conn.close()
except Exception:
    traceback.print_exc()
