# tests/test_questions.py
import json
from interview_agent.store.db import connect, init_schema
from interview_agent.store.questions import QuestionRepo

SEED = [
  {"id": 1, "topic": "jvm", "difficulty": 2, "question": "Q1",
   "answer_points": ["p1", "p2"]},
  {"id": 2, "topic": "mysql", "difficulty": 1, "question": "Q2",
   "answer_points": ["p1"]},
]

def make_repo(tmp_path):
    conn = connect(":memory:")
    init_schema(conn)
    seed = tmp_path / "s.json"
    seed.write_text(json.dumps(SEED, ensure_ascii=False), encoding="utf-8")
    repo = QuestionRepo(conn)
    repo.import_seed(str(seed))
    return repo, conn

def test_import_seed_skips_duplicates(tmp_path):
    repo, _ = make_repo(tmp_path)
    assert repo.import_seed(str(tmp_path / "s.json")) == 0  # second run: 0 new

def test_pick_unknown_topic_crosses_over(tmp_path):
    """Same-topic-first policy: an unknown topic is 'exhausted' immediately,
    so the picker crosses into other topics rather than returning None
    (the pool is never truly empty while any question remains)."""
    repo, _ = make_repo(tmp_path)
    got = repo.pick("nosuchtopic")
    assert got is not None and got.id in (1, 2)

def test_pick_same_topic_beats_global_wrong_note(tmp_path):
    """Core policy change: the selected topic's OWN questions win over
    another topic's wrong note; the wrong note only surfaces once this
    topic is exhausted."""
    repo, conn = make_repo(tmp_path)
    conn.execute("INSERT INTO wrong_notes(question_id, wrong_count, last_wrong_at)"
                 " VALUES (1, 1, datetime('now'))")
    assert repo.pick("mysql", wrong_only=False).id == 2   # mysql's own first
    # jvm still sees its wrong note first (same-topic wrong-first)
    assert repo.pick("jvm", wrong_only=False).id == 1
    # wrong_only on an in-topic-exhausted topic crosses topics
    assert repo.pick("mysql", wrong_only=True).id == 1

def test_pick_excludes_asked_with_fallback(tmp_path):
    """Wrong notes resurface LATER, not immediately (smoke-test finding)."""
    import json as _json
    conn = connect(":memory:")
    init_schema(conn)
    seed = [{"id": i, "topic": "jvm", "difficulty": 2, "question": f"Q{i}",
             "answer_points": ["p"]} for i in (1, 2, 3)]
    p = tmp_path / "s3.json"
    p.write_text(_json.dumps(seed), encoding="utf-8")
    repo = QuestionRepo(conn)
    repo.import_seed(str(p))
    conn.execute("INSERT INTO wrong_notes(question_id, wrong_count,"
                 " last_wrong_at) VALUES (1, 1, datetime('now'))")
    # exclude q1 (asked this session) -> another question comes out
    got = repo.pick("jvm", exclude_ids=[1])
    assert got.id != 1
    # wrong-first also respects exclusion: fall through (cross-topic none here)
    got = repo.pick("jvm", wrong_only=True, exclude_ids=[1])
    assert got is None
    # everything excluded -> exclusion ignored, q1 may resurface
    got = repo.pick("jvm", exclude_ids=[2, 3])
    assert got.id == 1
