# interview_agent/session_store.py
# Pluggable conversation-session persistence: Protocol + Memory/SQLite/Redis
# implementations + a factory that probes Redis and degrades to SQLite.
import json
from typing import Protocol

# redis is an optional dependency (not on the whitelist): importing it must
# never crash environments without the package. The factory treats a missing
# package exactly like an unreachable server and falls back to SQLite.
try:
    import redis
except ImportError:  # pragma: no cover - depends on environment
    redis = None

class SessionStore(Protocol):
    """Persistence contract for one conversation's message history."""

    def save(self, session_id: str, messages: list[dict]) -> None: ...
    def load(self, session_id: str) -> list[dict] | None: ...
    def touch(self, session_id: str) -> None: ...


class MemorySessionStore:
    """Process-lifetime dict store; sessions vanish on exit. Test/dev only."""

    def __init__(self) -> None:
        self._data: dict[str, list[dict]] = {}

    def save(self, session_id: str, messages: list[dict]) -> None:
        self._data[session_id] = [dict(m) for m in messages]

    def load(self, session_id: str) -> list[dict] | None:
        msgs = self._data.get(session_id)
        return [dict(m) for m in msgs] if msgs is not None else None

    def touch(self, session_id: str) -> None:
        pass  # no timestamps to refresh


class SqliteSessionStore:
    """Store backed by the sessions table (Task 2 schema)."""

    def __init__(self, conn) -> None:
        self.conn = conn
        # Opportunistic purge: drop sessions idle for over 7 days (cheap GC,
        # no cron needed).
        self.conn.execute(
            "DELETE FROM sessions WHERE updated_at <"
            " datetime('now', '-7 days')")
        self.conn.commit()

    def save(self, session_id: str, messages: list[dict]) -> None:
        self.conn.execute(
            "INSERT INTO sessions (id, messages, updated_at)"
            " VALUES (?, ?, datetime('now'))"
            " ON CONFLICT(id) DO UPDATE SET messages = excluded.messages,"
            " updated_at = excluded.updated_at",
            (session_id, json.dumps(messages, ensure_ascii=False)))
        self.conn.commit()

    def load(self, session_id: str) -> list[dict] | None:
        row = self.conn.execute(
            "SELECT messages FROM sessions WHERE id = ?",
            (session_id,)).fetchone()
        return json.loads(row[0]) if row is not None else None

    def touch(self, session_id: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET updated_at = datetime('now') WHERE id = ?",
            (session_id,))
        self.conn.commit()


class RedisSessionStore:
    """Store backed by Redis string keys with a TTL."""

    def __init__(self, client, ttl: int = 86400) -> None:
        self.client = client
        self.ttl = ttl

    def _key(self, session_id: str) -> str:
        return f"ia:session:{session_id}"

    def save(self, session_id: str, messages: list[dict]) -> None:
        # SET with ex: every write re-arms the TTL, so touch is implicit;
        # key and payload stay positional (mirrors redis-py signature).
        self.client.set(self._key(session_id),
                        json.dumps(messages, ensure_ascii=False), ex=self.ttl)

    def load(self, session_id: str) -> list[dict] | None:
        raw = self.client.get(self._key(session_id))
        return json.loads(raw) if raw is not None else None

    def touch(self, session_id: str) -> None:
        self.client.expire(self._key(session_id), self.ttl)


def make_session_store(cfg, conn) -> tuple[SessionStore, str]:
    """Choose a backend: Redis when configured AND reachable, else SQLite.

    Truthiness (not `is not None`) decides "configured": the env var may be
    present but blank, and an empty string must never reach from_url.
    Returns (store, backend_name) so callers can surface which one won.
    """
    if not cfg.redis_url:
        return SqliteSessionStore(conn), "sqlite"
    if redis is None:  # package absent: same degradation as ping failure
        print("Redis 不可用,会话将存 SQLite")
        return SqliteSessionStore(conn), "sqlite"
    try:
        client = redis.Redis.from_url(cfg.redis_url, socket_timeout=0.5)
        client.ping()
        return RedisSessionStore(client), "redis"
    except Exception:
        print("Redis 不可用,会话将存 SQLite")
        return SqliteSessionStore(conn), "sqlite"
