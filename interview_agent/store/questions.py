# interview_agent/store/questions.py
import json
import sqlite3
from dataclasses import dataclass

@dataclass
class Question:
    id: int
    topic: str
    difficulty: int
    question: str
    answer_points: list[str]

class QuestionRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def import_seed(self, json_path: str) -> int:
        """Import seed questions; skip ids already present. Returns count."""
        with open(json_path, encoding="utf-8") as f:
            rows = json.load(f)
        existing = {r[0] for r in self.conn.execute("SELECT id FROM questions")}
        new = [r for r in rows if r["id"] not in existing]
        self.conn.executemany(
            "INSERT INTO questions(id, topic, difficulty, question, answer_points)"
            " VALUES (:id, :topic, :difficulty, :question, :answer_points_json)",
            [{**r, "answer_points_json": json.dumps(r["answer_points"], ensure_ascii=False)}
             for r in new])
        self.conn.commit()
        return len(new)

    def _row_to_q(self, row) -> Question:
        return Question(row[0], row[1], row[2], row[3], json.loads(row[4]))

    def get(self, question_id: int) -> Question | None:
        row = self.conn.execute(
            "SELECT id, topic, difficulty, question, answer_points"
            " FROM questions WHERE id=?", (question_id,)).fetchone()
        return self._row_to_q(row) if row else None

    def pick(self, topic: str, wrong_only: bool = False,
             exclude_ids: list[int] | None = None) -> Question | None:
        """Priority: unmastered wrong notes (oldest last_wrong_at first),
        then least-recently-attempted questions of the topic.
        exclude_ids are questions already asked this session; they are skipped
        when alternatives exist and ignored when everything else is excluded
        (so a wrong question resurfaces later, not immediately)."""
        exclude_ids = exclude_ids or []

        def _not_in() -> tuple[str, list]:
            if not exclude_ids:
                return "", []
            marks = ",".join("?" * len(exclude_ids))
            return f" AND q.id NOT IN ({marks})", list(exclude_ids)

        def _wrong_first():
            extra, params = _not_in()
            row = self.conn.execute(
                "SELECT q.id FROM questions q"
                " JOIN wrong_notes w ON w.question_id = q.id"
                f" WHERE w.mastered = 0{extra}"
                " ORDER BY w.last_wrong_at ASC LIMIT 1", params).fetchone()
            return self.get(row[0]) if row else None

        def _topic_order():
            extra, params = _not_in()
            row = self.conn.execute(
                "SELECT q.id FROM questions q"
                " LEFT JOIN attempts a ON a.question_id = q.id"
                f" WHERE q.topic = ?{extra} GROUP BY q.id"
                " ORDER BY MAX(a.created_at) IS NULL DESC, MAX(a.created_at) ASC"
                " LIMIT 1", [topic] + params).fetchone()
            return self.get(row[0]) if row else None

        q = _wrong_first()
        if q is None and not wrong_only:
            q = _topic_order()
        if q is None and exclude_ids and not wrong_only:
            # everything excluded: retry once ignoring the exclusion
            # (wrong_only never relaxes — a just-asked wrong note waits)
            exclude_ids = []
            q = _wrong_first()
            if q is None:
                q = _topic_order()
        return q
