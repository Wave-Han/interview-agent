# tests/test_session_store.py
import json
from unittest.mock import MagicMock
from interview_agent.store.db import connect, init_schema
from interview_agent.session_store import (MemorySessionStore, SqliteSessionStore,
                                           RedisSessionStore, make_session_store)
from interview_agent.config import Config

MSGS = [{"role": "user", "content": "hi"}]

def test_protocol_memory():
    s = MemorySessionStore(); s.save("t", MSGS)
    assert s.load("t") == MSGS and s.load("nope") is None; s.touch("t")

def test_protocol_sqlite():
    conn = connect(":memory:"); init_schema(conn)
    s = SqliteSessionStore(conn); s.save("t", MSGS)
    assert s.load("t") == MSGS and s.load("nope") is None; s.touch("t")

def test_protocol_redis_stub():
    r = MagicMock()
    s = RedisSessionStore(r); s.save("t", MSGS)
    key = r.set.call_args[0][0]
    assert key == "ia:session:t" and json.loads(r.set.call_args[0][1]) == MSGS
    r.get.return_value = json.dumps(MSGS); assert s.load("t") == MSGS
    r.get.return_value = None; assert s.load("x") is None
    s.touch("t"); r.expire.assert_called_once()

def test_factory_falls_back_when_ping_fails(monkeypatch):
    import interview_agent.session_store as ss
    conn = connect(":memory:"); init_schema(conn)
    monkeypatch.setattr(ss.redis, "Redis",
                        MagicMock(from_url=MagicMock(
                            side_effect=Exception("no redis"))))
    cfg = Config("u", "k", "m", ":memory:", redis_url="redis://x", embedding_model="e")
    store, backend = make_session_store(cfg, conn)
    assert backend == "sqlite" and isinstance(store, SqliteSessionStore)

def test_sqlite_expires_old_sessions():
    conn = connect(":memory:"); init_schema(conn)
    conn.execute("INSERT INTO sessions VALUES ('old','[]', datetime('now','-8 days'))")
    conn.commit()
    SqliteSessionStore(conn)                      # constructor purges
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
