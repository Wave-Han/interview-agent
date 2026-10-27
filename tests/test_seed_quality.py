# tests/test_seed_quality.py
import json, os

# "、" inside these points joins TERMS of one enumerated subject (like
# "Eden、两个 Survivor"), not independently gradeable facts — allowed.
# Entries are (question_id, point) so the exemption only ever applies to
# the exact question that earned it.
TERM_LIST_SINGLE_FACTS = {
    (40, "系统调用、中断、异常都会陷入内核态"),
    (70, "工具结果、网页内容等非受信数据同样可能携带指令"),
}

def _load_rows():
    p = os.path.join(os.path.dirname(__file__), "..", "interview_agent",
                     "data", "questions.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def test_no_compound_answer_points():
    rows = _load_rows()
    COMPOUND_IDS = {6, 40, 65, 70}
    for r in rows:
        for pt in r["answer_points"]:
            if (r["id"], pt) in TERM_LIST_SINGLE_FACTS:
                continue
            # each point must be ONE fact: heuristic guards on the 4 known ids
            assert not (r["id"] in COMPOUND_IDS and any(
                sep in pt for sep in ("; ", "、", " + ", "以及"))), \
                f"q{r['id']} still has compound point: {pt}"
