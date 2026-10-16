# tests/test_attempts.py
import json
from interview_agent.store.db import connect, init_schema
from interview_agent.store.questions import QuestionRepo
from interview_agent.store.attempts import AttemptRepo

def setup_repos(tmp_path, scores):
    conn = connect(":memory:")
    init_schema(conn)
    seed = tmp_path / "s.json"
    seed.write_text(json.dumps(
        [{"id": 1, "topic": "jvm", "difficulty": 2, "question": "Q",
          "answer_points": ["p"]}], ensure_ascii=False), encoding="utf-8")
    QuestionRepo(conn).import_seed(str(seed))
    repo = AttemptRepo(conn)
    for i, s in enumerate(scores):
        repo.record(1, f"ans{i}", s, "fb")
    return conn

def test_wrong_then_mastered_flow(tmp_path):
    conn = setup_repos(tmp_path, [0.2, 0.9, 0.9])
    w = conn.execute("SELECT wrong_count, streak_right, mastered FROM wrong_notes").fetchone()
    assert w == (1, 2, 1)  # one wrong, then 2-right streak => mastered

def test_score_clamped(tmp_path):
    conn = setup_repos(tmp_path, [1.5])
    s = conn.execute("SELECT score FROM attempts").fetchone()[0]
    assert s == 1.0        # Review Focus #4

def test_stats(tmp_path):
    conn = setup_repos(tmp_path, [0.2, 1.0])
    st = AttemptRepo(conn).stats("jvm")
    assert st == {"attempts": 2, "avg_score": 0.6, "wrong_count": 1}

def test_latest_feedback(tmp_path):
    """Authoritative review comes from DB, not the model's free text."""
    conn = setup_repos(tmp_path, [0.2, 0.9])
    from interview_agent.store.attempts import AttemptRepo
    assert AttemptRepo(conn).latest_feedback(1) == "fb"
    assert AttemptRepo(conn).latest_feedback(999) is None
