# interview_agent/eval/runner.py
import logging
import random
from dataclasses import dataclass
from datetime import date

from ..agent.loop import run_agent
from ..session import build_system_prompt, build_rubric_message
from ..tools.registry import ToolRegistry


class EvalRecorder:
    """In-memory sink for the model's record_result call. Unlike the quiz
    flow's arepo-backed handler, nothing is persisted: eval runs must never
    write learning tables."""

    def __init__(self):
        self.last: tuple[float, str] | None = None

    def record(self, question_id: int, score: float, feedback: str) -> dict:
        # question_id accepted but not cross-checked (tolerant design):
        # recorder.last is trusted as the outcome of the current case.
        self.last = (score, feedback)
        return {"ok": True}


def build_eval_registry(recorder: EvalRecorder) -> ToolRegistry:
    """Registry whose only tool is record_result, schema identical to the
    quiz version but routed to the recorder instead of the attempts store."""
    reg = ToolRegistry()

    def record_result(question_id: int, score: float, feedback: str,
                      user_answer: str) -> dict:
        # user_answer kept in the signature to match the shared schema,
        # then dropped: eval grading is not a real attempt.
        return recorder.record(question_id, score, feedback)

    reg.register({"type": "function", "function": {
        "name": "record_result",
        "description": "Persist grading of one user answer. score is 0~1"
                       " hit-rate of answer points. Call exactly once per"
                       " answered question.",
        "parameters": {"type": "object",
                       "properties": {
                           "question_id": {"type": "integer"},
                           "score": {"type": "number"},
                           "feedback": {"type": "string"},
                           "user_answer": {"type": "string"}},
                       "required": ["question_id", "score", "feedback",
                                    "user_answer"]}}}, record_result)
    return reg


def validate_golden(golden: list, qrepo) -> None:
    """Every golden question_id must resolve to a stored question."""
    for entry in golden:
        qid = entry["question_id"]
        if qrepo.get(qid) is None:
            raise ValueError(f"黄金集包含不存在的题目 id: {qid}")


@dataclass
class CaseResult:
    question_id: int
    band: str
    expected_range: list[float]
    score: float | None   # None when no_record / error
    hit: bool
    status: str           # hit / miss / no_record / error


@dataclass
class EvalReport:
    total: int
    hits: int
    no_record: int
    errors: int
    avg_delta: float
    per_band: dict        # band -> {"n": int, "hits": int}
    cases: list[CaseResult]

    def format_table(self) -> str:
        """One-screen Chinese summary for terminal output."""
        lines = [
            f"总案例: {self.total}  命中: {self.hits}"
            f"  命中率: {self._rate(self.hits, self.total)}",
            f"no_record: {self.no_record}  error: {self.errors}"
            f"  平均分差: {self.avg_delta:.3f}",
            "分档统计:",
        ]
        for band in _ordered_bands(self.per_band):
            s = self.per_band[band]
            lines.append(f"  {band:<8} n={s['n']:<3} 命中={s['hits']:<3}"
                         f"  命中率={self._rate(s['hits'], s['n'])}")
        return "\n".join(lines)

    def write_markdown(self, path: str, model: str = "") -> None:
        """Write the full report (date, optional grader model name, per-band
        table, per-case rows) to path as UTF-8 markdown."""
        lines = [f"# Eval 报告 {date.today().isoformat()}", ""]
        if model:
            lines.append(f"- 判题模型: {model}")
        lines += [
            f"- 总案例: {self.total}",
            f"- 命中: {self.hits}(命中率 {self._rate(self.hits, self.total)})",
            f"- no_record: {self.no_record} / error: {self.errors}",
            f"- 平均分差: {self.avg_delta:.3f}",
            "",
            "## 分档明细",
            "",
            "| 档位 | 案例数 | 命中数 | 命中率 |",
            "| --- | --- | --- | --- |",
        ]
        for band in _ordered_bands(self.per_band):
            s = self.per_band[band]
            lines.append(f"| {band} | {s['n']} | {s['hits']} |"
                         f" {self._rate(s['hits'], s['n'])} |")
        lines += ["", "## 逐 case 结果", "",
                  "| 题目 id | 档位 | 期望区间 | 模型评分 | 结果 |",
                  "| --- | --- | --- | --- | --- |"]
        for c in self.cases:
            score = f"{c.score:.2f}" if c.score is not None else "-"
            lines.append(f"| {c.question_id} | {c.band} | {c.expected_range} |"
                         f" {score} | {c.status} |")
        lines.append("")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    @staticmethod
    def _rate(hits: int, n: int) -> str:
        return f"{hits / n * 100:.1f}%" if n else "0.0%"


# Canonical display order for bands. per_band keys are data-driven (a golden
# set may lack a band entirely), so render only what exists — canonical
# good->partial->bad order first, any unknown band appended after.
BAND_ORDER = ("good", "partial", "bad")


def _ordered_bands(per_band: dict) -> list[str]:
    known = [b for b in BAND_ORDER if b in per_band]
    extra = [b for b in per_band if b not in BAND_ORDER]
    return known + extra


def run_eval(client, qrepo, golden: list, sample: int | None = None,
             seed: int = 42) -> EvalReport:
    """Grade every golden case through the real agent loop with storage
    isolation: fresh recorder + eval registry per case, system prompt reused
    verbatim from the quiz flow."""
    validate_golden(golden, qrepo)

    # Flatten golden into per-case work items: (question, case_spec).
    all_cases = []
    for entry in golden:
        q = qrepo.get(entry["question_id"])
        for case in entry["cases"]:
            all_cases.append((q, case))
    if sample is not None:
        if sample > len(all_cases):
            raise ValueError(f"sample 数量超过案例总数: {len(all_cases)}")
        all_cases = random.Random(seed).sample(all_cases, sample)

    results: list[CaseResult] = []
    for q, case in all_cases:
        lo, hi = case["range"]
        recorder = EvalRecorder()
        registry = build_eval_registry(recorder)
        # Seed with the system message ONLY: run_agent appends the rubric
        # user message itself (extending the list in place).
        messages = [{"role": "system", "content": build_system_prompt()}]
        try:
            run_agent(client, registry, "",
                      build_rubric_message(q, case["answer"]),
                      on_output=lambda s: None, max_tool_calls=6,
                      messages=messages)
        except Exception as e:
            # Real-run failures must stay diagnosable: the table only shows
            # an error count, so the per-case cause goes to the log.
            logging.warning(f"eval case qid={q.id} failed: {e}")
            results.append(CaseResult(q.id, case["band"], case["range"],
                                      None, False, "error"))
            continue
        if recorder.last is None:
            results.append(CaseResult(q.id, case["band"], case["range"],
                                      None, False, "no_record"))
        else:
            score = recorder.last[0]
            hit = lo <= score <= hi
            results.append(CaseResult(q.id, case["band"], case["range"],
                                      score, hit, "hit" if hit else "miss"))

    hits = sum(1 for r in results if r.status == "hit")
    no_record = sum(1 for r in results if r.status == "no_record")
    errors = sum(1 for r in results if r.status == "error")
    scored = [r for r in results if r.status in ("hit", "miss")]
    avg_delta = (sum(abs(r.score - (r.expected_range[0] + r.expected_range[1]) / 2)
                     for r in scored) / len(scored)) if scored else 0.0
    per_band: dict = {}
    for r in results:
        band = per_band.setdefault(r.band, {"n": 0, "hits": 0})
        band["n"] += 1
        if r.status == "hit":
            band["hits"] += 1
    return EvalReport(len(results), hits, no_record, errors, avg_delta,
                      per_band, results)
