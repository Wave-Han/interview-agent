"""Hand-written cosine similarity retriever (pure math, no dependencies)."""

import math


def cosine(a: list[float], b: list[float]) -> float:
    """Return cosine similarity between vectors a and b.

    Either vector being all-zero yields 0.0 (avoids division by zero).
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def top_k(
    query: list[float],
    candidates: list[tuple[int, list[float]]],
    k: int = 3,
) -> list[tuple[int, float]]:
    """Return (id, similarity) pairs sorted by similarity descending.

    At most k results; fewer if fewer candidates exist.
    """
    scored = [(cid, cosine(query, vec)) for cid, vec in candidates]
    return sorted(scored, key=lambda t: t[1], reverse=True)[:k]
