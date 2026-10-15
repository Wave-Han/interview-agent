# interview_agent/tools/builtins.py
from .registry import ToolRegistry

def _f(name, desc, props, required, handler):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props,
                       "required": required}}}, handler

def build_default_registry(qrepo, arepo) -> ToolRegistry:
    reg = ToolRegistry()

    def pick_question(topic: str, wrong_only: bool = False) -> dict:
        q = qrepo.pick(topic, wrong_only)
        if q is None:
            return {"message": f"no question available for topic '{topic}'"}
        return {"question_id": q.id, "topic": q.topic,
                "difficulty": q.difficulty, "question": q.question}

    def record_result(question_id: int, score: float, feedback: str,
                      user_answer: str) -> dict:
        arepo.record(question_id, user_answer, score, feedback)
        return {"ok": True}

    def get_stats(topic: str) -> dict:
        return arepo.stats(topic)

    for schema, handler in [
        _f("pick_question", "Pick one interview question. Call at session start and"
           " whenever ready for the next question. Prefer wrong_only when the user"
           " asks to review mistakes.",
           {"topic": {"type": "string"},
            "wrong_only": {"type": "boolean"}}, ["topic"], pick_question),
        _f("record_result", "Persist grading of one user answer. score is 0~1"
           " hit-rate of answer points. Call exactly once per answered question.",
           {"question_id": {"type": "integer"}, "score": {"type": "number"},
            "feedback": {"type": "string"},
            "user_answer": {"type": "string"}},
           ["question_id", "score", "feedback", "user_answer"], record_result),
        _f("get_stats", "Get accuracy stats for a topic.",
           {"topic": {"type": "string"}}, ["topic"], get_stats),
    ]:
        reg.register(schema, handler)
    return reg
