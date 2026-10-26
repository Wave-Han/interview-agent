# interview_agent/store/db.py
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
  id INTEGER PRIMARY KEY,
  topic TEXT NOT NULL,
  difficulty INTEGER DEFAULT 2,
  question TEXT NOT NULL,
  answer_points TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  question_id INTEGER NOT NULL REFERENCES questions(id),
  user_answer TEXT NOT NULL,
  score REAL NOT NULL,
  feedback TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS wrong_notes (
  question_id INTEGER PRIMARY KEY REFERENCES questions(id),
  wrong_count INTEGER DEFAULT 1,
  streak_right INTEGER DEFAULT 0,
  mastered INTEGER DEFAULT 0,
  last_wrong_at TEXT
);
CREATE TABLE IF NOT EXISTS question_vectors (
  question_id INTEGER PRIMARY KEY REFERENCES questions(id),
  dim INTEGER NOT NULL,
  vec BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  messages TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

def connect(db_path: str) -> sqlite3.Connection:
    """Open connection with foreign keys enabled."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_schema(conn: sqlite3.Connection) -> None:
    """Create tables if missing; safe to call repeatedly."""
    conn.executescript(SCHEMA)
