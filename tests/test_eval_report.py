# tests/test_eval_report.py
from interview_agent.eval.runner import CaseResult, EvalReport

def _report(sample_cases=None):
    cases = sample_cases or [
        CaseResult(7, "good", [0.7, 1.0], 0.9, True, "hit"),
        CaseResult(7, "bad", [0.0, 0.2], 0.5, False, "miss"),
    ]
    return EvalReport(total=2, hits=1, no_record=0, errors=0,
                      avg_delta=0.15, per_band={"good": {"n": 1, "hits": 1},
                                                "partial": {"n": 0, "hits": 0},
                                                "bad": {"n": 1, "hits": 0}},
                      cases=cases)

def test_format_table_shows_rate():
    t = _report().format_table()
    assert "50.0%" in t and "good" in t and "bad" in t

def test_write_markdown(tmp_path):
    p = tmp_path / "r.md"
    _report().write_markdown(str(p))
    text = p.read_text(encoding="utf-8")
    assert "命中" in text and "good" in text and "0.9" in text

def test_sample_reproducible(tmp_path):
    # Review Focus #5: same seed -> same case selection (via run_eval)
    from interview_agent.store.db import connect, init_schema
    from interview_agent.store.questions import QuestionRepo
    from interview_agent.eval.runner import run_eval
    conn = connect(":memory:"); init_schema(conn)
    for i in range(1, 6):
        conn.execute("INSERT INTO questions VALUES (?,'jvm',2,'Q?','[\"p\"]')", (i,))
    conn.commit()
    golden = [{"question_id": i,
               "cases": [{"band": "good", "range": [0.7, 1.0], "answer": "a"}]}
              for i in range(1, 6)]
    class OneShot:
        def chat(self, m, tools=None, tool_choice=None):
            from interview_agent.llm.client import LLMResponse, ToolCall
            return LLMResponse("", [ToolCall("c", "record_result",
                                 {"question_id": 1, "score": 0.9,
                                  "feedback": "f", "user_answer": "x"})],
                               "tool_calls")
    r1 = run_eval(OneShot(), QuestionRepo(conn), golden, sample=3)
    r2 = run_eval(OneShot(), QuestionRepo(conn), golden, sample=3)
    assert [c.question_id for c in r1.cases] == [c.question_id for c in r2.cases]
    assert r1.total == 3
