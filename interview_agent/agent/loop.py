# interview_agent/agent/loop.py
import json

def run_agent(client, registry, system: str, user_input: str,
              on_output=print, max_tool_calls: int = 20,
              messages=None) -> str:
    """Hand-written ReAct loop: model fills the form, code executes, feed back.
    Pass an existing messages list to continue a session (extended in place)."""
    if messages is None:
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user_input}]
    else:
        messages.append({"role": "user", "content": user_input})
    for _ in range(max_tool_calls):
        resp = client.chat(messages, registry.schemas())
        if not resp.tool_calls:
            on_output(resp.content)
            return resp.content
        messages.append({"role": "assistant", "content": resp.content or "",
                         "tool_calls": [{"id": c.id, "type": "function",
                                         "function": {"name": c.name,
                                                      "arguments": json.dumps(c.arguments, ensure_ascii=False)}}
                                        for c in resp.tool_calls]})
        for c in resp.tool_calls:
            try:
                result = registry.execute(c.name, c.arguments)
            except Exception as e:  # defensive: a broken tool must not kill the loop
                result = json.dumps({"error": f"{type(e).__name__}: {e}"},
                                    ensure_ascii=False)
            messages.append({"role": "tool", "tool_call_id": c.id,
                             "content": result})
            on_output(f"[tool] {c.name} -> {result[:120]}")
    # Safety valve fired: make it visible to the caller, not just the return value.
    stop = "Stopped: too many tool calls in one session."
    on_output(stop)
    return stop
