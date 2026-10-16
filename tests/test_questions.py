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

def test_pick_unknown_topic_returns_none(tmp_path):
    repo, _ = make_repo(tmp_path)
    assert repo.pick("nosuchtopic") is None      # Review Focus #1

def test_pick_prefers_wrong_notes(tmp_path):
    repo, conn = make_repo(tmp_path)
    # mark q1 as unmastered wrong note, most recent
    conn.execute("INSERT INTO wrong_notes(question_id, wrong_count, last_wrong_at)"
                 " VALUES (1, 1, datetime('now'))")
    assert repo.pick("mysql", wrong_only=False).id == 1  # wrong note wins over mysql's own

def test_pick_excludes_asked_with_fallback(tmp_path):
    """Wrong notes resurface LATER, not immediately (smoke-test finding)."""
    import json as _json
    from interview_agent.store.db import connect, init_schema
    from interview_agent.store.questions import QuestionRepo
    conn = connect(":memory:")
    init_schema(conn)
    seed = [{"id": i, "topic": "jvm", "difficulty": 2, "question": f"Q{i}",
             "answer_points": ["p"]} for i in (1, 2, 3)]
    p = tmp_path / "s3.json"
    p.write_text(_json.dumps(seed), encoding="utf-8")
    repo = QuestionRepo(conn)
    repo.import_seed(str(p))
    # q1 becomes an unmastered wrong note (just answered wrong)
    conn.execute("INSERT INTO wrong_notes(question_id, wrong_count,"
                 " last_wrong_at) VALUES (1, 1, datetime('now'))")
    # exclude q1 (asked this session) -> another question comes out
    got = repo.pick("jvm", exclude_ids=[1])
    assert got.id != 1
    # wrong-first also respects exclusion: fall through to topic order
    got = repo.pick("jvm", wrong_only=True, exclude_ids=[1])
    assert got is None
    # everything excluded -> exclusion ignored, q1 may resurface
    got = repo.pick("jvm", exclude_ids=[2, 3])
    assert got.id == 1
