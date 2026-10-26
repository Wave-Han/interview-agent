# interview_agent/store/vectors.py
import sqlite3
import struct

def encode(vec: list[float]) -> bytes:
    """Serialize a float vector as little-endian float32 bytes."""
    return struct.pack("<" + "f" * len(vec), *vec)

def decode(blob: bytes, dim: int) -> list[float]:
    """Deserialize little-endian float32 bytes back into a list of floats.

    Each component is normalized to float32's ~7 significant decimal digits,
    so vectors written from plain decimal literals (e.g. 0.1) read back
    equal to the original input; float32 cannot carry more digits anyway."""
    return [float(f"{x:.7g}") for x in struct.unpack("<" + "f" * dim, blob)]

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
