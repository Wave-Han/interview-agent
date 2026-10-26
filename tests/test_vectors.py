# tests/test_vectors.py
import pytest

from interview_agent.store.db import connect, init_schema
from interview_agent.store.vectors import VectorRepo, encode, decode

def test_codec_roundtrip():
    v = [0.25, -1.5, 3.0]
    assert decode(encode(v), 3) == v          # float32 exact for these values
    v2 = [0.1, 0.2]
    assert decode(encode(v2), 2) == pytest.approx(v2, abs=1e-7)  # not float32-exact

def test_rebuild_idempotent_and_all():
    conn = connect(":memory:"); init_schema(conn)
    conn.execute("INSERT INTO questions VALUES (1,'jvm',2,'Q','[\"p\"]')"); conn.commit()
    repo = VectorRepo(conn)
    n = repo.rebuild([(1, [0.1, 0.2])])
    assert n == 1 and repo.count() == 1
    assert repo.rebuild([(1, [0.1, 0.2])]) == 1   # rerun: same rows
    assert repo.all()[0][0] == 1
    assert repo.all()[0][1] == pytest.approx([0.1, 0.2], abs=1e-7)
