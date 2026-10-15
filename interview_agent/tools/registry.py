# interview_agent/tools/registry.py
import json, traceback

class ToolRegistry:
    """Map tool name -> (json-schema, handler). Never raises to the model."""
    def __init__(self):
        self._tools = {}

    def register(self, schema: dict, handler) -> None:
        self._tools[schema["function"]["name"]] = (schema, handler)

    def schemas(self) -> list[dict]:
        return [s for s, _ in self._tools.values()]

    def execute(self, name: str, arguments: dict) -> str:
        if name not in self._tools:
            return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)
        try:
            return json.dumps(self._tools[name][1](**arguments),
                              ensure_ascii=False, default=str)
        except Exception:
            return json.dumps({"error": traceback.format_exc(limit=1)},
                              ensure_ascii=False)

def build_default_registry(qrepo, arepo) -> ToolRegistry:
    """Delegate to builtins.build_default_registry; imported lazily because
    builtins imports ToolRegistry from this module (avoids circular import)."""
    from .builtins import build_default_registry as _impl
    return _impl(qrepo, arepo)
