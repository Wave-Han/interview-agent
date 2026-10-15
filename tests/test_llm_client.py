# tests/test_llm_client.py
import httpx, pytest
from interview_agent.config import Config
from interview_agent.llm.client import LLMClient, LLMConnectionError

CFG = Config("https://fake/v4", "sk-test", "m", ":memory:")

def test_chat_parses_tool_calls(monkeypatch):
    def fake_post(self, url, **kw):
        # httpx >= 0.28: raise_for_status() needs a request bound to the response
        return httpx.Response(200, json={"choices": [{
            "finish_reason": "tool_calls",
            "message": {"content": "", "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "pick_question",
                             "arguments": "{\"topic\": \"jvm\"}"}}]}}]},
                             request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    resp = LLMClient(CFG).chat([{"role": "user", "content": "hi"}])
    assert resp.finish_reason == "tool_calls"
    assert resp.tool_calls[0].arguments == {"topic": "jvm"}

def test_retry_then_fail(monkeypatch):
    calls = {"n": 0}
    def flaky(self, url, **kw):
        calls["n"] += 1
        raise httpx.ConnectError("boom")
    monkeypatch.setattr(httpx.Client, "post", flaky)
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(LLMConnectionError):
        LLMClient(CFG).chat([{"role": "user", "content": "hi"}])
    assert calls["n"] == 3   # 1 + 2 retries
