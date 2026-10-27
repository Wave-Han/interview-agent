# interview_agent/store/attempts.py
import sqlite3

class AttemptRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def record(self, question_id: int, user_answer: str,
               score: float, feedback: str) -> None:
        """Persist an attempt and update the wrong-note state machine."""
        score = max(0.0, min(1.0, score))
        self.conn.execute(
            "INSERT INTO attempts(question_id, user_answer, score, feedback)"
            " VALUES (?,?,?,?)", (question_id, user_answer, score, feedback))
        # State machine computed in Python: plain SQL only. No dialect upsert
        # (ON CONFLICT / ON DUPLICATE KEY) and no SET right-hand side that
        # reads a column being updated (MySQL evaluates SET left-to-right,
        # SQLite against OLD values), so behavior is portable across both.
        row = self.conn.execute(
            "SELECT wrong_count, streak_right FROM wrong_notes"
            " WHERE question_id=?", (question_id,)).fetchone()
        if score < 0.6:
            if row is None:
                self.conn.execute(
                    "INSERT INTO wrong_notes(question_id, wrong_count,"
                    " streak_right, mastered, last_wrong_at)"
                    " VALUES (?,1,0,0,datetime('now'))", (question_id,))
            else:
                self.conn.execute(
                    "UPDATE wrong_notes SET wrong_count=?, streak_right=0,"
                    " mastered=0, last_wrong_at=datetime('now')"
                    " WHERE question_id=?", (row[0] + 1, question_id))
        elif row is not None:
            new_streak = row[1] + 1
            self.conn.execute(
                "UPDATE wrong_notes SET streak_right=?, mastered=?"
                " WHERE question_id=?",
                (new_streak, 1 if new_streak >= 2 else 0, question_id))
        self.conn.commit()

    def max_attempt_id(self, question_id: int) -> int | None:
        """Highest attempt id for a question; None when never attempted.
        Grade() snapshots this before the LLM turn: ids are AUTOINCREMENT,
        so an unchanged value afterwards proves no NEW attempt was recorded
        this round (model skipped the tool despite forcing)."""
        row = self.conn.execute(
            "SELECT MAX(id) FROM attempts WHERE question_id=?",
            (question_id,)).fetchone()
        return row[0] if row and row[0] is not None else None

    def latest_feedback(self, question_id: int) -> str | None:
        """Most recent feedback for a question — the authoritative review
        (the model's free-form turn output is NOT trusted for display)."""
        row = self.conn.execute(
            "SELECT feedback FROM attempts WHERE question_id=?"
            " ORDER BY id DESC LIMIT 1", (question_id,)).fetchone()
        return row[0] if row else None

    def stats(self, topic: str) -> dict:
        row = self.conn.execute(
            "SELECT COUNT(*), IFNULL(AVG(a.score),0) FROM attempts a"
            " JOIN questions q ON q.id=a.question_id WHERE q.topic=?",
            (topic,)).fetchone()
        wrong = self.conn.execute(
            "SELECT COUNT(*) FROM wrong_notes w JOIN questions q ON q.id=w.question_id"
            " WHERE q.topic=? AND w.mastered=0", (topic,)).fetchone()[0]
        return {"attempts": row[0], "avg_score": round(row[1], 2),
                "wrong_count": wrong}
