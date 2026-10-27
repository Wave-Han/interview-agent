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

class LLMAPIError(Exception):
    """Non-retryable client error (4xx other than 429) from the LLM API."""
    def __init__(self, status_code: int, message: str = ""):
        super().__init__(message or f"LLM API error: {status_code}")
        self.status_code = status_code

class LLMClient:
    """Thin OpenAI-compatible chat client (works with GLM/DeepSeek/Kimi)."""
    # The provider (Zhipu) caps one embeddings request at 64 input items
    # (found via real smoke test), so embed() chunks internally.
    EMBED_BATCH = 64

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._http_client: httpx.Client | None = None

    @property
    def _http(self) -> httpx.Client:
        """Single shared httpx.Client, created lazily for connection reuse."""
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=60)
        return self._http_client

    def _post(self, path: str, body: dict) -> dict:
        """POST body to cfg.base_url+path with shared retry semantics.

        4xx (non-429) fails fast as LLMAPIError; network/5xx/timeout/malformed
        JSON retry up to 3 attempts with exponential backoff, then raise
        LLMConnectionError. No sleep after the final attempt.
        """
        url = f"{self.cfg.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.cfg.api_key}"}
        last_err = None
        for attempt in range(3):
            try:
                r = self._http.post(url, headers=headers, json=body)
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if 400 <= status < 500 and status != 429:
                    raise LLMAPIError(status, e.response.text) from e
                last_err = e
            except (httpx.HTTPError, ValueError) as e:
                last_err = e
            if attempt < 2:  # exponential backoff: 1s, 2s; none after final attempt
                time.sleep(2 ** attempt)
        raise LLMConnectionError(str(last_err))

    def chat(self, messages, tools=None,
             tool_choice: dict | str | None = None) -> LLMResponse:
        # tool_choice: optional OpenAI-compatible tool-choice directive —
        # object form {"type": "function", "function": {"name": ...}} or
        # string form "auto"/"none"/"required". Sent only when set so
        # callers keep full control over request shape.
        body = {"model": self.cfg.model, "messages": messages}
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
        payload = self._post("/chat/completions", body)
        try:
            msg = payload["choices"][0]
            calls = [ToolCall(tc["id"], tc["function"]["name"],
                              json.loads(tc["function"]["arguments"] or "{}"))
                     for tc in msg["message"].get("tool_calls") or []]
            return LLMResponse(msg["message"].get("content") or "",
                               calls, msg.get("finish_reason", "stop"))
        except KeyError as e:
            raise LLMConnectionError(f"malformed response: missing {e}") from e

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts; returned vectors ordered to match the input list.

        Requests are chunked at EMBED_BATCH (provider cap) and the per-chunk
        results concatenated, so callers see one call for any input size.
        """
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.EMBED_BATCH):
            chunk = texts[start:start + self.EMBED_BATCH]
            payload = self._post("/embeddings",
                                 {"model": self.cfg.embedding_model,
                                  "input": chunk})
            try:
                data = payload["data"]
                if len(data) != len(chunk):
                    raise ValueError(
                        f"embedding count mismatch: sent {len(chunk)}, "
                        f"got {len(data)}")
                vectors.extend(item["embedding"]
                               for item in sorted(data, key=lambda d: d["index"]))
            except KeyError as e:
                raise LLMConnectionError(
                    f"malformed response: missing {e}") from e
        return vectors
