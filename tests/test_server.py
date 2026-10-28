# tests/test_server.py
import pytest
from fastapi.testclient import TestClient
from interview_agent.store.db import connect, init_schema
from interview_agent.server import create_app

@pytest.fixture()
def client_pkg(monkeypatch):
    conn = connect(":memory:"); init_schema(conn)
    conn.execute("INSERT INTO questions VALUES (7,'jvm',2,'Q?','[\"p1\",\"p2\"]')")
    conn.commit()
    class FakeLLM:
        def __init__(self, cfg): pass
        def chat(self, messages, tools=None, tool_choice=None):
            from interview_agent.llm.client import LLMResponse, ToolCall
            return LLMResponse("", [ToolCall("c", "record_result",
                                 {"question_id": 7, "score": 0.8,
                                  "feedback": "覆盖两点", "user_answer": "x"})],
                               "tool_calls")
    monkeypatch.setattr("interview_agent.server.make_client", FakeLLM)
    app = create_app(None, conn)          # cfg None -> make_client never uses cfg fields here
    return TestClient(app), conn

def test_question_endpoint_with_exclude(client_pkg):
    tc, _ = client_pkg
    r = tc.get("/api/question", params={"topic": "jvm"})      # Review Focus #3
    assert r.json()["question_id"] == 7
    r2 = tc.get("/api/question", params={"topic": "jvm", "exclude_ids": "7"})
    assert r2.json() == {"message": "no question available for topic 'jvm'"}

def test_grade_records_and_returns(client_pkg):
    tc, conn = client_pkg
    r = tc.post("/api/grade", json={"question_id": 7, "answer": "我的回答"})
    body = r.json()
    assert body["recorded"] is True and body["score"] == 0.8
    assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1

def test_grade_skipped_tool_semantics(client_pkg, monkeypatch):
    tc, conn = client_pkg
    class Plain:
        def __init__(self, cfg): pass
        def chat(self, m, tools=None, tool_choice=None):
            from interview_agent.llm.client import LLMResponse
            return LLMResponse("直接点评", [], "stop")
    monkeypatch.setattr("interview_agent.server.make_client", Plain)
    r = tc.post("/api/grade", json={"question_id": 7, "answer": "x"})
    assert r.json() == {"recorded": False,
                        "message": "判题未完成(模型未调用判分工具)"}  # Review Focus #1
    assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0

def test_grade_unknown_question_404(client_pkg):
    tc, _ = client_pkg
    assert tc.post("/api/grade", json={"question_id": 99,
                                       "answer": "x"}).status_code == 404

def test_ask_empty_index_message(client_pkg, monkeypatch):    # Review Focus #4
    tc, _ = client_pkg
    class Embed0:
        def __init__(self, cfg): pass
        def chat(self, m, tools=None, tool_choice=None): raise AssertionError
        def embed(self, texts): return [[0.1]]
    monkeypatch.setattr("interview_agent.server.make_client", Embed0)
    r = tc.post("/api/ask", json={"query": "什么是浮动垃圾"})
    assert r.status_code == 200 and "index" in r.json()["message"]

def test_stats_endpoint(client_pkg):
    tc, conn = client_pkg
    conn.execute("INSERT INTO attempts(question_id,user_answer,score,feedback)"
                 " VALUES (7,'a',0.5,'f')"); conn.commit()
    assert tc.get("/api/stats", params={"topic": "jvm"}).json() == \
        {"attempts": 1, "avg_score": 0.5, "wrong_count": 1}
