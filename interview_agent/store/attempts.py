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
        if score < 0.6:
            self.conn.execute(
                "INSERT INTO wrong_notes(question_id, wrong_count, streak_right,"
                " mastered, last_wrong_at) VALUES (?,1,0,0,datetime('now'))"
                " ON CONFLICT(question_id) DO UPDATE SET"
                " wrong_count=wrong_count+1, streak_right=0, mastered=0,"
                " last_wrong_at=datetime('now')", (question_id,))
        else:
            self.conn.execute(
                "UPDATE wrong_notes SET streak_right=streak_right+1,"
                " mastered=CASE WHEN streak_right+1>=2 THEN 1 ELSE 0 END"
                " WHERE question_id=?", (question_id,))
        self.conn.commit()

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
