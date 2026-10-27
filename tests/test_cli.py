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

def test_save_with_fallback_double_failure_prints_not_raises(capsys):
    from interview_agent.store.db import connect, init_schema
    from interview_agent.session_store import MemorySessionStore
    from interview_agent import __main__ as m
    conn = connect(":memory:"); init_schema(conn)
    class BrokenRedis:
        def save(self, *a, **k): raise ConnectionError("redis died")
        def load(self, *a, **k): return None
        def touch(self, *a, **k): pass
    class BrokenSqlite:
        def save(self, *a, **k): raise RuntimeError("sqlite also died")
        def load(self, *a, **k): return None
        def touch(self, *a, **k): pass
    import unittest.mock as mock
    with mock.patch.object(m, "SqliteSessionStore", return_value=BrokenSqlite()):
        store = m.save_with_fallback(BrokenRedis(), conn, "t", [])
    out = capsys.readouterr().out
    assert "本地保存也失败" in out            # graceful, not a raise

def test_rebuild_asked_extracts_rubric_ids():
    from interview_agent.__main__ import rebuild_asked
    msgs = [
        {"role": "user", "content": "question_id: 7\nQuestion: Q7\npoints"},
        {"role": "user", "content": "question_id: 8\nQuestion: Q8\npoints"},
        {"role": "assistant", "content": "点评:答得不错(无 id 行)"},
    ]
    assert rebuild_asked(msgs) == {7, 8}
