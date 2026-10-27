# tests/test_eval_runner.py
import pytest
from interview_agent.store.db import connect, init_schema
from interview_agent.store.questions import QuestionRepo
from interview_agent.eval.runner import (EvalRecorder, build_eval_registry,
                                         validate_golden, run_eval)

def _seed_conn():
    conn = connect(":memory:"); init_schema(conn)
    conn.execute("INSERT INTO questions VALUES (7,'jvm',2,'什么是浮动垃圾?',"
                 "'[\"并发期新产生\",\"本轮收不掉\"]')")
    conn.commit()
    return conn

GOLDEN = [{"question_id": 7, "cases": [
    {"band": "good", "range": [0.7, 1.0], "answer": "完整答案"},
    {"band": "bad", "range": [0.0, 0.2], "answer": "错误答案"},
]}]

class FakeLLM:
    """Returns a record_result tool call then plain text, per case."""
    def __init__(self, score=0.9):
        self.score = score
    def chat(self, messages, tools=None):
        from interview_agent.llm.client import LLMResponse, ToolCall
        return LLMResponse("", [ToolCall("c1", "record_result",
                             {"question_id": 7, "score": self.score,
                              "feedback": "ok", "user_answer": "x"})],
                           "tool_calls")

def test_validate_golden_rejects_unknown_id():
    with pytest.raises(ValueError):        # Review Focus #2
        validate_golden([{"question_id": 999, "cases": []}],
                        QuestionRepo(_seed_conn()))

def test_run_eval_hits_and_isolation():
    conn = _seed_conn()
    report = run_eval(FakeLLM(0.9), QuestionRepo(conn), GOLDEN)
    assert report.total == 2 and report.hits == 1
    st = [c.status for c in report.cases]
    assert st == ["hit", "miss"]
    # Review Focus #3: eval must not write learning tables
    assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM wrong_notes").fetchone()[0] == 0

def test_run_eval_no_record_when_model_skips_tool():
    class SkipTool:
        def chat(self, messages, tools=None):
            from interview_agent.llm.client import LLMResponse
            return LLMResponse("直接给分 0.9", [], "stop")
    report = run_eval(SkipTool(), QuestionRepo(_seed_conn()), GOLDEN)
    assert report.no_record == 2 and report.hits == 0   # Review Focus #1

def test_run_eval_error_case_does_not_abort():
    class HalfBroken:
        def __init__(self): self.n = 0
        def chat(self, messages, tools=None):
            self.n += 1
            if self.n == 1:
                raise RuntimeError("boom")
            from interview_agent.llm.client import LLMResponse, ToolCall
            return LLMResponse("", [ToolCall("c", "record_result",
                                 {"question_id": 7, "score": 0.9,
                                  "feedback": "f", "user_answer": "x"})],
                               "tool_calls")
    report = run_eval(HalfBroken(), QuestionRepo(_seed_conn()), GOLDEN)
    assert report.errors == 1 and report.total == 2
