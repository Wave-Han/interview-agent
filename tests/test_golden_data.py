# tests/test_golden_data.py
import json, os
GOLDEN = os.path.join(os.path.dirname(__file__), "..", "interview_agent",
                      "data", "golden.json")

def test_golden_shape_and_quality():
    rows = json.load(open(GOLDEN, encoding="utf-8"))
    for row in rows:
        assert isinstance(row["question_id"], int) and row["question_id"] >= 1
        assert len(row["cases"]) == 3
        bands = {c["band"] for c in row["cases"]}
        assert bands == {"good", "partial", "bad"}
        for c in row["cases"]:
            lo, hi = c["range"]
            assert 0.0 <= lo < hi <= 1.0
            assert c["answer"].strip() and len(c["answer"]) >= 8   # non-empty with real content
    assert len(rows) == 20

def test_golden_covers_historical_wrong_questions():
    rows = json.load(open(GOLDEN, encoding="utf-8"))
    texts = json.dumps(rows, ensure_ascii=False)
    # the 20 questions must truly cover all 8 topics: verified by looking up each question_id in the question bank
    qpath = os.path.join(os.path.dirname(__file__), "..", "interview_agent",
                         "data", "questions.json")
    questions = {q["id"]: q["topic"] for q in json.load(open(qpath, encoding="utf-8"))}
    topics = {questions[r["question_id"]] for r in rows}
    assert topics == {"jvm", "thread_pool", "mysql", "network",
                      "os", "redis", "netty_algo", "agent"}
