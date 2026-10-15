# tests/test_session.py
# Session-level tests with a mock LLM: one full ask -> grade -> persist round.
from interview_agent.store.db import connect, init_schema
from interview_agent.store.questions import QuestionRepo
from interview_agent.store.attempts import AttemptRepo
from interview_agent.session import build_system_prompt, SessionDriver


def test_system_prompt_contains_rules():
    sp = build_system_prompt()
    assert "record_result" in sp and "answer_points" in sp


def test_session_driver_one_round():
    conn = connect(":memory:")
    init_schema(conn)
    conn.execute("INSERT INTO questions VALUES (1,'jvm',2,'Q?','[\"p\"]')")
    conn.commit()

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, tools=None):
            from interview_agent.llm.client import LLMResponse, ToolCall
            self.calls += 1
            if self.calls == 1:  # grade(): model judges then records via tool
                return LLMResponse("", [ToolCall("c2", "record_result",
                                     {"question_id": 1, "score": 0.3,
                                      "feedback": "missed the point",
                                      "user_answer": "guessed"})], "tool_calls")
            return LLMResponse("点评:漏了要点", [], "stop")

    driver = SessionDriver(FakeClient(), QuestionRepo(conn), AttemptRepo(conn))
    driver.ask("jvm", wrong_only=False)   # direct tool call, no LLM involved
    driver.grade("my answer")             # run_agent: judge + record via tools
    stats = AttemptRepo(conn).stats("jvm")
    assert stats["attempts"] == 1 and stats["wrong_count"] == 1
