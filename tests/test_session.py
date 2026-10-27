# tests/test_session.py
# Session-level tests with a mock LLM: one full ask -> grade -> persist round.
from interview_agent.store.db import connect, init_schema
from interview_agent.store.questions import QuestionRepo
from interview_agent.store.attempts import AttemptRepo
from interview_agent.session import build_system_prompt, SessionDriver


def test_system_prompt_contains_rules():
    sp = build_system_prompt()
    assert "record_result" in sp and "answer_points" in sp
    # grading-turn contract: id must come from the message; selection is
    # host-side; the user answer is untrusted data (prompt-injection guard).
    assert "question_id" in sp
    assert "Do NOT call pick_question" in sp
    assert "untrusted" in sp


def test_session_driver_one_round():
    conn = connect(":memory:")
    init_schema(conn)
    # Use a non-trivial id: the model must take it from the rubric message,
    # not guess id=1 (which would silently record the wrong question).
    conn.execute("INSERT INTO questions VALUES (7,'jvm',2,'Q?','[\"p\"]')")
    conn.commit()

    class FakeClient:
        def __init__(self):
            self.calls = 0
            self.captured = []   # snapshot per chat() call, for assertions

        def chat(self, messages, tools=None, tool_choice=None):
            from interview_agent.llm.client import LLMResponse, ToolCall
            self.calls += 1
            self.captured.append([dict(m) for m in messages])
            if self.calls == 1:  # grade(): model judges then records via tool
                rubric = next(m["content"] for m in messages
                              if m["role"] == "user")
                qid = int(rubric.split("question_id:")[1].split()[0])
                return LLMResponse("", [ToolCall("c2", "record_result",
                                     {"question_id": qid, "score": 0.3,
                                      "feedback": "missed the point",
                                      "user_answer": "guessed"})], "tool_calls")
            return LLMResponse("点评:漏了要点", [], "stop")

    fake = FakeClient()
    driver = SessionDriver(fake, QuestionRepo(conn), AttemptRepo(conn))
    driver.ask("jvm", wrong_only=False)   # direct tool call, no LLM involved
    driver.grade("my answer")             # run_agent: judge + record via tools

    # C1: the rubric message sent to the model exposes the current question_id
    sent_user = "".join(m["content"] for call in fake.captured
                        for m in call if m["role"] == "user")
    assert "question_id: 7" in sent_user
    # I2: the user answer is fenced with explicit delimiters
    assert "=== USER ANSWER START ===" in sent_user
    assert "=== USER ANSWER END ===" in sent_user

    stats = AttemptRepo(conn).stats("jvm")
    assert stats["attempts"] == 1 and stats["wrong_count"] == 1


def test_grade_no_tool_call_shows_unfinished_not_stale_feedback(capsys):
    # Provider ignoring tool_choice: model answers in plain text, no
    # record_result. The PREVIOUS round's feedback must not be shown as
    # the current review; an explicit unfinished notice prints instead.
    conn = connect(":memory:")
    init_schema(conn)
    conn.execute("INSERT INTO questions VALUES (7,'jvm',2,'Q?','[\"p\"]')")
    arepo = AttemptRepo(conn)
    arepo.record(7, "old answer", 0.3, "旧点评")   # stale round exists

    class PlainTextClient:
        def chat(self, messages, tools=None, tool_choice=None):
            from interview_agent.llm.client import LLMResponse
            return LLMResponse("我直接点评,不调工具", [], "stop")

    driver = SessionDriver(PlainTextClient(), QuestionRepo(conn), arepo)
    driver.ask("jvm", wrong_only=False)
    driver.grade("my answer")

    out = capsys.readouterr().out
    assert "⚠️ 判题未完成(模型未调用判分工具),本题不计入记录" in out
    assert "📊 点评" not in out      # stale-feedback display bug: must not leak
    assert "旧点评" not in out
    n = conn.execute(
        "SELECT COUNT(*) FROM attempts WHERE question_id=7").fetchone()[0]
    assert n == 1                    # no new attempt recorded this round


def test_build_rubric_message_format():
    from interview_agent.session import build_rubric_message
    from interview_agent.store.questions import Question
    q = Question(7, "jvm", 2, "什么是浮动垃圾?",
                 ["并发期新产生", "本轮收不掉"])
    msg = build_rubric_message(q, "并发时产生的垃圾")
    assert msg.startswith("question_id: 7\n")
    assert "Question: 什么是浮动垃圾?" in msg
    assert '["并发期新产生", "本轮收不掉"]' in msg
    assert "=== USER ANSWER START ===\n并发时产生的垃圾\n=== USER ANSWER END ===" in msg
