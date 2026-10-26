# tests/test_cli.py
from interview_agent.__main__ import save_with_fallback

def test_save_with_fallback_swaps_to_sqlite():
    from interview_agent.store.db import connect, init_schema
    from interview_agent.session_store import SqliteSessionStore
    conn = connect(":memory:"); init_schema(conn)
    class Broken:
        def save(self, *a, **k): raise ConnectionError("redis died")
        def load(self, *a, **k): return None
        def touch(self, *a, **k): pass
    store = Broken()
    store = save_with_fallback(store, conn, "jvm", [{"role": "user", "content": "x"}])
    assert isinstance(store, SqliteSessionStore)          # Review Focus #3
    assert store.load("jvm") == [{"role": "user", "content": "x"}]

def test_save_with_fallback_returns_store_unchanged_on_success():
    from interview_agent.store.db import connect, init_schema
    from interview_agent.session_store import MemorySessionStore
    conn = connect(":memory:"); init_schema(conn)
    ok = MemorySessionStore()
    out = save_with_fallback(ok, conn, "t", [])
    assert out is ok and ok.load("t") == []
