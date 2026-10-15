# tests/test_db.py
import sqlite3
from interview_agent.store.db import connect, init_schema

def test_init_schema_creates_tables_idempotently():
    conn = connect(":memory:")
    init_schema(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"questions", "attempts", "wrong_notes"} <= tables
    init_schema(conn)  # idempotent
    assert True

def test_connect_sets_foreign_keys():
    conn = connect(":memory:")
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1
