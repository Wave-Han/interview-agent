# tests/test_tools.py
import json
from interview_agent.store.db import connect, init_schema
from interview_agent.store.questions import QuestionRepo
from interview_agent.store.attempts import AttemptRepo
from interview_agent.tools.registry import ToolRegistry, build_default_registry

def make_reg():
    conn = connect(":memory:")
    init_schema(conn)
    conn.execute("INSERT INTO questions VALUES (1,'jvm',2,'Q1','[\"p1\"]')")
    conn.commit()
    return build_default_registry(QuestionRepo(conn), AttemptRepo(conn))

def test_pick_question_hides_answer_points():
    reg = make_reg()
    out = json.loads(reg.execute("pick_question", {"topic": "jvm"}))
    assert "answer_points" not in out and out["question_id"] == 1

def test_unknown_tool_returns_error_not_raise():
    reg = make_reg()
    out = json.loads(reg.execute("no_such", {}))
    assert "error" in out                # Review Focus #3

def test_record_result_flow():
    reg = make_reg()
    reg.execute("record_result", {"question_id": 1, "score": 0.3,
                                  "feedback": "f", "user_answer": "a"})
    stats = json.loads(reg.execute("get_stats", {"topic": "jvm"}))
    assert stats["wrong_count"] == 1

def test_schemas_shape():
    reg = make_reg()
    names = {t["function"]["name"] for t in reg.schemas()}
    assert names == {"pick_question", "record_result", "get_stats"}
