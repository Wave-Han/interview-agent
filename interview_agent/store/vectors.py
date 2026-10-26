# interview_agent/store/vectors.py
import sqlite3
import struct

def encode(vec: list[float]) -> bytes:
    """Serialize a float vector as little-endian float32 bytes."""
    return struct.pack("<" + "f" * len(vec), *vec)

def decode(blob: bytes, dim: int) -> list[float]:
    """Decode a float32 little-endian blob into a plain float list (lossless)."""
    return list(struct.unpack(f"<{dim}f", blob))

class VectorRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def rebuild(self, rows: list[tuple[int, list[float]]]) -> int:
        """Replace all stored vectors in one transaction. Returns row count."""
        self.conn.execute("DELETE FROM question_vectors")
        self.conn.executemany(
            "INSERT INTO question_vectors VALUES (?,?,?)",
            [(qid, len(vec), encode(vec)) for qid, vec in rows])
        self.conn.commit()
        return len(rows)

    def all(self) -> list[tuple[int, list[float]]]:
        """Return all (question_id, vector) pairs."""
        return [(row[0], decode(row[2], row[1]))
                for row in self.conn.execute(
                    "SELECT question_id, dim, vec FROM question_vectors")]

    def count(self) -> int:
        """Return number of stored vectors."""
        return self.conn.execute(
            "SELECT COUNT(*) FROM question_vectors").fetchone()[0]
