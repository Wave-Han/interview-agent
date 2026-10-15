# interview_agent/llm/client.py
import json, time
import httpx
from dataclasses import dataclass, field
from interview_agent.config import Config

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict

@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"

class LLMConnectionError(Exception):
    pass

class LLMClient:
    """Thin OpenAI-compatible chat client (works with GLM/DeepSeek/Kimi)."""
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def chat(self, messages, tools=None) -> LLMResponse:
        body = {"model": self.cfg.model, "messages": messages}
        if tools:
            body["tools"] = tools
        last_err = None
        for attempt in range(3):  # exponential backoff: 1s, 2s, 4s
            try:
                with httpx.Client(timeout=60) as c:
                    r = c.post(f"{self.cfg.base_url}/chat/completions",
                               headers={"Authorization": f"Bearer {self.cfg.api_key}"},
                               json=body)
                r.raise_for_status()
                msg = r.json()["choices"][0]
                calls = [ToolCall(tc["id"], tc["function"]["name"],
                                  json.loads(tc["function"]["arguments"] or "{}"))
                         for tc in msg["message"].get("tool_calls") or []]
                return LLMResponse(msg["message"].get("content") or "",
                                   calls, msg.get("finish_reason", "stop"))
            except (httpx.HTTPError, KeyError, ValueError) as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise LLMConnectionError(str(last_err))
