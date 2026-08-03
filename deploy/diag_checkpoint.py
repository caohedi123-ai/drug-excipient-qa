# -*- coding: utf-8 -*-
"""诊断 langgraph checkpoint 建表问题"""
import psycopg

CONN = "postgresql://postgres:PharmaKB_2024_Secure_Pw@postgres:5432/pharma_kb"

DDL_TABLES = [
    (
        "checkpoints",
        """
        CREATE TABLE IF NOT EXISTS checkpoints (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            parent_checkpoint_id TEXT,
            type TEXT,
            checkpoint JSONB NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
        )
        """,
    ),
    (
        "checkpoint_blobs",
        """
        CREATE TABLE IF NOT EXISTS checkpoint_blobs (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            type TEXT NOT NULL,
            blob BYTEA,
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, type)
        )
        """,
    ),
    (
        "checkpoint_writes",
        """
        CREATE TABLE IF NOT EXISTS checkpoint_writes (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            idx INTEGER NOT NULL,
            channel TEXT NOT NULL,
            type TEXT,
            blob BYTEA,
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
        )
        """,
    ),
]

conn = psycopg.connect(CONN, autocommit=True)
for name, ddl in DDL_TABLES:
    try:
        conn.execute(ddl)
        print(f"OK  {name}")
    except Exception as e:
        print(f"ERR {name}: {e}")
conn.close()
print("DONE")
