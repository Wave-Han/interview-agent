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

def test_embed_parses_and_orders(monkeypatch):
    import httpx
    from interview_agent.llm.client import LLMClient
    def fake_post(self, url, **kw):
        assert url.endswith("/embeddings") and kw["json"]["input"] == ["b", "a"]
        return httpx.Response(200, json={"data": [
            {"index": 1, "embedding": [0.2]}, {"index": 0, "embedding": [0.1]}]},
            request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    out = LLMClient(CFG).embed(["b", "a"])
    assert out == [[0.1], [0.2]]      # sorted by index

def test_embed_count_mismatch_raises(monkeypatch):
    import httpx, pytest
    from interview_agent.llm.client import LLMClient, LLMResponse
    def fake_post(self, url, **kw):
        return httpx.Response(200, json={"data": [
            {"index": 0, "embedding": [0.1]}]}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with pytest.raises(ValueError):   # Review Focus #5
        LLMClient(CFG).embed(["a", "b"])

def test_4xx_no_retry(monkeypatch):
    import httpx, pytest
    from interview_agent.llm.client import LLMClient, LLMAPIError
    calls = {"n": 0}
    def fake_post(self, url, **kw):
        calls["n"] += 1
        r = httpx.Response(401, json={"error": "bad key"})
        r.request = httpx.Request("POST", url)
        return r
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with pytest.raises(LLMAPIError) as ei:
        LLMClient(CFG).chat([{"role": "user", "content": "x"}])
    assert ei.value.status_code == 401 and calls["n"] == 1

def test_malformed_200_body_wrapped(monkeypatch):
    # 200 with missing "choices": parsing must not leak a raw KeyError.
    def fake_post(self, url, **kw):
        return httpx.Response(200, json={"unexpected": True},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with pytest.raises(LLMConnectionError):
        LLMClient(CFG).chat([{"role": "user", "content": "x"}])

def test_embed_chunks_at_64(monkeypatch):
    import httpx
    from interview_agent.llm.client import LLMClient
    calls = []
    def fake_post(self, url, **kw):
        calls.append(kw["json"]["input"])
        data = [{"index": i, "embedding": [float(len(calls)), float(i)]}
                for i in range(len(kw["json"]["input"]))]
        return httpx.Response(200, json={"data": data},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    out = LLMClient(CFG).embed([f"t{i}" for i in range(65)])   # Review Focus #4
    assert calls == [[f"t{i}" for i in range(64)], ["t64"]]
    assert len(out) == 65 and out[64] == [2.0, 0.0]            # 2nd batch, index 0
