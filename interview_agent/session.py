# interview_agent/session.py
import json

from .tools.registry import build_default_registry
from .agent.loop import run_agent


def build_system_prompt() -> str:
    return (
        "You are a strict technical interviewer for Java backend interviews."
        " Session flow: call pick_question to get a question and show it;"
        " after the user answers, you will receive the question's answer_points"
        " (grading rubric) injected as user message; grade strictly by point"
        " coverage, call record_result exactly once with score (0~1 = fraction"
        " of points hit) and concise Chinese feedback naming missed points,"
        " then continue with the next question. Judge in Chinese.")


class SessionDriver:
    """Two-phase driver: ask() picks+shows a question (direct tool call,
    no LLM); grade() injects rubric + user answer into run_agent so the
    model judges and records via tools. Session history lives in
    self.messages and is reused across grades."""

    def __init__(self, client, qrepo, arepo, max_tool_calls=6):
        self.client = client
        self.qrepo = qrepo
        self.arepo = arepo
        self.registry = build_default_registry(qrepo, arepo)
        self.messages = [{"role": "system", "content": build_system_prompt()}]
        self.max_tool_calls = max_tool_calls
        self.current = None

    def ask(self, topic: str, wrong_only: bool) -> None:
        out = json.loads(self.registry.execute(
            "pick_question", {"topic": topic, "wrong_only": wrong_only}))
        print(out)
        self.current = out

    def grade(self, user_answer: str) -> None:
        q = self.qrepo.get(self.current["question_id"])
        rubric_msg = ("Question: %s\nanswer_points(rubric): %s\nuser answer: %s"
                      % (q.question, json.dumps(q.answer_points, ensure_ascii=False),
                         user_answer))
        run_agent(self.client, self.registry, "", rubric_msg,
                  on_output=print,
                  max_tool_calls=self.max_tool_calls,
                  messages=self.messages)
