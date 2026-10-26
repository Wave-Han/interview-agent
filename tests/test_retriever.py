from interview_agent.rag.retriever import cosine, top_k

def test_cosine_known_values():
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([2, 0], [5, 0]) == 1.0
    assert cosine([1, 0], [-3, 0]) == -1.0
    assert cosine([0, 0], [1, 1]) == 0.0     # Review Focus #4: zero vector

def test_top_k_orders_and_truncates():
    cands = [(1, [1, 0]), (2, [0, 1]), (3, [0.9, 0.1]), (4, [-1, 0])]
    out = top_k([1, 0], cands, k=3)
    assert [i for i, _ in out] == [1, 3, 2] and out[0][1] >= out[1][1] >= out[2][1]
    assert len(top_k([1, 0], cands[:2], k=3)) == 2   # fewer than k
