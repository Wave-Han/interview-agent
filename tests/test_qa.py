# tests/test_qa.py
import pytest
from interview_agent.rag.qa import run_ask, pick_recommendation, IndexEmptyError

def _q(i, topic="jvm"):  # helper builds Question
    from interview_agent.store.questions import Question
    return Question(i, topic, 2, f"Q{i}", ["p"])

def test_run_ask_empty_index_raises():
    class VR:
        def count(self): return 0
    with pytest.raises(IndexEmptyError):
        run_ask(object(), None, set(), VR(), "any")

def test_run_ask_builds_prompt_with_material():
    class VR:
        def count(self): return 1
        def all(self): return [(7, [1.0, 0.0])]
    class Cli:
        def __init__(self): self.calls = []
        def embed(self, texts):
            self.calls.append(("embed", texts)); return [[1.0, 0.0]]
        def chat(self, messages, tools=None):
            self.calls.append(("chat", messages))
            from interview_agent.llm.client import LLMResponse
            return LLMResponse("答案", [], "stop")
    class QR:
        def get(self, i): return _q(i)
    cli = Cli()
    out = run_ask(cli, QR(), set(), VR(), "什么是浮动垃圾")
    assert out == "答案"
    assert cli.calls[0] == ("embed", ["什么是浮动垃圾"])
    msgs = cli.calls[-1][1]
    assert "题#7" in msgs[1]["content"]
    content = msgs[1]["content"]
    assert "候选人问题:" in content
    assert "=== USER QUESTION START ===" in content
    assert "=== USER QUESTION END ===" in content
    assert "什么是浮动垃圾" in content
    assert "untrusted data" in msgs[0]["content"]

def test_pick_recommendation_prefers_wrong():
    qs = {1: _q(1), 2: _q(2)}
    class QR:
        def get(self, i): return qs[i]
    assert pick_recommendation([2, 1], QR(), wrong_ids={1}).id == 1
    assert pick_recommendation([2], QR(), wrong_ids=set()).id == 2
    assert pick_recommendation([], QR(), wrong_ids={1}) is None
