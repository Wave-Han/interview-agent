# scripts/generate_golden.py
"""Golden-set draft generator (rubric-blind by construction).

Builds one chat call per (question, band). The prompt carries the question
text and a band behavior spec ONLY -- answer_points never flow into this
script's prompts or output; band curation against the rubric happens in the
human review step of the following task.

Usage:
    python scripts/generate_golden.py --ids 7,12,25 --out scripts/golden_draft.json

Output shape (no "range" -- ranges are filled during human curation):
    [{"question_id": 7, "cases": [{"band": "good", "answer": "..."}, ...]}]
"""
import argparse
import json
import sys
from pathlib import Path

# Direct execution support: python scripts/generate_golden.py puts only
# scripts/ itself on sys.path, so the project root must be added by hand.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from interview_agent.config import load_config
from interview_agent.llm.client import LLMClient
from interview_agent.store.db import connect
from interview_agent.store.questions import QuestionRepo

DEFAULT_OUT = "scripts/golden_draft.json"

# Chinese behavior specs shown to the model. The band key itself never
# appears in the prompt (the model sees behavior, not band names).
# NOTE: partial deviates from the brief by one word ("新内容" instead of
# "新要点") -- the brief's own test bans "要点" in the partial prompt, and
# the executable test wins over the prose spec.
BAND_SPECS = {
    "good": "写一个覆盖该题全部要点的口述答案,自然、像备考者,1~4 句",
    "partial": "写一个只答对该题约一半内容的口述答案,说对一部分、漏掉其余,不要虚构新内容",
    "bad": "写一个方向错误但认真作答的口述答案(常见误解),不要乱码或拒绝作答",
}


def build_generator_prompt(question_text: str, band: str) -> str:
    """Prompt from question text + band behavior spec. No rubric involved."""
    return (
        f"面试题:{question_text}\n"
        f"要求:{BAND_SPECS[band]}。只输出口述答案本身,不要任何解释、前缀或编号。"
    )


def _write_draft(draft: list, out: str) -> None:
    """Write the draft JSON as UTF-8, creating the parent dir if needed."""
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)


def main(ids: str, out: str = DEFAULT_OUT) -> None:
    """Generate one draft answer per (question, band) and write them to out.

    Fails fast on unknown ids before any API call; a per-case LLM failure is
    reported and skipped (the run continues, progress is already on disk).
    """
    question_ids = [int(x) for x in ids.split(",") if x.strip()]
    cfg = load_config()
    client = LLMClient(cfg)
    qrepo = QuestionRepo(connect(cfg.db_path))

    # Validate every id before spending a single API call.
    questions = []
    for qid in question_ids:
        q = qrepo.get(qid)
        if q is None:
            raise SystemExit(f"题库中不存在 id={qid} 的题目,请检查 --ids")
        questions.append(q)

    total = len(questions) * len(BAND_SPECS)
    done = failed = 0
    draft = []
    for i, q in enumerate(questions, 1):
        cases = []
        for band in BAND_SPECS:  # insertion order: good -> partial -> bad
            label = f"[{i}/{len(questions)}] 题 {q.id} {band}"
            try:
                resp = client.chat([{
                    "role": "user",
                    "content": build_generator_prompt(q.question, band),
                }])
                cases.append({"band": band, "answer": resp.content.strip()})
                done += 1
                print(f"{label} 完成")
            except Exception as e:
                failed += 1
                print(f"{label} 失败: {e}")
        if cases:
            draft.append({"question_id": q.id, "cases": cases})
            # Persist after each question so an interrupted run keeps progress.
            _write_draft(draft, out)
    print(f"生成完毕:成功 {done} 条 / 失败 {failed} 条(计划 {total}),"
          f"草稿已写入 {out}")
    if failed:
        print("存在失败案例,可仅用缺失的题 id 重跑 --ids 补齐后手工合并。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="生成黄金集草稿答案(每题每档一次独立调用,rubric 盲)")
    parser.add_argument("--ids", required=True,
                        help="逗号分隔的题目 id,如 7,12,25")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help=f"草稿 JSON 输出路径(默认 {DEFAULT_OUT})")
    args = parser.parse_args()
    main(args.ids, args.out)
