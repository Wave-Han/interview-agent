# tests/test_loop.py
from interview_agent.agent.loop import run_agent

class FakeClient:
    """Scripted responses: tool call -> tool call(bad json name) -> final."""
    def __init__(self, script):
        self.script, self.seen = script, []
    def chat(self, messages, tools=None):
        self.seen.append(list(messages))   # snapshot, so tests can inspect roles
        return self.script.pop(0)

def resp_tool(call_id, name, args_json):
    from interview_agent.llm.client import LLMResponse, ToolCall
    return LLMResponse("", [ToolCall(call_id, name, args_json)], "tool_calls")

def resp_text(t):
    from interview_agent.llm.client import LLMResponse
    return LLMResponse(t, [], "stop")

def test_loop_executes_tool_and_feeds_back():
    client = FakeClient([
        resp_tool("c1", "pick_question", {"topic": "jvm"}),
        resp_text("here is your question")])
    class Reg:
        def schemas(self): return []
        def execute(self, name, args): return '{"question_id": 1}'
    out = run_agent(client, Reg(), "sys", "start")
    assert out == "here is your question"
    assert client.seen[1][-1]["role"] == "tool"   # result fed back

def test_loop_bad_arguments_not_crash():
    class BoomArgs(str):  # arguments that json.loads already parsed -> we pass dict
        pass
    client = FakeClient([
        resp_tool("c1", "pick_question", {"no_topic": True}),  # wrong kwargs
        resp_text("recovered")])
    class Reg:
        def schemas(self): return []
        def execute(self, name, args): raise TypeError("bad kwargs")
    out = run_agent(client, Reg(), "s", "u")     # Review Focus #2
    assert out == "recovered"                     # error fed back, no crash

def test_loop_stops_at_max_tool_calls():
    client = FakeClient([resp_tool("c", "pick_question", {"topic": "x"})] * 99)
    class Reg:
        def schemas(self): return []
        def execute(self, name, args): return '{"ok": 1}'
    out = run_agent(client, Reg(), "s", "u", max_tool_calls=3)  # Review Focus #5
    assert "too many" in out.lower()

def test_loop_reuses_session_messages():
    client = FakeClient([resp_text("ok")])
    class Reg:
        def schemas(self): return []
        def execute(self, name, args): return "{}"
    shared = [{"role": "system", "content": "s"},
              {"role": "user", "content": "prev"}]
    run_agent(client, Reg(), "", "new", messages=shared)
    assert [m["content"] for m in shared] == ["s", "prev", "new"]

def test_force_first_tool_forces_only_first_call():
    seen = []
    class Client:
        def chat(self, messages, tools=None, tool_choice=None):
            seen.append(tool_choice)
            if len(seen) == 1:   # first turn: forced record_result
                return resp_tool("c1", "record_result",
                                 {"question_id": 7, "score": 1.0,
                                  "feedback": "f", "user_answer": "a"})
            return resp_text("review text")
    class Reg:
        def schemas(self): return []
        def execute(self, name, args): return '{"ok": true}'
    out = run_agent(Client(), Reg(), "s", "u",
                    force_first_tool="record_result")
    assert out == "review text"
    assert seen[0] == {"type": "function",
                       "function": {"name": "record_result"}}
    assert seen[1] is None   # post-tool review turn is free-form
